"""Match a pending job's request against the free capacity of each node.

Everything here is pure: callers load the Slurm data (``core.load_job_records``,
``core.load_nodes``, ``core.load_partitions``) and pass it in.

Requests are read from ``scontrol --json show job`` records. Memory and CPUs come from the
per-unit fields (``memory_per_tres``, ``memory_per_cpu``, ``cpus_per_tres``) rather than
``tres_req_str``: after ``scontrol update`` the latter keeps its old memory value, while
the scheduler allocates from the per-unit fields.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal, TypeAlias

from allegro_buddy.core import (
    BAD_NODE_FLAGS,
    canonical_gpu_type,
    expand_hostlist,
    infer_gpu_type_from_features,
    node_free,
    parse_int,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

Dim: TypeAlias = Literal['gpus', 'cpus', 'mem']
MemMode: TypeAlias = Literal['node', 'cpu', 'gpu']

DIMS: tuple[Dim, ...] = ('gpus', 'cpus', 'mem')
# Ties in "which resource binds" go to the scarcest one first.
BOTTLENECK_ORDER: tuple[Dim, ...] = ('gpus', 'mem', 'cpus')
DIM_LABELS: dict[Dim, str] = {'gpus': 'GPU', 'cpus': 'CPU', 'mem': 'mem'}
HINT_REASONS = frozenset({'Resources', 'Priority'})
MAX_SLOTS = 5
# Slurm reports "no limit" as INT64_MAX-like values.
UNLIMITED_THRESHOLD = 2**62

SKIP_DOWN = 'down or drained'
SKIP_FEATURE = 'missing feature'
SKIP_GPU = 'no matching GPU'
SKIP_EXCLUDED = 'excluded'
SKIP_NOT_REQUESTED = 'not in requested nodes'
SKIP_OUTSIDE_RESERVATION = 'outside its reservation'
RESERVATION_PREFIX = 'reservation '
_SHORT_SKIPS = {SKIP_DOWN: 'down', SKIP_OUTSIDE_RESERVATION: 'outside reservation'}
_UNUSABLE_FLAGS = (*BAD_NODE_FLAGS, 'NOT_RESPONDING')

_GRES_GPU = re.compile(r'gres/gpu(?::(?P<type>[^:,=]+))?[:=](?P<count>\d+)')
_MEM_TOKEN = re.compile(r'(?P<value>\d+(?:\.\d+)?)(?P<unit>[KMGTP]?)', re.IGNORECASE)
_MEM_UNITS_MB = {'K': 1 / 1024, '': 1, 'M': 1, 'G': 1024, 'T': 1024**2, 'P': 1024**3}
_SIMPLE_FEATURE = re.compile(r'^[A-Za-z0-9_.-]+$')


# ---------------------------------------------------------------------------
# Small parsers and formatters
# ---------------------------------------------------------------------------


def _number(record: dict[str, Any], key: str) -> int | None:
    """Read Slurm's ``{"set": ..., "number": ...}`` wrapper; None when unset."""
    value = record.get(key)
    if isinstance(value, dict):
        if not value.get('set') or value.get('infinite'):
            return None
        return int(value.get('number', 0))
    if isinstance(value, int):
        return value
    return None


def _gres_gpu(spec: str | None) -> tuple[str | None, int]:
    """``gres/gpu:RTX-A5000:4`` -> ``('RTX-A5000', 4)``; no GPU chunk -> ``(None, 0)``."""
    match = _GRES_GPU.search(spec or '')
    if match is None:
        return None, 0
    return match.group('type'), int(match.group('count'))


def _with_gpu_count(spec: str, count: int) -> str:
    """Replace the GPU count in a TRES spec, keeping its type and any other entries."""

    def replace_count(match: re.Match[str]) -> str:
        return match.group(0)[: match.start('count') - match.start()] + str(count)

    return _GRES_GPU.sub(replace_count, spec, count=1)


def _tres(spec: str | None) -> dict[str, str]:
    pairs = (item.partition('=') for item in (spec or '').split(','))
    return {key: value for key, sep, value in pairs if sep}


