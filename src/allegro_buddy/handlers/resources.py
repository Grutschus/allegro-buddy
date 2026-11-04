from __future__ import annotations

import socket
from typing import NamedTuple

from rich.table import Table
from rich.text import Text

from allegro_buddy.core import (
    CLI_NAME,
    CONSOLE,
    JustifyMethod,
    NodeFree,
    PartitionStats,
    TableRow,
    active_reservations,
    collect_display_gpu_types,
    current_groups,
    current_user,
    die,
    display_job_id,
    expand_nodelist,
    find_dev_jobs,
    format_eta,
    format_gpu_type_header,
    format_mem_value,
    format_pending_start,
    format_seconds,
    get_accessible_partitions,
    get_user_job_etas,
    get_user_jobs,
    gpu_free_text,
    gpu_type_label,
    hint,
    is_gpu_partition,
    is_nullish,
    iso_to_dt,
    job_gres_on_node,
    job_id_text,
    job_on_node,
    load_nodes,
    load_reservations,
    load_running_jobs,
    load_user_pending_jobs,
    muted,
    node_facts,
    node_free,
    node_is_idle,
    node_is_mixed,
    node_is_usable,
    node_text,
    parse_gpu_count,
    parse_gpu_ids,
    parse_index_blob,
    parse_node_gpu_types,
    parse_slurm_time,
    partition_text,
    ratio_text,
    recent_active_reservations,
    render_table,
    reservation_blocked_pending_jobs,
    reserved_nodes_map,
    run_parsable_rows,
    state_text,
    summarize_partitions,
    summarize_selected_partitions,
    truncate,
    upcoming_reservations,
    user_accounts,
    user_can_use_reservation,
    user_from_userid,
    warn,
)
from allegro_buddy.fit import HINT_REASONS
from allegro_buddy.handlers.why import queue_hints


def guess_node(args_node: str | None) -> str:
    if args_node:
        return args_node

    hostname = socket.gethostname()
    for name in (hostname, hostname.split('.', 1)[0]):
        if name in node_facts()['names']:
            return name

    dev_jobs = find_dev_jobs()
    for job in dev_jobs:
        if job.get('JobState') == 'RUNNING' and job.get('NodeList') not in {'', '(null)'}:
            nodes = expand_nodelist(job['NodeList'])
            if nodes:
                return nodes[0]

    user_jobs = [
        job
        for job in get_user_jobs()
        if job.get('JobState') == 'RUNNING'
        and parse_gpu_count(job.get('JOB_GRES')) > 0
        and job.get('NodeList') not in {'', '(null)'}
    ]
    nodes = expand_nodelist(user_jobs[0]['NodeList']) if user_jobs else []
    if not nodes:
        die(f'could not guess the node; name it: {CLI_NAME} node <node>')
    return nodes[0]


# Never wider than this: long lists (groups, node ranges) wrap rather than span a wide terminal.
MAX_WIDTH = 100


def _your_jobs_text(user: str) -> Text:
    """`1 running (next ends in 6h35m) · 2 pending`, or `none`."""
    pending, running = get_user_job_etas(user)
    parts: list[Text] = []
    for count_list, word, verb in ((running, 'running', 'next ends'), (pending, 'pending', 'first starts')):
        if not count_list:
            continue
        part = Text(f'{len(count_list)} {word}')
        known = [delta for delta in count_list if delta is not None]
        if known:
            soonest = min(known, key=lambda delta: delta.total_seconds())
            part.append(f' ({verb} in ')
            part.append(format_seconds(int(soonest.total_seconds())), style='cyan')
            part.append(')')
        parts.append(part)
    if not parts:
        return Text('none')
    return Text(' · ').join(parts)


def _accounts_text(rows: list[dict[str, str]]) -> Text:
    """`proj1 (default), proj2`: the accounts you can charge, default first."""
    default = next((row['DefaultAccount'] for row in rows if row['DefaultAccount']), '')
    accounts = sorted({row['Account'] for row in rows if row['Account']}, key=lambda a: (a != default, a))
    if not accounts:
        return muted()
    parts = [Text.assemble(a, (' (default)', 'dim') if a == default else '') for a in accounts]
    return Text(', ').join(parts)


