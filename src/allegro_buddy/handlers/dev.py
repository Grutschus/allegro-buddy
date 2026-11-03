from __future__ import annotations

import math
import shlex
import time
from pathlib import Path

from rich.text import Text

from allegro_buddy import settings
from allegro_buddy.core import (
    ACTIVE_STATES,
    CLI_NAME,
    CONSOLE,
    DEV_FRIENDLY_NAME,
    DEV_JOB_NAME,
    GPU_RESOURCE_CHUNK,
    base_job_id,
    build_dev_job_rows,
    canonical_gpu_type,
    choose_partition,
    collect_display_gpu_types,
    die,
    display_job_id,
    exec_replace,
    expand_nodelist,
    find_dev_jobs,
    format_seconds,
    get_job_detail,
    gpu_type_label,
    hint,
    is_gpu_partition,
    job_id_text,
    load_nodes,
    muted,
    node_text,
    parse_slurm_time,
    partition_text,
    render_table,
    run,
    warn,
)

DEV_JOB_COLUMNS: list = [
    ('JobID', 'left'),
    ('State', 'left'),
    ('Partition', 'left'),
    ('Node', 'left'),
    ('CPUs', 'right'),
    ('Memory', 'right'),
    ('GPUs', 'right'),
    ('Time left', 'left'),
]


def pick_single_dev_job(job_id: str | None) -> dict[str, str]:
    jobs = find_dev_jobs(job_id=job_id)
    if job_id is not None:
        if not jobs:
            die(f'no active {DEV_FRIENDLY_NAME} matched {job_id}')
        return jobs[0]

    if not jobs:
        die(f'no active {DEV_FRIENDLY_NAME}; start one with `{CLI_NAME} dev start`')
    if len(jobs) > 1:
        render_table(DEV_JOB_COLUMNS, build_dev_job_rows(jobs), title='Dev jobs')
        die(f'{len(jobs)} {DEV_FRIENDLY_NAME}s are active; pick one with `--jobid <id>`')
    return jobs[0]


def resolve_job_node(job: dict[str, str]) -> str:
    nodes = expand_nodelist(job.get('NodeList', ''))
    if not nodes:
        die(f'job {display_job_id(job)} has no assigned node yet')
    return nodes[0]


def dev_log_dir() -> Path:
    return Path(settings.load().get('dev', 'log_dir') or '~/slurm-output').expanduser()


def max_dev_allocations() -> int:
    return int(settings.load().get('dev', 'max_allocations') or 1)


def resolve_dev_gres_type(gpu_type: str | None, gpu_count: int) -> str | None:
    """The GRES type string, exactly as the nodes spell it, for a `--gpu-type`.

    Slurm compares GRES types case-sensitively, so sbatch must get e.g. `RTX-A5000`
    as configured on the nodes, never our canonical `rtx_a5000`.
    """
    if gpu_type is None:
        return None
    if gpu_count <= 0:
        die('--gpu-type requires `--gpu` to be at least 1')
    wanted = canonical_gpu_type(gpu_type)
    known: dict[str, str] = {}
    for node in load_nodes():
        for match in GPU_RESOURCE_CHUNK.finditer(node.get('Gres', '')):
            if match.group('type'):
                known.setdefault(
                    canonical_gpu_type(match.group('type')), match.group('type')
                )
    if wanted not in known:
        ordered = collect_display_gpu_types([dict.fromkeys(known, 1)])
        choices = ', '.join(gpu_type_label(name).lower() for name in ordered)
        die(
            f'unknown --gpu-type {gpu_type!r}; '
            + (
                f'this cluster has: {choices}'
                if known
                else 'this cluster has no typed GPUs'
            )
        )
    return known[wanted]


def login_hint() -> None:
    hint(f'`{CLI_NAME} l` opens a shell in it (short for `{CLI_NAME} dev login`)')
    if settings.load().get('cluster', 'node_login') == 'srun':
        hint('it joins with srun, inside the job\'s Slurm environment')
    else:
        hint('it joins with ssh; --srun keeps the job\'s Slurm environment (CUDA_VISIBLE_DEVICES)')


def render_dev_jobs(jobs: list[dict[str, str]], *, show_hint: bool = True) -> None:
    if not jobs:
        CONSOLE.print(muted(f'No active {DEV_FRIENDLY_NAME}.'))
        if show_hint:
            hint(f'`{CLI_NAME} dev start` requests one')
        return
    render_table(DEV_JOB_COLUMNS, build_dev_job_rows(jobs), title='Dev jobs')
    if show_hint and any(job.get('JobState') == 'RUNNING' for job in jobs):
        login_hint()