def mem_to_mb(token: str) -> int:
    """``40G`` -> 40960; unparseable -> 0."""
    match = _MEM_TOKEN.fullmatch(token.strip())
    if match is None:
        return 0
    factor = _MEM_UNITS_MB[match.group('unit').upper()]
    return math.ceil(float(match.group('value')) * factor)


def format_mem(mb: int) -> str:
    """Exact memory: ``40960`` -> ``40G``, ``1536`` -> ``1536M``."""
    if mb >= 1024 and mb % 1024 == 0:
        return f'{mb // 1024}G'
    return f'{mb}M'


def round_down_mb(mb: int) -> int:
    """Whole GB once at least 1G, so a suggestion never promises more than is free."""
    return mb // 1024 * 1024 if mb >= 1024 else mb


def _array_ranges(spec: str) -> Iterator[range]:
    for item in spec.split('%', 1)[0].split(','):
        span, _, step = item.partition(':')
        start, _, end = span.partition('-')
        try:
            yield range(int(start), int(end or start) + 1, int(step or 1))
        except ValueError:
            continue


def count_array_tasks(spec: str) -> int:
    """Tasks in ``0-11``, ``1,3,5-7``, ``0-10:2`` or ``0-11%2`` (the throttle is ignored)."""
    return sum(len(span) for span in _array_ranges(spec))


def _features(spec: str | None) -> tuple[frozenset[str], ...] | None:
    """Alternatives of required node features.

    ``()`` means no constraint and ``None`` an expression this module does not evaluate
    (brackets, counts, or ``&`` mixed with ``|``).
    """
    text = (spec or '').strip()
    if not text:
        return ()
    if '&' in text and '|' in text:
        return None
    if '|' in text:
        tokens = text.split('|')
        if all(_SIMPLE_FEATURE.match(token) for token in tokens):
            return tuple(frozenset({token}) for token in tokens)
        return None
    tokens = re.split(r'[&,]', text)
    if all(_SIMPLE_FEATURE.match(token) for token in tokens):
        return (frozenset(tokens),)
    return None


def mem_per_cpu_limits(partitions: list[dict[str, str]]) -> dict[str, int | None]:
    """``MaxMemPerCPU`` in MB per partition; None when the partition has no such limit."""
    limits: dict[str, int | None] = {}
    for partition in partitions:
        value = parse_int(partition.get('MaxMemPerCPU'))
        limits[partition.get('PartitionName', '')] = (
            value if 0 < value < UNLIMITED_THRESHOLD else None
        )
    return limits


def find_record(records: list[dict[str, Any]], jobid: str) -> dict[str, Any] | None:
    """Find a job by ``65177``, ``65177_[0-11]`` or ``65177_3``; pending records win."""
    wanted = jobid.strip()
    for record in records:
        if str(record.get('job_id', '')) == wanted:
            return record

    base, _, task = wanted.partition('_')
    task = task.strip('[]')
    matches: list[dict[str, Any]] = []
    for record in records:
        if str(_number(record, 'array_job_id') or '') != base:
            continue
        array_task = _number(record, 'array_task_id')
        spec = record.get('array_task_string') or ''
        if (
            not task
            or task == spec
            or (array_task is not None and str(array_task) == task)
            or (
                spec
                and task.isdigit()
                and any(int(task) in s for s in _array_ranges(spec))
            )
        ):
            matches.append(record)
    pending = [
        record for record in matches if 'PENDING' in (record.get('job_state') or [])
    ]
    return (pending or matches or [None])[0]


# ---------------------------------------------------------------------------
# Resource vectors and nodes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Amount:
    """Resources on one node: GPUs, CPUs and memory in MB."""

    gpus: int
    cpus: int
    mem: int

    def covers(self, need: Amount) -> bool:
        return all(getattr(self, dim) >= getattr(need, dim) for dim in DIMS)

    def short_of(self, need: Amount) -> tuple[Dim, ...]:
        return tuple(dim for dim in DIMS if getattr(self, dim) < getattr(need, dim))