def _render_you() -> None:
    """Who you are on the cluster: Slurm bills and limits by account (on Lise, a compute project)."""
    user = current_user()
    rows = user_accounts(user)
    qos = sorted({q for row in rows for q in row['QOS'].split(',') if q})
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style='dim', no_wrap=True)
    grid.add_column()  # wraps aligned to itself: a hanging indent for long lists
    grid.add_row('user', user)
    grid.add_row('accounts', _accounts_text(rows))
    if qos:
        grid.add_row('qos', ', '.join(qos))
    grid.add_row('jobs', _your_jobs_text(user))
    CONSOLE.print(Text('You', style='bold'))
    CONSOLE.print(grid, width=min(CONSOLE.width, MAX_WIDTH))


def _short_limit(value: str) -> Text:
    """Slurm time limit as `1h`, `2d2h`, `7d`; unparseable values as given."""
    seconds = parse_slurm_time(value) if value else None
    return muted(value.lower() or '-') if seconds is None else Text(format_seconds(seconds))


def _node_state_with_resv(
    state: str,
    resv_name: str | None,
    upcoming_resv_name: str | None = None,
) -> Text:
    text = state_text(state)
    if resv_name:
        text.append(f' [{resv_name}]', style='magenta')
    elif upcoming_resv_name:
        text.append(f' [{upcoming_resv_name}]', style='yellow')
    return text


def _resv_nodes(resv: dict[str, str]) -> str:
    nodes = resv.get('Nodes', '')
    if is_nullish(nodes):
        return '?'
    return nodes if len(nodes) <= 30 else f"{resv.get('NodeCnt', '?')} nodes"


def _render_reservations() -> None:
    all_resvs = load_reservations()
    active = recent_active_reservations(all_resvs)
    upcoming = upcoming_reservations(all_resvs)
    if not active and not upcoming:
        return

    user = current_user()
    groups = current_groups()
    rows: list[TableRow] = []
    for resv, is_active in [(r, True) for r in active] + [(r, False) for r in upcoming]:
        if is_active:
            when = Text.assemble(
                ('now', 'magenta'), (f", ends in {format_eta(resv.get('EndTime', ''))}", 'dim')
            )
        else:
            start = iso_to_dt(resv.get('StartTime', ''))
            end = iso_to_dt(resv.get('EndTime', ''))
            length = f', for {format_seconds(int((end - start).total_seconds()))}' if start and end else ''
            when = Text.assemble((f"in {format_eta(resv.get('StartTime', ''))}", 'yellow'), (length, 'dim'))
        if is_nullish(resv.get('Users')) and is_nullish(resv.get('Groups')):
            access = muted('maintenance')
        elif user_can_use_reservation(resv, user, groups):
            access = Text('you', style='green')
        else:
            access = muted('others')
        rows.append([resv.get('ReservationName', '?'), _resv_nodes(resv), when, access])

    CONSOLE.print()
    render_table(
        [('Reservation', 'left'), ('Nodes', 'left'), ('When', 'left'), ('For', 'left')],
        rows,
        title='Reservations',
        caption='jobs on these nodes must end before the reservation starts' if upcoming else None,
    )

    if active:
        blocked = reservation_blocked_pending_jobs(active, load_user_pending_jobs(user))
        if blocked:
            n = len(blocked)
            label = '1 of your pending jobs is' if n == 1 else f'{n} of your pending jobs are'
            warn(f'{label} blocked by an active reservation; see `{CLI_NAME} why`')


def _overview_row(name: Text, limit: Text, stats: PartitionStats) -> TableRow:
    return [
        name,
        limit,
        ratio_text(stats['idle_nodes'], stats['nodes']),
        gpu_free_text(stats['gpu_free'], stats['gpu_usable'], stats['gpu_total']),
        ratio_text(stats['cpu_free'], stats['cpu_total']),
        ratio_text(stats['mem_free_gb'], stats['mem_total_gb'], unit='G'),
    ]


