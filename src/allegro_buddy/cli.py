from __future__ import annotations

import contextlib
import copy
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import rich_click as click
from click.shell_completion import BashComplete, FishComplete, ShellComplete, ZshComplete

from allegro_buddy import settings
from allegro_buddy.core import (
    CLI_NAME,
    CONSOLE,
    DEFAULT_DEV_CPUS,
    DEFAULT_DEV_MEM,
    DEFAULT_DEV_TIME,
    ERROR_CONSOLE,
    find_dev_jobs,
    job_history_completion_ids,
    load_user_pending_jobs,
)
from allegro_buddy.handlers.dev import (
    cmd_dev_login,
    cmd_dev_start,
    cmd_dev_status,
    cmd_dev_stop,
)
from allegro_buddy.handlers.job import cmd_job_history, cmd_job_output
from allegro_buddy.handlers.resources import cmd_free, cmd_info, cmd_node, cmd_queue
from allegro_buddy.handlers.why import cmd_why

# Set in code so every subcommand inherits it; RICH_CLICK_THEME in the env still wins.
CLICK_CONTEXT_SETTINGS = {
    'help_option_names': ['-h', '--help'],
    'rich_help_config': click.RichHelpConfiguration(
        theme='modern',
        commands_table_column_types=['name_with_aliases', 'help'],
        max_width=100,
    ),
}
SHELL_COMPLETERS: dict[str, type[ShellComplete]] = {
    'bash': BashComplete,
    'zsh': ZshComplete,
    'fish': FishComplete,
}
DEFAULT_POLL_INTERVAL = 5.0
DEFAULT_WATCH_INTERVAL = 10.0

F = TypeVar('F', bound=Callable[..., Any])


def _normalize_gpu_type(_ctx, _param, value):
    if value is None:
        return None
    from allegro_buddy.core import canonical_gpu_type

    return canonical_gpu_type(value)


def load_default_map() -> dict[str, Any]:
    """Merged config [dev] values as a click default_map; explicit flags still win."""
    try:
        dev = settings.load().section('dev')
    except settings.ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    start = {
        settings.DEV_START_KEYS[key]: value
        for key, value in dev.items()
        if key in settings.DEV_START_KEYS
    }
    return {'dev': {'start': start}}


def watch_option(func: F) -> F:
    return click.option(
        '-w',
        '--watch',
        # Each refresh queries slurmctld; faster polling loads the shared controller.
        type=click.FloatRange(min=10),
        is_flag=False,
        flag_value=DEFAULT_WATCH_INTERVAL,
        default=None,
        metavar='[SECONDS]',
        help=f'refresh every SECONDS (default {DEFAULT_WATCH_INTERVAL:g}) until Ctrl-C',
    )(func)


def run_watched(render: Callable[[], None], interval: float | None) -> None:
    if interval is None:
        render()
        return
    try:
        while True:
            # render off-screen first so the old view stays up while Slurm answers
            # errors and warnings are captured too, or clear() would wipe them;
            # SystemExit from die(): show the error under the header, retry next round
            with (
                CONSOLE.capture() as capture,
                ERROR_CONSOLE.capture() as errors,
                contextlib.suppress(SystemExit),
            ):
                render()
            CONSOLE.clear()
            CONSOLE.print(
                f'every {interval:g}s · {time.strftime("%H:%M:%S")} · Ctrl-C to quit',
                style='dim',
            )
            sys.stderr.write(errors.get())
            sys.stderr.flush()
            sys.stdout.write(capture.get())
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        pass


def complete_jobid(
    _ctx: click.Context,
    _param: click.Parameter,
    incomplete: str,
) -> list[str]:
    return job_history_completion_ids(incomplete)


def complete_dev_jobid(
    _ctx: click.Context,
    _param: click.Parameter,
    incomplete: str,
) -> list[str]:
    ids = (job.get('JobId', '') for job in find_dev_jobs())
    return [job_id for job_id in ids if job_id.startswith(incomplete)]


def complete_pending_jobid(
    _ctx: click.Context,
    _param: click.Parameter,
    incomplete: str,
) -> list[str]:
    ids = (job.get('JobID', '') for job in load_user_pending_jobs())
    return [job_id for job_id in ids if job_id.startswith(incomplete)]