@dataclass(frozen=True)
class NodeCapacity:
    """A node's totals and what is still free, from a ``core.load_nodes()`` dict."""

    name: str
    state: str
    partitions: frozenset[str]
    features: frozenset[str]
    reservation: str
    cpus_total: int
    cpus_free: int
    mem_total: int
    mem_free: int
    gpus_total: tuple[tuple[str, int], ...]
    gpus_free: tuple[tuple[str, int], ...]

    @classmethod
    def from_node(cls, node: dict[str, str]) -> NodeCapacity:
        free = node_free(node)
        return cls(
            name=node.get('NodeName', ''),
            state=node.get('State', '').upper(),
            partitions=frozenset(
                part for part in node.get('Partitions', '').split(',') if part
            ),
            features=frozenset(
                feat for feat in node.get('ActiveFeatures', '').split(',') if feat
            ),
            reservation=node.get('Reservation', ''),
            cpus_total=free['cpu_total'],
            cpus_free=free['cpu_free'],
            mem_total=free['mem_total_mb'],
            mem_free=free['mem_free_mb'],
            gpus_total=tuple(sorted(free['gpu_total_by_type'].items())),
            gpus_free=tuple(sorted(free['gpu_free_by_type'].items())),
        )

    @property
    def planned(self) -> bool:
        """Backfill has set the node aside for another job."""
        return 'PLANNED' in self.state

    def gpus(self, kind: str | None, *, free: bool) -> int:
        """GPUs of one canonical type (all types for None), free or in total."""
        counts = self.gpus_free if free else self.gpus_total
        return sum(
            count for gpu_kind, count in counts if kind is None or gpu_kind == kind
        )