def _free_caption(some_unusable: bool) -> str:
    """The `+n` of `gpu_free_text`, explained only when one is shown."""
    if some_unusable:
        return 'free/total · +n idle, but on full or drained nodes'
    return 'free/total'


def cmd_info(*, all_partitions: bool) -> None:
    nodes = load_nodes()
    partitions = get_accessible_partitions(include_all=all_partitions)
    summaries = summarize_partitions(
        [partition['PartitionName'] for partition in partitions], nodes=nodes
    )
    cluster_stats = summarize_selected_partitions(
        {partition['PartitionName'] for partition in partitions},
        nodes=nodes,
    )

    rows: list[TableRow] = [_overview_row(Text('all', style='bold'), muted(), cluster_stats)]
    breaks = {0}
    previous = None
    for partition in partitions:
        name = partition['PartitionName']
        if previous is not None and is_gpu_partition(previous) != is_gpu_partition(name):
            breaks.add(len(rows) - 1)  # between GPU and CPU partitions
        previous = name
        limit = _short_limit(partition.get('MaxTime', ''))
        rows.append(_overview_row(partition_text(name), limit, summaries[name]))

    _render_you()
    CONSOLE.print()
    render_table(
        [
            ('Partition', 'left'),
            ('Time limit', 'left'),
            ('Idle nodes', 'right'),
            ('Free GPUs', 'right'),
            ('Free CPUs', 'right'),
            ('Free memory', 'right'),
        ],
        rows,
        title='Resource overview',
        caption=_free_caption(
            any(
                st['gpu_usable'] < st['gpu_free']
                for st in [cluster_stats, *summaries.values()]
            )
        ),
        section_breaks=breaks,
    )
    _render_reservations()


def cmd_queue(*, all_users: bool, user: str | None, partition: str | None) -> None:
    selected_user = None if all_users else (user or current_user())
    # %A is the raw job id, which matches `scontrol --json show job` records.
    format_string = '%i|%A|%u|%j|%T|%P|%M|%L|%S|%R'
    argv = ['squeue', '-h', f'--format={format_string}']
    if selected_user:
        argv.extend(['-u', selected_user])
    if partition:
        argv.extend(['-p', partition])
    jobs = run_parsable_rows(
        argv,
        [
            'jobid',
            'rawid',
            'user',
            'name',
            'state',
            'partition',
            'elapsed',
            'left',
            'start',
            'where',
        ],
    )
    if not jobs:
        whose = f' for {user}' if user and not all_users else ''
        CONSOLE.print(muted(f'No jobs{whose} in the queue.'))
        return

    show_user = selected_user is None
    show_start = any(job['state'] == 'PENDING' for job in jobs)
    show_elapsed = any(job['state'] != 'PENDING' for job in jobs)
    hint_ids = {
        job['rawid']
        for job in jobs
        if job['state'] == 'PENDING' and job['where'].strip('()') in HINT_REASONS
    }
    hints, hint_error = queue_hints(hint_ids) if hint_ids else ({}, None)

    rows = []
    for job in jobs:
        pending = job['state'] == 'PENDING'
        row: TableRow = [job_id_text(job['jobid'])]
        if show_user:
            row.append(job['user'])
        row.extend(
            [
                truncate(job['name'], 28),
                state_text(job['state']),
                partition_text(job['partition']),
            ]
        )
        if show_elapsed:
            # squeue reports 0:00 for pending jobs; leave the cell empty
            row.append(Text('') if pending else _slurm_duration(job['elapsed']))
        row.append(_slurm_duration(job['left']))
        if show_start:
            # 'in 2h10m' without the clock; '' renders as a dim dash when Slurm has
            # no estimate yet
            start = format_pending_start(job['start']) if pending else None
            row.append(start.split(' (')[0] if start else ('' if pending else Text('')))
        if pending:
            # the bottleneck hint explains the wait better than Slurm's reason code
            reason = hints.get(job['rawid']) or job['where'].strip('()')
            row.append(Text(truncate(reason, 32), style='yellow'))
        else:
            row.append(node_text(truncate(job['where'], 32), job['partition']))
        rows.append(row)

    columns: list[tuple[str, JustifyMethod]] = [('JobID', 'left')]
    if show_user:
        columns.append(('User', 'left'))
    columns.extend(
        [
            ('Name', 'left'),
            ('State', 'left'),
            ('Partition', 'left'),
        ]
    )
    if show_elapsed:
        columns.append(('Elapsed', 'right'))
    columns.append(('Time left', 'right'))
    if show_start:
        columns.append(('Start', 'left'))
    columns.append(('Node/Reason', 'left'))
    title = 'Queue · all users' if all_users else (f'Queue · {user}' if user else 'Queue')
    render_table(columns, rows, title=title)
    if hint_error:
        CONSOLE.print(muted(f'bottleneck hints unavailable: {hint_error}'))
    if hints:
        hint(f'`{CLI_NAME} why` shows what is short and what would start now')