def add_dev_login_options(func: F) -> F:
    # click lists options in decorator order, so apply them last-shown first
    func = click.option(
        '--command', help='run a command instead of opening a shell'
    )(func)
    func = click.option(
        '--srun',
        is_flag=True,
        help='use srun --overlap instead of ssh (keeps the job\'s GPU setup)',
    )(func)
    func = click.option(
        '--poll-interval',
        type=click.FloatRange(min=1),
        default=DEFAULT_POLL_INTERVAL,
        show_default=True,
        help='seconds between checks while waiting',
    )(func)
    func = click.option('--timeout', type=int, help='max seconds to wait (with --wait)')(func)
    func = click.option(
        '--wait', is_flag=True, help='wait until the job is RUNNING'
    )(func)
    return click.option(
        '--jobid',
        help='pick one dev job by id',
        shell_complete=complete_dev_jobid,
    )(func)


class _Main(click.RichGroup):
    def list_commands(self, ctx: click.Context) -> list[str]:
        # `l` right under `dev`, which it is part of (subgroups inherit this class).
        names = super().list_commands(ctx)
        if 'l' not in names or 'dev' not in names:
            return names
        names.remove('l')
        at = names.index('dev') + 1
        return [*names[:at], 'l', *names[at:]]


@click.group(cls=_Main, context_settings=CLICK_CONTEXT_SETTINGS, invoke_without_command=True)
@click.version_option(package_name='allegro-buddy')
@click.pass_context
def main(ctx: click.Context) -> None:
    """Allegro Buddy: a friendly Slurm helper."""
    ctx.default_map = load_default_map()
    if ctx.invoked_subcommand is None:
        ctx.invoke(info_command)


@main.command('info', short_help='show your partitions and a cluster summary')
@click.option(
    '--all-partitions',
    is_flag=True,
    help='include partitions you cannot use',
)
def info_command(all_partitions: bool) -> None:
    cmd_info(all_partitions=all_partitions)


@main.command('queue', short_help='show your jobs in the queue', aliases=['q'])
@click.option(
    '--all',
    'all_users',
    is_flag=True,
    help='show everyone\'s jobs',
)
@click.option('--user', help='show jobs of USER')
@click.option('-p', '--partition', help='filter by partition')
@watch_option
def queue_command(
    all_users: bool, user: str | None, partition: str | None, watch: float | None
) -> None:
    run_watched(
        lambda: cmd_queue(all_users=all_users, user=user, partition=partition), watch
    )



@main.command('why', short_help='explain what a pending job is waiting for')
@click.argument('jobid', required=False, shell_complete=complete_pending_jobid)
@click.option('--nodes', 'show_nodes', is_flag=True, help='add a per-node table')
@click.option(
    '--fix',
    type=click.Choice(['auto', 'mem', 'cpus', 'gpus']),
    is_flag=False,
    flag_value='auto',
    default=None,
    help='edit the job so it starts now (auto: best mem/cpus change)',
)
@click.option(
    '-y', '--yes', 'assume_yes', is_flag=True, help='apply --fix without asking'
)
def why_command(
    jobid: str | None,
    show_nodes: bool,
    fix: str | None,
    assume_yes: bool,
) -> None:
    """Explain why a pending job has not started and what would start it now.

    Without JOBID, cover each of your jobs waiting for resources.
    """
    cmd_why(jobid=jobid, show_nodes=show_nodes, fix=fix, assume_yes=assume_yes)


def _completion_var(prog: str) -> str:
    normalized = ''.join(ch if ch.isalnum() else '_' for ch in prog).strip('_')
    return f'_{normalized.upper()}_COMPLETE' if normalized else '_AB_COMPLETE'