# ---------------------------------------------------------------------------
# The request
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JobRequest:
    """What a pending job asks for on each node, and how it was asked for."""

    job_id: str
    display_id: str
    update_id: str
    user: str
    state: str
    reason: str
    partitions: tuple[str, ...]
    node_count: int
    gpus: int
    gpu_type: str | None
    gpu_kind: str | None
    cpus: int
    cpus_per_gpu: int | None
    min_cpus: int
    mem_mode: MemMode
    mem_value: int
    tres_per_node: str
    gpus_per_job: bool
    features: tuple[frozenset[str], ...] | None
    excluded: frozenset[str]
    required: frozenset[str]
    reservation: str
    exclusive: bool
    het: bool
    pending_tasks: int
    planned_nodes: str
    planned_start: int | None

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> JobRequest:
        job_id = str(record.get('job_id', ''))
        array_job = _number(record, 'array_job_id') or 0
        array_task = _number(record, 'array_task_id')
        task_spec = record.get('array_task_string') or ''
        if task_spec:
            display_id, update_id = f'{array_job}_[{task_spec}]', str(array_job)
            pending_tasks = count_array_tasks(task_spec)
        elif array_job and array_task is not None:
            display_id = update_id = f'{array_job}_{array_task}'
            pending_tasks = 1
        else:
            display_id = update_id = job_id
            pending_tasks = 1

        node_count = max(1, _number(record, 'node_count') or 1)
        tres_per_node = record.get('tres_per_node') or ''
        gpu_type, gpus = _gres_gpu(tres_per_node)
        gpus_per_job = False
        if not gpus:
            _, per_job = _gres_gpu(record.get('tres_per_job'))
            _, per_task = _gres_gpu(record.get('tres_per_task'))
            tasks = _number(record, 'tasks') or 1
            gpus = math.ceil((per_job or per_task * tasks) / node_count)
            gpus_per_job = gpus > 0

        feature_spec = record.get('features') or ''
        gpu_kind = canonical_gpu_type(gpu_type) if gpu_type else None
        if gpus and gpu_kind is None and '|' not in feature_spec:
            gpu_kind = infer_gpu_type_from_features(re.sub('&', ',', feature_spec))

        tres = _tres(record.get('tres_req_str'))
        _, cpus_per_gpu = _gres_gpu(record.get('cpus_per_tres'))
        total_cpus = _number(record, 'cpus') or parse_int(tres.get('cpu'), 1)
        min_cpus = _number(record, 'minimum_cpus_per_node') or 1
        # A pending job's `cpus` can sit below cpus_per_tres x GPUs, which is what it is
        # allocated (64665: cpus 2 with 4 CPUs per GPU; its twin 64664 got 4).
        cpus = max(math.ceil(total_cpus / node_count), min_cpus, cpus_per_gpu * gpus)

        _, mem_per_gpu = _gres_gpu(record.get('memory_per_tres'))
        mem_per_cpu = _number(record, 'memory_per_cpu')
        mem_per_node = _number(record, 'memory_per_node')
        mem_mode: MemMode
        if mem_per_gpu and gpus:
            mem_mode, mem_value = 'gpu', mem_per_gpu
        elif mem_per_cpu:
            mem_mode, mem_value = 'cpu', mem_per_cpu
        elif mem_per_node is not None:
            mem_mode, mem_value = 'node', mem_per_node
        else:
            mem_mode = 'node'
            mem_value = math.ceil(mem_to_mb(tres.get('mem', '0')) / node_count)

        return cls(
            job_id=job_id,
            display_id=display_id,
            update_id=update_id,
            user=record.get('user_name') or '',
            state=(record.get('job_state') or [''])[0],
            reason=record.get('state_reason') or '',
            partitions=tuple(
                part for part in (record.get('partition') or '').split(',') if part
            ),
            node_count=node_count,
            gpus=gpus,
            gpu_type=gpu_type,
            gpu_kind=gpu_kind if gpus else None,
            cpus=cpus,
            cpus_per_gpu=cpus_per_gpu or None,
            min_cpus=min_cpus,
            mem_mode=mem_mode,
            mem_value=mem_value,
            tres_per_node=tres_per_node,
            gpus_per_job=gpus_per_job,
            features=_features(feature_spec),
            excluded=expand_hostlist(record.get('excluded_nodes')),
            required=expand_hostlist(record.get('required_nodes')),
            reservation=record.get('resv_name') or '',
            exclusive='none' in (record.get('shared') or []),
            het=bool(_number(record, 'het_job_id')),
            pending_tasks=pending_tasks,
            planned_nodes=record.get('scheduled_nodes') or '',
            planned_start=_number(record, 'start_time') or None,
        )

    @property
    def whole_node_mem(self) -> bool:
        """``--mem=0``: the job wants all of a node's memory."""
        return self.mem_mode == 'node' and self.mem_value == 0

    def mem_for(self, gpus: int, cpus: int) -> int:
        if self.mem_mode == 'gpu':
            return self.mem_value * gpus
        if self.mem_mode == 'cpu':
            return self.mem_value * cpus
        return self.mem_value

    @property
    def amount(self) -> Amount:
        """The per-node request, before node-specific adjustments."""
        return Amount(self.gpus, self.cpus, self.mem_for(self.gpus, self.cpus))

    def need_on(self, node: NodeCapacity, mem_per_cpu_limit: int | None = None) -> Amount:
        """What the job needs on this node, including Slurm's own adjustments."""
        mem = (
            node.mem_total if self.whole_node_mem else self.mem_for(self.gpus, self.cpus)
        )
        cpus = self.cpus
        if mem_per_cpu_limit:
            # Slurm raises the CPU count until memory per CPU fits under MaxMemPerCPU.
            cpus = max(cpus, math.ceil(mem / mem_per_cpu_limit))
        need = Amount(self.gpus, cpus, mem)
        if self.exclusive:
            # The whole node, which must also be big enough for the request.
            total = self.total_on(node)
            return Amount(
                max(need.gpus, total.gpus),
                max(need.cpus, total.cpus),
                max(need.mem, total.mem),
            )
        return need

    def free_on(self, node: NodeCapacity) -> Amount:
        gpus = node.gpus(self.gpu_kind, free=True) if self.gpus else 0
        return Amount(gpus, node.cpus_free, node.mem_free)

    def total_on(self, node: NodeCapacity) -> Amount:
        gpus = node.gpus(self.gpu_kind, free=False) if self.gpus else 0
        return Amount(gpus, node.cpus_total, node.mem_total)

    def knob_value(self, knob: Dim) -> int:
        """The current value in the unit the job was submitted with."""
        if knob == 'mem':
            return self.mem_value
        if knob == 'cpus':
            return self.cpus_per_gpu or self.cpus
        return self.gpus

    def with_knob(self, knob: Dim, value: int) -> JobRequest:
        """The request after changing one knob, with Slurm's couplings applied.

        ``minimum_cpus_per_node`` stays as a floor: neither ``TresPerNode`` nor
        ``CpusPerTres`` lowers it. Without ``--cpus-per-gpu`` a CPU change is advice to
        resubmit, which would lower the floor too.
        """
        if knob == 'mem':
            return replace(self, mem_value=value)
        if knob == 'cpus':
            if self.cpus_per_gpu:
                cpus = max(value * self.gpus, self.min_cpus)
                return replace(self, cpus_per_gpu=value, cpus=cpus)
            return replace(self, cpus=value, min_cpus=min(self.min_cpus, value))
        cpus = (
            max(self.cpus_per_gpu * value, self.min_cpus)
            if self.cpus_per_gpu
            else self.cpus
        )
        return replace(self, gpus=value, cpus=cpus)

    def knob_flag(self, knob: Dim) -> str:
        """How the user asked for this knob, e.g. ``--mem-per-gpu``."""
        if knob == 'mem':
            return {'node': '--mem', 'cpu': '--mem-per-cpu', 'gpu': '--mem-per-gpu'}[
                self.mem_mode
            ]
        if knob == 'cpus':
            return '--cpus-per-gpu' if self.cpus_per_gpu else 'CPUs'
        return 'GPUs'

    def update_command(self, knob: Dim, value: int) -> list[str] | None:
        """The ``scontrol update`` that changes this knob in place, if there is one.

        Only the field matching how the job was submitted is touched: setting
        ``MinMemoryNode`` on a ``--mem-per-gpu`` job leaves ``MemPerTres`` in place and
        the job with two contradictory memory specs.

        CPUs change in place only through ``CpusPerTres``. On a ``-c 4`` job,
        ``NumCPUs`` leaves ``MinCPUsNode`` and ``CPUsPerTask`` at 4, and
        ``CPUsPerTask`` leaves ``NumCPUs`` at 4, so those jobs have to be resubmitted.
        """
        if knob == 'mem':
            field = {
                'node': f'MinMemoryNode={value}',
                'cpu': f'MinMemoryCPU={value}',
                'gpu': f'MemPerTres=gres/gpu:{value}',
            }[self.mem_mode]
        elif knob == 'cpus':
            if not self.cpus_per_gpu:
                return None
            field = f'CpusPerTres=gres/gpu:{value}'
        else:
            if self.gpus_per_job or not _GRES_GPU.search(self.tres_per_node):
                return None
            field = f'TresPerNode={_with_gpu_count(self.tres_per_node, value)}'
        return ['scontrol', 'update', f'JobId={self.update_id}', field]