class _FreeNode(NamedTuple):
    """One node row of `ab free`: what `node_free()` says plus how to show it."""

    name: str
    state: str
    partitions: str
    free: NodeFree
    idle: bool
    schedulable: bool  # IDLE or MIXED: can take a job now

    @property
    def gpu_free(self) -> int:
        return sum(self.free['gpu_free_by_type'].values())

    @property
    def mem_gb(self) -> tuple[int, int]:
        return round(self.free['mem_free_mb'] / 1024), round(self.free['mem_total_mb'] / 1024)


def _free_nodes(
    nodes: list[dict[str, str]],
    partition_names: set[str],
    *,
    kind: str,
    gpu_type: str | None,
    reserved_by: dict[str, dict[str, str]],
) -> list[_FreeNode]:
    """The nodes `ab free` counts, most free GPUs, then CPUs, first."""
    entries: list[_FreeNode] = []
    for node in nodes:
        overlap = [p for p in node.get('Partitions', '').split(',') if p in partition_names]
        free = node_free(node)
        gpu_total_by_type = free['gpu_total_by_type']
        if not overlap or (kind == 'gpu') != bool(sum(gpu_total_by_type.values())):
            continue
        if gpu_type and not gpu_total_by_type.get(gpu_type):
            continue
        state = node.get('State', '')
        if not node_is_usable(node):
            # Surface MAINT+RESERVED nodes when the user can use the reservation.
            resv = reserved_by.get(node.get('NodeName', ''))
            upper = state.upper()
            if not (
                'MAINT' in upper
                and 'RESERVED' in upper
                and resv
                and user_can_use_reservation(resv, current_user(), current_groups())
            ):
                continue
            state = 'RESERVED'
        idle = node_is_idle(node)
        entries.append(
            _FreeNode(
                node.get('NodeName', ''),
                state,
                ','.join(overlap),
                free,
                idle,
                idle or node_is_mixed(node),
            )
        )
    entries.sort(key=lambda e: (-e.gpu_free, -e.free['cpu_free'], e.name))
    return entries


def _render_free_gpu_partitions(
    partition_names: list[str],
    summaries: dict[str, PartitionStats],
    cluster_stats: PartitionStats,
    gpu_types: list[str],
) -> None:
    def row(name: Text, stats: PartitionStats) -> TableRow:
        return [name] + [
            gpu_free_text(
                stats['gpu_free_by_type'].get(gt, 0),
                stats['gpu_usable_by_type'].get(gt, 0),
                stats['gpu_total_by_type'].get(gt, 0),
            )
            for gt in gpu_types
        ]

    shown = [cluster_stats] + [
        summaries[name] for name in partition_names if summaries[name]['gpu_total'] > 0
    ]
    rows = [row(Text('all', style='bold'), cluster_stats)] + [
        row(partition_text(name), summaries[name])
        for name in partition_names
        if summaries[name]['gpu_total'] > 0
    ]
    columns: list[tuple[str, JustifyMethod]] = [('Partition', 'left')]
    columns += [(format_gpu_type_header('', gt), 'right') for gt in gpu_types]
    render_table(
        columns,
        rows,
        title='Free GPUs',
        caption=_free_caption(any(st['gpu_usable'] < st['gpu_free'] for st in shown)),
        section_breaks={0},
    )


