from __future__ import annotations

import getpass
import grp
import json
import os
import re
import shlex
import subprocess
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, NoReturn, TypeAlias, TypedDict

from rich import box
from rich.console import Console, RenderableType
from rich.table import Table
from rich.text import Text

from allegro_buddy import settings

CLI_NAME = "ab"
DEV_JOB_NAME = "ab-dev"
DEV_FRIENDLY_NAME = "dev job"
DEFAULT_DEV_CPUS = 2
DEFAULT_DEV_MEM = "8G"
DEFAULT_DEV_TIME = "08:00:00"
DEFAULT_JOB_OUTPUT_TAIL_LINES = 200
SACCT_HISTORY_HEADERS = [
    "JobIDRaw",
    "JobID",
    "JobName",
    "State",
    "ExitCode",
    "End",
    "Reason",
]
NULLISH_VALUES = {"", "(null)", "none", "n/a", "unknown"}

# Cluster-neutral GPU type aliases and labels; a cluster preset or the user's
# [gpu-aliases] / [gpu-labels] sections add to and override these.
GPU_TYPE_SYNONYMS = {
    "tesla_v100": "v100",
    "tesla_a100": "a100",
    "nvidia_a100": "a100",
    "nvidia_h100": "h100",
}
GPU_TYPE_LABELS = {
    "a100": "A100",
    "h100": "H100",
    "h200": "H200",
    "v100": "V100",
    "generic": "GPU",
}
GPU_RESOURCE_CHUNK = re.compile(
    r"(?:^|[\s,])(?:gres/)?gpu(?::(?P<type>[A-Za-z0-9._-]+))?[:=](?P<count>\d+)(?:\((?P<meta>[^)]*)\))?"
)

RUNNING_STATES = {"RUNNING", "COMPLETING", "CONFIGURING"}
ACTIVE_STATES = RUNNING_STATES | {"PENDING"}
NON_TERMINAL_JOB_STATES = ACTIVE_STATES | {"SUSPENDED"}
BAD_NODE_FLAGS = ("DOWN", "DRAIN", "FAIL", "INVAL", "REBOOT", "MAINT")
STATE_STYLES = {
    "RUNNING": "bold green",
    "PENDING": "bold yellow",
    "COMPLETING": "cyan",
    "CONFIGURING": "cyan",
    "IDLE": "green",
    "MIXED": "yellow",
    "ALLOCATED": "blue",
    "REBOOT": "yellow",
    "MAINT": "magenta",
    "DOWN": "bold red",
    "FAILED": "bold red",
    "CANCELLED": "red",
    "TIMEOUT": "red",
    "OUT_OF_MEMORY": "bold red",
    "NODE_FAIL": "bold red",
    "PREEMPTED": "red",
}

CONSOLE = Console()
ERROR_CONSOLE = Console(stderr=True)
JustifyMethod: TypeAlias = Literal["default", "left", "center", "right", "full"]
OutputStream: TypeAlias = Literal["stdout", "stderr"]
TableCell: TypeAlias = RenderableType
TableRow: TypeAlias = list[TableCell]


class PartitionStats(TypedDict):
    nodes: int
    idle_nodes: int
    cpu_total: int
    cpu_free: int
    mem_total_gb: int
    mem_free_gb: int
    gpu_total: int
    gpu_free: int
    gpu_usable: int
    gpu_total_by_type: dict[str, int]
    gpu_free_by_type: dict[str, int]
    gpu_usable_by_type: dict[str, int]


def empty_partition_stats() -> PartitionStats:
    return {
        "nodes": 0,
        "idle_nodes": 0,
        "cpu_total": 0,
        "cpu_free": 0,
        "mem_total_gb": 0,
        "mem_free_gb": 0,
        "gpu_total": 0,
        "gpu_free": 0,
        "gpu_usable": 0,
        "gpu_total_by_type": {},
        "gpu_free_by_type": {},
        "gpu_usable_by_type": {},
    }


def die(message: str, exit_code: int = 1) -> NoReturn:
    ERROR_CONSOLE.print(Text.assemble(("error: ", "bold red"), message))
    raise SystemExit(exit_code)


def warn(message: str | Text) -> None:
    ERROR_CONSOLE.print(Text.assemble(("warning: ", "bold yellow"), message))


def hint(text: str) -> None:
    """A grey tip that names a command and says what it does."""
    CONSOLE.print(Text(f"ⓘ {text}", style="dim"))