def wait_for_job_running(
    job_id: str, poll_interval: float, timeout: int | None
) -> dict[str, str]:
    start = time.time()
    # Transient spinner: gone once the job runs, and silent off a terminal.
    with CONSOLE.status(Text.assemble('Waiting for ', job_id_text(job_id))) as status:
        while True:
            job = get_job_detail(job_id)
            if job is None:
                die(f'job {job_id} disappeared before it started')
            state = job.get('JobState', '')
            if state == 'RUNNING':
                break
            if state not in ACTIVE_STATES:
                die(f'job {job_id} ended ({state}) before it started')
            if timeout is not None and time.time() - start > timeout:
                die(f'timed out waiting for {job_id} to start')
            status.update(
                Text.assemble(
                    'Waiting for ',
                    job_id_text(job_id),
                    muted(f' ({state.lower()}: {job.get("Reason", "unknown")})'),
                )
            )
            time.sleep(poll_interval)
    node = job.get('NodeList', '')
    CONSOLE.print(
        Text.assemble(
            job_id_text(job_id),
            ' is running on ',
            node_text(node, job.get('Partition', '')),
        )
    )
    return job


def cmd_dev_start(
    *,
    partition: str,
    time_limit: str,
    gpu: int | None,
    gpu_type: str | None,
    cpus: int,
    mem: str,
    account: str | None,
    constraint: str | None,
    exclude: str | None,
    node: str | None,
    replace: bool,
    no_wait: bool,
    login: bool,
    timeout: int | None,
    poll_interval: float,
) -> None:
    # Validate mutually-exclusive flags BEFORE any state-changing call so a
    # bad invocation can't silently cancel the user's existing dev job.
    if login and no_wait:
        die('`--no-wait` cannot be used together with `--login`')

    existing = find_dev_jobs()
    limit = max_dev_allocations()
    if len(existing) >= limit and not replace:
        render_dev_jobs(existing, show_hint=False)
        die(
            f'you already have {len(existing)} {DEV_FRIENDLY_NAME}(s) (limit {limit}); '
            f'stop with `{CLI_NAME} dev stop` or pass `--replace`'
        )

    selected_partition = choose_partition(partition, gpu or 0, cpus, time_limit)
    gpu_partition = is_gpu_partition(selected_partition)
    # No --gpu and no [dev] gpu: one GPU on a GPU partition, none elsewhere.
    gpu_count = gpu if gpu is not None else int(gpu_partition)
    gres_type = resolve_dev_gres_type(gpu_type, gpu_count)

    if gpu_partition and gpu_count <= 0:
        die('GPU partitions require `--gpu` to be at least 1')
    if not gpu_partition and gpu_count > 0:
        die(
            f'partition {selected_partition} has no GPU nodes; drop --gpu or choose a GPU partition'
        )

    log_dir = dev_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = str(log_dir / f'{DEV_JOB_NAME}-%j.out')
    # Trap SIGTERM/SIGINT to no-op; background sleep + wait unblocks cleanly on Slurm shutdown.
    wrap = 'trap : TERM INT; sleep infinity & wait'

    cpus_per_gpu = math.ceil(cpus / gpu_count) if gpu_count > 0 else cpus
    if gpu_count > 0 and cpus % gpu_count != 0:
        warn(
            f'--cpus {cpus} is not divisible by --gpu {gpu_count}; '
            f'using {cpus_per_gpu * gpu_count} CPUs ({cpus_per_gpu} per GPU)'
        )
    argv = [
        'sbatch',
        '--parsable',
        f'--job-name={DEV_JOB_NAME}',
        f'--partition={selected_partition}',
        f'--time={time_limit}',
        f'--mem={mem}',
        f'--output={output_pattern}',
        f'--wrap={wrap}',
    ]
    if gpu_count > 0:
        argv.append(f'--cpus-per-gpu={cpus_per_gpu}')
        gres_spec = f'gpu:{gres_type}:{gpu_count}' if gres_type else f'gpu:{gpu_count}'
        argv.append(f'--gres={gres_spec}')
    else:
        argv.append(f'--cpus-per-task={cpus}')
    if account:
        argv.append(f'--account={account}')
    if constraint:
        argv.append(f'--constraint={constraint}')
    if exclude:
        argv.append(f'--exclude={exclude}')
    if node:
        argv.append(f'--nodelist={node}')

    # Cancel only now, after every check that can still fail, so a bad
    # --replace request never costs the user their running allocation.
    if existing and replace:
        run(['scancel', *[job['JobId'] for job in existing]], capture_output=False)
        CONSOLE.print(
            muted(f'Canceled {", ".join(display_job_id(j) for j in existing)}.')
        )
        time.sleep(1)

    proc = run(argv)
    # `sbatch --parsable` returns "<jobid>" on a single-cluster setup and
    # "<jobid>;<cluster>" on multi-cluster Slurm. Strip the suffix.
    job_id = proc.stdout.strip().split(';', 1)[0]

    seconds = parse_slurm_time(time_limit)
    request = [
        f'{gpu_count} GPU' + (f' {gres_type}' if gres_type else '') if gpu_count else '',
        f'{cpus} CPUs',
        mem,
        format_seconds(seconds) if seconds is not None else time_limit,
        f'constraint {constraint}' if constraint else '',
    ]
    CONSOLE.print(
        Text.assemble(
            f'Submitted {DEV_FRIENDLY_NAME} ',
            job_id_text(job_id),
            ' on ',
            partition_text(selected_partition),
            muted(f' ({", ".join(part for part in request if part)})'),
        )
    )

    if login or not no_wait:
        try:
            wait_for_job_running(job_id, poll_interval, timeout)
        except KeyboardInterrupt:
            CONSOLE.print(
                muted(
                    f'Detached; {job_id} stays queued ({CLI_NAME} dev stop cancels it).'
                )
            )
            raise
        if login:
            cmd_dev_login(
                jobid=job_id,
                wait=False,
                timeout=timeout,
                poll_interval=poll_interval,
                srun=False,
                command=None,
            )  # replaces this process, so no next step
        else:
            login_hint()
        return

    detail = get_job_detail(job_id) or {}
    if detail.get('JobState') == 'RUNNING':
        login_hint()
    else:
        hint(f'`{CLI_NAME} l --wait` joins it once it runs (short for `{CLI_NAME} dev login --wait`)')