def _render_free_by_node(entries: list[_FreeNode], gpu_type: str | None) -> None:
    """Nodes with GPUs a job can get right now, most free first: `gpu084 (4), gpu101 (3)`."""
    found = [
        (e.name, e.free['gpu_free_by_type'].get(gpu_type, 0) if gpu_type else e.gpu_free)
        for e in entries
        if e.schedulable
    ]
    found = sorted(((n, c) for n, c in found if c > 0), key=lambda item: -item[1])
    CONSOLE.print()
    if not found:
        CONSOLE.print(muted('No node can take a GPU job right now.'))
        return
    CONSOLE.print(Text('Nodes with free GPUs', style='bold'))
    # Packed by hand: rich would break a line between a node and its count.
    width = min(CONSOLE.width, MAX_WIDTH)
    line = Text()
    for i, (name, count) in enumerate(found):
        item = Text.assemble(node_text(name), (f' ({count})', 'green'))
        if i < len(found) - 1:
            item.append(',', style='dim')
        if line and len(line) + 1 + len(item) > width:
            CONSOLE.print(line)
            line = Text()
        if line:
            line.append(' ')
        line.append_text(item)
    CONSOLE.print(line)


def _render_free_node_table(
    entries: list[_FreeNode],
    *,
    kind: str,
    gpu_types: list[str],
    resv_map: dict[str, str],
    upcoming_resv_map: dict[str, str],
) -> None:
    """`ab free --nodes`: one row per node plus a total row."""
    usable = dict.fromkeys(gpu_types, 0)
    free_gpus = dict.fromkeys(gpu_types, 0)
    total_gpus = dict.fromkeys(gpu_types, 0)
    cpu_free = cpu_total = mem_free = mem_total = 0
    rows: list[TableRow] = []
    for e in entries:
        mem_free_gb, mem_total_gb = e.mem_gb
        cpu_free += e.free['cpu_free']
        cpu_total += e.free['cpu_total']
        mem_free += mem_free_gb
        mem_total += mem_total_gb
        state = _node_state_with_resv(
            e.state, resv_map.get(e.name), upcoming_resv_map.get(e.name)
        )
        row: TableRow = [node_text(e.name), state]
        if kind == 'cpu':
            row.append(e.partitions)
        style = 'green' if e.idle else 'yellow' if e.schedulable else 'dim'
        for gt in gpu_types:
            g_free = e.free['gpu_free_by_type'].get(gt, 0)
            g_total = e.free['gpu_total_by_type'].get(gt, 0)
            usable[gt] += g_free if e.schedulable else 0
            free_gpus[gt] += g_free
            total_gpus[gt] += g_total
            row.append(ratio_text(g_free, g_total, free_style=style))
        row.append(ratio_text(e.free['cpu_free'], e.free['cpu_total']))
        row.append(ratio_text(mem_free_gb, mem_total_gb, unit='G'))
        rows.append(row)

    columns: list[tuple[str, JustifyMethod]] = [('Node', 'left'), ('State', 'left')]
    if kind == 'cpu':
        columns.append(('Partitions', 'left'))
    columns += [(format_gpu_type_header('', gt), 'right') for gt in gpu_types]
    columns += [('Free CPUs', 'right'), ('Free memory', 'right')]
    if rows:
        total: TableRow = [Text('total', style='bold'), Text('')]
        if kind == 'cpu':
            total.append(Text(''))
        total += [gpu_free_text(free_gpus[gt], usable[gt], total_gpus[gt]) for gt in gpu_types]
        total.append(ratio_text(cpu_free, cpu_total))
        total.append(ratio_text(mem_free, mem_total, unit='G'))
        rows.append(total)
    render_table(
        columns,
        rows,
        title='CPU nodes' if kind == 'cpu' else 'GPU nodes',
        caption=_free_caption(any(usable[gt] < free_gpus[gt] for gt in gpu_types)),
        section_breaks={len(rows) - 2},
    )