# ---------------------------------------------------------------------------
# The diagnosis
# ---------------------------------------------------------------------------


def skip_reason(request: JobRequest, node: NodeCapacity) -> str | None:
    """Why a node in one of the job's partitions cannot take the job at all, or None."""
    flags = _UNUSABLE_FLAGS
    if request.reservation:
        if node.reservation != request.reservation:
            return SKIP_OUTSIDE_RESERVATION
        # Maintenance reservations flag their nodes MAINT; members may still use them.
        flags = tuple(flag for flag in flags if flag != 'MAINT')
    elif node.reservation:
        return RESERVATION_PREFIX + node.reservation
    if any(flag in node.state for flag in flags):
        return SKIP_DOWN
    if node.name in request.excluded:
        return SKIP_EXCLUDED
    if request.required and node.name not in request.required:
        return SKIP_NOT_REQUESTED
    if request.features and not any(
        alternative <= node.features for alternative in request.features
    ):
        return SKIP_FEATURE
    if request.gpus and node.gpus(request.gpu_kind, free=False) == 0:
        return SKIP_GPU
    return None


@dataclass(frozen=True)
class NodeFit:
    """One eligible node: what the job needs there, what is free, and the totals."""

    node: NodeCapacity
    need: Amount
    free: Amount
    total: Amount
    limit: int | None

    @property
    def short(self) -> tuple[Dim, ...]:
        return self.free.short_of(self.need)

    @property
    def fits(self) -> bool:
        return self.free.covers(self.need)

    @property
    def holds(self) -> bool:
        """The node could take the job once it is empty."""
        return self.total.covers(self.need)


