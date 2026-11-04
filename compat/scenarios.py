"""The scenario matrix: every way the differential harness runs `bab`.

A scenario is argv plus everything around it: the fake Slurm world, environment
overrides, stdin, pipe or pseudo-terminal, files written before the run (paths relative
to the scratch dir T; `@TMP@` in contents and env values becomes T), modes to set, files
to capture afterwards, a SIGINT after N seconds, and further runs in the same T.

Scratch layout: T/home ($HOME, the cwd), T/config ($XDG_CONFIG_HOME), T/cache
($XDG_CACHE_HOME), T/site/config.ini ($AB_SITE_CONFIG). Every run also captures
`.tree`, the list of everything under T afterwards.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import worlds as W

World = dict[str, Any]


@dataclass
class Scenario:
    name: str
    argv: list[str]
    category: str
    world: str | Callable[[], World] = 'demo'
    tweak: Callable[[World], None] | None = None
    env: dict[str, str | None] = field(default_factory=dict)  # None: unset
    stdin: str | None = None
    tty: str = 'pipe'  # 'pipe' | 'pty' (stdin/stdout/stderr on one terminal, no echo)
    winsize: tuple[int, int] | None = None  # pty rows, cols (default 25 x $COLUMNS or 80)
    files: dict[str, str | bytes] = field(default_factory=dict)
    modes: dict[str, int] = field(default_factory=dict)
    capture: list[str] = field(default_factory=list)
    sigint_after: float | None = None
    timeout: float = 60.0
    path_without_slurm: bool = False
    then: list[list[str]] = field(default_factory=list)  # more runs, same T
    # (regex, replacement) on the captured stdout/stderr bytes of both sides
    normalize: list[tuple[bytes, bytes]] = field(default_factory=list)

    def describe(self) -> dict[str, Any]:
        return {
            'name': self.name,
            'category': self.category,
            'argv': self.argv,
            'then': self.then,
            'world': self.world if isinstance(self.world, str) else 'custom',
            'tweak': self.tweak is not None,
            'env': self.env,
            'stdin': self.stdin,
            'tty': self.tty,
            'files': sorted(self.files),
            'capture': self.capture,
            'sigint_after': self.sigint_after,
            'path_without_slurm': self.path_without_slurm,
            'normalize': [[p.decode(), r.decode()] for p, r in self.normalize],
        }


SCENARIOS: list[Scenario] = []


def add(name: str, argv: list[str], category: str, **kwargs: Any) -> None:
    if any(s.name == name for s in SCENARIOS):
        raise ValueError(f'duplicate scenario {name}')
    SCENARIOS.append(Scenario(name=name, argv=argv, category=category, **kwargs))


# ---------------------------------------------------------------------------
# World tweaks
# ---------------------------------------------------------------------------


def chain(*tweaks: Callable[[World], None]) -> Callable[[World], None]:
    def apply(world: World) -> None:
        for tweak in tweaks:
            tweak(world)

    return apply


def without_jobs(*ids: str) -> Callable[[World], None]:
    def apply(world: World) -> None:
        world['jobs'] = [job for job in world['jobs'] if job['id'] not in ids]

    return apply


def no_jobs(world: World) -> None:
    world['jobs'] = []


def with_jobs(*jobs: dict[str, Any]) -> Callable[[World], None]:
    def apply(world: World) -> None:
        world['jobs'] = [*world['jobs'], *copy.deepcopy(jobs)]

    return apply


def change_job(job_id: str, **changes: Any) -> Callable[[World], None]:
    def apply(world: World) -> None:
        for job in world['jobs'] + world.get('finished', []):
            if job['id'] == job_id:
                job.update(changes)

    return apply


def change_node(name: str, **changes: str) -> Callable[[World], None]:
    def apply(world: World) -> None:
        for node in world['nodes']:
            if node['NodeName'] == name:
                node.update(changes)

    return apply


def setitem(**items: Any) -> Callable[[World], None]:
    def apply(world: World) -> None:
        world.update(copy.deepcopy(items))

    return apply


def sbatch(**rule: Any) -> Callable[[World], None]:
    def apply(world: World) -> None:
        world['sbatch'].update(rule)

    return apply


# Console.status on a terminal: how many spinner frames show depends on timing (12.5/s);
# keep the cursor hide/show and everything around them.
SPINNER = (rb'\x1b\[\?25l.*?\x1b\[\?25h', b'\x1b[?25l<spinner frames>\x1b[?25h')
USER_CONFIG = 'config/allegro-buddy/config.ini'
SITE_CONFIG = 'site/config.ini'
CACHE_FILE = 'cache/allegro-buddy/cluster-name.login1'
COLS = ('160', '80')


def cols(width: str, **env: str | None) -> dict[str, str | None]:
    return {'COLUMNS': width, **env}


# ---------------------------------------------------------------------------
# tests/demo_cluster.py SCENARIOS (the tests/snapshots/allegro-*.txt), 160 and 80 cols
# ---------------------------------------------------------------------------

DEMO = [
    ('help', ['-h'], {}),
    ('queue', ['queue'], {}),
    ('queue-all', ['q', '--all'], {}),
    ('why', ['why'], {}),
    ('why-job', ['why', '70120'], {}),
    ('why-nodes', ['why', '70120', '--nodes'], {}),
    ('why-fix', ['why', '70122'], {}),
    (
        'why-fix-confirm',
        ['why', '70122', '--fix'],
        {'stdin': 'n\n', 'env': {'BAB_TEST_INTERACTIVE': '1'}},
    ),
    ('node', ['node', 'gpu102'], {}),
    ('node-shared', ['node', 'gpu201'], {}),
    ('node-cpu', ['node', 'cmp201'], {}),
    ('job-history', ['job', 'history'], {}),
    ('job-output', ['job', 'output', '70090'], {}),
    ('dev-status', ['dev', 'status'], {}),
    ('dev-start', ['dev', 'start', '--no-wait'], {'tweak': without_jobs('70110')}),
    ('dev-stop', ['dev', 'stop'], {}),
    ('config-show', ['config', 'show'], {}),
    ('error-unknown-job', ['why', '999999'], {}),
]
for _name, _argv, _extra in DEMO:
    for _w in COLS:
        _kw = copy.deepcopy({k: v for k, v in _extra.items() if k != 'tweak'})
        _kw['env'] = {**_kw.get('env', {}), 'COLUMNS': _w}
        add(f'demo-{_name}-c{_w}', _argv, 'demo', tweak=_extra.get('tweak'), **_kw)

# test_demo_output.py's other cases
add('demo-node-drained', ['node', 'gpu102'], 'demo', env=cols('160'),
    tweak=chain(no_jobs, change_node('gpu102', State='IDLE+DRAIN')))
add('demo-node-used-without-indices', ['node', 'gpu102'], 'demo', env=cols('160'),
    tweak=chain(no_jobs, change_node('gpu102', GresUsed='gpu:RTX-A5000:2(IDX:N/A)')))
add('demo-node-multi-node-share', ['node', 'gpu102'], 'demo', env=cols('160'),
    tweak=change_job('70104', node='gpu[101-102]', detail_line=(
        'JobId=70104 JobName=finetune UserId=bob(1001) JobState=RUNNING Reason=None '
        'SubmitTime=2026-11-03T09:15:00 StartTime=2026-11-03T09:20:00 '
        'EndTime=2026-11-05T09:20:00 Partition=gpu NodeList=gpu[101-102] NumCPUs=8 '
        'MinMemoryNode=32G TresPerNode=gres/gpu:RTX-A5000:2 JOB_GRES=gpu:RTX-A5000:2 '
        'Nodes=gpu101 CPU_IDs=0-1 Mem=8192 GRES=gpu:RTX-A5000:1(IDX:1) '
        'Nodes=gpu102 CPU_IDs=0-5 Mem=24576 GRES=gpu:RTX-A5000:1(IDX:3) '
        'StdErr=/home/bob/slurm-70104.out StdOut=/home/bob/slurm-70104.out')))
add('demo-free-full-node', ['free'], 'demo', env=cols('160'),
    tweak=change_node('gpu102', CPUAlloc='16', State='ALLOCATED'))
add('demo-node-multi-node-share-c80', ['node', 'gpu101'], 'demo', env=cols('80'),
    tweak=change_job('70104', node='gpu[101-102]'))

# ---------------------------------------------------------------------------
# tests/test_cluster_output.py (FakeSlurm worlds)
# ---------------------------------------------------------------------------

for _w in COLS:
    for _name, _argv in [
        ('info', ['info']),
        ('free', ['free']),
        ('free-nodes', ['free', '--nodes']),
        ('free-cpu', ['free', '--kind', 'cpu', '--nodes']),
        ('free-a5000', ['free', '-G', 'a5000', '--nodes']),
    ]:
        add(f'plain-{_name}-c{_w}', _argv, 'cluster', world='plain', env=cols(_w))
    add(f'nojson-free-nodes-c{_w}', ['free', '--nodes'], 'cluster', world='nojson', env=cols(_w))
    add(f'other-info-c{_w}', ['info'], 'cluster', world='other', env=cols(_w))
    add(f'other-free-c{_w}', ['free'], 'cluster', world='other', env=cols(_w))
    add(f'lise-info-c{_w}', ['info'], 'cluster', world='lise', env=cols(_w))
    add(f'lise-free-c{_w}', ['free'], 'cluster', world='lise', env=cols(_w))
    add(f'lise-free-nodes-c{_w}', ['free', '--nodes'], 'cluster', world='lise', env=cols(_w))

for _i, _args in enumerate([
    [],
    ['--gpu-type', 'a5000'],
    ['--gpu-type', 'gtx1080', '-g', '2'],
    ['-p', 'small', '-g', '0', '-c', '4'],
]):
    add(f'plain-dev-start-argv-{_i}', ['dev', 'start', '--no-wait', *_args], 'cluster',
        world='plain', env=cols('160'))
add('other-dev-start-default-partition', ['dev', 'start', '--no-wait'], 'cluster',
    world='other', env=cols('160'))
add('other-dev-start-a100', ['dev', 'start', '--no-wait', '-p', 'a100', '--gpu-type', 'A100'],
    'cluster', world='other', env=cols('160'))
add('other-dev-start-unknown-gpu-type',
    ['dev', 'start', '--no-wait', '-p', 'a100', '--gpu-type', 'a5000'], 'cluster',
    world='other', env=cols('160'))
add('cpuonly-free', ['free'], 'cluster', world='cpuonly', env=cols('160'))
add('cpuonly-free-cpu-nodes', ['free', '--kind', 'cpu', '--nodes'], 'cluster',
    world='cpuonly', env=cols('160'))
add('nodefault-dev-start', ['dev', 'start', '--no-wait'], 'cluster', world='nodefault',
    env=cols('160'))
_LAYERS = {SITE_CONFIG: '[dev]\ncpus = 4\nmem = 16G\n', USER_CONFIG: '[dev]\nmem = 32G\n'}
add('plain-config-show-layers', ['config', 'show'], 'cluster', world='plain',
    env=cols('160'), files=_LAYERS)
add('plain-config-show-layers-c80', ['config', 'show'], 'cluster', world='plain',
    env=cols('80'), files=_LAYERS)
add('plain-dev-start-layers', ['dev', 'start', '--no-wait'], 'cluster', world='plain',
    env=cols('160'), files=_LAYERS)
add('plain-ab-cluster-none-config', ['config', 'show'], 'cluster', world='plain',
    env=cols('160', AB_CLUSTER='none'))
add('plain-ab-cluster-none-dev-start', ['dev', 'start', '--no-wait', '-g', '0'], 'cluster',
    world='plain', env=cols('160', AB_CLUSTER='none'))
add('lise-dev-start-defaults', ['dev', 'start', '--no-wait'], 'cluster', world='lise',
    env=cols('160'))
add('lise-dev-start-h200', ['dev', 'start', '--no-wait', '-p', 'gpu-h200', '--gpu-type', 'h200'],
    'cluster', world='lise', env=cols('160'))
add('plain-cluster-name-probed-once', ['free'], 'cluster', world='plain', env=cols('160'),
    then=[['free']], capture=[CACHE_FILE])

# ---------------------------------------------------------------------------
# Colour and terminals: FORCE_COLOR / NO_COLOR / TERM / pty
# ---------------------------------------------------------------------------

MAIN_VIEWS = [
    ('info', ['info']),
    ('free', ['free']),
    ('free-nodes', ['free', '--nodes']),
    ('free-cpu', ['free', '--kind', 'cpu']),
    ('queue', ['queue']),
    ('queue-all', ['q', '--all']),
    ('why', ['why']),
    ('why-nodes', ['why', '70120', '--nodes']),
    ('why-fix', ['why', '70122']),
    ('node', ['node', 'gpu102']),
    ('node-shared', ['node', 'gpu201']),
    ('job-history', ['job', 'history']),
    ('job-output', ['job', 'output', '70090']),
    ('dev-status', ['dev', 'status']),
    ('config-show', ['config', 'show']),
    ('help', ['-h']),
    ('dev-start-help', ['dev', 'start', '-h']),
    ('error-unknown-job', ['why', '999999']),
    ('usage-error', ['free', '--kind', 'nvme']),
]
for _name, _argv in MAIN_VIEWS:
    add(f'color-{_name}-c160', _argv, 'color', env=cols('160', FORCE_COLOR='1'))
for _name, _argv in MAIN_VIEWS[:6] + MAIN_VIEWS[15:17]:
    add(f'color-{_name}-c80', _argv, 'color', env=cols('80', FORCE_COLOR='1'))
for _name, _argv in [('info', ['info']), ('help', ['-h']), ('queue', ['queue']),
                     ('error-unknown-job', ['why', '999999'])]:
    add(f'pty-{_name}', _argv, 'color', tty='pty', env=cols('120'))
    add(f'pty-{_name}-winsize', _argv, 'color', tty='pty', env={'COLUMNS': None},
        winsize=(30, 132))
    add(f'pty-{_name}-dumb', _argv, 'color', tty='pty', env=cols('120', TERM='dumb'))
    add(f'pty-{_name}-no-color', _argv, 'color', tty='pty', env=cols('120', NO_COLOR='1'))
add('pty-info-truecolor', ['info'], 'color', tty='pty', env=cols('120', COLORTERM='truecolor'))
add('pty-info-term-xterm', ['info'], 'color', tty='pty', env=cols('120', TERM='xterm'))
add('pty-info-term-unset', ['info'], 'color', tty='pty', env=cols('120', TERM=None))
add('pty-job-output', ['job', 'output', '70090'], 'color', tty='pty', env=cols('100'))
add('pty-dev-status', ['dev', 'status'], 'color', tty='pty', env=cols('100'))
add('pty-config-show', ['config', 'show'], 'color', tty='pty', env=cols('100'))
add('pty-completion-bash', ['completion', 'bash'], 'color', tty='pty', env=cols('100'))
add('color-info-no-color', ['info'], 'color', env=cols('160', FORCE_COLOR='1', NO_COLOR='1'))
add('color-help-no-color', ['-h'], 'color', env=cols('160', FORCE_COLOR='1', NO_COLOR='1'))
add('color-dev-status-force-empty', ['dev', 'status'], 'color', env=cols('160', FORCE_COLOR=''))
add('color-dev-status-force-0', ['dev', 'status'], 'color', env=cols('160', FORCE_COLOR='0'))
add('color-info-dumb', ['info'], 'color', env=cols('160', FORCE_COLOR='1', TERM='dumb'))
add('color-info-truecolor', ['info'], 'color',
    env=cols('160', FORCE_COLOR='1', COLORTERM='truecolor'))
add('color-info-256', ['info'], 'color', env=cols('160', FORCE_COLOR='1', TERM='xterm-256color'))
add('color-help-github-actions', ['-h'], 'color', env=cols('100', GITHUB_ACTIONS='true'))
add('color-help-py-colors', ['-h'], 'color', env=cols('100', PY_COLORS='1'))
for _w in ('40', '60', '100', '200', 'abc', '0'):
    add(f'width-info-c{_w}', ['info'], 'width', env=cols(_w))
    add(f'width-help-c{_w}', ['-h'], 'width', env=cols(_w))
add('width-info-unset', ['info'], 'width', env={'COLUMNS': None})
add('width-free-nodes-c60', ['free', '--nodes'], 'width', env=cols('60'))
add('width-queue-all-c60', ['q', '--all'], 'width', env=cols('60'))
add('width-why-nodes-c60', ['why', '70120', '--nodes'], 'width', env=cols('60'))
add('width-dev-start-help-c60', ['dev', 'start', '-h'], 'width', env=cols('60'))
add('width-lines-set', ['info'], 'width', env=cols('100', LINES='5'))
for _theme in ('plain', 'nord-box', 'forest-slim', 'quartz-robo', 'cargo-nu', 'dracula',
               'mono', 'modern', 'star-modern', 'bogus', 'nord-bogus'):
    add(f'theme-help-{_theme}', ['-h'], 'theme',
        env=cols('100', FORCE_COLOR='1', RICH_CLICK_THEME=_theme))
for _theme in ('plain', 'nord-box', 'cargo-nu'):
    add(f'theme-dev-start-help-{_theme}', ['dev', 'start', '-h'], 'theme',
        env=cols('100', FORCE_COLOR='1', RICH_CLICK_THEME=_theme))
    add(f'theme-usage-error-{_theme}', ['free', '--kind', 'nvme'], 'theme',
        env=cols('100', FORCE_COLOR='1', RICH_CLICK_THEME=_theme))
add('theme-help-plain-nocolor', ['-h'], 'theme', env=cols('100', RICH_CLICK_THEME='plain'))

# ---------------------------------------------------------------------------
# Help for every command and subgroup
# ---------------------------------------------------------------------------

COMMANDS = [
    [], ['info'], ['queue'], ['q'], ['why'], ['completion'], ['free'], ['node'],
    ['gpualloc'], ['job'], ['job', 'history'], ['job', 'output'], ['dev'],
    ['dev', 'start'], ['dev', 'status'], ['dev', 'login'], ['dev', 'stop'], ['l'],
    ['config'], ['config', 'show'],
]  # fmt: skip
for _cmd in COMMANDS:
    _slug = '-'.join(_cmd) or 'root'
    add(f'help-{_slug}-c80', [*_cmd, '-h'], 'help', env=cols('80'))
    add(f'help-{_slug}-c120', [*_cmd, '--help'], 'help', env=cols('120'))
add('help-root-long-c100', ['--help'], 'help', env=cols('100'))
add('help-root-c100-unset', ['-h'], 'help', env={'COLUMNS': None})
add('help-job-no-subcommand', ['job'], 'help', env=cols('100'))
add('help-dev-no-subcommand', ['dev'], 'help', env=cols('100'))
add('help-config-no-subcommand', ['config'], 'help', env=cols('100'))
add('help-after-args', ['q', '-p', 'gpu', '-h'], 'help', env=cols('100'))
add('help-before-subcommand', ['-h', 'queue'], 'help', env=cols('100'))
add('help-dev-start-config-defaults', ['dev', 'start', '-h'], 'help', env=cols('100'),
    files={USER_CONFIG: '[dev]\nmem = 32G\ngpu = 2\ngpu-type = RTX_A5000\ntime = 04:00:00\n'
                        'partition = gpusmall\ncpus = 6\n'})
add('help-dev-start-site-defaults', ['dev', 'start', '-h'], 'help', env=cols('100'),
    files={SITE_CONFIG: '[dev]\nmem = 64G\naccount = ml-lab\n'})
add('help-dev-start-lise-preset', ['dev', 'start', '-h'], 'help', world='lise',
    env=cols('100'))
add('help-dev-start-invalid-config', ['dev', 'start', '-h'], 'help', env=cols('100'),
    files={USER_CONFIG: '[dev]\ngpus = 2\n'})
add('help-root-invalid-config', ['-h'], 'help', env=cols('100'),
    files={USER_CONFIG: '[dev]\ngpus = 2\n'})
add('help-completion-shell-env', ['completion', '-h'], 'help',
    env=cols('100', SHELL='/bin/zsh'))

# ---------------------------------------------------------------------------
# CLI parsing: tests/test_cli.py as a differential argv matrix
# ---------------------------------------------------------------------------

CLI = [
    ('version', ['--version']),
    ('version-short-v', ['-V']),
    ('version-after-command', ['info', '--version']),
    ('no-args', []),
    ('info-all-partitions', ['info', '--all-partitions']),
    ('alias-q', ['q']),
    ('alias-q-all', ['q', '--all']),
    ('queue-user', ['queue', '--user', 'bob']),
    ('queue-user-equals', ['queue', '--user=bob']),
    ('queue-user-empty', ['queue', '--user', 'nobody']),
    ('queue-partition', ['queue', '-p', 'gpusmall']),
    ('queue-partition-attached', ['queue', '-pgpusmall']),
    ('queue-partition-repeated', ['queue', '-p', 'gpusmall', '-p', 'gpu']),
    ('queue-all-and-user', ['queue', '--all', '--user', 'bob']),
    ('queue-partition-missing-value', ['queue', '-p']),
    ('queue-unknown-option', ['queue', '-x']),
    ('queue-option-typo', ['queue', '--al']),
    ('queue-watch-too-small', ['q', '--watch', '5']),
    ('queue-watch-attached-too-small', ['q', '-w5']),
    ('queue-watch-equals-too-small', ['q', '--watch=9.99']),
    ('queue-watch-not-a-number', ['q', '-w', 'abc']),
    ('queue-watch-inf', ['q', '-w', '-inf']),
    ('queue-extra-arg', ['queue', 'extra']),
    ('alias-l', ['l']),
    ('alias-l-command', ['l', '--command', 'nvidia-smi']),
    ('gpualloc', ['gpualloc', 'gpu102']),
    ('gpualloc-guess', ['gpualloc']),
    ('unknown-command', ['bogus']),
    ('unknown-command-typo', ['qeue']),
    ('unknown-command-close', ['inf']),
    ('unknown-root-option', ['--bogus']),
    ('unknown-subcommand', ['dev', 'bogus']),
    ('unknown-job-subcommand', ['job', 'histroy']),
    ('info-extra-arg', ['info', 'extra']),
    ('info-option-typo', ['info', '--all-partition']),
    ('node-two-args', ['node', 'gpu101', 'gpu102']),
    ('node-double-dash', ['node', '--', 'gpu102']),
    ('node-unknown', ['node', 'nosuch']),
    ('node-dash-arg', ['node', '-gpu102']),
    ('why-double-dash', ['why', '--', '70120']),
    ('why-fix-bad-choice', ['why', '70122', '--fix', 'disk']),
    ('why-fix-without-job', ['why', '--fix']),
    ('why-fix-before-yes', ['why', '70122', '--fix', '-y']),
    ('why-fix-equals', ['why', '70122', '--fix=mem', '-y']),
    ('why-fix-then-nodes', ['why', '70122', '--nodes', '--fix', 'cpus', '-y']),
    ('why-yes-without-fix', ['why', '70120', '-y']),
    ('why-yes-without-job', ['why', '-y']),
    ('why-fix-job-after', ['why', '--fix', 'mem', '70122', '-y']),
    ('why-fix-flag-then-job', ['why', '--fix', '70122']),
    ('why-two-jobs', ['why', '70120', '70122']),
    ('why-running-job', ['why', '70110']),
    ('why-array-like-id', ['why', '70120_[0-3]']),
    ('free-kind-bad-choice', ['free', '--kind', 'nvme']),
    ('free-kind-repeated', ['free', '--kind', 'cpu', '--kind', 'gpu']),
    ('free-kind-attached', ['free', '--kind=cpu']),
    ('free-gpu-type-upper', ['free', '--gpu-type', 'A100']),
    ('free-gpu-type-a5000', ['free', '-G', 'A5000']),
    ('free-gpu-type-synonym', ['free', '-G', 'rtx-a5000', '--nodes']),
    ('free-gpu-type-gtx', ['free', '-G', 'gtx1080']),
    ('free-gpu-type-unknown', ['free', '-G', 'h100', '--nodes']),
    ('free-partition', ['free', '--nodes', '-p', 'gpusmall']),
    ('free-partition-unknown', ['free', '-p', 'nosuch']),
    ('free-cpu-partition', ['free', '--kind', 'cpu', '-p', 'small']),
    ('free-cpu-nodes', ['free', '--kind', 'cpu', '--nodes']),
    ('job-history-limit', ['job', 'history', '--limit', '2']),
    ('job-history-limit-zero', ['job', 'history', '--limit', '0']),
    ('job-history-limit-negative', ['job', 'history', '--limit', '-1']),
    ('job-history-limit-100', ['job', 'history', '--limit', '100']),
    ('job-history-limit-bad', ['job', 'history', '--limit', 'abc']),
    ('job-history-limit-float', ['job', 'history', '--limit', '1.5']),
    ('job-output-missing-arg', ['job', 'output']),
    ('job-output-stderr-first', ['job', 'output', '--stderr', '70090']),
    ('dev-start-gpu-not-int', ['dev', 'start', '-g', 'x']),
    ('dev-start-timeout-float', ['dev', 'start', '--timeout', '1.5']),
    ('dev-start-poll-zero', ['dev', 'start', '--poll-interval', '0']),
    ('dev-start-poll-half', ['dev', 'start', '--poll-interval', '0.5']),
    ('dev-start-poll-text', ['dev', 'start', '--poll-interval', 'soon']),
    ('dev-login-poll-zero', ['dev', 'login', '--poll-interval', '0']),
    ('l-poll-zero', ['l', '--poll-interval', '0']),
    ('dev-start-cpus-attached', ['dev', 'start', '-c4', '--no-wait', '--replace']),
    ('dev-start-short-cluster', ['dev', 'start', '-pgpu', '-g1', '-t1:00:00', '--no-wait',
                                 '--replace']),
    ('completion-bad-shell', ['completion', 'tcsh']),
    ('completion-two-shells', ['completion', 'bash', 'zsh']),
    ('config-show-extra', ['config', 'show', 'extra']),
    ('double-dash-root', ['--', 'info']),
    ('empty-string-command', ['']),
]
for _name, _argv in CLI:
    add(f'cli-{_name}', _argv, 'cli', env=cols('100'))
add('cli-no-args-c160', [], 'cli', env=cols('160'))
add('cli-version-pty', ['--version'], 'cli', tty='pty', env=cols('100'))
add('cli-unknown-command-color', ['bogus'], 'cli', env=cols('100', FORCE_COLOR='1'))
add('cli-unknown-command-pty', ['bogus'], 'cli', tty='pty', env=cols('100'))

# ---------------------------------------------------------------------------
# `why`: tests/test_why.py against controlled records and nodes
# ---------------------------------------------------------------------------


def why(records, nodes=None, **kw) -> Callable[[], World]:
    return lambda: W.why_world(records, nodes, **kw)


GTX084 = W.node_dict('gpu084', gres='gpu:GTX-1080ti:4', features='Intel,GTX-1080ti')
ARRAY, CPU, PLAIN_GPU = W.ARRAY_JOB, W.CPU_JOB, W.PLAIN_GPU_JOB
WHY = [
    ('overview', ['why'], why([ARRAY, {**PLAIN_GPU, 'user_name': 'bob'},
                               {**CPU, 'state_reason': 'Dependency'}])),
    ('overview-array', ['why'], why([ARRAY])),
    ('overview-points-at-fix', ['why'], why([CPU])),
    ('overview-nothing-waiting', ['why'], why([{**ARRAY, 'user_name': 'bob'}])),
    ('overview-three-jobs', ['why'], why([ARRAY, CPU, PLAIN_GPU])),
    ('detail', ['why', '65177'], why([ARRAY])),
    ('detail-array-task', ['why', '65177_3'], why([ARRAY])),
    ('detail-array-spec', ['why', '65177_[0-11]'], why([ARRAY])),
    ('detail-other-gpu-type', ['why', '65177', '--nodes'], why([ARRAY], [*W.LIVE_NODES, GTX084])),
    ('detail-no-matching-nodes', ['why', '65177'], why([ARRAY], [GTX084])),
    ('detail-short-resource', ['why', '64267'], why([CPU])),
    ('detail-short-resource-nodes', ['why', '64267', '--nodes'], why([CPU])),
    ('detail-no-fix-slots', ['why', '65177'], why([ARRAY])),
    ('detail-gpu-fix', ['why', '65177'], why([ARRAY], [W.GPU110])),
    ('detail-gpu-fix-nodes', ['why', '65177', '--nodes'], why([ARRAY], [W.GPU110])),
    ('detail-resubmit', ['why', '65177'],
     why([{**ARRAY, 'tres_per_node': '', 'tres_per_job': 'gres/gpu:4'}], [W.GPU110])),
    ('detail-fits-now', ['why', '65160'], why([PLAIN_GPU], [W.node_dict('gpu110', state='IDLE')])),
    ('detail-never-fits', ['why', '64267'], why([{**CPU, 'cpus': W.number(64)}])),
    ('detail-nodes-table', ['why', '65177', '--nodes'], why([ARRAY])),
    ('detail-dependency', ['why', '65177'], why([{**ARRAY, 'state_reason': 'Dependency'}])),
    ('detail-dependency-cpu', ['why', '64267'], why([{**CPU, 'state_reason': 'Dependency'}])),
    ('detail-running', ['why', '65177'], why([{**ARRAY, 'job_state': ['RUNNING']}])),
    ('detail-unknown', ['why', '99999'], why([ARRAY])),
    ('detail-feature-or', ['why', '65160'], why([{**PLAIN_GPU, 'features': 'RTX-A5000|GTX-1080ti'}])),
    ('detail-multi-node', ['why', '64267', '--nodes'],
     why([{**CPU, 'node_count': W.number(2), 'cpus': W.number(8)}])),
    ('detail-reservation', ['why', '65177', '--nodes'], why([{**ARRAY, 'resv_name': 'maint'}])),
    ('detail-mem-per-cpu', ['why', '64267'],
     why([{**CPU, 'memory_per_cpu': W.number(14336), 'memory_per_node': W.number(None)}])),
    ('detail-excluded', ['why', '65177', '--nodes'], why([{**ARRAY, 'excluded_nodes': 'gpu105'}])),
    ('detail-required', ['why', '65177', '--nodes'], why([{**ARRAY, 'required_nodes': 'gpu106'}])),
    ('option-fix-needs-job', ['why', '--fix'], why([ARRAY])),
    ('option-yes-needs-fix', ['why', '65177', '-y'], why([ARRAY])),
]
for _name, _argv, _world in WHY:
    add(f'why-{_name}', _argv, 'why', world=_world, env=cols('160'))
for _name in ('overview', 'detail', 'detail-nodes-table', 'detail-gpu-fix'):
    _argv, _world = next((a, w) for n, a, w in WHY if n == _name)
    add(f'why-{_name}-c80', _argv, 'why', world=_world, env=cols('80'))
    add(f'why-{_name}-color', _argv, 'why', world=_world, env=cols('120', FORCE_COLOR='1'))

UPDATED_CPU = W.UPDATED_CPU_JOB
FULL_CMP238 = W.node_dict('cmp238', partitions='small,big', gres='(null)', cpus=40,
                          cpus_alloc=40)
FIX = [
    ('yes-applies', ['why', '64267', '--fix', '-y'], why([CPU], after=[UPDATED_CPU]), {}),
    ('held-job', ['why', '64267', '--fix', '-y'],
     why([{**CPU, 'state_reason': 'JobHeldUser'}]), {}),
    ('no-terminal-no-yes', ['why', '64267', '--fix'], why([CPU]), {}),
    ('interactive-0', ['why', '64267', '--fix'], why([CPU]),
     {'env': {'BAB_TEST_INTERACTIVE': '0'}, 'stdin': 'y\n'}),
    ('other-users-job', ['why', '64267', '--fix', '-y'], why([CPU]),
     {'env': {'USER': 'bob', 'LOGNAME': 'bob'}}),
    ('multi-node', ['why', '64267', '--fix', '-y'],
     why([{**CPU, 'node_count': W.number(2), 'cpus': W.number(8)}]), {}),
    ('heterogeneous', ['why', '64267', '--fix', '-y'],
     why([{**CPU, 'het_job_id': W.number(64267)}]), {}),
    ('only-gpu-fix', ['why', '65177', '--fix', '-y'], why([ARRAY], [W.GPU110]), {}),
    ('knob-without-fix', ['why', '64267', '--fix', 'cpus', '-y'], why([CPU]), {}),
    ('gpu-fix-without-command', ['why', '65177', '--fix', 'gpus', '-y'],
     why([{**ARRAY, 'tres_per_node': '', 'tres_per_job': 'gres/gpu:4'}], [W.GPU110]), {}),
    ('auto-only-advice', ['why', '64267', '--fix', '-y'],
     why([W.CPUS_PER_TASK_JOB], [W.THREE_FREE_CPUS]), {}),
    ('already-fits', ['why', '65160', '--fix', '-y'],
     why([PLAIN_GPU], [W.node_dict('gpu110', state='IDLE')]), {}),
    ('auto-skips-cpu-fix', ['why', '64267', '--fix', '-y'],
     why([W.CPUS_PER_TASK_JOB], [*W.LIVE_NODES, W.THREE_FREE_CPUS],
         after=[{**W.CPUS_PER_TASK_JOB, 'memory_per_node': W.number(32768)}]), {}),
    ('explicit-gpu-fix', ['why', '65177', '--fix', 'gpus', '-y'],
     why([ARRAY], [W.GPU110],
         after=[{**ARRAY, 'tres_per_node': 'gres/gpu:RTX-A5000:2', 'cpus': W.number(8)}]), {}),
    ('explicit-mem-fix', ['why', '64267', '--fix', 'mem', '-y'],
     why([CPU], after=[UPDATED_CPU]), {}),
    ('failed-update', ['why', '64267', '--fix', '-y'],
     why([CPU], update_exit=1, update_stderr='Access denied\n'), {}),
    ('failed-update-silent', ['why', '64267', '--fix', '-y'], why([CPU], update_exit=3), {}),
    ('partial-array-update', ['why', '64267', '--fix', '-y'],
     why([CPU], after=[UPDATED_CPU], update_exit=1,
         update_stderr='64267_[0-49]: Job is no longer pending execution\n'), {}),
    ('mismatch-after-update', ['why', '64267', '--fix', '-y'], why([CPU], after=[CPU]), {}),
    ('cluster-changed', ['why', '64267', '--fix', '-y'],
     why([CPU], after=[UPDATED_CPU], nodes_after=[FULL_CMP238]), {}),
    ('job-gone', ['why', '64267', '--fix', '-y'],
     why([CPU], after=[PLAIN_GPU], records_filter=False), {}),
    ('job-started', ['why', '64267', '--fix', '-y'],
     why([CPU], after=[{**UPDATED_CPU, 'job_state': ['RUNNING']}]), {}),
    ('reread-fails', ['why', '64267', '--fix', '-y'], why([CPU], after=[]), {}),
    ('prompt-yes-pipe', ['why', '64267', '--fix'], why([CPU], after=[UPDATED_CPU]),
     {'env': {'BAB_TEST_INTERACTIVE': '1'}, 'stdin': 'y\n'}),
    ('prompt-no-pipe', ['why', '64267', '--fix'], why([CPU]),
     {'env': {'BAB_TEST_INTERACTIVE': '1'}, 'stdin': 'n\n'}),
    ('prompt-eof-pipe', ['why', '64267', '--fix'], why([CPU]),
     {'env': {'BAB_TEST_INTERACTIVE': '1'}, 'stdin': ''}),
    ('prompt-garbage-pipe', ['why', '64267', '--fix'], why([CPU], after=[UPDATED_CPU]),
     {'env': {'BAB_TEST_INTERACTIVE': '1'}, 'stdin': 'maybe\nYES\n'}),
    ('prompt-yes-pty', ['why', '64267', '--fix'], why([CPU], after=[UPDATED_CPU]),
     {'tty': 'pty', 'stdin': 'y\n'}),
    ('prompt-no-pty', ['why', '64267', '--fix'], why([CPU]), {'tty': 'pty', 'stdin': 'n\n'}),
    ('prompt-default-pty', ['why', '64267', '--fix'], why([CPU]), {'tty': 'pty', 'stdin': '\n'}),
    ('prompt-garbage-pty', ['why', '64267', '--fix'], why([CPU]),
     {'tty': 'pty', 'stdin': 'sure\nno way\nn\n'}),
    ('prompt-eof-pty', ['why', '64267', '--fix'], why([CPU]), {'tty': 'pty', 'stdin': '\x04'}),
    ('prompt-uppercase-pty', ['why', '64267', '--fix'], why([CPU], after=[UPDATED_CPU]),
     {'tty': 'pty', 'stdin': 'Y\n'}),
    ('prompt-interactive-0-pty', ['why', '64267', '--fix'], why([CPU]),
     {'tty': 'pty', 'stdin': 'y\n', 'env': {'BAB_TEST_INTERACTIVE': '0'}}),
]
for _name, _argv, _world, _extra in FIX:
    _env = {'COLUMNS': '120', **_extra.pop('env', {})}
    add(f'fix-{_name}', _argv, 'fix', world=_world, env=_env, **_extra)
add('fix-demo-yes', ['why', '70122', '--fix', '-y'], 'fix', env=cols('120'))
add('fix-demo-mem-yes', ['why', '70122', '--fix', 'mem', '-y'], 'fix', env=cols('120'))
add('fix-demo-cpus-yes', ['why', '70122', '--fix', 'cpus', '-y'], 'fix', env=cols('120'))
add('fix-demo-gpus-yes', ['why', '70122', '--fix', 'gpus', '-y'], 'fix', env=cols('120'))
add('fix-demo-priority-job', ['why', '70121', '--fix', '-y'], 'fix', env=cols('120'))
add('fix-demo-other-user', ['why', '70131', '--fix', '-y'], 'fix', env=cols('120'))
add('fix-demo-confirm-pty', ['why', '70122', '--fix'], 'fix', tty='pty', stdin='y\n',
    env=cols('120'))
add('fix-demo-color', ['why', '70122', '--fix', '-y'], 'fix',
    env=cols('120', FORCE_COLOR='1'))

# ---------------------------------------------------------------------------
# dev start / status / login / stop (tests/test_dev.py, test_cli.py)
# ---------------------------------------------------------------------------

NO_DEV = without_jobs('70110')
SECOND_DEV = with_jobs(W.demo_job('70111', 'alice', 'ab-dev', 'RUNNING', 'gpusmall', 480, 2,
                                  8192, 1, 'GTX-1080ti', 'gpu201', '3', started=-20))
PENDING_DEV = change_job('70110', state='PENDING', reason='Priority', node='', started=0)
RUNS_AT_ONCE = sbatch(becomes={'after_polls': 0, 'node': 'gpu102', 'gpu_idx': '2'})
RUNS_LATER = sbatch(becomes={'after_polls': 1, 'node': 'gpu102', 'gpu_idx': '2'})
DEV = [
    ('status-jobid', ['dev', 'status', '--jobid', '70110'], {}),
    ('status-jobid-unknown', ['dev', 'status', '--jobid', '999'], {}),
    ('status-none', ['dev', 'status'], {'tweak': NO_DEV}),
    ('status-two', ['dev', 'status'], {'tweak': SECOND_DEV}),
    ('status-pending', ['dev', 'status'], {'tweak': PENDING_DEV}),
    ('status-completing', ['dev', 'status'], {'tweak': change_job('70110', state='COMPLETING')}),
    ('status-srun-config', ['dev', 'status'],
     {'files': {USER_CONFIG: '[cluster]\nnode-login = srun\n'}}),
    ('start-limit-reached', ['dev', 'start', '--no-wait'], {}),
    ('start-limit-reached-two', ['dev', 'start'], {'tweak': SECOND_DEV}),
    ('start-max-allocations', ['dev', 'start', '--no-wait'],
     {'files': {USER_CONFIG: '[dev]\nmax-allocations = 2\n'}}),
    ('start-replace', ['dev', 'start', '--no-wait', '--replace'], {}),
    ('start-replace-two', ['dev', 'start', '--no-wait', '--replace'], {'tweak': SECOND_DEV}),
    ('start-replace-bad-partition', ['dev', 'start', '--replace', '-p', 'gpuu'], {}),
    ('start-replace-bad-gpu-type', ['dev', 'start', '--replace', '--gpu-type', 'h100'], {}),
    ('start-replace-too-long', ['dev', 'start', '--replace', '-t', '3-00:00:00'], {}),
    ('start-login-no-wait', ['dev', 'start', '--login', '--no-wait'], {}),
    ('start-login-no-wait-replace', ['dev', 'start', '--login', '--no-wait', '--replace'], {}),
    ('start-cpu-partition', ['dev', 'start', '--no-wait', '-p', 'small', '-g', '0'],
     {'tweak': NO_DEV}),
    ('start-cpu-partition-gpu', ['dev', 'start', '--no-wait', '-p', 'small', '-g', '1'],
     {'tweak': NO_DEV}),
    ('start-gpu-partition-zero-gpus', ['dev', 'start', '--no-wait', '-g', '0'],
     {'tweak': NO_DEV}),
    ('start-gpu-type-zero-gpus', ['dev', 'start', '--no-wait', '-p', 'small', '-g', '0',
                                  '--gpu-type', 'a5000'], {'tweak': NO_DEV}),
    ('start-unknown-gpu-type', ['dev', 'start', '--no-wait', '--gpu-type', 'h100'],
     {'tweak': NO_DEV}),
    ('start-not-divisible', ['dev', 'start', '--no-wait', '-g', '2', '--cpus', '3'],
     {'tweak': NO_DEV}),
    ('start-all-flags', ['dev', 'start', '--no-wait', '-p', 'gpusmall', '-t', '2:00:00', '-g',
                         '2', '--gpu-type', 'gtx1080', '-c', '8', '-m', '24G', '--account',
                         'teaching', '--constraint', 'Intel', '--exclude', 'gpu201', '-n',
                         'gpu202'], {'tweak': NO_DEV}),
    ('start-time-unparsable', ['dev', 'start', '--no-wait', '-t', 'soon'], {'tweak': NO_DEV}),
    ('start-time-days', ['dev', 'start', '--no-wait', '-t', '1-12'], {'tweak': NO_DEV}),
    ('start-time-too-long', ['dev', 'start', '--no-wait', '-t', '99:00:00'], {'tweak': NO_DEV}),
    ('start-unknown-partition', ['dev', 'start', '--no-wait', '-p', 'nosuch'],
     {'tweak': NO_DEV}),
    ('start-auto-partition', ['dev', 'start', '--no-wait', '-p', 'auto', '-g', '0'],
     {'tweak': NO_DEV}),
    ('start-sbatch-fails', ['dev', 'start', '--no-wait'],
     {'tweak': chain(NO_DEV, sbatch(exit=1, stderr='sbatch: error: QOSMaxSubmitJobPerUserLimit\n'))}),
    ('start-sbatch-cluster-suffix', ['dev', 'start', '--no-wait'],
     {'tweak': chain(NO_DEV, sbatch(suffix=';allegro'))}),
    ('start-runs-at-once', ['dev', 'start'], {'tweak': chain(NO_DEV, RUNS_AT_ONCE)}),
    ('start-runs-after-poll', ['dev', 'start', '--poll-interval', '1'],
     {'tweak': chain(NO_DEV, RUNS_LATER)}),
    ('start-no-wait-running', ['dev', 'start', '--no-wait'],
     {'tweak': chain(NO_DEV, RUNS_AT_ONCE)}),
    ('start-ends-before-start', ['dev', 'start'],
     {'tweak': chain(NO_DEV, sbatch(becomes={'after_polls': 0, 'state': 'FAILED',
                                             'reason': 'NonZeroExitCode'}))}),
    ('start-timeout', ['dev', 'start', '--timeout', '0', '--poll-interval', '1'],
     {'tweak': chain(NO_DEV, sbatch(becomes={'after_polls': 5}))}),
    ('start-login', ['dev', 'start', '--login'], {'tweak': chain(NO_DEV, RUNS_AT_ONCE)}),
    ('start-login-srun-config', ['dev', 'start', '--login'],
     {'tweak': chain(NO_DEV, RUNS_AT_ONCE),
      'files': {USER_CONFIG: '[cluster]\nnode-login = srun\n'}}),
    ('start-replace-login', ['dev', 'start', '--login', '--replace'],
     {'tweak': RUNS_AT_ONCE}),
    ('start-config-defaults', ['dev', 'start', '--no-wait', '-g', '1'],
     {'tweak': NO_DEV, 'files': {USER_CONFIG: '[dev]\ngpu = 2\ngpu-type = RTX_A5000\n'
                                              'mem = 32G\ntime = 04:00:00\n'}}),
    ('start-config-log-dir', ['dev', 'start', '--no-wait'],
     {'tweak': NO_DEV, 'files': {USER_CONFIG: '[dev]\nlog-dir = @TMP@/logs/dev\n'},
      'capture': []}),
    ('start-config-log-dir-tilde', ['dev', 'start', '--no-wait'],
     {'tweak': NO_DEV, 'files': {USER_CONFIG: '[dev]\nlog_dir = ~/my logs\n'}}),
    ('start-config-partition', ['dev', 'start', '--no-wait'],
     {'tweak': NO_DEV, 'files': {SITE_CONFIG: '[dev]\npartition = gpushort\ntime = 2:00:00\n'
                                              'account = ml-lab\n'
                                              'constraint = Intel\nexclude = gpu201\n'}}),
    ('start-config-gpu-zero-cpu-partition', ['dev', 'start', '--no-wait', '-p', 'micro', '-t',
                                              '30'],
     {'tweak': NO_DEV, 'files': {USER_CONFIG: '[dev]\ngpu = 0\ncpus = 1\nmem = 2G\n'}}),
    ('start-config-bad-gpu', ['dev', 'start', '--no-wait'],
     {'tweak': NO_DEV, 'files': {USER_CONFIG: '[dev]\ngpu = two\n'}}),
    ('start-config-bad-cpus', ['dev', 'start', '--no-wait'],
     {'tweak': NO_DEV, 'files': {USER_CONFIG: '[dev]\ncpus = 1.5\n'}}),
    ('start-plain-disappears', ['dev', 'start'], {'world': 'plain'}),
    ('start-groups-no-access', ['dev', 'start', '--no-wait', '-p', 'big', '-g', '0'],
     {'world': 'groups'}),
    ('start-pty-runs-at-once', ['dev', 'start'],
     {'tweak': chain(NO_DEV, RUNS_AT_ONCE), 'tty': 'pty', 'normalize': [SPINNER]}),
    ('start-pty-runs-after-poll', ['dev', 'start', '--poll-interval', '1'],
     {'tweak': chain(NO_DEV, RUNS_LATER), 'tty': 'pty', 'normalize': [SPINNER]}),
    ('login-pty-pending-wait', ['l', '--wait', '--poll-interval', '1'],
     {'tweak': chain(PENDING_DEV, change_job('70110', becomes={'after_polls': 1,
                                                              'node': 'gpu101'})),
      'tty': 'pty', 'normalize': [SPINNER]}),
    ('login', ['dev', 'login'], {}),
    ('login-command', ['dev', 'login', '--command', 'cd x && make'], {}),
    ('login-srun', ['dev', 'login', '--srun'], {}),
    ('login-srun-command', ['dev', 'login', '--srun', '--command', 'nvidia-smi -L'], {}),
    ('login-srun-config', ['l'], {'files': {USER_CONFIG: '[cluster]\nnode-login = srun\n'}}),
    ('login-ssh-config', ['l'], {'files': {USER_CONFIG: '[cluster]\nnode-login = ssh\n'}}),
    ('login-ssh-fails', ['l'], {'tweak': setitem(ssh={'exit': 255, 'stdout': '',
                                                      'stderr': 'ssh: connect refused\n'})}),
    ('login-jobid', ['l', '--jobid', '70110'], {}),
    ('login-jobid-unknown', ['l', '--jobid', '999'], {}),
    ('login-none', ['l'], {'tweak': NO_DEV}),
    ('login-two', ['l'], {'tweak': SECOND_DEV}),
    ('login-two-jobid', ['l', '--jobid', '70111'], {'tweak': SECOND_DEV}),
    ('login-pending', ['l'], {'tweak': PENDING_DEV}),
    ('login-pending-command', ['l', '--command', 'make'], {'tweak': PENDING_DEV}),
    ('login-pending-wait', ['l', '--wait', '--poll-interval', '1'],
     {'tweak': chain(PENDING_DEV, change_job('70110', becomes={'after_polls': 1,
                                                              'node': 'gpu101'}))}),
    ('login-pending-wait-timeout', ['l', '--wait', '--timeout', '0', '--poll-interval', '1'],
     {'tweak': PENDING_DEV}),
    ('login-multi-node', ['l'], {'tweak': change_job('70110', node='gpu[101-102]')}),
    ('stop', ['dev', 'stop'], {}),
    ('stop-two', ['dev', 'stop'], {'tweak': SECOND_DEV}),
    ('stop-jobid', ['dev', 'stop', '--jobid', '70111'], {'tweak': SECOND_DEV}),
    ('stop-jobid-unknown', ['dev', 'stop', '--jobid', '999'], {}),
    ('stop-none', ['dev', 'stop'], {'tweak': NO_DEV}),
    ('stop-scancel-fails', ['dev', 'stop'],
     {'tweak': setitem(scancel={'exit': 1, 'stderr': 'scancel: error: Kill job error\n'})}),
]
for _name, _argv, _extra in DEV:
    add(f'dev-{_name}', _argv, 'dev', env=cols('120'), **_extra)
add('dev-status-c80', ['dev', 'status'], 'dev', env=cols('80'), tweak=SECOND_DEV)
add('dev-start-c80', ['dev', 'start', '--no-wait'], 'dev', env=cols('80'), tweak=NO_DEV)

# ---------------------------------------------------------------------------
# job history / output
# ---------------------------------------------------------------------------

LONG_LOG = ''.join(f'step {i:03d}: loss {1 / (i + 1):.4f}\n' for i in range(250))
SACCT_FALLBACK = setitem(finished=[], sacct_jobs={
    '70090': 'alice|@TMP@/demo/slurm-%j.out|@TMP@/demo/slurm-%j.err|70090|prep-data|70090',
    '70080_3': 'alice|@TMP@/demo/%x-%A_%a.out|@TMP@/demo/%x-%A_%a.err|70083|sweep|70080_3',
    '70085': 'bob|/home/bob/slurm-%j.out|/home/bob/slurm-%j.out|70085|x|70085',
    '70086': 'alice|None|None|70086|x|70086',
    '70087': 'alice|@TMP@/demo/out-%u-%4j-%N-%%.log|@TMP@/demo/e.log|70087|x|70087',
})
JOB = [
    ('history-c80', ['job', 'history'], {'env': cols('80')}),
    ('history-empty', ['job', 'history'], {'world': 'plain'}),
    ('history-only-active', ['job', 'history'],
     {'tweak': setitem(sacct_rows=W.SACCT_ROWS[:2])}),
    ('history-dev-jobs-hidden', ['job', 'history'],
     {'tweak': setitem(sacct_rows=['70060|70060|ab-dev|TIMEOUT|0:0|2026-11-01T09:00:00|None'])}),
    ('history-old-and-odd', ['job', 'history'], {'tweak': setitem(sacct_rows=[
        '1|1|old|COMPLETED|0:0|2025-12-31T23:59:59|None',
        '2|2|this-year|COMPLETED|0:0|2026-01-05T08:00:00|None',
        '3|3|a-very-long-job-name-that-is-cut-off|FAILED|2:0|2026-11-03T09:59:00|None',
        '4|4|no-end|NODE_FAIL|0:0|Unknown|None',
        '5|5|dup|COMPLETED|0:0|2026-11-02T10:00:00|None',
        '5|5|dup|COMPLETED|0:0|2026-11-02T10:00:00|None',
        '6|6|weird-end|PREEMPTED|0:0|later|None',
        '7|7|null-exit|BOOT_FAIL||2026-11-02T10:00:00|None',
        '8_1|8_1|array|COMPLETED|0:9|2026-10-28T10:00:00|None',
        '9|9|future|COMPLETED|0:0|2026-11-04T10:00:00|None',
        '|||missing-id||||',
        'short|row',
    ])}),
    ('history-sacct-fails', ['job', 'history'],
     {'tweak': setitem(sacct_fail={'exit': 1, 'stderr':
         'sacct: error: Problem talking to the database: Connection refused\n'})}),
    ('history-sacct-localhost', ['job', 'history'],
     {'tweak': setitem(sacct_fail={'exit': 1, 'stderr':
         'sacct: error: slurm_persist_conn_open_without_init: failed to open persistent '
         'connection to host:localhost:6819: Connection refused\n'})}),
    ('history-sacct-localhost-slurm-conf', ['job', 'history'],
     {'tweak': setitem(sacct_fail={'exit': 1, 'stderr':
         'sacct: error: failed to open persistent connection to host:localhost:6819\n'}),
      'env': {'SLURM_CONF': '/etc/slurm/slurm.conf'}}),
    ('history-sacct-fails-silently', ['job', 'history'],
     {'tweak': setitem(sacct_fail={'exit': 2})}),
    ('output-stderr', ['job', 'output', '70090', '--stderr'], {}),
    ('output-stderr-file', ['job', 'output', '70090', '--stderr'],
     {'tweak': change_job('70090', stderr='@TMP@/demo/slurm-70090.err'),
      'files': {'demo/slurm-70090.err': 'warning: something odd\n'}}),
    ('output-other-user', ['job', 'output', '70102'], {}),
    ('output-unknown', ['job', 'output', '999999'], {}),
    ('output-running-own', ['job', 'output', '70110'], {}),
    ('output-long', ['job', 'output', '70090'], {'files': {'demo/slurm-70090.out': LONG_LOG}}),
    ('output-exactly-200', ['job', 'output', '70090'],
     {'files': {'demo/slurm-70090.out': ''.join(f'{i}\n' for i in range(200))}}),
    ('output-empty', ['job', 'output', '70090'], {'files': {'demo/slurm-70090.out': ''}}),
    ('output-blank', ['job', 'output', '70090'], {'files': {'demo/slurm-70090.out': '\n \n'}}),
    ('output-no-newline', ['job', 'output', '70090'],
     {'files': {'demo/slurm-70090.out': 'no newline at the end'}}),
    ('output-markup', ['job', 'output', '70090'],
     {'files': {'demo/slurm-70090.out': '[bold]not markup[/bold] :smile: \x1b[31mred\x1b[0m\n'
                                         'tab\there\n' + 'x' * 300 + '\n'}}),
    ('output-binary', ['job', 'output', '70090'],
     {'files': {'demo/slurm-70090.out': b'caf\xc3 ok\n\xff\xfe end\n'}}),
    ('output-directory', ['job', 'output', '70090'],
     {'tweak': change_job('70090', stdout='@TMP@/demo')}),
    ('output-missing-file', ['job', 'output', '70090'],
     {'tweak': change_job('70090', stdout='@TMP@/demo/gone.out')}),
    ('output-unreadable', ['job', 'output', '70090'], {'modes': {'demo/slurm-70090.out': 0o000}}),
    ('output-sacct-fallback', ['job', 'output', '70090'], {'tweak': SACCT_FALLBACK}),
    ('output-sacct-fallback-stderr', ['job', 'output', '70090', '--stderr'],
     {'tweak': SACCT_FALLBACK, 'files': {'demo/slurm-70090.err': 'err text\n'}}),
    ('output-sacct-array', ['job', 'output', '70080_3'],
     {'tweak': SACCT_FALLBACK, 'files': {'demo/sweep-70080_3.out': 'task 3\n'}}),
    ('output-sacct-other-user', ['job', 'output', '70085'], {'tweak': SACCT_FALLBACK}),
    ('output-sacct-none', ['job', 'output', '70086'], {'tweak': SACCT_FALLBACK}),
    ('output-sacct-patterns', ['job', 'output', '70087'], {'tweak': SACCT_FALLBACK}),
    ('output-env-in-path', ['job', 'output', '70090'],
     {'tweak': change_job('70090', stdout='$HOME/../demo/slurm-70090.out')}),
    ('output-tilde-path', ['job', 'output', '70090'],
     {'tweak': change_job('70090', stdout='~/out/%j.log'),
      'files': {'home/out/70090.log': 'from home\n'}}),
    ('output-c80', ['job', 'output', '70090'], {'env': cols('80')}),
]
for _name, _argv, _extra in JOB:
    _env = {'COLUMNS': '120', **_extra.pop('env', {})}
    add(f'job-{_name}', _argv, 'job', env=_env, **_extra)

# ---------------------------------------------------------------------------
# queue: tests/test_queue.py (squeue fields as given, bottleneck hints)
# ---------------------------------------------------------------------------

Q_RUNNING = {**W.demo_job('64612', 'bob', 'train', 'RUNNING', 'gpu', 480, 4, 8192,
                          node='gpu081', started=-62),
             'squeue': {'M': '1:02:03', 'L': '6:57:57', 'S': '2026-10-05T12:34:00'}}
Q_PENDING = {**W.demo_job('64613', 'carol', 'eval', 'PENDING', 'gpu', 480, 16, 40960,
                          reason='Resources'),
             'squeue': {'S': '2099-01-01T08:00:00'}}
Q_PENDING_NO_ESTIMATE = {**W.demo_job('64614', 'carol', 'post', 'PENDING', 'gpu', 480, 16,
                                      40960, reason='Dependency')}
Q_RECORD = {**W.ARRAY_JOB, 'job_id': 64613, 'array_job_id': W.number(0),
            'array_task_string': '', 'user_name': 'carol'}
Q_NODE = W.node_dict('gpu106', cpus_alloc=4, mem_alloc=81920,
                     gres_used='gpu:RTX-A5000:2(IDX:0-1)', features='Intel,RTX-A5000')
Q_ARRAY = {**W.demo_job('65177', 'alice', 'sweep', 'PENDING', 'gpu', 120, 16, 40960, 4,
                        'RTX-A5000', reason='Resources'),
           'display_id': '65177_[0-11]', 'squeue': {'S': '2026-11-03T13:10:00'}}


def queue_world(jobs, records=None, nodes=None, *, scontrol_fail=False) -> Callable[[], World]:
    def build() -> World:
        world = W.plain()
        world['jobs'] = copy.deepcopy(jobs)
        world['records'] = copy.deepcopy([Q_RECORD] if records is None else records)
        world['nodes'] = copy.deepcopy([Q_NODE] if nodes is None else nodes)
        if scontrol_fail:
            world['fail'] = [{'argv': ['scontrol', flag], 'exit': 1, 'stderr': 'down\n'}
                             for flag in ('--json', '--oneliner')]
        return world

    return build


def q_job(base: dict[str, Any], **squeue: str) -> dict[str, Any]:
    job = copy.deepcopy(base)
    job['squeue'] = {**job.get('squeue', {}), **squeue}
    return job


QUEUE = [
    ('all-users', ['q', '--all'], queue_world([Q_RUNNING, Q_PENDING])),
    ('user-carol', ['q', '--user', 'carol'], queue_world([Q_PENDING])),
    ('scontrol-fails', ['q', '--user', 'carol'], queue_world([Q_PENDING], scontrol_fail=True)),
    ('job-left-scontrol', ['q', '--all'], queue_world([Q_PENDING], records=[])),
    ('no-hint-reasons', ['q', '--all'], queue_world([Q_RUNNING, Q_PENDING_NO_ESTIMATE])),
    ('under-an-hour', ['q', '--all'], queue_world([q_job(Q_RUNNING, L='40:00')])),
    ('running-only', ['q', '--all'], queue_world([Q_RUNNING])),
    ('pending-only', ['q', '--user', 'carol'], queue_world([Q_PENDING, Q_PENDING_NO_ESTIMATE])),
    ('empty-other-user', ['q', '--user', 'bob'], queue_world([])),
    ('empty-own', ['q'], queue_world([])),
    ('empty-all', ['q', '--all'], queue_world([])),
    ('start-due', ['q', '--all'], queue_world([q_job(Q_PENDING, S='2026-11-03T09:00:00')])),
    ('start-soon', ['q', '--all'], queue_world([q_job(Q_PENDING, S='2026-11-03T13:10:00')])),
    ('start-next-week', ['q', '--all'], queue_world([q_job(Q_PENDING, S='2026-11-12T08:00:00')])),
    ('odd-times', ['q', '--all'], queue_world([
        q_job(Q_RUNNING, L='UNLIMITED', M='3-04:05:06'),
        q_job({**Q_RUNNING, 'id': '64615'}, L='INVALID', M='0:59'),
        q_job({**Q_RUNNING, 'id': '64616'}, L='1-00:00:00', M='59:59'),
    ])),
    ('long-cells', ['q', '--all'], queue_world([
        q_job({**Q_RUNNING, 'name': 'an-extremely-long-job-name-that-goes-on-and-on'},
              R='gpu[081-089,101-109,201-209],cmp[001-099]'),
        q_job({**Q_PENDING_NO_ESTIMATE, 'reason':
               'ReqNodeNotAvail, UnavailableNodes:gpu[081-089,101-109]'}),
    ])),
    ('array-pending', ['q'], queue_world([Q_ARRAY], records=[W.ARRAY_JOB],
                                         nodes=W.LIVE_NODES)),
    ('array-pending-fixable', ['q'], queue_world([Q_ARRAY], records=[W.ARRAY_JOB],
                                                 nodes=[W.GPU110])),
    ('cpu-pending-fixable', ['q', '--all'], queue_world(
        [{**W.demo_job('64267', 'alice', 'big', 'PENDING', 'big', 600, 4, 57344,
                       reason='Resources'), 'display_id': '64267_[50-142]'}],
        records=[W.CPU_JOB], nodes=W.LIVE_NODES)),
]
for _name, _argv, _world in QUEUE:
    add(f'queue-{_name}', _argv, 'queue', world=_world, env=cols('200'))
for _name in ('all-users', 'array-pending', 'long-cells'):
    _argv, _world = next((a, w) for n, a, w in QUEUE if n == _name)
    add(f'queue-{_name}-c80', _argv, 'queue', world=_world, env=cols('80'))
    add(f'queue-{_name}-color', _argv, 'queue', world=_world, env=cols('120', FORCE_COLOR='1'))

# ---------------------------------------------------------------------------
# GPU counting, node states, reservations (test_gpu*.py, test_stats.py)
# ---------------------------------------------------------------------------


def mixed() -> World:
    nd = W.node_dict
    world = W.plain()
    clock_now = '2026-11-03T10:00:00'
    world['nodes'] = [
        nd('gpu1', gpus_used=3, cpus_alloc=6, mem_alloc=40000),
        nd('gpu2', gpus_used=1, cpus_alloc=2, mem_alloc=8000),
        nd('gpu3', state='MAINT+RESERVED', gpus_used=0),
        nd('gpu4', state='MAINT+RESERVED', gpus_used=0),
        nd('cmp1', gres='(null)', partitions='gpu,small', cpus=64, cpus_alloc=60),
        nd('gpu5', partitions='other'),
        nd('gpu6', state='DOWN+NOT_RESPONDING'),
        nd('gpu7', state='IDLE+DRAIN'),
        nd('gpu8', state='ALLOCATED', gpus_used=2, cpus_alloc=16),
        nd('gpu9', gres='gpu:4', features='Intel,A100', gpus_used=1, state='MIXED'),
        nd('gpu10', gres='gpu:a100:2,gpu:v100:2',
           gres_used='gpu:a100:1(IDX:0),gpu:v100:0(IDX:N/A)', features=''),
        nd('gpu11', state='MIXED+PLANNED', spec_mem=2048, gpus_used=2),
        nd('gpu12', gres='gpu:tesla_v100:2(S:0-1)', features='', state='IDLE',
           gres_used='gpu:tesla_v100:0(IDX:N/A)'),
        nd('gpu13', gres='gpu:4', features='Intel', gres_used='gpu:2(IDX:0,2)'),
        nd('cmp2', gres='(null)', partitions='small', state='IDLE', cpus=32, mem=256000),
        nd('cmp3', gres='(null)', partitions='small', state='MIXED+COMPLETING', cpus=32,
           cpus_alloc=31, mem=256000, mem_alloc=255000),
    ]
    world['partitions'] = W.partition_props({
        'gpu': ('2-00:00:00', 'NO'), 'other': ('UNLIMITED', 'NO'),
        'small': ('30', 'YES'), 'empty': ('1:00:00', 'NO'),
    })
    resv = ('ReservationName={name} StartTime={start} EndTime={end} Duration=1-00:00:00 '
            'Nodes={nodes} NodeCnt={count} CoreCnt=16 Features=(null) PartitionName=(null) '
            'Flags=MAINT,SPEC_NODES TRES=cpu=16 Users={users} Groups={groups} '
            'Accounts=(null) Licenses=(null) State={state} BurstBuffer=(null)')
    world['reservations'] = [
        resv.format(name='mine', start='2026-11-02T10:00:00', end='2026-11-04T10:00:00',
                    nodes='gpu3', count=1, users='alice', groups='(null)', state='ACTIVE'),
        resv.format(name='other', start='2026-11-02T10:00:00', end='2026-11-05T12:30:00',
                    nodes='gpu4', count=1, users='bob', groups='(null)', state='ACTIVE'),
        resv.format(name='ancient', start='2026-09-01T10:00:00', end='2027-01-01T00:00:00',
                    nodes='gpu5', count=1, users='bob', groups='(null)', state='ACTIVE'),
        resv.format(name='maint', start='2026-11-05T08:00:00', end='2026-11-05T20:00:00',
                    nodes='gpu1,gpu2', count=2, users='(null)', groups='(null)',
                    state='INACTIVE'),
        resv.format(name='course', start='2026-11-20T08:00:00', end='2026-11-21T08:00:00',
                    nodes='gpu[9-10],gpu[11-13],cmp[1-3],gpu[1-2],gpu6,gpu7', count=12,
                    users='(null)', groups='users,staff', state='INACTIVE'),
        resv.format(name='past', start='2026-11-01T08:00:00', end='2026-11-02T08:00:00',
                    nodes='gpu8', count=1, users='alice', groups='(null)', state='INACTIVE'),
        'ReservationName=nonodes StartTime=2026-11-06T00:00:00 EndTime=2026-11-06T01:00:00 '
        'Nodes=(null) NodeCnt=0 Users=alice Groups=(null) State=INACTIVE',
    ]
    world['jobs'] = [
        W.demo_job('80001', 'alice', 'blocked-maint', 'PENDING', 'gpu', 60, 1, 1024,
                   reason='ReqNodeNotAvail, Reserved for maintenance'),
        W.demo_job('80002', 'alice', 'blocked-other', 'PENDING', 'gpu', 60, 1, 1024,
                   reason='Reservation other is busy'),
        W.demo_job('80003', 'alice', 'not-blocked', 'PENDING', 'gpu', 60, 1, 1024,
                   reason='Resources', start_estimate=45),
        W.demo_job('80004', 'alice', 'running', 'RUNNING', 'gpu', 600, 2, 4096, 1, '',
                   'gpu13', '0', started=-30),
    ]
    assert clock_now == W.NOW
    return world


def specmem() -> World:
    world = W.plain()
    world['nodes'] = [W.node_dict('gpu081', spec_mem=2048)]
    return world


MIXED = [
    ('info', ['info']),
    ('info-all', ['info', '--all-partitions']),
    ('free', ['free']),
    ('free-nodes', ['free', '--nodes']),
    ('free-a100', ['free', '-G', 'a100', '--nodes']),
    ('free-v100', ['free', '-G', 'v100']),
    ('free-generic', ['free', '-G', 'generic', '--nodes']),
    ('free-cpu', ['free', '--kind', 'cpu']),
    ('free-cpu-nodes', ['free', '--kind', 'cpu', '--nodes']),
    ('node-multi-type', ['node', 'gpu10']),
    ('node-generic-typed', ['node', 'gpu9']),
    ('node-untyped-ids', ['node', 'gpu13']),
    ('node-drained', ['node', 'gpu7']),
    ('node-down', ['node', 'gpu6']),
    ('node-reserved', ['node', 'gpu3']),
    ('node-specmem', ['node', 'gpu11']),
    ('node-socket-gres', ['node', 'gpu12']),
    ('node-cpu', ['node', 'cmp3']),
    ('queue', ['q']),
    ('config-show', ['config', 'show']),
]
for _name, _argv in MIXED:
    add(f'mixed-{_name}', _argv, 'gpu', world=mixed, env=cols('160'))
for _name in ('info', 'free', 'free-nodes'):
    _argv = next(a for n, a in MIXED if n == _name)
    add(f'mixed-{_name}-c80', _argv, 'gpu', world=mixed, env=cols('80'))
    add(f'mixed-{_name}-color', _argv, 'gpu', world=mixed, env=cols('160', FORCE_COLOR='1'))
add('mixed-info-groups-staff', ['info'], 'gpu', world=mixed,
    env=cols('160', BAB_TEST_GROUPS='staff'))
add('mixed-free-nodes-other-user', ['free', '--nodes'], 'gpu', world=mixed,
    env=cols('160', USER='bob', LOGNAME='bob'))
add('specmem-node', ['node', 'gpu081'], 'gpu', world=specmem, env=cols('120'))
add('specmem-free-nodes', ['free', '--nodes'], 'gpu', world=specmem, env=cols('120'))

# ---------------------------------------------------------------------------
# Shell completion: scripts, --install, and real completion requests
# ---------------------------------------------------------------------------

for _shell in ('bash', 'zsh', 'fish'):
    add(f'completion-script-{_shell}', ['completion', _shell], 'completion', env=cols('100'))
    add(f'completion-script-{_shell}-prog', ['completion', _shell, '--prog', 'allegro-buddy'],
        'completion', env=cols('100'))
    add(f'completion-source-{_shell}', [], 'completion',
        env=cols('100', _BAB_COMPLETE=f'{_shell}_source'))
for _shell in ('/bin/zsh', '/usr/bin/fish', '/bin/bash', '/bin/tcsh', '', 'bash'):
    add(f'completion-detect-{_shell.strip("/").replace("/", "-") or "empty"}', ['completion'],
        'completion', env=cols('100', SHELL=_shell))
add('completion-detect-unset', ['completion'], 'completion', env=cols('100', SHELL=None))
add('completion-prog-symbols', ['completion', 'bash', '--prog', '---'], 'completion',
    env=cols('100'))
add('completion-prog-dotted', ['completion', 'zsh', '--prog', 'my.tool'], 'completion',
    env=cols('100'))
add('completion-prog-unicode', ['completion', 'bash', '--prog', 'bäb'], 'completion',
    env=cols('100'))

_BASH_SCRIPT = 'home/.local/share/allegro-buddy/completion-bab.bash'
_ZSH_SCRIPT = 'home/.local/share/allegro-buddy/completion-bab.zsh'
add('completion-install-bash-twice', ['completion', 'bash', '--install'], 'completion',
    env=cols('100'), files={'home/.bashrc': 'export FOO=1'},
    then=[['completion', 'bash', '--install']], capture=['home/.bashrc', _BASH_SCRIPT])
add('completion-install-zsh-twice', ['completion', 'zsh', '--install'], 'completion',
    env=cols('100'), files={'home/.zshrc': 'autoload -U colors\n'},
    then=[['completion', 'zsh', '--install']], capture=['home/.zshrc', _ZSH_SCRIPT])
add('completion-install-bash-no-rc', ['completion', '--install'], 'completion',
    env=cols('100', SHELL='/bin/bash'), capture=['home/.bashrc', _BASH_SCRIPT])
add('completion-install-zsh-zdotdir', ['completion', 'zsh', '--install'], 'completion',
    env=cols('100', ZDOTDIR='@TMP@/zdot'), modes={'zdot': 0o755},
    capture=['zdot/.zshrc', 'home/.zshrc', _ZSH_SCRIPT])
add('completion-install-xdg-data', ['completion', 'bash', '--install'], 'completion',
    env=cols('100', XDG_DATA_HOME='@TMP@/data'),
    capture=['home/.bashrc', 'data/allegro-buddy/completion-bab.bash'])
add('completion-install-fish', ['completion', '--install', '--prog', 'allegro-buddy'],
    'completion', env=cols('100', SHELL='/usr/bin/fish'),
    capture=['config/fish/completions/allegro-buddy.fish'], then=[['completion', 'fish',
                                                                    '--install']])
add('completion-install-fish-no-xdg', ['completion', 'fish', '--install'], 'completion',
    env=cols('100', XDG_CONFIG_HOME=None), capture=['home/.config/fish/completions/bab.fish'])
add('completion-install-already-sourced', ['completion', 'bash', '--install'], 'completion',
    env=cols('100'), capture=['home/.bashrc'],
    files={'home/.bashrc': "# mine\n[ -f '@TMP@/home/.local/share/allegro-buddy/"
                           "completion-bab.bash' ] && . '@TMP@/home/.local/share/"
                           "allegro-buddy/completion-bab.bash'\n"})
add('completion-install-no-shell', ['completion', '--install'], 'completion',
    env=cols('100', SHELL=None))


def complete(name: str, kind: str, words: str, cword: str, **extra: Any) -> None:
    env = cols('100', _BAB_COMPLETE=f'{kind}_complete', COMP_WORDS=words, COMP_CWORD=cword)
    add(f'complete-{kind}-{name}', [], 'completion', env=env, **extra)


for _kind in ('bash', 'zsh'):
    complete('commands', _kind, 'bab ', '1')
    complete('commands-prefix', _kind, 'bab d', '1')
    complete('root-options', _kind, 'bab --', '1')
    complete('queue-options', _kind, 'bab q --', '2')
    complete('dev-subcommands', _kind, 'bab dev ', '2')
    complete('job-output-ids', _kind, 'bab job output ', '3')
    complete('job-output-prefix', _kind, 'bab job output 7008', '3')
    complete('why-pending-ids', _kind, 'bab why ', '2')
    complete('why-pending-prefix', _kind, 'bab why 7012', '2')
    complete('why-fix-choices', _kind, 'bab why 70122 --fix ', '4')
    complete('dev-login-jobid', _kind, 'bab dev login --jobid ', '4')
    complete('l-jobid', _kind, 'bab l --jobid 7', '3')
    complete('dev-stop-jobid', _kind, 'bab dev stop --jobid ', '4')
    complete('free-kind', _kind, 'bab free --kind ', '3')
    complete('completion-shells', _kind, 'bab completion ', '2')
    complete('node-arg', _kind, 'bab node ', '2')
    complete('after-double-dash', _kind, 'bab why -- ', '3')
    complete('dev-start-options', _kind, 'bab dev start --', '3')
    complete('hidden-command', _kind, 'bab gpu', '1')
complete('commands', 'fish', 'bab ', '')
complete('commands-prefix', 'fish', 'bab q', 'q')
complete('queue-options', 'fish', 'bab q --', '--')
complete('job-output-ids', 'fish', 'bab job output ', '')
complete('why-pending-ids', 'fish', 'bab why 70', '70')
complete('free-kind', 'fish', 'bab free --kind ', '')
complete('job-output-ids-sacct-fails', 'bash', 'bab job output ', '3',
         tweak=setitem(sacct_fail={'exit': 1, 'stderr': 'down\n'}))
complete('why-ids-squeue-fails', 'bash', 'bab why ', '2',
         tweak=setitem(fail=[{'argv': ['squeue'], 'exit': 1, 'stderr': 'down\n'}]))
complete('dev-jobid-two', 'bash', 'bab dev login --jobid ', '4', tweak=SECOND_DEV)
add('complete-unknown-instruction', [], 'completion',
    env=cols('100', _BAB_COMPLETE='tcsh_complete', COMP_WORDS='bab ', COMP_CWORD='1'))
add('complete-wrong-var-name', [], 'completion',
    env=cols('100', _AB_COMPLETE='bash_complete', COMP_WORDS='bab ', COMP_CWORD='1'))
add('complete-invalid-config', [], 'completion', files={USER_CONFIG: '[dev]\ngpus = 2\n'},
    env=cols('100', _BAB_COMPLETE='bash_complete', COMP_WORDS='bab dev start --',
             COMP_CWORD='3'))

# ---------------------------------------------------------------------------
# Settings: presets, layers, the ClusterName cache
# ---------------------------------------------------------------------------

SETTINGS = [
    ('ab-cluster-allegro', ['config', 'show'], {'env': {'AB_CLUSTER': 'allegro'}}),
    ('ab-cluster-bhlrn4', ['config', 'show'], {'env': {'AB_CLUSTER': 'bhlrn4'}}),
    ('ab-cluster-none', ['config', 'show'], {'env': {'AB_CLUSTER': 'none'}}),
    ('ab-cluster-empty', ['config', 'show'], {'env': {'AB_CLUSTER': ''}}),
    ('ab-cluster-unknown', ['config', 'show'], {'env': {'AB_CLUSTER': 'nowhere'}}),
    ('ab-cluster-unknown-info', ['info'], {'env': {'AB_CLUSTER': 'nowhere'}}),
    ('ab-cluster-bhlrn4-info', ['info'], {'env': {'AB_CLUSTER': 'bhlrn4'}}),
    ('ab-cluster-none-info', ['info'], {'env': {'AB_CLUSTER': 'none'}}),
    ('ab-cluster-beats-file', ['config', 'show'],
     {'env': {'AB_CLUSTER': 'allegro'}, 'files': {USER_CONFIG: '[cluster]\npreset = bhlrn4\n'}}),
    ('cluster-elsewhere', ['config', 'show'], {'world': 'other'}),
    ('cluster-unnamed', ['config', 'show'], {'world': 'noname'}),
    ('cluster-lise', ['config', 'show'], {'world': 'lise'}),
    ('user-preset', ['config', 'show'], {'files': {USER_CONFIG: '[cluster]\npreset = bhlrn4\n'}}),
    ('site-preset-none', ['config', 'show'], {'files': {SITE_CONFIG: '[cluster]\npreset = none\n'}}),
    ('user-beats-site-preset', ['config', 'show'],
     {'files': {SITE_CONFIG: '[cluster]\npreset = none\n',
                USER_CONFIG: '[cluster]\npreset = allegro\n'}}),
    ('site-only', ['config', 'show'],
     {'files': {SITE_CONFIG: '[dev]\npartition = gpusmall\n[cluster]\nnode-login = srun\n'}}),
    ('everything', ['config', 'show'], {'files': {
        SITE_CONFIG: '[dev]\ncpus = 4\nmem = 16G\n[gpu-aliases]\nampere = rtx_a5000\n',
        USER_CONFIG: '# comment\n[dev]\nMem = 32G ; inline\nlog-dir = ~/logs  # here\n'
                     'max_allocations = 2\nGPU-Type = a5000\n[cluster]\ngpu-partitions = '
                     'gpu, gpusmall\nnode_login = ssh\n[gpu-labels]\nRTX-A5000 = Ampere\n'
                     'GTX-1080ti = Pascal\n[gpu-aliases]\nGTX = gtx_1080ti\n'}}),
    ('labels-free', ['free', '--nodes'], {'files': {
        USER_CONFIG: '[gpu-labels]\ngtx_1080ti = Pascal\nrtx_a5000 = Ampere A5000\n'}}),
    ('aliases-free', ['free', '-G', 'ampere', '--nodes'], {'files': {
        USER_CONFIG: '[gpu-aliases]\nAmpere = RTX-A5000\n'}}),
    ('aliases-dev-start', ['dev', 'start', '--no-wait', '--replace', '--gpu-type', 'pascal'],
     {'files': {USER_CONFIG: '[gpu-aliases]\npascal = gtx1080\n'}}),
    ('gpu-partitions-override', ['info'],
     {'files': {USER_CONFIG: '[cluster]\ngpu-partitions = gpusmall,small\n'}}),
    ('gpu-partitions-free', ['free'],
     {'files': {USER_CONFIG: '[cluster]\ngpu-partitions = gpusmall,small\n'}}),
    ('no-preset-queue-color', ['q', '--all'],
     {'env': {'AB_CLUSTER': 'none', 'FORCE_COLOR': '1'}, 'tweak': no_jobs}),
    ('no-preset-queue-color-plain', ['q', '--all'],
     {'env': {'AB_CLUSTER': 'none', 'FORCE_COLOR': '1'}}),
    ('cache-cold', ['config', 'show'], {'capture': [CACHE_FILE]}),
    ('cache-warm', ['config', 'show'], {'files': {CACHE_FILE: 'allegro\n'},
                                        'capture': [CACHE_FILE]}),
    ('cache-warm-other', ['config', 'show'], {'files': {CACHE_FILE: '  bhlrn4  \n'}}),
    ('cache-warm-unknown', ['config', 'show'], {'files': {CACHE_FILE: 'elsewhere'}}),
    ('cache-empty-file', ['config', 'show'], {'files': {CACHE_FILE: '\n'},
                                              'capture': [CACHE_FILE]}),
    ('cache-unwritable', ['free'], {'modes': {'cache': 0o555}, 'then': [['free']]}),
    ('cache-unreadable', ['config', 'show'],
     {'files': {CACHE_FILE: 'bhlrn4\n'}, 'modes': {CACHE_FILE: 0o000}}),
    ('cache-other-host', ['config', 'show'],
     {'files': {'cache/allegro-buddy/cluster-name.otherhost': 'bhlrn4\n'}}),
    ('cache-hostname-hook', ['config', 'show'],
     {'env': {'BAB_TEST_HOSTNAME': 'gpu101.cluster'},
      'files': {'cache/allegro-buddy/cluster-name.gpu101.cluster': 'bhlrn4\n'}}),
    ('cache-unnamed-not-written', ['free'], {'world': 'noname', 'then': [['free']]}),
    ('cache-probe-fails', ['config', 'show'], {'tweak': setitem(config_exit=1)}),
    ('cache-xdg-unset', ['config', 'show'],
     {'env': {'XDG_CACHE_HOME': None, 'XDG_CONFIG_HOME': None, 'AB_SITE_CONFIG': None}}),
    ('site-config-default-path', ['config', 'show'], {'env': {'AB_SITE_CONFIG': None}}),
    ('site-config-empty-env', ['config', 'show'], {'env': {'AB_SITE_CONFIG': ''}}),
]
INVALID = [
    ('unknown-key', '[dev]\ngpus = 2\n'),
    ('node-login', '[cluster]\nnode-login = mosh\n'),
    ('max-allocations', '[dev]\nmax-allocations = 0\n'),
    ('max-allocations-text', '[dev]\nmax-allocations = many\n'),
    ('preset', '[cluster]\npreset = nowhere\n'),
    ('section-case', '[Dev]\ngpu = 1\n'),
    ('no-section', 'gpu = 1\n'),
    ('duplicate-key', '[dev]\ngpu = 1\ngpu = 2\n'),
    ('duplicate-section', '[dev]\ngpu = 1\n[dev]\nmem = 2G\n'),
    ('bad-line', '[dev]\nthis is not a setting\n'),
]
for _name, _argv, _extra in SETTINGS:
    _env = {'COLUMNS': '160', **_extra.pop('env', {})}
    add(f'settings-{_name}', _argv, 'settings', env=_env, **_extra)
for _name, _text in INVALID:
    for _cmd, _argv in (('dev-start', ['dev', 'start']), ('info', ['info']),
                        ('config-show', ['config', 'show'])):
        add(f'invalid-{_name}-{_cmd}', _argv, 'settings', env=cols('120'),
            files={USER_CONFIG: _text})
add('invalid-site-file', ['info'], 'settings', env=cols('120'),
    files={SITE_CONFIG: '[nope]\n'})
add('invalid-site-file-c80', ['info'], 'settings', env=cols('80'),
    files={SITE_CONFIG: '[nope]\n'})
add('invalid-unreadable-user-file', ['info'], 'settings', env=cols('120'),
    files={USER_CONFIG: '[dev]\n'}, modes={USER_CONFIG: 0o000})
add('invalid-user-file-is-dir', ['info'], 'settings', env=cols('120'),
    modes={USER_CONFIG: 0o755})
add('invalid-version-still-works', ['--version'], 'settings', env=cols('120'),
    files={USER_CONFIG: '[dev]\ngpus = 2\n'})
add('invalid-color', ['info'], 'settings', env=cols('120', FORCE_COLOR='1'),
    files={USER_CONFIG: '[dev]\ngpus = 2\n'})

# ---------------------------------------------------------------------------
# --watch: SIGINT after a few seconds (the interval is at least 10 s, so one frame)
# ---------------------------------------------------------------------------

WATCH = [
    ('queue-pipe', ['q', '-w'], {}),
    ('queue-interval', ['q', '-w', '10', '-p', 'gpusmall'], {}),
    ('queue-flag-before-option', ['q', '-w', '-p', 'gpusmall'], {}),
    ('queue-equals', ['queue', '--watch=15'], {}),
    ('queue-attached', ['q', '-w12'], {}),
    ('free-nodes', ['free', '--watch', '30', '--nodes'], {}),
    ('free-pty', ['free', '-w'], {'tty': 'pty'}),
    ('queue-pty', ['q', '--all', '-w'], {'tty': 'pty'}),
    ('free-pty-color', ['free', '-w'], {'tty': 'pty', 'env': {'TERM': 'xterm-256color'}}),
    ('free-down', ['free', '-w'], {'world': 'down'}),
    ('free-down-pty', ['free', '-w'], {'world': 'down', 'tty': 'pty'}),
    ('queue-force-color', ['q', '-w'], {'env': {'FORCE_COLOR': '1'}}),
    ('queue-hint-error', ['q', '--user', 'carol', '-w'],
     {'world': queue_world([Q_PENDING], scontrol_fail=True)}),
]
for _name, _argv, _extra in WATCH:
    _env = {'COLUMNS': '120', **_extra.pop('env', {})}
    add(f'watch-{_name}', _argv, 'watch', env=_env, sigint_after=3.0, **_extra)

# ---------------------------------------------------------------------------
# Slurm missing, failing, empty or busy; node guessing; group access
# ---------------------------------------------------------------------------

MAIN = [
    ('info', ['info']), ('free', ['free']), ('free-cpu', ['free', '--kind', 'cpu']),
    ('queue', ['q']), ('why', ['why']), ('why-job', ['why', '70120']),
    ('node', ['node', 'gpu101']), ('node-guess', ['node']), ('dev-status', ['dev', 'status']),
    ('dev-start', ['dev', 'start', '--no-wait']), ('dev-stop', ['dev', 'stop']),
    ('login', ['l']), ('job-history', ['job', 'history']),
    ('job-output', ['job', 'output', '70090']), ('config-show', ['config', 'show']),
]
for _name, _argv in MAIN:
    add(f'noslurm-{_name}', _argv, 'errors', env=cols('120'), path_without_slurm=True)
    add(f'down-{_name}', _argv, 'errors', world='down', env=cols('120'))
    add(f'empty-{_name}', _argv, 'errors', world='empty', env=cols('120'))
for _name, _argv in [('info', ['info']), ('dev-status', ['dev', 'status']), ('queue', ['q']),
                     ('node', ['node', 'cmp201']), ('why', ['why']), ('login', ['l']),
                     ('dev-start', ['dev', 'start', '--no-wait'])]:
    add(f'busy-{_name}', _argv, 'errors', world='busy', env=cols('160'))
add('errors-unexpected-squeue-output', ['q'], 'errors', env=cols('120'),
    tweak=with_jobs({**W.demo_job('1', 'alice', 'odd|name', 'RUNNING', 'gpu', 10, 1, 1024,
                                  node='gpu101')}))
add('errors-slurm-json-garbage', ['why'], 'errors', env=cols('120'),
    tweak=setitem(fail=[{'argv': ['scontrol', '--json', 'show', 'job'], 'exit': 0,
                         'stdout': 'not json'}]))
add('errors-slurm-json-garbage-job', ['why', '70120'], 'errors', env=cols('120'),
    tweak=setitem(fail=[{'argv': ['scontrol', '--json', 'show', 'job'], 'exit': 0,
                         'stdout': '{"jobs": "oops"'}]))
add('errors-nodes-json-garbage', ['free'], 'errors', env=cols('120'),
    tweak=setitem(fail=[{'argv': ['scontrol', '--json', 'show', 'nodes'], 'exit': 0,
                         'stdout': '[]'}]))
add('errors-nodes-json-old-slurm', ['free', '--nodes'], 'errors', env=cols('120'),
    tweak=setitem(fail=[{'argv': ['scontrol', '--json', 'show', 'nodes'], 'exit': 0,
                         'stdout': '{"nodes": [{"name": "gpu101", "state": "mixed", '
                                   '"state_flags": ["DRAIN"], "cpus": 16, "alloc_cpus": 4, '
                                   '"real_memory": 92000, "alloc_memory": 16384, "gres": '
                                   '"gpu:RTX-A5000:4", "gres_used": "gpu:RTX-A5000:1(IDX:0)",'
                                   ' "partitions": ["gpu"]}]}'}]))
add('errors-squeue-fails', ['q'], 'errors', env=cols('120'),
    tweak=setitem(fail=[{'argv': ['squeue'], 'exit': 1,
                         'stderr': 'squeue: error: Invalid user: alice\n'}]))
add('errors-squeue-fails-quiet', ['q'], 'errors', env=cols('120'),
    tweak=setitem(fail=[{'argv': ['squeue'], 'exit': 7}]))
add('errors-squeue-fails-stdout', ['dev', 'status'], 'errors', env=cols('120'),
    tweak=setitem(fail=[{'argv': ['squeue'], 'exit': 1, 'stdout': 'only stdout\n'}]))
add('errors-sacctmgr-fails', ['info'], 'errors', env=cols('160'),
    tweak=setitem(sacctmgr_fail={'exit': 1, 'stderr': 'sacctmgr: error\n'}))
add('errors-sacctmgr-empty', ['info'], 'errors', env=cols('160'), tweak=setitem(sacctmgr=''))
add('errors-sacctmgr-many', ['info'], 'errors', env=cols('100'), tweak=setitem(
    sacctmgr='|proj-a|normal,long,interactive,gpu-debug,very-long-qos-name\n'
             'proj-b|proj-b|normal\nproj-b|proj-c|\nproj-b|proj-d-with-a-long-name|x,y,z\n'
             'proj-b|proj-e|a\nproj-b|proj-f|b\nproj-b|proj-g|c\nproj-b|proj-h|d\n'))
add('errors-noname-sacctmgr', ['info'], 'errors', world='noname', env=cols('160'))
add('errors-noslurm-version', ['--version'], 'errors', path_without_slurm=True)
add('errors-noslurm-help', ['-h'], 'errors', path_without_slurm=True, env=cols('100'))
add('errors-noslurm-completion', ['completion', 'bash'], 'errors', path_without_slurm=True)

for _host, _extra in [('gpu102', {}), ('gpu102.cluster.example', {}), ('cmp301', {}),
                      ('login1', {}), ('login1', {'tweak': NO_DEV}),
                      ('login1', {'tweak': chain(PENDING_DEV, with_jobs(W.demo_job(
                          '70150', 'alice', 'train', 'RUNNING', 'gpu', 600, 4, 8192, 2,
                          'RTX-A5000', 'gpu[101-102]', '2-3', started=-10)))}),
                      ('login1', {'tweak': chain(NO_DEV, with_jobs(W.demo_job(
                          '70151', 'alice', 'cpu-job', 'RUNNING', 'small', 600, 4, 8192,
                          node='cmp201', started=-10)))})]:
    _i = sum(1 for s in SCENARIOS if s.name.startswith(f'node-guess-{_host}'))
    add(f'node-guess-{_host}{"-" + str(_i) if _i else ""}', ['node'], 'node',
        env=cols('120', BAB_TEST_HOSTNAME=_host), **_extra)
add('node-guess-plain', ['node'], 'node', world='plain', env=cols('120'))
add('node-gpu101', ['node', 'gpu101'], 'node', env=cols('120'))
add('node-cmp301-idle', ['node', 'cmp301'], 'node', env=cols('120'))
add('node-c60', ['node', 'gpu201'], 'node', env=cols('60'))

for _groups in ('users', 'hpc', 'students', 'amd-users,students', ''):
    _g = _groups.replace(',', '+') or 'none'
    add(f'groups-{_g}-info', ['info'], 'groups', world='groups',
        env=cols('160', BAB_TEST_GROUPS=_groups))
    add(f'groups-{_g}-free-cpu', ['free', '--kind', 'cpu', '--nodes'], 'groups',
        world='groups', env=cols('160', BAB_TEST_GROUPS=_groups))
add('groups-none-free', ['free'], 'groups', world='groups', env=cols('160', BAB_TEST_GROUPS=''))
add('groups-info-all', ['info', '--all-partitions'], 'groups', world='groups',
    env=cols('160', BAB_TEST_GROUPS='students'))
add('groups-dev-start-denied', ['dev', 'start', '--no-wait', '-p', 'gpumicro'], 'groups',
    world='groups', env=cols('160', BAB_TEST_GROUPS='students'))
add('groups-dev-start-auto-denied', ['dev', 'start', '--no-wait', '-g', '0'], 'groups',
    world='nodefault', env=cols('160', BAB_TEST_GROUPS=''))
add('groups-dev-start-allowed', ['dev', 'start', '--no-wait', '-p', 'big', '-g', '0'],
    'groups', world='groups', env=cols('160', BAB_TEST_GROUPS='hpc'))


def by_name() -> dict[str, Scenario]:
    return {scenario.name: scenario for scenario in SCENARIOS}

# ---------------------------------------------------------------------------
# Strings Rich treats specially: markup and emoji codes in plain-str table cells,
# wide characters, highlighting of plain strings printed outside tables
# ---------------------------------------------------------------------------

NASTY_NAMES = {
    '70102': '[bold]evil[/bold]',
    '70103': 'sweep[1-3]:rocket:',
    '70104': 'データ処理-🚀-run',
    '70120': '[red]train[/] \\[x]',
    '70121': 'eval:smile:-1080',
    '70122': 'back\\slash [i]y[/i]',  # not [link]: Rich gives it a random id
    '70130': 'wide-名前-is-long-and-gets-truncated',
}


def nasty(world: World) -> None:
    for job in world['jobs']:
        job['name'] = NASTY_NAMES.get(job['id'], job['name'])
    world['sacct_rows'] = [
        '70090|70090|[bold]prep[/bold]|COMPLETED|0:0|2026-11-03T08:41:12|None',
        '70085|70085|データ処理-🚀|FAILED|1:0|2026-11-02T23:17:40|None',
        '70080_3|70080_3|:rocket: sweep|TIMEOUT|0:0|2026-11-02T18:00:05|None',
        '70077|70077|a [b] c [/b]|CANCELLED by 1000|0:0|2026-11-02T12:30:00|None',
    ]


for _name, _argv in [('queue-all', ['q', '--all']), ('job-history', ['job', 'history']),
                     ('node', ['node', 'gpu201']), ('node-wide', ['node', 'gpu102']),
                     ('queue', ['q'])]:
    add(f'nasty-{_name}', _argv, 'nasty', tweak=nasty, env=cols('160'))
    add(f'nasty-{_name}-c80', _argv, 'nasty', tweak=nasty, env=cols('80'))
    add(f'nasty-{_name}-color', _argv, 'nasty', tweak=nasty, env=cols('160', FORCE_COLOR='1'))
add('nasty-dev-stop-color', ['dev', 'stop'], 'nasty', env=cols('120', FORCE_COLOR='1'))
add('nasty-dev-stop-two-color', ['dev', 'stop'], 'nasty', tweak=SECOND_DEV,
    env=cols('120', FORCE_COLOR='1'))
add('nasty-dev-start-replace-color', ['dev', 'start', '--no-wait', '--replace'], 'nasty',
    env=cols('120', FORCE_COLOR='1'))
add('nasty-fix-declined-color', ['why', '64267', '--fix'], 'nasty', world=why([CPU]),
    stdin='n\n', env=cols('120', FORCE_COLOR='1', BAB_TEST_INTERACTIVE='1'))
add('nasty-job-output-color', ['job', 'output', '70090'], 'nasty',
    env=cols('120', FORCE_COLOR='1'),
    files={'demo/slurm-70090.out': '[bold]x[/bold] :smile: 42 0x1f 3.14 True None '
                                   'https://example.org /a/b "str" \'q\' <tag> ()\n'})
add('nasty-config-show-color', ['config', 'show'], 'nasty', env=cols('160', FORCE_COLOR='1'),
    files={USER_CONFIG: '[dev]\naccount = [bold]proj[/bold]\nconstraint = :smile:\n'
                        '[gpu-labels]\nrtx_a5000 = [red]A5k\n'})
add('nasty-labels-free-color', ['free', '--nodes'], 'nasty', env=cols('160', FORCE_COLOR='1'),
    files={USER_CONFIG: '[gpu-labels]\nrtx_a5000 = [red]A5k\ngtx_1080ti = 🚀\n'})
add('nasty-sacctmgr-markup', ['info'], 'nasty', env=cols('120', FORCE_COLOR='1'),
    tweak=setitem(sacctmgr='[b]x|[b]x|[i]q:smile:\n'))
add('nasty-user-markup', ['q', '--all'], 'nasty', env=cols('160'),
    tweak=change_job('70102', user='[bold]eve'))