def cmd_free(
    *,
    kind: str,
    show_nodes: bool,
    partition_filter: str | None,
    gpu_type: str | None = None,
) -> None:
    nodes = load_nodes()
    all_resvs = load_reservations()
    active_resvs = active_reservations(all_resvs)
    resv_map = reserved_nodes_map(active_resvs)
    upcoming_resv_map = reserved_nodes_map(upcoming_reservations(all_resvs))
    active_resv_by_name = {
        resv.get('ReservationName', ''): resv for resv in active_resvs
    }

    partitions = get_accessible_partitions(include_all=False)
    names = [
        partition['PartitionName']
        for partition in partitions
        if (kind == 'gpu') == is_gpu_partition(partition['PartitionName'])
        and (not partition_filter or partition['PartitionName'] == partition_filter)
    ]
    if not names:
        if kind == 'gpu' and not partition_filter and partitions:
            die(f'no partition you can use has GPUs; try `{CLI_NAME} free --kind cpu`')
        die('no partitions matched this filter')
    summaries = summarize_partitions(names, nodes=nodes)
    cluster_stats = summarize_selected_partitions(set(names), nodes=nodes)

    gpu_types = collect_display_gpu_types(
        [
            cluster_stats['gpu_total_by_type'],
            cluster_stats['gpu_free_by_type'],
            *[summaries[name]['gpu_free_by_type'] for name in names],
        ]
    )
    if gpu_type:
        gpu_types = [gt for gt in gpu_types if gt == gpu_type]

    entries = _free_nodes(
        nodes,
        set(names),
        kind=kind,
        gpu_type=gpu_type,
        reserved_by={
            node: active_resv_by_name[resv]
            for node, resv in resv_map.items()
            if resv in active_resv_by_name
        },
    )

    if show_nodes:
        _render_free_node_table(
            entries,
            kind=kind,
            gpu_types=gpu_types if kind == 'gpu' else [],
            resv_map=resv_map,
            upcoming_resv_map=upcoming_resv_map,
        )
    elif kind == 'cpu':
        # Partition overview; GPU columns are always empty there.
        overview = [_overview_row(Text('all', style='bold'), muted(), cluster_stats)]
        overview += [
            _overview_row(partition_text(name), muted(), summaries[name]) for name in names
        ]
        render_table(
            [
                ('Partition', 'left'),
                ('Idle nodes', 'right'),
                ('Free CPUs', 'right'),
                ('Free memory', 'right'),
            ],
            [[row[0], row[2], row[4], row[5]] for row in overview],
            title='Free CPUs',
            caption='free/total',
            section_breaks={0},
        )
    else:
        if gpu_types:
            _render_free_gpu_partitions(names, summaries, cluster_stats, gpu_types)
        _render_free_by_node(entries, gpu_type)

    # One warning per reservation that covers a node counted above.
    shown = {e.name for e in entries}
    active_names = {resv_map[n] for n in shown if n in resv_map}
    for resv in active_resvs:
        if resv.get('ReservationName') in active_names:
            warn(
                f"{resv['ReservationName']} reserves {_resv_nodes(resv)} "
                f"for {format_eta(resv.get('EndTime', ''))} more"
            )
    upcoming_names = {upcoming_resv_map[n] for n in shown if n in upcoming_resv_map}
    for resv in upcoming_reservations(all_resvs):
        if resv.get('ReservationName') in upcoming_names:
            warn(
                f"{resv['ReservationName']} reserves {_resv_nodes(resv)} in "
                f"{format_eta(resv.get('StartTime', ''))}; jobs there must end by then"
            )


def _ids(ids: list[int] | set[int]) -> str:
    return ','.join(map(str, sorted(ids)))