@dataclass(frozen=True)
class Fix:
    """The largest value of one knob that lets the job start right now."""

    knob: Dim
    old: int
    new: int
    request: JobRequest
    nodes: tuple[str, ...]
    command: list[str] | None

    @property
    def cut(self) -> float:
        """How much of the knob the user gives up, as a fraction."""
        return (self.old - self.new) / self.old


@dataclass(frozen=True)
class Slot:
    """A free amount (memory rounded down) no other eligible node beats outright."""

    free: Amount
    nodes: tuple[str, ...]


@dataclass(frozen=True)
class Diagnosis:
    request: JobRequest
    rows: tuple[NodeFit, ...]
    skipped: tuple[tuple[str, int], ...]
    fixes: tuple[Fix, ...]
    slots: tuple[Slot, ...]

    @property
    def fits(self) -> tuple[str, ...]:
        return tuple(row.node.name for row in self.rows if row.fits)

    @property
    def fits_now(self) -> bool:
        return bool(self.rows) and len(self.fits) >= self.request.node_count

    @property
    def never_fits(self) -> bool:
        holding = sum(row.holds for row in self.rows)
        return bool(self.rows) and holding < self.request.node_count

    @property
    def unavailable(self) -> tuple[tuple[str, int], ...]:
        """Skipped nodes of the right kind that are reserved or down.

        Nodes with another GPU type or missing features are not capacity the job is
        missing out on, so they stay out of this count.
        """
        return tuple(
            (reason, count)
            for reason, count in self.skipped
            if reason.startswith(RESERVATION_PREFIX)
            or reason in (SKIP_DOWN, SKIP_OUTSIDE_RESERVATION)
        )

    @property
    def planned(self) -> frozenset[str]:
        return frozenset(row.node.name for row in self.rows if row.node.planned)

    @property
    def dims(self) -> tuple[Dim, ...]:
        """The resources this job asks for (GPUs only for GPU jobs)."""
        return tuple(dim for dim in DIMS if dim != 'gpus' or self.request.gpus)

    def short_count(self, dim: Dim) -> int:
        return sum(dim in row.short for row in self.rows)

    def best_free(self, dim: Dim) -> int:
        return max((getattr(row.free, dim) for row in self.rows), default=0)

    def max_total(self, dim: Dim) -> int:
        return max((getattr(row.total, dim) for row in self.rows), default=0)

    @property
    def bottleneck(self) -> Dim:
        """The resource short on the most eligible nodes."""
        order = [dim for dim in BOTTLENECK_ORDER if dim in self.dims]
        return max(order, key=lambda dim: (self.short_count(dim), -order.index(dim)))

    def fix_for(self, knob: Dim) -> Fix | None:
        return next((fix for fix in self.fixes if fix.knob == knob), None)

    def lead_fix(self) -> Fix | None:
        """The fix ``ab q`` and ``ab why`` lead with, and plain ``--fix`` applies.

        Fixes Slurm can apply in place come first, then the smallest cut. GPU-count
        changes come after memory and CPUs: job scripts usually hard-code the number
        of GPUs (``torchrun --nproc_per_node=4``).
        """
        return min(
            self.fixes,
            key=lambda fix: (fix.command is None, fix.knob == 'gpus', fix.cut),
            default=None,
        )