def cmd_dev_status(*, jobid: str | None) -> None:
    render_dev_jobs(find_dev_jobs(job_id=jobid))


def cmd_dev_login(
    *,
    jobid: str | None,
    wait: bool,
    timeout: int | None,
    poll_interval: float,
    srun: bool,
    command: str | None,
) -> None:
    job = pick_single_dev_job(jobid)
    if job.get('JobState') != 'RUNNING':
        if wait:
            job = wait_for_job_running(job['JobId'], poll_interval, timeout)
        else:
            CONSOLE.print(
                Text.assemble(
                    job_id_text(display_job_id(job)),
                    f' is {job.get("JobState", "").lower()}',
                    muted(f' ({job.get("Reason", "unknown")})'),
                )
            )
            hint(f'`{CLI_NAME} l --wait` waits for it to start, then joins')
            raise SystemExit(1)  # did not log in or run --command

    node = resolve_job_node(job)

    if srun or settings.load().get('cluster', 'node_login') == 'srun':
        if command:
            exec_replace(
                [
                    'srun',
                    '--jobid',
                    base_job_id(job['JobId']),
                    '--overlap',
                    '-N1',
                    '-n1',
                    'bash',
                    '-lc',
                    command,
                ]
            )
        exec_replace(
            [
                'srun',
                '--jobid',
                base_job_id(job['JobId']),
                '--overlap',
                '--pty',
                'bash',
                '-l',
            ]
        )

    if command:
        # ssh joins its args and the remote shell re-splits them: quote once.
        exec_replace(['ssh', '-t', node, 'bash -lc ' + shlex.quote(command)])
    exec_replace(['ssh', '-t', node])


def cmd_dev_stop(*, jobid: str | None) -> None:
    jobs = find_dev_jobs(job_id=jobid)
    if not jobs:
        CONSOLE.print(muted(f'No active {DEV_FRIENDLY_NAME} to stop.'))
        return
    run(['scancel', *[job['JobId'] for job in jobs]], capture_output=False)
    CONSOLE.print(f'Canceled {", ".join(display_job_id(job) for job in jobs)}.')