def cmd_node(*, node: str | None) -> None:
    nodes = load_nodes()  # also primes node_facts(), so guess_node won't reload
    node_name = guess_node(node)
    node_info = next((n for n in nodes if n.get('NodeName') == node_name), None)
    if node_info is None:
        die(f'unknown node: {node_name}')

    total_gpus = parse_gpu_count(node_info.get('Gres'))
    jobs = sorted(
        (
            job
            for job in load_running_jobs()
            if node_name in expand_nodelist(job.get('NodeList', ''))
        ),
        key=lambda job: (
            parse_gpu_ids(job_gres_on_node(job, node_name)) or [total_gpus],
            display_job_id(job),
        ),
    )

    # Heading: the node and what is free on it, the answer to "can I use this node?"
    free = node_free(node_info)
    free_gpus = sum(free['gpu_free_by_type'].values())
    usable = node_is_usable(node_info)
    types = {
        gpu_type_label(t) for t in parse_node_gpu_types(node_info.get('Gres')).values()
    }
    gpu_unit = f' {types.pop()}' if len(types) == 1 else ' GPUs'
    # A drained or down node says so first: nothing on it can be scheduled.
    state = Text('') if usable else Text.assemble('  ', state_text(node_info['State']))
    gpu_part = (
        [ratio_text(free_gpus, total_gpus, unit=gpu_unit), muted(' · ')]
        if total_gpus
        else []
    )
    CONSOLE.print(
        Text.assemble(
            (node_name, 'bold'),
            state,
            muted('  free ' if usable else '  idle '),
            *gpu_part,
            ratio_text(free['cpu_free'], free['cpu_total'], unit=' CPUs'),
            muted(' · '),
            ratio_text(
                round(free['mem_free_mb'] / 1024),
                round(free['mem_total_mb'] / 1024),
                unit='G mem',
            ),
        )
    )

    owned: set[int] = set()
    rows: list[TableRow] = []
    for job in jobs:
        share = job_on_node(job, node_name)
        gpu_ids = parse_gpu_ids(job_gres_on_node(job, node_name))
        owned.update(gpu_ids)
        # One node: NumCPUs is exact. Several: count this node's CPU_IDs.
        single = len(expand_nodelist(job.get('NodeList', ''))) == 1
        cpus = (
            job.get('NumCPUs', '')
            if single
            else len(parse_index_blob(share.get('CPU_IDs', '')))
        )
        row: TableRow = [
            job_id_text(display_job_id(job)),
            user_from_userid(job.get('UserId', '')),
            truncate(job.get('JobName', ''), 24),
        ]
        if total_gpus:
            row.append(_ids(gpu_ids) if gpu_ids else muted())
        row += [
            str(cpus or '-'),
            format_mem_value(share.get('Mem')),
            format_eta(job.get('EndTime', '')),
        ]
        rows.append(row)

    # GresUsed is the authoritative record of GPUs in use; a used GPU no job claims is
    # reported as "owner unknown" so we never overstate what is free.
    used_ids = set(parse_gpu_ids(node_info.get('GresUsed')))
    used_count = total_gpus - free_gpus
    unknown_ids = used_ids - owned
    unknown = max(len(unknown_ids), used_count - len(owned))
    notes: list[str] = []
    if rows and len(used_ids | owned) >= used_count:  # we know which GPUs are free
        free_ids = set(range(total_gpus)) - used_ids - owned
        if free_ids:
            notes.append(f'{"free" if usable else "idle"} GPUs: {_ids(free_ids)}')
    if unknown:
        which = (
            f'GPUs {_ids(unknown_ids)}'
            if len(unknown_ids) == unknown
            else f'{unknown} GPUs'
        )
        notes.append(f'{which} in use, owner unknown')

    if not rows:
        CONSOLE.print(muted(f'No jobs on {node_name}.'))
        if notes:
            CONSOLE.print(muted(' · '.join(notes)))
        return
    columns: list[tuple[str, JustifyMethod]] = [
        ('JobID', 'left'),
        ('User', 'left'),
        ('Name', 'left'),
    ]
    if total_gpus:
        columns.append(('GPUs', 'left'))
    columns += [('CPUs', 'right'), ('Memory', 'right'), ('Time left', 'right')]
    render_table(
        columns, rows, title=f'Jobs on {node_name}', caption=' · '.join(notes) or None
    )


def _slurm_duration(value: str) -> str:
    """squeue's ``1-00:00:00`` / ``6:35:00`` / ``15:00`` as ``1d`` / ``6h35m`` / ``15m``."""
    seconds = parse_slurm_time(value)
    if seconds is None:  # UNLIMITED, INVALID, ...
        return value
    return format_seconds(seconds)