def _limit_for(
    node: NodeCapacity,
    partitions: tuple[str, ...],
    limits: Mapping[str, int | None],
) -> int | None:
    """The most permissive ``MaxMemPerCPU`` among the partitions the node shares."""
    values = [
        limits.get(partition) for partition in partitions if partition in node.partitions
    ]
    known = [value for value in values if value is not None]
    if not values or len(known) < len(values):
        return None
    return max(known)


def _fits_with(request: JobRequest, row: NodeFit) -> bool:
    return request.free_on(row.node).covers(request.need_on(row.node, row.limit))


def _candidates(request: JobRequest, rows: Sequence[NodeFit], knob: Dim) -> list[int]:
    """Values below the current one to try for a knob, largest first."""
    old = request.knob_value(knob)
    if knob != 'mem':
        return list(range(old - 1, 0, -1))
    values: set[int] = set()
    for row in rows:
        per_unit = row.free.mem
        if request.mem_mode == 'cpu':
            per_unit //= max(1, row.need.cpus)
        elif request.mem_mode == 'gpu':
            per_unit //= max(1, request.gpus)
        value = round_down_mb(per_unit)
        if 0 < value < old:
            values.add(value)
    return sorted(values, reverse=True)


def _best_fix(request: JobRequest, rows: Sequence[NodeFit], knob: Dim) -> Fix | None:
    if knob == 'gpus' and not request.gpus:
        return None
    if knob == 'cpus' and request.cpus_per_gpu and not request.gpus:
        return None
    if knob == 'mem' and request.whole_node_mem:
        return None
    for value in _candidates(request, rows, knob):
        changed = request.with_knob(knob, value)
        nodes = tuple(row.node.name for row in rows if _fits_with(changed, row))
        if len(nodes) >= request.node_count:
            return Fix(
                knob=knob,
                old=request.knob_value(knob),
                new=value,
                request=changed,
                nodes=nodes,
                command=request.update_command(knob, value),
            )
    return None


def _slots(request: JobRequest, rows: Sequence[NodeFit]) -> tuple[Slot, ...]:
    groups: dict[Amount, list[str]] = {}
    for row in rows:
        free = Amount(row.free.gpus, row.free.cpus, round_down_mb(row.free.mem))
        if (request.gpus and not free.gpus) or not free.cpus or not free.mem:
            continue
        groups.setdefault(free, []).append(row.node.name)
    frontier = [
        amount
        for amount in groups
        if not any(other != amount and other.covers(amount) for other in groups)
    ]
    frontier.sort(key=lambda amount: (-amount.gpus, -amount.cpus, -amount.mem))
    return tuple(Slot(amount, tuple(groups[amount])) for amount in frontier[:MAX_SLOTS])


def diagnose(
    request: JobRequest,
    nodes: Sequence[NodeCapacity],
    mem_per_cpu_limits: Mapping[str, int | None] | None = None,
) -> Diagnosis:
    """Compare the request with every node in the job's partitions."""
    limits = mem_per_cpu_limits or {}
    wanted = set(request.partitions)
    rows: list[NodeFit] = []
    skipped: Counter[str] = Counter()
    for node in nodes:
        if not node.partitions & wanted:
            continue
        reason = skip_reason(request, node)
        if reason is not None:
            skipped[reason] += 1
            continue
        limit = _limit_for(node, request.partitions, limits)
        rows.append(
            NodeFit(
                node=node,
                need=request.need_on(node, limit),
                free=request.free_on(node),
                total=request.total_on(node),
                limit=limit,
            )
        )
    diagnosis = Diagnosis(
        request=request,
        rows=tuple(rows),
        skipped=tuple(skipped.most_common()),
        fixes=(),
        slots=_slots(request, rows),
    )
    if diagnosis.fits_now or request.exclusive:
        return diagnosis
    fixes = tuple(
        fix
        for knob in ('mem', 'cpus', 'gpus')
        if (fix := _best_fix(request, rows, knob)) is not None
    )
    return replace(diagnosis, fixes=fixes)