def _completion_destinations(shell: str, prog: str) -> tuple[Path, Path | None]:
    """Where the script goes, and the startup file that sources it (fish reads its own dir)."""
    env = os.environ
    if shell == 'fish':
        config = Path(env.get('XDG_CONFIG_HOME') or Path.home() / '.config')
        return config / 'fish' / 'completions' / f'{prog}.fish', None
    data = Path(env.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share')
    script = data / 'allegro-buddy' / f'completion-{prog}.{shell}'
    if shell == 'bash':
        return script, Path.home() / '.bashrc'
    return script, Path(env.get('ZDOTDIR') or Path.home()) / '.zshrc'


def _install_completion(shell: str, prog: str, source: str) -> None:
    # A file sourced from the rc, not `eval "$(ab completion ...)"`: the eval runs `ab` on
    # every shell start, and fails when the rc is read before ~/.local/bin is on PATH.
    script, startup = _completion_destinations(shell, prog)
    if shell == 'zsh':  # click's script calls compdef, which needs compinit first
        source = '(( $+functions[compdef] )) || { autoload -Uz compinit && compinit; }\n' + source
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(source + '\n')
    note = ''
    if startup is not None:
        line = f"[ -f '{script}' ] && . '{script}'"
        existing = startup.read_text() if startup.is_file() else ''
        if line in existing:
            note = f'; {startup} already sources it'
        else:
            separator = '' if not existing or existing.endswith('\n') else '\n'
            with startup.open('a') as rc:
                rc.write(f'{separator}{line}\n')
            note = f', sourced from {startup}'
    click.echo(f'Installed {shell} completion{note}. Open a new shell to use it.')


@main.command('completion', short_help='generate or install shell completion')
@click.argument('shell', type=click.Choice(['bash', 'zsh', 'fish']), required=False)
@click.option(
    '--prog',
    default=CLI_NAME,
    show_default=True,
    help='program name to complete',
)
@click.option(
    '--install',
    is_flag=True,
    help='install it and source it from your shell startup file',
)
def completion_command(shell: str | None, prog: str, install: bool) -> None:
    """Print the completion script for SHELL (default: $SHELL), or --install it."""
    if shell is None:
        shell = Path(os.environ.get('SHELL', '')).name
        if shell not in SHELL_COMPLETERS:
            raise click.UsageError(
                f'cannot detect a supported shell from $SHELL ({shell or "unset"!r}); '
                'pass one of bash, zsh, fish'
            )
    completer = SHELL_COMPLETERS[shell](
        cli=main,
        ctx_args={},
        prog_name=prog,
        complete_var=_completion_var(prog),
    )
    if install:
        _install_completion(shell, prog, completer.source())
    else:
        click.echo(completer.source())


@main.command('free', short_help='show free GPUs and cluster resources')
@click.option(
    '--kind',
    type=click.Choice(['gpu', 'cpu']),
    default='gpu',
    show_default=True,
    help='partitions to show',
)
@click.option('--nodes', is_flag=True, help='add a per-node table')
@click.option('-p', '--partition', help='limit the node table to one partition')
@click.option(
    '-G',
    '--gpu-type',
    callback=_normalize_gpu_type,
    help='only this GPU type, e.g. a5000',
)
@watch_option
def free_command(
    kind: str,
    nodes: bool,
    partition: str | None,
    gpu_type: str | None,
    watch: float | None,
) -> None:
    run_watched(
        lambda: cmd_free(
            kind=kind,
            show_nodes=nodes,
            partition_filter=partition,
            gpu_type=gpu_type,
        ),
        watch,
    )


@main.command('node', short_help="show which jobs use a node's GPUs, CPUs and memory")
@click.argument('node', required=False)
def node_command(node: str | None) -> None:
    """Show the jobs on NODE (default: this node, or the node of your job)."""
    cmd_node(node=node)


@main.command('gpualloc', hidden=True)  # the old name of `node`
@click.argument('node', required=False)
def gpualloc_command(node: str | None) -> None:
    cmd_node(node=node)


@main.group('job', short_help='show finished jobs and their output')
def job_group() -> None:
    pass


@job_group.command('history', short_help='list your finished jobs (last 30 days)')
@click.option(
    '--limit',
    type=int,
    default=50,
    show_default=True,
    help='how many jobs to show (0: all)',
)
def job_history_command(limit: int) -> None:
    cmd_job_history(limit=limit)


@job_group.command('output', short_help='show the end of a job\'s output')
@click.argument('jobid', shell_complete=complete_jobid)
@click.option('--stderr', is_flag=True, help='show stderr instead of stdout')
def job_output_command(jobid: str, stderr: bool) -> None:
    cmd_job_output(jobid=jobid, stderr=stderr)


@main.group('dev', short_help='start, join and stop a dev job')
def dev_group() -> None:
    pass


@dev_group.command('start', short_help='submit a detached dev job')
@click.option(
    '-p',
    '--partition',
    default='auto',
    show_default=True,
    help="partition, or auto for Slurm's default",
)
@click.option(
    '-t',
    '--time',
    'time_limit',
    default=DEFAULT_DEV_TIME,
    show_default=True,
    help='Slurm time limit',
)
@click.option(
    '-g',
    '--gpu',
    type=int,
    default=None,
    show_default='1 on GPU partitions, else 0',
    help='GPUs to request',
)
@click.option(
    '--gpu-type',
    type=str,
    callback=_normalize_gpu_type,
    show_default='any',
    help='GPU type, e.g. a5000',
)
@click.option(
    '-c',
    '--cpus',
    type=int,
    default=DEFAULT_DEV_CPUS,
    show_default=True,
    help='CPUs to request',
)
@click.option(
    '-m', '--mem', default=DEFAULT_DEV_MEM, show_default=True, help='memory to request'
)
@click.option('--account', help='Slurm account')
@click.option(
    '--constraint',
    help='Slurm node feature constraint (prefer --gpu-type)',
)
@click.option('--exclude', help='comma-separated nodes to exclude')
@click.option('-n', '--node', help='request a specific node')
@click.option('--replace', is_flag=True, help='cancel existing dev jobs first')
@click.option(
    '--no-wait',
    is_flag=True,
    help='return right after submitting (not with --login)',
)
@click.option(
    '--login',
    is_flag=True,
    help='open a shell once the job is RUNNING (not with --no-wait)',
)
@click.option('--timeout', type=int, help='max seconds to wait for RUNNING')
@click.option(
    '--poll-interval',
    type=click.FloatRange(min=1),
    default=DEFAULT_POLL_INTERVAL,
    show_default=True,
    help='seconds between checks while waiting',
)
def dev_start_command(
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
    """Submit a detached dev job. Flags override the [dev] config (ab config show)."""
    cmd_dev_start(
        partition=partition,
        time_limit=time_limit,
        gpu=gpu,
        gpu_type=gpu_type,
        cpus=cpus,
        mem=mem,
        account=account,
        constraint=constraint,
        exclude=exclude,
        node=node,
        replace=replace,
        no_wait=no_wait,
        login=login,
        timeout=timeout,
        poll_interval=poll_interval,
    )


@dev_group.command('status', short_help='show your dev job')
@click.option(
    '--jobid',
    help='pick one dev job by id',
    shell_complete=complete_dev_jobid,
)
def dev_status_command(jobid: str | None) -> None:
    cmd_dev_status(jobid=jobid)


@dev_group.command('login', short_help='join a running dev job')
@add_dev_login_options
def dev_login_command(
    jobid: str | None,
    wait: bool,
    timeout: int | None,
    poll_interval: float,
    srun: bool,
    command: str | None,
) -> None:
    cmd_dev_login(
        jobid=jobid,
        wait=wait,
        timeout=timeout,
        poll_interval=poll_interval,
        srun=srun,
        command=command,
    )


@dev_group.command('stop', short_help='cancel your dev job')
@click.option(
    '--jobid',
    help='pick one dev job by id',
    shell_complete=complete_dev_jobid,
)
def dev_stop_command(jobid: str | None) -> None:
    cmd_dev_stop(jobid=jobid)


@main.group('config', short_help='show where settings come from')
def config_group() -> None:
    pass


@config_group.command('show', short_help='list every setting and its source')
def config_show_command() -> None:
    from allegro_buddy.handlers.config import cmd_config_show

    cmd_config_show()


l_command = copy.copy(dev_login_command)
l_command.short_help = 'join a running dev job (short for ab dev login)'
main.add_command(l_command, name='l')


if __name__ == '__main__':
    main()
