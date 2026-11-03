from __future__ import annotations

import shlex
import sys
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypeAlias

import click
from rich.text import Text

from allegro_buddy.core import (
    CLI_NAME,
    CONSOLE,
    TableRow,
    base_job_id,
    current_user,
    die,
    format_pending_start,
    gpu_type_label,
    hint,
    job_id_text,
    load_job_records,
    load_nodes,
    load_partitions,
    muted,
    partition_text,
    render_table,
    run,
    state_text,
    warn,
)
from allegro_buddy.fit import (
    HINT_REASONS,
    JobRequest,
    NodeCapacity,
    diagnose,
    find_record,
    format_free,
    format_mem,
    join_names,
    mem_per_cpu_limits,
    never_fits_reason,
    queue_hint,
    skip_summary,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from allegro_buddy.core import JustifyMethod
    from allegro_buddy.fit import Diagnosis, Dim, Fix

Inputs: TypeAlias = tuple[list[dict[str, Any]], list[NodeCapacity], dict[str, int | None]]

ROW_LABELS: dict[Dim, str] = {'gpus': 'GPU', 'cpus': 'CPU', 'mem': 'Mem'}


def load_inputs(*, strict: bool = True, job_id: str | None = None) -> Inputs:
    """Job records (all, or one job's), node capacities and partition memory limits."""
    records = load_job_records(job_id, strict=strict)
    nodes = [NodeCapacity.from_node(node) for node in load_nodes(strict=strict)]
    limits = mem_per_cpu_limits(load_partitions(strict=strict))
    return records, nodes, limits


def queue_hints(job_ids: set[str]) -> tuple[dict[str, str], str | None]:
    """Bottleneck hint per raw job id for ``ab q``, or why there are none."""
    try:
        records, nodes, limits = load_inputs(strict=False)
        if not records or not nodes:
            return {}, 'scontrol returned no job or node data'
        hints: dict[str, str] = {}
        for record in records:
            job_id = str(record.get('job_id', ''))
            if job_id in job_ids:
                request = JobRequest.from_record(record)
                hints[job_id] = queue_hint(diagnose(request, nodes, limits))
    except Exception as exc:  # the hints decorate `ab q`; they must never break it
        return {}, f'{type(exc).__name__}: {exc}'
    return hints, None


# ---------------------------------------------------------------------------
# Wording
# ---------------------------------------------------------------------------

PROSE_LABELS: dict[Dim, str] = {'gpus': 'GPUs', 'cpus': 'CPUs', 'mem': 'memory'}


def _gpu_label(request: JobRequest) -> str:
    return gpu_type_label(request.gpu_kind) if request.gpu_kind else 'GPU'


def describe_request(request: JobRequest, *, detailed: bool = False) -> str:
    """``4x A5000 · 16 CPU · 40G``; detailed adds the per-CPU/per-GPU settings."""
    parts: list[str] = []
    if request.gpus:
        parts.append(f'{request.gpus}x {_gpu_label(request)}')
    cpus = f'{request.cpus} CPU'
    if detailed and request.cpus_per_gpu:
        cpus += f' ({request.cpus_per_gpu}/GPU)'
    parts.append(cpus)
    if request.whole_node_mem:
        parts.append('all memory')
    else:
        mem = format_mem(request.amount.mem)
        if detailed and request.mem_mode != 'node':
            mem += f' ({format_mem(request.mem_value)}/{request.mem_mode.upper()})'
        parts.append(mem)
    text = ' · '.join(parts)
    if request.node_count > 1:
        text += f' on each of {request.node_count} nodes'
    return text


def _node_names(names: Sequence[str], planned: Collection[str], limit: int = 3) -> str:
    """Node names with ``*`` on the ones backfill has set aside."""
    return join_names([f'{name}*' if name in planned else name for name in names], limit)


def fix_label(fix: Fix) -> str:
    """``--mem 56G → 32G`` or ``GPUs 4 → 2 (→ 8 CPU, 20G)``."""
    show = format_mem if fix.knob == 'mem' else str
    label = f'{fix.request.knob_flag(fix.knob)} {show(fix.old)} → {show(fix.new)}'
    after = fix.request.amount
    if fix.knob == 'gpus' and (fix.request.cpus_per_gpu or fix.request.mem_mode == 'gpu'):
        label += f' (→ {after.cpus} CPU, {format_mem(after.mem)})'
    elif fix.knob == 'cpus' and fix.request.mem_mode == 'cpu':
        label += f' (→ {format_mem(after.mem)})'
    return label


def _and(words: Sequence[str]) -> str:
    return ' and '.join([', '.join(words[:-1]), words[-1]] if len(words) > 1 else words)


def _start_text(request: JobRequest) -> str | None:
    """``in 2h10m (Tue 12:10)`` from Slurm's backfill estimate, if it has one."""
    if not request.planned_start:
        return None
    return format_pending_start(datetime.fromtimestamp(request.planned_start).isoformat())


def _why(diagnosis: Diagnosis) -> Text:
    """Why the job waits, plus Slurm's start estimate when that means something."""
    request = diagnosis.request
    if not diagnosis.rows:
        skipped = skip_summary(diagnosis.skipped, short=False)
        where = skipped or f'none in {",".join(request.partitions)}'
        return Text(f'no usable nodes: {where}', style='red')
    if diagnosis.never_fits:
        return Text(
            f'never fits: {never_fits_reason(diagnosis)}; waiting will not help',
            style='red',
        )
    if diagnosis.fits_now:
        text = Text(f'fits now on {join_names(diagnosis.fits)}', style='green')
        if request.reason == 'Priority':
            text.append(', held for higher-priority jobs')
    else:
        short = [
            PROSE_LABELS[dim] for dim in diagnosis.dims if diagnosis.short_count(dim)
        ]
        text = Text.assemble('waiting for ', (_and(short), 'yellow'), ' to free up')
    start = _start_text(request)
    if start:  # format_pending_start says 'due (Tue 12:10)' once the estimate passed
        text.append(
            f' · start {start}' if start.startswith('due') else f' · starts {start}'
        )
        if request.planned_nodes:
            text.append(f' on {request.planned_nodes}')
    return text


def _runnable_fix(diagnosis: Diagnosis) -> tuple[Fix, str] | None:
    """The fix plain ``--fix`` applies (or ``--fix gpus`` when only GPUs help)."""
    fix = diagnosis.lead_fix()
    # A held job, a dependency or a QOS limit still blocks it after the change.
    if fix is None or fix.command is None or diagnosis.request.reason not in HINT_REASONS:
        return None
    return fix, '--fix gpus' if fix.knob == 'gpus' else '--fix'


def _fix_command(diagnosis: Diagnosis) -> str | None:
    runnable = _runnable_fix(diagnosis)
    if runnable is None:
        return None
    return f'{CLI_NAME} why {diagnosis.request.update_id} {runnable[1]}'


def _change(diagnosis: Diagnosis) -> Text | None:
    """The one change that starts the job now, or that there is none."""
    if not diagnosis.rows or diagnosis.fits_now:
        return None
    fix = diagnosis.lead_fix()
    if fix is None:
        return muted('no single change starts it now')
    blocked = diagnosis.request.reason not in HINT_REASONS
    text = Text.assemble(
        ('would fit now with ', 'yellow') if blocked else ('starts now with ', 'bold green'),
        (fix_label(fix), 'bold cyan'),
    )
    if fix.command is None:
        text.append(' (change the script and resubmit)', style='dim')
    return text


def _render_summary(diagnosis: Diagnosis, *, detailed: bool = False) -> None:
    """Job line, why it waits (and when it starts), the change that starts it now."""
    request = diagnosis.request
    head = Text.assemble(
        job_id_text(request.display_id),
        '  ',
        partition_text(','.join(request.partitions)),
        f'  {describe_request(request, detailed=detailed)}',
    )
    if request.pending_tasks > 1:
        head.append(f'  ({request.pending_tasks} tasks)', style='dim')
    CONSOLE.print(head)
    why = _why(diagnosis)
    if request.reason not in HINT_REASONS:
        why = Text.assemble((request.reason, 'yellow'), ' first, then ', why)
    CONSOLE.print(Text.assemble('  ', why))
    change = _change(diagnosis)
    if change is not None:
        CONSOLE.print(Text.assemble('  ', change))
        command = None if detailed else _fix_command(diagnosis)
        if command:
            CONSOLE.print(muted(f'  ⓘ `{command}` changes the job so it starts now'))


# ---------------------------------------------------------------------------
# ab why (overview)
# ---------------------------------------------------------------------------


def _render_overview(
    records: list[dict[str, Any]],
    nodes: list[NodeCapacity],
    limits: dict[str, int | None],
) -> None:
    user = current_user()
    requests = [
        JobRequest.from_record(record)
        for record in records
        if record.get('user_name') == user
        and 'PENDING' in (record.get('job_state') or [])
        and record.get('state_reason') in HINT_REASONS
    ]
    if not requests:
        CONSOLE.print(muted('None of your pending jobs is waiting for resources.'))
        return
    for request in requests:
        _render_summary(diagnose(request, nodes, limits))


# ---------------------------------------------------------------------------
# ab why JOBID
# ---------------------------------------------------------------------------


def _render_other_fixes(diagnosis: Diagnosis) -> None:
    shown = diagnosis.lead_fix()
    others = [fix_label(fix) for fix in diagnosis.fixes if fix is not shown]
    if others and not diagnosis.fits_now:
        CONSOLE.print(muted(f'  or {", or ".join(others)}'))


def _render_slots(diagnosis: Diagnosis) -> None:
    request = diagnosis.request
    columns: list[tuple[str, JustifyMethod]] = [('GPUs', 'left')] if request.gpus else []
    columns += [('CPUs', 'right'), ('Memory', 'right'), ('Nodes', 'left')]
    rows: list[TableRow] = []
    for slot in diagnosis.slots:
        row: TableRow = (
            [f'{slot.free.gpus}x {_gpu_label(request)}'] if request.gpus else []
        )
        row += [
            str(slot.free.cpus),
            format_mem(slot.free.mem),
            _node_names(slot.nodes, diagnosis.planned, limit=4),
        ]
        rows.append(row)
    planned = any(
        name in diagnosis.planned for slot in diagnosis.slots for name in slot.nodes
    )
    caption = '* held for another job' if planned else None
    CONSOLE.print()
    render_table(columns, rows, title='Biggest free slots', caption=caption)


def _render_nodes(diagnosis: Diagnosis) -> None:
    dims = diagnosis.dims
    columns: list[tuple[str, JustifyMethod]] = [('Node', 'left'), ('State', 'left')]
    columns += [(ROW_LABELS[dim], 'right') for dim in dims]
    ordered = sorted(
        diagnosis.rows,
        key=lambda row: (len(row.short), -row.free.gpus, -row.free.cpus, -row.free.mem),
    )
    rows: list[TableRow] = []
    for fit in ordered:
        row: TableRow = [fit.node.name, fit.node.state]
        for dim in dims:
            free = format_free(dim, getattr(fit.free, dim))
            total = format_free(dim, getattr(fit.total, dim))
            if free.endswith('G') and total.endswith('G'):
                free = free[:-1]  # 73/89G, as in ab free
            row.append(Text(f'{free}/{total}', style='red' if dim in fit.short else ''))
        rows.append(row)
    CONSOLE.print()
    render_table(
        columns, rows, title='Eligible nodes', caption='free/total, red is short'
    )
    if diagnosis.unavailable:
        unavailable = skip_summary(diagnosis.unavailable, short=False)
        CONSOLE.print(muted(f'Not counted: {unavailable}.'))
    if diagnosis.request.features is None:
        CONSOLE.print(muted('Feature constraint not checked; every node counts.'))


def _render_detail(diagnosis: Diagnosis, *, show_nodes: bool) -> None:
    _render_summary(diagnosis, detailed=True)
    if not diagnosis.rows:
        return
    _render_other_fixes(diagnosis)
    if not diagnosis.fits_now and not diagnosis.fixes and diagnosis.slots:
        _render_slots(diagnosis)
    if show_nodes:
        _render_nodes(diagnosis)
    command = _fix_command(diagnosis)
    if command and not diagnosis.fits_now:
        hint(f'`{command}` changes the job so it starts now')


# ---------------------------------------------------------------------------
# ab why JOBID --fix
# ---------------------------------------------------------------------------


def _interactive() -> bool:
    return sys.stdin.isatty()


def _resources(request: JobRequest) -> tuple[object, ...]:
    """The fields a fix changes, for comparing the request Slurm reports afterwards."""
    return (
        request.gpus,
        request.cpus,
        request.cpus_per_gpu,
        request.mem_mode,
        request.mem_value,
    )


def _choose_fix(diagnosis: Diagnosis, choice: str) -> Fix:
    """The fix ``--fix`` applies; only fixes with an in-place command qualify."""
    request = diagnosis.request
    if choice == 'auto':
        fix = diagnosis.lead_fix()
        if fix is not None and fix.knob == 'gpus' and fix.command is not None:
            die(
                f'only fewer GPUs get {request.display_id} started in place; '
                'if your script copes with that, rerun with --fix gpus'
            )
    else:
        fix = next((fix for fix in diagnosis.fixes if fix.knob == choice), None)
    if fix is None:
        what = 'single' if choice == 'auto' else choice
        die(f'no {what} change gets {request.display_id} started right now')
    if fix.command is None:
        die(
            f'{fix_label(fix)} would start {request.display_id}, but Slurm cannot change '
            'that in place; change the job script and resubmit'
        )
    return fix


def _report_fix(fix: Fix, limits: dict[str, int | None]) -> bool:
    """Re-read the job; True when Slurm now holds the request we asked for."""
    expected = fix.request
    records = load_job_records(expected.job_id, strict=False)
    if not records:
        warn(f'could not re-read the job; check `scontrol show job {expected.update_id}`')
        return False
    record = find_record(records, expected.job_id)
    if record is None:
        CONSOLE.print(
            Text(
                f'Updated; {expected.display_id} is no longer listed, it may have started.'
            )
        )
        return True
    updated = JobRequest.from_record(record)
    if updated.state != 'PENDING':
        CONSOLE.print(
            Text.assemble(
                f'Updated; {updated.display_id} is now ', state_text(updated.state)
            )
        )
        return True
    if _resources(updated) != _resources(expected):
        warn(
            f'Slurm now reports {describe_request(updated, detailed=True)}, '
            f'expected {describe_request(expected, detailed=True)}; '
            f'check `scontrol show job {updated.update_id}`'
        )
        return False
    nodes = [NodeCapacity.from_node(node) for node in load_nodes(strict=False)]
    after = diagnose(updated, nodes, limits)
    if after.fits_now:
        count = len(after.fits)
        CONSOLE.print(
            Text(
                f'Updated; {updated.display_id} now asks for {describe_request(updated)} '
                f'and fits on {count} {"node" if count == 1 else "nodes"}.',
                style='green',
            )
        )
    else:
        warn(
            f'updated to {describe_request(updated)}, but the cluster changed and it '
            f'no longer fits; run `{CLI_NAME} why {updated.update_id}` again'
        )
    return True


def _apply_fix(
    diagnosis: Diagnosis,
    choice: str,
    *,
    assume_yes: bool,
    limits: dict[str, int | None],
) -> None:
    request = diagnosis.request
    if request.user != current_user():
        die(
            f'{request.display_id} belongs to {request.user}; --fix only changes your own jobs'
        )
    if request.het:
        die('--fix does not change heterogeneous jobs')
    if request.node_count > 1:
        die(
            '--fix does not change multi-node jobs; '
            f'use the commands from `{CLI_NAME} why {request.update_id}`'
        )
    if request.reason not in HINT_REASONS:
        die(
            f'{request.display_id} waits for {request.reason}, not resources; '
            '--fix would not start it'
        )
    if diagnosis.fits_now:
        names = join_names(diagnosis.fits)
        CONSOLE.print(
            Text(f'{request.display_id} already fits on {names}; nothing to change.')
        )
        return

    fix = _choose_fix(diagnosis, choice)
    command = fix.command or []
    CONSOLE.print(
        Text.assemble(
            (fix_label(fix), 'cyan'), f' starts {request.display_id} now. This runs:'
        )
    )
    CONSOLE.print(Text(f'  $ {shlex.join(command)}', style='bold'))
    note = 'Only the allocation changes, not the job script'
    if request.pending_tasks > 1:
        note += f'; applies to all {request.pending_tasks} pending tasks'
    CONSOLE.print(muted(f'{note}.'))

    if not assume_yes:
        if not _interactive():
            die('refusing to change the job without confirmation; rerun with --yes')
        if not click.confirm('Apply?', default=False):
            CONSOLE.print('Left unchanged.')
            return

    proc = run(command, check=False)
    if proc.returncode != 0:
        # An array update also reports its running tasks, which cannot change, so a
        # non-zero exit can still have updated the pending ones: re-read and compare.
        detail = (proc.stderr or proc.stdout or '').strip()
        warn(f'scontrol: {detail or f"exit code {proc.returncode}"}')
    if not _report_fix(fix, limits):
        raise SystemExit(1)


def cmd_why(
    *,
    jobid: str | None,
    show_nodes: bool,
    fix: str | None,
    assume_yes: bool,
) -> None:
    if fix is not None and jobid is None:
        die(f'--fix needs a job id, e.g. {CLI_NAME} why 65177 --fix')
    if assume_yes and fix is None:
        die('--yes only applies together with --fix')

    # %A_[...] and 65177_3 both live under the array's base id
    records, nodes, limits = load_inputs(job_id=jobid and base_job_id(jobid))
    if jobid is None:
        _render_overview(records, nodes, limits)
        return

    record = find_record(records, jobid)
    if record is None:
        die(
            f'job {jobid} not found; finished jobs drop out of scontrol soon after they end'
        )
    request = JobRequest.from_record(record)
    if request.state != 'PENDING':
        CONSOLE.print(
            Text.assemble(
                f'{request.display_id} is ', state_text(request.state), ', not waiting.'
            )
        )
        return
    diagnosis = diagnose(request, nodes, limits)
    if fix is not None:
        _apply_fix(diagnosis, fix, assume_yes=assume_yes, limits=limits)
        return
    _render_detail(diagnosis, show_nodes=show_nodes)