# ---------------------------------------------------------------------------
# Wording shared by `ab q` and `ab why`
# ---------------------------------------------------------------------------


def join_names(names: Sequence[str], limit: int = 1) -> str:
    """``gpu110 +2``: the first names and how many more there are."""
    shown = ', '.join(names[:limit])
    return f'{shown} +{len(names) - limit}' if len(names) > limit else shown


def format_free(dim: Dim, value: int) -> str:
    """A free amount; memory rounded down so it never overstates what is there."""
    return format_mem(round_down_mb(value)) if dim == 'mem' else str(value)


def format_need(dim: Dim, value: int) -> str:
    return format_mem(value) if dim == 'mem' else str(value)


def _plural(count: int, word: str) -> str:
    return f'{count} {word}' if count == 1 else f'{count} {word}s'


def skip_summary(skipped: tuple[tuple[str, int], ...], *, short: bool) -> str:
    """``2 reserved, 1 down`` (short) or ``2 in reservation maint, ...`` (long)."""
    if not short:
        return ', '.join(
            f'{count} in {reason}'
            if reason.startswith(RESERVATION_PREFIX)
            else f'{count} {reason}'
            for reason, count in skipped
        )
    totals: Counter[str] = Counter()
    for reason, count in skipped:
        label = 'reserved' if reason.startswith(RESERVATION_PREFIX) else reason
        totals[_SHORT_SKIPS.get(label, label)] += count
    return ', '.join(f'{count} {label}' for label, count in totals.items())


def never_fits_reason(diagnosis: Diagnosis) -> str:
    """Why no eligible node could ever hold the request, e.g. ``max 16 CPUs/node``."""
    need = diagnosis.request.amount
    units = {'gpus': ' GPUs', 'cpus': ' CPUs', 'mem': ''}
    for dim in BOTTLENECK_ORDER:
        if dim in diagnosis.dims and getattr(need, dim) > diagnosis.max_total(dim):
            return f'max {format_free(dim, diagnosis.max_total(dim))}{units[dim]}/node'
    if diagnosis.request.node_count > 1:
        holding = sum(row.holds for row in diagnosis.rows)
        return f'needs {diagnosis.request.node_count} nodes, {holding} are big enough'
    return 'no node is big enough in every resource at once'


def fix_phrase(fix: Fix) -> str:
    """The change in a few words: ``mem ≤ 9G``, ``≤ 3 CPUs/GPU``, ``≤ 2 GPUs``."""
    if fix.knob == 'mem':
        unit = {'node': '', 'cpu': '/CPU', 'gpu': '/GPU'}[fix.request.mem_mode]
        return f'mem ≤ {format_mem(fix.new)}{unit}'
    if fix.knob == 'cpus':
        if fix.request.cpus_per_gpu:
            return f'≤ {fix.new} CPUs/GPU'
        return f'≤ {_plural(fix.new, "CPU")}'
    return f'≤ {_plural(fix.new, "GPU")}'


def queue_hint(diagnosis: Diagnosis) -> str:
    """One phrase for the ``Node/Reason`` cell of ``ab q``."""
    request = diagnosis.request
    if not diagnosis.rows:
        summary = skip_summary(diagnosis.skipped, short=True)
        return f'no usable nodes ({summary})' if summary else 'no usable nodes'
    if diagnosis.never_fits:
        return f'never fits: {never_fits_reason(diagnosis)}'
    if diagnosis.fits_now:
        if request.reason == 'Priority':
            return 'fits now · held for higher prio'
        return f'fits now on {join_names(diagnosis.fits)}'
    fix = diagnosis.lead_fix()
    if fix is not None:
        return f'starts now w/ {fix_phrase(fix)}'
    dim = diagnosis.bottleneck
    best = format_free(dim, diagnosis.best_free(dim))
    need = format_need(dim, getattr(request.amount, dim))
    return f'{DIM_LABELS[dim]}-bound · max {best}/{need} free'