def run(
    argv: list[str],
    *,
    check: bool = True,
    capture_output: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(
            argv,
            check=False,
            capture_output=capture_output,
            text=text,
        )
    except FileNotFoundError:
        if check:
            die(f"required command not found: {argv[0]}")
        # Unchecked callers already treat a non-zero exit as "Slurm can't say".
        return subprocess.CompletedProcess(
            argv, 127, stdout="", stderr=f"command not found: {argv[0]}"
        )

    if check and proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        detail = stderr or stdout or f"command failed with exit code {proc.returncode}"
        die(f"{shlex.join(argv)} failed: {detail}")
    return proc


def exec_replace(argv: list[str]) -> NoReturn:
    try:
        os.execvp(argv[0], argv)
    except FileNotFoundError:
        die(f"command not found: {argv[0]}")


def parse_prop_line(line: str) -> dict[str, str]:
    return {
        match.group(1): match.group(2)
        for match in re.finditer(r"(\S+?)=(.*?)(?=\s+\S+=|$)", line.strip())
    }


def parse_pipe_rows(output: str, headers: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        rows.append(
            {
                header: parts[i] if i < len(parts) else ""
                for i, header in enumerate(headers)
            }
        )
    return rows


def run_parsable_rows(
    argv: list[str],
    headers: list[str],
    *,
    check: bool = True,
) -> list[dict[str, str]]:
    proc = run(argv, check=check)
    return parse_pipe_rows(proc.stdout, headers)


def is_nullish(value: str | None) -> bool:
    return value is None or value.strip().lower() in NULLISH_VALUES


def current_user() -> str:
    return getpass.getuser()


def current_groups() -> set[str]:
    group_ids = os.getgroups()
    groups = set()
    for gid in group_ids:
        try:
            groups.add(grp.getgrgid(gid).gr_name)
        except KeyError:
            continue
    return groups


def user_accounts(user: str) -> list[dict[str, str]]:
    """Your Slurm associations on this cluster (account, QOS, default account); [] if unknown."""
    cluster = settings.slurm_cluster_name()
    return run_parsable_rows(
        ["sacctmgr", "-nP", "show", "user", user, "withassoc",
         *([f"cluster={cluster}"] if cluster else []),
         "format=DefaultAccount,Account,QOS"],
        ["DefaultAccount", "Account", "QOS"],
        check=False,
    )  # fmt: skip


def user_from_userid(value: str) -> str:
    return value.split("(", 1)[0]


def display_job_id(job: dict[str, str]) -> str:
    array_job_id = job.get("ArrayJobId")
    array_task_id = job.get("ArrayTaskId")
    if array_job_id and array_task_id and array_task_id not in {"N/A", "(null)"}:
        return f"{array_job_id}_{array_task_id}"
    return job.get("JobId", "")


def truncate(value: str, width: int) -> str:
    if width <= 0 or len(value) <= width:
        return value
    return value[: width - 1] + "…"  # same marker rich uses when it cuts a cell


def as_cell(value: object) -> TableCell:
    if isinstance(value, Text):
        return value
    if value is None:
        return Text("-", style="dim")
    if isinstance(value, str) and value == "":
        return Text("-", style="dim")
    return str(value)


def render_table(
    columns: list[tuple[str, JustifyMethod]],
    rows: list[TableRow],
    *,
    title: str | None = None,
    caption: str | None = None,
    section_breaks: set[int] | None = None,
    width: int | None = None,
) -> None:
    """`width` caps the table (long cells wrap); None lets it use the terminal."""
    if not rows:
        CONSOLE.print(muted("Nothing to show."))
        return

    table = Table(
        title=title,
        title_style="bold",
        box=box.SIMPLE,
        show_edge=False,
        pad_edge=False,
        header_style="bold",
    )
    for header, justify in columns:
        table.add_column(header, justify=justify)
    for i, row in enumerate(rows):
        end_section = section_breaks is not None and i in section_breaks
        table.add_row(*[as_cell(cell) for cell in row], end_section=end_section)
    CONSOLE.print(table, width=width)
    if caption:
        # Not rich's caption: that one wraps to the table's width.
        CONSOLE.print(muted(caption))


def state_text(state: str) -> Text:
    return Text(state, style=STATE_STYLES.get(state, "white"))


# Styling never calls Slurm: it uses config or nodes some earlier step already loaded.
def partition_text(name: str) -> Text:
    if is_gpu_partition(name, detect=False):
        return Text(name, style="bold green")
    # Not knowing the nodes (e.g. `ab q` with nothing pending) is not knowing it's CPU-only.
    known = _NODE_FACTS is not None or settings.load().get_list("cluster", "gpu_partitions")
    return Text(name, style="bold blue" if known else "bold")


def node_text(name: str, partition: str = "") -> Text:
    """Green for GPU nodes: known from loaded nodes, or by the job's partition."""
    if not name or name in {"(pending)", "(null)"}:
        return Text(name or "(pending)", style="yellow")
    gpu = name in (_NODE_FACTS or {}).get("gpu_nodes", ()) or any(
        is_gpu_partition(part, detect=False) for part in partition.split(",") if part
    )
    return Text(name, style="green" if gpu else "blue")


def job_id_text(job_id: str) -> Text:
    return Text(job_id, style="cyan")


def ratio_text(
    free: int,
    total: int,
    *,
    unit: str = "",
    free_style: str = "green",
) -> Text:
    if total <= 0:
        return Text("-", style="dim")

    text = Text()
    text.append(str(free), style=free_style if free > 0 else "dim")
    text.append("/", style="dim")
    text.append(str(total), style="dim")
    if unit:
        text.append(unit, style="dim")
    return text


def muted(value: str = "-") -> Text:
    return Text(value, style="dim")


def parse_slurm_time(value: str) -> int | None:
    value = value.strip()
    upper = value.upper()
    if upper in {"UNLIMITED", "INFINITE", "INFINITY", "N/A"}:
        return None

    try:
        days = 0
        rest = value
        if "-" in value:
            day_part, rest = value.split("-", 1)
            days = int(day_part)

        parts = rest.split(":")
        if len(parts) == 3:
            hours, minutes, seconds = map(int, parts)
        elif len(parts) == 2:
            # Slurm: "D-HH:MM" with a day part, "MM:SS" without one.
            if "-" in value:
                hours, minutes = map(int, parts)
                seconds = 0
            else:
                hours = 0
                minutes, seconds = map(int, parts)
        elif len(parts) == 1:
            if "-" in value:
                hours = int(parts[0])
                minutes = 0
            else:
                hours = 0
                minutes = int(parts[0])
            seconds = 0
        else:
            return None
    except ValueError:
        return None

    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def format_seconds(value: int | None) -> str:
    """``45s``, ``40m``, ``6h35m``, ``2d2h``: zero units and seconds above a minute dropped."""
    if value is None:
        return "unlimited"
    value = max(0, value)
    if value < 60:
        return f"{value}s"
    days, rem = divmod(value, 86400)
    hours, rem = divmod(rem, 3600)
    units = ((days, "d"), (hours, "h"), (rem // 60, "m"))
    return "".join(f"{n}{unit}" for n, unit in units if n)


def iso_to_dt(value: str) -> datetime | None:
    if not value or value in {"Unknown", "N/A", "None"}:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def format_eta(end_time: str, *, now: datetime | None = None) -> str:
    end_dt = iso_to_dt(end_time)
    if end_dt is None:
        return "unknown"
    reference = now if now is not None else datetime.now()
    return format_seconds(int((end_dt - reference).total_seconds()))


def format_pending_start(start_time: str, *, now: datetime | None = None) -> str | None:
    """Format a pending job's estimated start as ``in 2h10m (Tue 16:40)``, or None.

    Starts up to six calendar days ahead show the weekday, later ones the date; an
    estimate that has already passed shows ``due``.
    """
    start_dt = iso_to_dt(start_time)
    if start_dt is None:
        return None
    reference = now if now is not None else datetime.now()
    if (start_dt.date() - reference.date()).days < 7:
        clock = start_dt.strftime("%a %H:%M")
    else:
        clock = start_dt.strftime("%b %d %H:%M")
    if start_dt <= reference:
        return f"due ({clock})"
    return f"in {format_timedelta(start_dt - reference)} ({clock})"


def format_timedelta(delta: timedelta) -> str:
    return format_seconds(int(delta.total_seconds()))


def parse_int(value: str | None, default: int = 0) -> int:
    if not value or value in {"(null)", "N/A"}:
        return default
    try:
        return int(float(value))
    except ValueError:
        return default


def parse_mb_to_gb(value: str | None) -> int:
    return round(parse_int(value) / 1024)


def format_mem_value(value: str | None) -> str:
    if not value or value in {"(null)", "N/A"}:
        return "-"
    if re.fullmatch(r"\d+", value):
        return f"{parse_mb_to_gb(value)}G"
    return value


GPU_FEATURE_TYPE_HINTS = (
    "a5000",
    "a100",
    "h100",
    "h200",
    "v100",
    "gtx",
    "tesla",
    "titan",
)


def canonical_gpu_type(gpu_type: str | None) -> str:
    normalized = settings.normalize_gpu_type(gpu_type or "")
    if not normalized:
        return "generic"
    aliases = settings.load().gpu_aliases
    return aliases.get(normalized) or GPU_TYPE_SYNONYMS.get(normalized, normalized)


def gpu_type_label(gpu_type: str) -> str:
    return (
        settings.load().gpu_labels.get(gpu_type)
        or GPU_TYPE_LABELS.get(gpu_type)
        or gpu_type.upper().replace("_", "")
    )


def parse_gpu_type_counts(spec: str | None) -> dict[str, int]:
    if not spec:
        return {}

    counts: dict[str, int] = {}
    for match in GPU_RESOURCE_CHUNK.finditer(spec):
        gpu_type = canonical_gpu_type(match.group("type"))
        count = int(match.group("count"))
        counts[gpu_type] = counts.get(gpu_type, 0) + count
    return counts


def infer_gpu_type_from_features(feature_blob: str | None) -> str | None:
    if not feature_blob or feature_blob in {"(null)", "N/A"}:
        return None

    for raw_token in feature_blob.split(","):
        token = raw_token.strip()
        if not token:
            continue
        token_lower = token.lower()
        if not any(hint in token_lower for hint in GPU_FEATURE_TYPE_HINTS):
            continue

        gpu_type = canonical_gpu_type(token)
        if gpu_type != "generic":
            return gpu_type
    return None


def infer_node_gpu_type(node: dict[str, str]) -> str | None:
    for field in ("ActiveFeatures", "AvailableFeatures", "Features"):
        gpu_type = infer_gpu_type_from_features(node.get(field))
        if gpu_type is not None:
            return gpu_type
    return None


def node_gpu_type_counts(node: dict[str, str]) -> dict[str, int]:
    counts = parse_gpu_type_counts(node.get("Gres"))
    generic_count = counts.get("generic", 0)
    if generic_count <= 0:
        return counts

    inferred_type = infer_node_gpu_type(node)
    if inferred_type is None:
        return counts

    typed_counts = {
        gpu_type: count for gpu_type, count in counts.items() if gpu_type != "generic"
    }
    typed_counts[inferred_type] = typed_counts.get(inferred_type, 0) + generic_count
    return typed_counts


def parse_gpu_count(spec: str | None) -> int:
    return sum(parse_gpu_type_counts(spec).values())


def add_gpu_type_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for gpu_type, count in source.items():
        target[gpu_type] = target.get(gpu_type, 0) + count


def parse_index_blob(blob: str) -> list[int]:
    ids: list[int] = []
    for part in blob.split(","):
        item = part.strip()
        if not item:
            continue
        if "-" in item:
            start, end = item.split("-", 1)
            try:
                ids.extend(range(int(start), int(end) + 1))
            except ValueError:
                continue
            continue
        try:
            ids.append(int(item))
        except ValueError:
            continue
    return ids


def parse_gpu_ids(spec: str | None) -> list[int]:
    if not spec:
        return []
    ids: list[int] = []
    for idx_blob in re.findall(r"IDX:([0-9,-]+)", spec):
        ids.extend(parse_index_blob(idx_blob))
    return sorted(set(ids))


def parse_node_gpu_types(spec: str | None) -> dict[int, str]:
    if not spec:
        return {}

    mapping: dict[int, str] = {}
    pending: list[tuple[str, int]] = []

    for match in GPU_RESOURCE_CHUNK.finditer(spec):
        gpu_type = canonical_gpu_type(match.group("type"))
        count = int(match.group("count"))
        meta = match.group("meta") or ""

        index_match = re.search(r"IDX:([0-9,-]+)", meta)
        if index_match:
            for gpu_id in parse_index_blob(index_match.group(1)):
                mapping[gpu_id] = gpu_type
            continue

        pending.append((gpu_type, count))

    total = sum(parse_gpu_type_counts(spec).values())
    remaining = [gpu_id for gpu_id in range(total) if gpu_id not in mapping]
    cursor = 0
    for gpu_type, count in pending:
        for _ in range(count):
            if cursor >= len(remaining):
                break
            mapping[remaining[cursor]] = gpu_type
            cursor += 1
    return mapping


def collect_display_gpu_types(count_maps: list[dict[str, int]]) -> list[str]:
    discovered = {
        gpu_type
        for count_map in count_maps
        for gpu_type, count in count_map.items()
        if count > 0
    }

    ordered: list[str] = []
    for gpu_type in [*settings.load().gpu_labels, "generic"]:
        if gpu_type in discovered and gpu_type not in ordered:
            ordered.append(gpu_type)
    ordered.extend(
        sorted(gpu_type for gpu_type in discovered if gpu_type not in ordered)
    )
    return ordered


def format_gpu_type_header(prefix: str, gpu_type: str) -> str:
    label = gpu_type_label(gpu_type)
    return f"{prefix}{label}" if prefix else label


def load_partitions(*, strict: bool = True) -> list[dict[str, str]]:
    proc = run(["scontrol", "--oneliner", "show", "partition"], check=strict)
    if proc.returncode != 0:
        return []
    return [parse_prop_line(line) for line in proc.stdout.splitlines() if line.strip()]


def partition_allowed(partition: dict[str, str], groups: set[str]) -> bool:
    deny_groups = partition.get("DenyGroups", "")
    if not is_nullish(deny_groups) and deny_groups.strip().upper() != "ALL":
        denied = {item for item in deny_groups.split(",") if item}
        if denied & groups:
            return False
    allow_groups = partition.get("AllowGroups", "ALL")
    if is_nullish(allow_groups) or allow_groups.strip().upper() == "ALL":
        return True
    allowed = {item for item in allow_groups.split(",") if item}
    return bool(allowed & groups)


def _max_time(partition: dict[str, str]) -> float:
    return parse_slurm_time(partition.get("MaxTime", "UNLIMITED")) or float("inf")


def sort_partitions(partitions: list[dict[str, str]]) -> list[dict[str, str]]:
    """GPU partitions first; a family (`gpu-a100`, `gpu-a100:test`) stays together,
    and families and their members go shortest MaxTime first."""

    def family(partition: dict[str, str]) -> str:
        return partition["PartitionName"].split(":")[0]

    shortest: dict[str, float] = {}
    for partition in partitions:
        shortest[family(partition)] = min(shortest.get(family(partition), float("inf")), _max_time(partition))
    return sorted(
        partitions,
        key=lambda p: (
            not is_gpu_partition(p["PartitionName"]),
            shortest[family(p)],
            family(p),
            _max_time(p),
            p["PartitionName"],
        ),
    )


def get_accessible_partitions(*, include_all: bool = False) -> list[dict[str, str]]:
    groups = current_groups()
    partitions = load_partitions()
    if not include_all:
        partitions = [
            partition
            for partition in partitions
            if partition_allowed(partition, groups)
        ]
    return sort_partitions(partitions)


class NodeFacts(TypedDict):
    names: set[str]
    gpu_nodes: set[str]
    gpu_partitions: set[str]


# What the last node load showed; detection reads it instead of calling Slurm again.
_NODE_FACTS: NodeFacts | None = None


def remember_nodes(nodes: list[dict[str, str]]) -> None:
    global _NODE_FACTS
    gpu_nodes = [node for node in nodes if parse_gpu_count(node.get("Gres")) > 0]
    _NODE_FACTS = {
        "names": {node.get("NodeName", "") for node in nodes},
        "gpu_nodes": {node.get("NodeName", "") for node in gpu_nodes},
        "gpu_partitions": {
            part
            for node in gpu_nodes
            for part in node.get("Partitions", "").split(",")
            if part
        },
    }


def node_facts() -> NodeFacts:
    if _NODE_FACTS is None:
        load_nodes(strict=False)
    assert _NODE_FACTS is not None
    return _NODE_FACTS


def is_gpu_partition(name: str, *, detect: bool = True) -> bool:
    """`[cluster] gpu-partitions` if set, else: any node in it has a GPU GRES.

    With ``detect=False`` this only uses nodes already loaded, never calls Slurm.
    """
    configured = settings.load().get_list("cluster", "gpu_partitions")
    if configured:
        return name in configured
    facts = node_facts() if detect else _NODE_FACTS
    return facts is not None and name in facts["gpu_partitions"]


def load_nodes(*, strict: bool = True) -> list[dict[str, str]]:
    proc = run(["scontrol", "--json", "show", "nodes"], check=False)
    try:
        nodes = nodes_from_json(proc.stdout) if proc.returncode == 0 else None
    except (ValueError, AttributeError):
        nodes = None
    if nodes is None:
        # Slurm without JSON output (old release, no data_parser plugin).
        fallback = run(["scontrol", "--oneliner", "show", "node"], check=strict)
        nodes = [
            node_from_props(parse_prop_line(line))
            for line in fallback.stdout.splitlines()
            if line.strip()
        ] if fallback.returncode == 0 else []
    remember_nodes(nodes)
    return nodes


def node_from_props(props: dict[str, str]) -> dict[str, str]:
    """A `scontrol --oneliner show node` line in the shape `nodes_from_json` returns."""
    features = props.get("AvailableFeatures") or props.get("Features") or ""
    return {
        "NodeName": props.get("NodeName", ""),
        "State": props.get("State", ""),
        "CPUTot": props.get("CPUTot", "0"),
        "CPUAlloc": props.get("CPUAlloc", "0"),
        "RealMemory": props.get("RealMemory", "0"),
        "AllocMem": props.get("AllocMem", "0"),
        "Gres": props.get("Gres") or "(null)",
        "GresUsed": props.get("GresUsed", ""),
        "Partitions": props.get("Partitions", ""),
        "ActiveFeatures": props.get("ActiveFeatures", ""),
        "Features": features,
        "Reservation": props.get("Reservation", ""),
        "SpecMem": props.get("MemSpecLimit", "0"),
    }


def nodes_from_json(stdout: str) -> list[dict[str, str]]:
    raw_nodes: list[dict] = json.loads(stdout).get("nodes", [])
    result: list[dict[str, str]] = []
    for n in raw_nodes:
        state_list = n.get("state") or []
        if isinstance(state_list, str):  # Slurm 22.05: "down" plus separate state_flags
            state_list = [state_list.upper(), *(n.get("state_flags") or [])]
        result.append({
            "NodeName": n.get("name", ""),
            "State": "+".join(state_list),
            "CPUTot": str(n.get("cpus", 0)),
            "CPUAlloc": str(n.get("alloc_cpus", 0)),
            "RealMemory": str(n.get("real_memory", 0)),
            "AllocMem": str(n.get("alloc_memory", 0)),
            "Gres": n.get("gres") or "(null)",
            "GresUsed": n.get("gres_used") or "",
            "Partitions": ",".join(n.get("partitions") or []),
            "ActiveFeatures": ",".join(n.get("active_features") or []),
            "Features": ",".join(n.get("features") or []),
            "Reservation": n.get("reservation") or "",
            "SpecMem": str(n.get("specialized_memory") or 0),
        })
    return result


def node_is_usable(node: dict[str, str]) -> bool:
    state = node.get("State", "").upper()
    return not any(flag in state for flag in BAD_NODE_FLAGS)


def node_is_idle(node: dict[str, str]) -> bool:
    return "IDLE" in node.get("State", "").upper()


def node_is_mixed(node: dict[str, str]) -> bool:
    return "MIXED" in node.get("State", "").upper()


def gpu_free_text(free: int, usable: int, total: int) -> Text:
    """`usable+n/total`: `+n` are idle GPUs a job can't get (full or drained nodes).

    free   = all unassigned GPUs (idle, not part of any job)
    usable = free GPUs on IDLE or MIXED nodes (can actually schedule there)
    """
    if total <= 0:
        return Text("-", style="dim")
    text = Text()
    text.append(str(usable), style="green" if usable > 0 else "dim")
    if usable < free:  # before the total, so 3+2/8 doesn't read as 3/10
        text.append(f"+{free - usable}", style="yellow")
    text.append("/", style="dim")
    text.append(str(total), style="dim")
    return text


_HOSTLIST_PART = re.compile(
    r"^(?P<prefix>[^\[\]]*)\[(?P<ranges>[^\]]+)\](?P<suffix>[^\[\]]*)$"
)


def _split_top_level(spec: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current = ""
    for char in spec:
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
            continue
        depth += {"[": 1, "]": -1}.get(char, 0)
        current += char
    parts.append(current)
    return [part.strip() for part in parts if part.strip()]


def expand_hostlist(spec: str | None) -> frozenset[str]:
    """Expand ``gpu[101-103,105],cmp001`` without calling ``scontrol show hostnames``."""
    names: set[str] = set()
    for part in _split_top_level(spec or ""):
        match = _HOSTLIST_PART.match(part)
        if match is None:
            names.add(part)
            continue
        expanded: set[str] = set()
        for item in match.group("ranges").split(","):
            start, _, end = item.partition("-")
            try:
                first, last = int(start), int(end or start)
            except ValueError:
                expanded = {part}
                break
            expanded.update(
                f"{match.group('prefix')}{index:0{len(start)}d}{match.group('suffix')}"
                for index in range(first, last + 1)
            )
        names.update(expanded)
    return frozenset(names)


_NUMBERED_NAME = re.compile(r"^(?P<prefix>.*?)(?P<number>\d+)$")


def expand_nodelist(nodelist: str) -> list[str]:
    nodelist = nodelist.strip()
    if not nodelist or nodelist in {"(null)", "None"}:
        return []
    return sorted(expand_hostlist(nodelist))


def normalize_sacct_state(state: str) -> str:
    token = state.strip().split(" ", 1)[0]
    return token.rstrip("+")


def job_state_is_finished(state: str) -> bool:
    token = normalize_sacct_state(state)
    return bool(token) and token not in NON_TERMINAL_JOB_STATES


def _history_sort_key(job: dict[str, str]) -> tuple[float, int, str]:
    end_time = iso_to_dt(job.get("End", ""))
    end_rank = end_time.timestamp() if end_time is not None else float("-inf")
    job_id = job.get("JobId", "")
    return (end_rank, parse_int(base_job_id(job_id), default=-1), job_id)


def load_job_history(
    user: str | None = None,
    *,
    strict: bool = True,
    since: str = "now-30days",
) -> list[dict[str, str]]:
    selected_user = user or current_user()
    argv = [
        "sacct",
        "--parsable2",
        "--noheader",
        "-X",
        f"--user={selected_user}",
        # Bounded window: the full history since 1970 is heavy on slurmdbd.
        f"--starttime={since}",
        f"--format={','.join(SACCT_HISTORY_HEADERS)}",
    ]
    proc = run(argv, check=False)
    if proc.returncode != 0:
        if not strict:
            return []

        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        detail = stderr or stdout or f"command failed with exit code {proc.returncode}"
        hint = ""
        if "host:localhost:6819" in detail and not os.environ.get("SLURM_CONF"):
            hint = (
                " (tip: set SLURM_CONF to a user config that points "
                "AccountingStorageHost to your slurmdbd host)"
            )
        die(f"{shlex.join(argv)} failed: {detail}{hint}")

    raw_rows = parse_pipe_rows(proc.stdout, SACCT_HISTORY_HEADERS)
    history: list[dict[str, str]] = []
    for row in raw_rows:
        job_id = (row.get("JobIDRaw") or row.get("JobID") or "").strip()
        if not job_id:
            continue
        normalized = dict(row)
        normalized["JobId"] = job_id
        normalized["StateToken"] = normalize_sacct_state(row.get("State", ""))
        normalized["HistorySource"] = "sacct"
        history.append(normalized)

    history.sort(key=_history_sort_key, reverse=True)

    unique_history: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for row in history:
        job_id = row.get("JobId", "")
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)
        unique_history.append(row)
    return unique_history


def load_job_records(
    job_id: str | None = None, *, strict: bool = True
) -> list[dict[str, Any]]:
    """Jobs slurmctld still knows (all, or one job id), as ``scontrol --json show job`` records."""
    argv = ["scontrol", "--json", "show", "job"]
    # an unknown job id is an answer, not a Slurm failure
    proc = run([*argv, job_id] if job_id else argv, check=strict and job_id is None)
    if proc.returncode != 0:
        return []
    try:
        return json.loads(proc.stdout).get("jobs", [])
    except (ValueError, AttributeError):
        if strict:
            die("this needs a Slurm whose `scontrol --json show job` works", exit_code=2)
        return []


def parse_job_detail_line(line: str) -> dict[str, str]:
    # --details repeats "Nodes=... GRES=..." once per node block; keep them all
    # so callers can pick the block for one node (parse_prop_line keeps the last).
    job = parse_prop_line(line)
    _, sep, blocks = line.partition(" Nodes=")
    if sep:
        job["NodeBlocks"] = blocks
    return job


def job_on_node(job: dict[str, str], node: str) -> dict[str, str]:
    """The job's ``Nodes=... CPU_IDs=... Mem=... GRES=...`` block for one node, or {}."""
    for block in job.get("NodeBlocks", "").split(" Nodes="):
        props = parse_prop_line("Nodes=" + block)
        if node in expand_nodelist(props.get("Nodes", "")):
            return props
    return {}


def job_gres_on_node(job: dict[str, str], node: str) -> str:
    block = job_on_node(job, node)
    return block.get("GRES", "") if block else job.get("GRES", "")


def load_job_details(job_id: str | None = None) -> list[dict[str, str]]:
    """All jobs slurmctld knows, or one job (every task, for an array id)."""
    argv = ["scontrol", "--oneliner", "--details", "show", "job"]
    proc = run([*argv, job_id] if job_id else argv, check=job_id is None)
    if proc.returncode != 0:  # the job ended and dropped out since we looked
        return []
    return [parse_job_detail_line(line) for line in proc.stdout.splitlines() if line.strip()]


def get_job_detail(job_id: str) -> dict[str, str] | None:
    jobs = load_job_details(job_id)
    return jobs[0] if jobs else None


def base_job_id(job_id: str) -> str:
    return job_id.split("_", 1)[0]


# shortcut: past this many jobs one full listing beats one scontrol call per job
USER_JOB_DETAIL_LIMIT = 20


def get_user_jobs(user: str | None = None, *, name: str | None = None) -> list[dict[str, str]]:
    """One user's jobs; squeue filters on the controller, so we skip everyone else's."""
    user = user or current_user()
    argv = ["squeue", "-h", f"--user={user}", "--format=%F"]
    if name:
        argv.append(f"--name={name}")
    # %F: an array's base id, so one scontrol call returns all its tasks
    job_ids = list(dict.fromkeys(run(argv).stdout.split()))
    if len(job_ids) > USER_JOB_DETAIL_LIMIT:
        return [
            job
            for job in load_job_details()
            if user_from_userid(job.get("UserId", "")) == user
            and (not name or job.get("JobName") == name)
        ]
    return [job for job_id in job_ids for job in load_job_details(job_id)]


def load_running_jobs() -> list[dict[str, str]]:
    return [job for job in load_job_details() if job.get("JobState") in RUNNING_STATES]


def load_reservations() -> list[dict[str, str]]:
    proc = run(["scontrol", "--oneliner", "show", "reservation"], check=False)
    if proc.returncode != 0:
        return []
    return [
        parse_prop_line(line)
        for line in proc.stdout.splitlines()
        if line.strip() and "ReservationName=" in line
    ]


# Active reservations older than this are suppressed from the display panel.
RESERVATION_MAX_ACTIVE_DISPLAY_AGE = timedelta(days=30)


def active_reservations(reservations: list[dict[str, str]]) -> list[dict[str, str]]:
    return [r for r in reservations if r.get("State", "").upper() == "ACTIVE"]


def recent_active_reservations(
    reservations: list[dict[str, str]],
    *,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """Active reservations whose start time is within RESERVATION_MAX_ACTIVE_DISPLAY_AGE."""
    reference = now if now is not None else datetime.now()
    result = []
    for r in active_reservations(reservations):
        start = iso_to_dt(r.get("StartTime", ""))
        if start is None or (reference - start) <= RESERVATION_MAX_ACTIVE_DISPLAY_AGE:
            result.append(r)
    return result


def upcoming_reservations(
    reservations: list[dict[str, str]],
    *,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """Return INACTIVE reservations whose start time is in the future."""
    reference = now if now is not None else datetime.now()
    result = []
    for r in reservations:
        if r.get("State", "").upper() != "INACTIVE":
            continue
        start = iso_to_dt(r.get("StartTime", ""))
        if start is not None and start > reference:
            result.append(r)
    return result


SQUEUE_PENDING_HEADERS = ["JobID", "Name", "Partition", "TimeLimit", "Reason"]


def load_user_pending_jobs(user: str | None = None) -> list[dict[str, str]]:
    selected_user = user or current_user()
    proc = run(
        [
            "squeue",
            "-h",
            "--state=PD",
            f"--user={selected_user}",
            "--format=%i|%j|%P|%l|%R",
        ],
        check=False,
    )
    if proc.returncode != 0:
        return []
    return parse_pipe_rows(proc.stdout, SQUEUE_PENDING_HEADERS)


def reservation_blocked_pending_jobs(
    resvs: list[dict[str, str]],
    pending_jobs: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Return pending jobs whose squeue Reason indicates a reservation conflict."""
    resv_names_lower = {
        r.get("ReservationName", "").lower() for r in resvs if r.get("ReservationName")
    }
    blocked = []
    for job in pending_jobs:
        reason = (job.get("Reason") or "").lower()
        if not reason:
            continue
        # Whole words only: a reservation "res" must not match "Resources".
        words = set(re.split(r"[\s,():]+", reason))
        if "reserved for maintenance" in reason or resv_names_lower & words:
            blocked.append(job)
    return blocked


def reserved_nodes_map(reservations: list[dict[str, str]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for resv in reservations:
        nodes_str = resv.get("Nodes", "")
        if is_nullish(nodes_str):
            continue
        resv_name = resv.get("ReservationName", "resv")
        for node in expand_nodelist(nodes_str):
            mapping[node] = resv_name
    return mapping


def user_can_use_reservation(
    reservation: dict[str, str], user: str, groups: set[str]
) -> bool:
    users = reservation.get("Users", "")
    if not is_nullish(users):
        return user in users.split(",")
    res_groups = reservation.get("Groups", "")
    if not is_nullish(res_groups):
        return bool(groups & set(res_groups.split(",")))
    return False


def _eta_delta(iso_value: str, *, now: datetime) -> timedelta | None:
    target = iso_to_dt(iso_value)
    if target is None:
        return None
    return target - now


def get_user_job_etas(
    user: str | None = None,
    *,
    now: datetime | None = None,
) -> tuple[list[timedelta | None], list[timedelta | None]]:
    selected_user = user or current_user()
    jobs = get_user_jobs(selected_user)
    reference = now if now is not None else datetime.now()
    pending: list[timedelta | None] = []
    running: list[timedelta | None] = []
    for job in jobs:
        state = job.get("JobState", "")
        if state == "PENDING":
            pending.append(_eta_delta(job.get("StartTime", ""), now=reference))
        elif state == "RUNNING":
            running.append(_eta_delta(job.get("EndTime", ""), now=reference))
    return pending, running


def get_user_job_history(
    user: str | None = None,
    *,
    finished_only: bool,
    strict: bool = True,
    since: str = "now-30days",
) -> list[dict[str, str]]:
    history = load_job_history(user=user, strict=strict, since=since)
    history = [job for job in history if job.get("JobName") != DEV_JOB_NAME]
    if not finished_only:
        return history
    return [job for job in history if job_state_is_finished(job.get("State", ""))]


def job_history_completion_ids(
    incomplete: str = "", user: str | None = None
) -> list[str]:
    # TAB runs this on every press, so look back only a short window.
    history = get_user_job_history(
        user=user, finished_only=False, strict=False, since="now-2days"
    )
    matches: list[str] = []
    seen: set[str] = set()

    for job in history:
        job_id = job.get("JobId", "")
        if not job_id:
            continue
        candidates = [job_id]
        root_job_id = base_job_id(job_id)
        if root_job_id != job_id:
            candidates.append(root_job_id)

        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            if incomplete and not candidate.startswith(incomplete):
                continue
            seen.add(candidate)
            matches.append(candidate)
    return matches


def is_success_exit_code(exit_code: str) -> bool:
    if not exit_code or ":" not in exit_code:
        return False
    status, signal = exit_code.split(":", 1)
    return status == "0" and signal == "0"


def exit_code_text(exit_code: str) -> Text:
    if is_nullish(exit_code):
        return muted()
    if is_success_exit_code(exit_code):
        return muted(exit_code)
    return Text(exit_code, style="red")


def format_history_end(end_time: str, *, now: datetime | None = None) -> str:
    """``today 08:41``, ``Mon 23:17`` within the week, else the date."""
    end_dt = iso_to_dt(end_time)
    if end_dt is None:
        return "-" if is_nullish(end_time) else end_time
    reference = now if now is not None else datetime.now()
    days = (reference.date() - end_dt.date()).days
    if days == 0:
        return end_dt.strftime("today %H:%M")
    if 0 < days < 7:
        return end_dt.strftime("%a %H:%M")
    if end_dt.year == reference.year:
        return end_dt.strftime("%b %d %H:%M")
    return end_dt.strftime("%Y-%m-%d")


def build_job_history_rows(jobs: list[dict[str, str]]) -> list[TableRow]:
    rows: list[TableRow] = []
    for job in jobs:
        # JobID is 123_7 for array tasks, like ab q shows; JobId is sacct's raw id.
        job_id = job.get("JobID") or job.get("JobId") or job.get("JobIDRaw") or ""
        state = job.get("StateToken") or normalize_sacct_state(job.get("State", ""))
        rows.append(
            [
                job_id_text(job_id),
                truncate(job.get("JobName", ""), 26),
                state_text(state),
                exit_code_text(job.get("ExitCode", "")),
                format_history_end(job.get("End", "")),
            ]
        )
    return rows


def resolve_slurm_output_path(
    template: str,
    job_id: str,
    *,
    raw_id: str = "",
    name: str = "",
    user: str = "",
) -> Path | None:
    """Fill in Slurm's filename patterns (sacct prints them unexpanded)."""
    if is_nullish(template):
        return None
    base_id = base_job_id(job_id)
    values = {
        "J": raw_id or job_id,
        "j": raw_id or base_id,  # %j is an array task's own id, not the array's
        "A": base_id,
        "a": job_id.split("_", 1)[1] if "_" in job_id else "0",
        "x": name,
        "u": user,
    }

    def fill(match: re.Match[str]) -> str:
        width, key = match.groups()
        if key == "%":
            return "%"
        value = values.get(key)
        if value is None:  # pattern we cannot know (%N, %t, ...): keep as is
            return match.group(0)
        return value.zfill(int(width)) if width else value

    resolved = re.sub(r"%(\d*)(.)", fill, template.strip())
    return Path(os.path.expandvars(resolved)).expanduser()


def resolve_job_output_path(
    job_id: str,
    *,
    stream: OutputStream,
    user: str | None = None,
) -> Path | None:
    field = "StdOut" if stream == "stdout" else "StdErr"
    expected_user = user or current_user()

    # No fallback to the array's base id: that record is another task, with its own log.
    detail = get_job_detail(job_id)
    if detail is None:
        # slurmctld forgets finished jobs after MinJobAge; sacct (Slurm 23.02+) keeps the
        # paths, but as unexpanded patterns (--expand-pattern only exists on newer Slurm).
        rows = run_parsable_rows(
            [
                "sacct", "-X", "-n", "-P", "-j", job_id,
                "--format=User,StdOut,StdErr,JobIDRaw,JobName,JobID",
            ],
            ["UserId", "StdOut", "StdErr", "JobIDRaw", "JobName", "JobID"],
            check=False,
        )
        detail = rows[0] if rows else None
    if detail is None:
        return None
    owner = user_from_userid(detail.get("UserId", ""))
    if owner and owner != expected_user:
        return None
    return resolve_slurm_output_path(
        detail.get(field, ""),
        detail.get("JobID") or job_id,  # 123_7 even when asked by raw id, for %A_%a
        raw_id=detail.get("JobIDRaw", ""),
        name=detail.get("JobName", ""),
        user=owner or expected_user,
    )


def read_log_tail(path: Path, *, max_lines: int = DEFAULT_JOB_OUTPUT_TAIL_LINES) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            if max_lines <= 0:
                return handle.read()
            return "".join(deque(handle, maxlen=max_lines))
    except OSError as exc:
        die(f"could not read {path}: {exc}")


def get_job_output(
    job_id: str,
    *,
    stream: OutputStream = "stdout",
    tail_lines: int = DEFAULT_JOB_OUTPUT_TAIL_LINES,
    user: str | None = None,
) -> tuple[Path, str]:
    output_path = resolve_job_output_path(job_id, stream=stream, user=user)
    if output_path is None:
        die(f"could not resolve {stream} path for job {job_id}")
    if not output_path.exists():
        die(f"{stream} file for job {job_id} does not exist yet: {output_path}")
    if not output_path.is_file():
        die(f"{stream} path for job {job_id} is not a file: {output_path}")
    return output_path, read_log_tail(output_path, max_lines=tail_lines)


def find_dev_jobs(
    user: str | None = None, *, job_id: str | None = None
) -> list[dict[str, str]]:
    jobs = [
        job
        for job in get_user_jobs(user, name=DEV_JOB_NAME)
        if job.get("JobName") == DEV_JOB_NAME
        # COMPLETING is a job already on its way out (after `ab dev stop` or --replace).
        and job.get("JobState") in ACTIVE_STATES - {"COMPLETING"}
        and (
            job_id is None
            or job.get("JobId") == job_id
            or base_job_id(job.get("JobId", "")) == base_job_id(job_id)
        )
    ]

    def sort_key(job: dict[str, str]) -> tuple[int, float]:
        state_rank = 0 if job.get("JobState") == "RUNNING" else 1
        submit_time = iso_to_dt(job.get("SubmitTime", ""))
        time_rank = -submit_time.timestamp() if submit_time is not None else 0.0
        return (state_rank, time_rank)

    return sorted(jobs, key=sort_key)


def choose_partition(
    partition_name: str, _gpu_count: int, _cpus: int, time_limit: str
) -> str:
    partitions = {
        item["PartitionName"]: item
        for item in get_accessible_partitions(include_all=True)
    }
    groups = current_groups()
    selected_partition = partition_name
    if partition_name == "auto":
        # No [dev] partition configured: use the partition Slurm marks Default=YES.
        selected_partition = next(
            (name for name, item in partitions.items() if item.get("Default") == "YES"),
            "",
        )
        if not selected_partition:
            accessible = [
                name for name, item in partitions.items() if partition_allowed(item, groups)
            ]
            die(
                "this cluster has no default partition; pass --partition or set "
                f"`partition` in [dev] of {settings.user_config_path()} "
                f"(you can use: {', '.join(accessible) or 'none'})"
            )
    partition = partitions.get(selected_partition)
    if partition is None:
        die(f"unknown partition: {selected_partition}")
    if not partition_allowed(partition, groups):
        die(f"you do not appear to have access to partition {selected_partition}")

    requested_seconds = parse_slurm_time(time_limit)
    max_time = parse_slurm_time(partition.get("MaxTime", "UNLIMITED"))
    if (
        requested_seconds is not None
        and max_time is not None
        and requested_seconds > max_time
    ):
        die(
            f"requested time {time_limit} exceeds the {selected_partition} "
            "partition limit; set --partition explicitly"
        )

    return selected_partition


class NodeFree(TypedDict):
    cpu_total: int
    cpu_free: int
    mem_total_mb: int
    mem_free_mb: int
    gpu_total_by_type: dict[str, int]
    gpu_free_by_type: dict[str, int]


def node_free(node: dict[str, str]) -> NodeFree:
    """Free CPUs, memory (MB, minus SpecMem) and GPUs by type on one node.

    The one place this math lives: `ab free`, `ab info` and `ab why` all use it.
    """
    cpu_total = parse_int(node.get("CPUTot"))
    mem_total = parse_int(node.get("RealMemory")) - parse_int(node.get("SpecMem"))
    total = node_gpu_type_counts(node)
    used = parse_gpu_type_counts(node.get("GresUsed"))
    # Untyped GresUsed on a node with one typed GPU kind belongs to that kind.
    generic_used = used.pop("generic", 0) if "generic" not in total else 0
    if generic_used and len(total) == 1:
        (only_kind,) = total
        used[only_kind] = used.get(only_kind, 0) + generic_used
    return {
        "cpu_total": cpu_total,
        "cpu_free": max(0, cpu_total - parse_int(node.get("CPUAlloc"))),
        "mem_total_mb": mem_total,
        "mem_free_mb": max(0, mem_total - parse_int(node.get("AllocMem"))),
        "gpu_total_by_type": total,
        "gpu_free_by_type": {
            kind: max(0, count - used.get(kind, 0)) for kind, count in total.items()
        },
    }


def _summarize(
    names: list[str],
    nodes: list[dict[str, str]],
    *,
    merged: bool,
) -> dict[str, PartitionStats]:
    wanted = set(names)
    summary = {name: empty_partition_stats() for name in ([""] if merged else names)}
    for node in nodes:
        if not node_is_usable(node):
            continue
        here = [p for p in node.get("Partitions", "").split(",") if p in wanted]
        if not here:
            continue
        free = node_free(node)
        gpu_free = sum(free["gpu_free_by_type"].values())
        is_idle = node_is_idle(node)
        is_schedulable = is_idle or node_is_mixed(node)
        for name in [""] if merged else here:
            bucket = summary[name]
            bucket["nodes"] += 1
            bucket["idle_nodes"] += int(is_idle)
            bucket["cpu_total"] += free["cpu_total"]
            bucket["cpu_free"] += free["cpu_free"]
            bucket["mem_total_gb"] += round(free["mem_total_mb"] / 1024)
            bucket["mem_free_gb"] += round(free["mem_free_mb"] / 1024)
            bucket["gpu_total"] += sum(free["gpu_total_by_type"].values())
            bucket["gpu_free"] += gpu_free
            add_gpu_type_counts(bucket["gpu_total_by_type"], free["gpu_total_by_type"])
            add_gpu_type_counts(bucket["gpu_free_by_type"], free["gpu_free_by_type"])
            if is_schedulable:
                bucket["gpu_usable"] += gpu_free
                add_gpu_type_counts(bucket["gpu_usable_by_type"], free["gpu_free_by_type"])
    return summary


def summarize_partitions(
    names: list[str],
    *,
    nodes: list[dict[str, str]] | None = None,
) -> dict[str, PartitionStats]:
    return _summarize(names, nodes if nodes is not None else load_nodes(), merged=False)


def summarize_selected_partitions(
    partition_names: set[str],
    *,
    nodes: list[dict[str, str]] | None = None,
) -> PartitionStats:
    if not partition_names:
        return empty_partition_stats()
    visible = nodes if nodes is not None else load_nodes()
    return _summarize(sorted(partition_names), visible, merged=True)[""]


def build_dev_job_rows(jobs: list[dict[str, str]]) -> list[TableRow]:
    rows: list[TableRow] = []
    for job in jobs:
        job_id = display_job_id(job)
        state = job.get("JobState", "")
        partition = job.get("Partition", "")
        node = job.get("NodeList", "")
        cpus = str(parse_int(job.get("NumCPUs")))
        mem = format_mem_value(job.get("Mem", job.get("MinMemoryNode", "")))
        gpus = str(
            parse_gpu_count(job.get("JOB_GRES"))
            or parse_gpu_count(job.get("TresPerNode"))
            or parse_gpu_count(job.get("GRES"))
        )
        detail = (
            format_eta(job.get("EndTime", ""))
            if state == "RUNNING"
            else muted(job.get("Reason", "") or "-")
        )
        rows.append(
            [
                job_id_text(job_id),
                state_text(state),
                partition_text(partition),
                muted() if is_nullish(node) else node_text(truncate(node, 18), partition),
                cpus,
                mem,
                gpus,
                detail,
            ]
        )
    return rows
