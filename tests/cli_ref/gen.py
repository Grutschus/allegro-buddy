"""Generate tests/cli_ref/cases.json from the Python reference (run as `bab`).

    python tests/cli_ref/gen.py            # with a venv that has allegro-buddy==2.7,
                                           # click==8.3.2, rich==15.0.0, rich-click==1.9.9

Each case runs `ref_bab.py ARGV` in a fresh, isolated environment (see `run_case`) and
records stdout, stderr, the exit code and selected files. Paths under the per-case temp
root are written as `$ROOT`. tests/cli_ref.rs replays every case against the Rust binary.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REF = HERE / 'ref_bab.py'

COMMANDS = [
    [], ['info'], ['queue'], ['q'], ['why'], ['completion'], ['free'], ['node'],
    ['gpualloc'], ['job'], ['job', 'history'], ['job', 'output'], ['dev'],
    ['dev', 'start'], ['dev', 'status'], ['dev', 'login'], ['dev', 'stop'], ['config'],
    ['config', 'show'], ['l'],
]

CASES: list[dict] = []


def case(name, argv, env=None, config=None, files=(), stub=True, stdin=''):
    CASES.append(
        {
            'name': name,
            'argv': list(argv),
            'env': env or {},
            'config': config,
            'files': list(files),
            'stub': stub,
            'stdin': stdin,
        }
    )


def slug(argv):
    return ' '.join(repr(a) if not a or ' ' in a else a for a in argv) or 'root'


# --- help pages ---------------------------------------------------------------------
for cmd in COMMANDS:
    case(f'help-{slug(cmd)}', [*cmd, '-h'], {'COLUMNS': '100'})
    case(f'help80-{slug(cmd)}', [*cmd, '--help'])
    case(f'helpcolor-{slug(cmd)}', [*cmd, '-h'], {'COLUMNS': '100', 'FORCE_COLOR': '1'})
for width in ('40', '60', '72', '99', '101', '160'):
    for cmd in ([], ['dev', 'start'], ['why'], ['free'], ['q'], ['dev', 'login']):
        case(f'help{width}-{slug(cmd)}', [*cmd, '-h'], {'COLUMNS': width})
for env_name, env in {
    'nocolor': {'FORCE_COLOR': '1', 'NO_COLOR': '1', 'COLUMNS': '100'},
    'truecolor': {'FORCE_COLOR': '1', 'COLORTERM': 'truecolor', 'COLUMNS': '100'},
    '256': {'FORCE_COLOR': '1', 'TERM': 'xterm-256color', 'COLUMNS': '100'},
    'dumb': {'TERM': 'dumb', 'COLUMNS': '100'},
    'forcecolor0': {'FORCE_COLOR': '0', 'COLUMNS': '100'},
    'pycolors': {'PY_COLORS': '1', 'COLUMNS': '100'},
    'gha': {'GITHUB_ACTIONS': 'true', 'COLUMNS': '100'},
    'termwidth': {'TERMINAL_WIDTH': '70'},
}.items():
    for cmd in ([], ['dev', 'start']):
        case(f'help-{env_name}-{slug(cmd)}', [*cmd, '-h'], env)
for theme in ('default', 'modern', 'box', 'nu', 'slim', 'robo', 'quartz', 'forest-modern',
              'dracula-box', 'nord-nu', 'solarized-robo', 'star-slim', 'cargo-modern',
              'quartz2-box', 'red', 'nonexistent'):
    for cmd in ([], ['dev', 'start'], ['why']):
        case(f'theme-{theme}-{slug(cmd)}', [*cmd, '-h'],
             {'RICH_CLICK_THEME': theme, 'COLUMNS': '100', 'FORCE_COLOR': '1'})
case('help-config-defaults', ['dev', 'start', '-h'], {'COLUMNS': '100'},
     config='[dev]\nmem = 32G\ngpu-type = a5000\ncpus = 4\ntime = 1-00:00:00\n')
case('help-config-broken', ['dev', 'start', '-h'], {'COLUMNS': '100'}, config='[dev]\ngpus = 2\n')
case('help-root-config-broken', ['-h'], {'COLUMNS': '100'}, config='[dev]\ngpus = 2\n')
case('help-noargs-dev', ['dev'], {'COLUMNS': '100'})
case('help-noargs-job', ['job'], {'COLUMNS': '100'})
case('help-noargs-config', ['config'], {'COLUMNS': '100'})
case('help-noargs-dev-color', ['dev'], {'COLUMNS': '100', 'FORCE_COLOR': '1'})
case('version', ['--version'])
case('version-first', ['--version', '-h'])
case('help-first', ['-h', '--version'])

# --- parsing and dispatch -------------------------------------------------------------
PARSE = [
    [], ['info'], ['info', '--all-partitions'], ['queue'], ['q'], ['queue', '--all'],
    ['queue', '--user', 'alice'], ['queue', '-p', 'gpusmall'], ['q', '-w'], ['q', '-w', '15'],
    ['q', '--watch=30'], ['q', '-w', '-p', 'gpu'], ['q', '-w15'], ['q', '-w=15'],
    ['q', '--watch', '5'], ['q', '--watch', 'abc'], ['q', '--watch', 'nan'],
    ['q', '--watch', 'inf'], ['q', '--watch', '1e1'], ['q', '--watch', ' 12 '],
    ['q', '--watch', '1_0'], ['q', '--watch', '1__0'], ['q', '--watch', '-5'],
    ['q', '--watch', '0.00001'], ['q', '--watch', '1e-7'], ['q', '--watch', '9.99999'],
    ['q', '--watch', '1e20'], ['q', '-pgpu'], ['q', '-p'], ['q', '--user'],
    ['q', '--partition='], ['q', '--all', '--all'], ['q', '-p', 'a', '-p', 'b'],
    ['q', 'extra'], ['q', 'a', 'b'], ['q', '--'], ['q', '--', '-x'], ['q', '--nod'],
    ['q', '--use', 'alice'], ['q', '--al'], ['q', '-x'], ['q', '-ax'], ['q', '--all=1'],
    ['q', '--wat'], ['q', '--watc', '20'], ['q', '-'], ['q', '---all'], ['q', '-all'],
    ['q', '--bogus', '-h'], ['q', '-h', '--bogus'], ['q', '--watch', '5', '-h'],
    ['q', '--user', 'x', '--watch', '5', '-p'], ['q', '--watch', '--user', 'bob'],
    ['free'], ['free', '--kind', 'cpu'], ['free', '--kind', 'nvme'], ['free', '--kind'],
    ['free', '--kind', 'GPU'], ['free', '--nodes', '-p', 'gpu', '-G', 'A5000'],
    ['free', '-G', 'a5000'], ['free', '--gpu-type', 'gtx1080'], ['free', '-GRTX-A5000'],
    ['free', '--watch', '30', '--nodes'], ['free', '-w'], ['free', '--kind', 'x', '--watch', '1'],
    ['free', '--watch', '1', '--kind', 'x'], ['free', '--node'], ['free', '--gpu'],
    ['why'], ['why', '65177', '--fix'], ['why', '65177', '--fix', 'mem'], ['why', '--fix', '65177'],
    ['why', '65177', '--fix', 'disk'], ['why', '65177', '--nodes', '--fix', 'cpus', '-y'],
    ['why', '--fix=gpus'], ['why', '--fix='], ['why', '-y', '1', '2'], ['why', '--fix', '-y'],
    ['why', '-yy'], ['why', '--yes', '1'], ['why', '--fix', 'Auto'],
    ['node'], ['node', 'gpu042'], ['gpualloc', 'gpu042'], ['node', 'a', 'b'], ['gpualloc'],
    ['job', 'history'], ['job', 'history', '--limit', '100'], ['job', 'history', '--limit', 'abc'],
    ['job', 'history', '--limit', '1_000'], ['job', 'history', '--limit', ' -5 '],
    ['job', 'history', '--limit', '1.5'], ['job', 'history', '--limit', '+7'],
    ['job', 'output'], ['job', 'output', '12345'], ['job', 'output', '--stderr', '12345'],
    ['job', 'outputs'], ['job', '-x'], ['job', '--'], ['job', 'output', '1', '2'],
    ['dev', 'start'], ['dev', 'start', '-p', 'gpusmall', '-g', '2'],
    ['dev', 'start', '--gpu-type', 'A5000'], ['dev', 'start', '--gpu-type', 'RTX-A5000'],
    ['dev', 'start', '-g', 'x'], ['dev', 'start', '--poll-interval', '0'],
    ['dev', 'start', '--poll-interval', '0.5'], ['dev', 'start', '--poll-interval', '1'],
    ['dev', 'start', '-c', '4', '-m', '16G', '-t', '1:00:00', '--account', 'a',
     '--constraint', 'c', '--exclude', 'n1,n2', '-n', 'n3', '--replace', '--no-wait',
     '--login', '--timeout', '60', '--poll-interval', '2'],
    ['dev', 'start', '--gpu-type'], ['dev', 'start', '--time=2:00:00', '-c4', '-g0'],
    ['dev', 'status'], ['dev', 'status', '--jobid', '1'], ['dev', 'login'],
    ['dev', 'login', '--wait', '--timeout', '5', '--srun', '--command', 'nvidia-smi'],
    ['dev', 'stop', '--jobid', '7'], ['dev', 'stop', 'x'], ['dev', 'stat'],
    ['l'], ['l', '--command', 'x'], ['l', '--poll-interval', '0'], ['l', '--wait'],
    ['config', 'show'], ['config', 'show', 'x'], ['config', 'shw'],
    ['foo'], ['inf'], ['--foo'], ['-x'], ['--vers'], ['--version', 'extra'],
    ['--', 'info'], ['--', '-h'], ['--', '--bogus'], ['--'], [''], ['-h', 'info'],
    ['--help=1'], ['--version=1'], ['-hx'], ['-xh'], ['info', '--all-partition'],
    ['info', '--all-partitions=yes'], ['info', 'x'], ['Q'], ['q', '-h', 'x'],
]
for argv in PARSE:
    case(f'parse-{slug(argv)}', argv, {'COLUMNS': '100'})

DEV_CONFIGS = {
    'presets': '[dev]\ngpu = 2\ngpu-type = RTX_A5000\nmem = 32G\ntime = 04:00:00\n',
    'unknown-key': '[dev]\ngpus = 2\n',
    'bad-int': '[dev]\ncpus = abc\n',
    'bad-section': '[Dev]\ngpu = 1\n',
    'empty-gpu': '[dev]\ngpu =\n',
    'partition': '[dev]\npartition = small\naccount = acc\nconstraint = x\nexclude = n1\n',
    'syntax': 'not ini\n',
}
for cfg_name, text in DEV_CONFIGS.items():
    for argv in (['dev', 'start'], ['dev', 'start', '-g', '1', '-c', '8'], ['info'], [],
                 ['--version'], ['l'], ['dev', 'start', '-h'], ['foo'], ['q', '--bad']):
        case(f'config-{cfg_name}-{slug(argv)}', argv, {'COLUMNS': '100'}, config=text)

# --- completion scripts and install -------------------------------------------------
case('completion-shell-zsh', ['completion'], {'SHELL': '/bin/zsh'})
case('completion-shell-tcsh', ['completion'], {'SHELL': '/bin/tcsh', 'COLUMNS': '100'})
case('completion-shell-unset', ['completion'], {'COLUMNS': '100'})
case('completion-shell-empty', ['completion'], {'SHELL': '', 'COLUMNS': '100'})
case('completion-shell-quote', ['completion'], {'SHELL': "/bin/it's", 'COLUMNS': '100'})
case('completion-shell-fish-slash', ['completion'], {'SHELL': '/usr/bin/fish/'})
for shell in ('bash', 'zsh', 'fish'):
    case(f'completion-{shell}', ['completion', shell])
    case(f'completion-{shell}-prog', ['completion', shell, '--prog', 'allegro-buddy'])
case('completion-prog-weird', ['completion', 'zsh', '--prog', 'my.tool-x'])
case('completion-prog-empty', ['completion', 'fish', '--prog', '--'])
case('completion-ksh', ['completion', 'ksh'], {'COLUMNS': '100'})
case('completion-bash-nobash', ['completion', 'bash'], {'PATH': '/nonexistent'})
for shell, rc in (('bash', '.bashrc'), ('zsh', '.zshrc')):
    case(f'install-{shell}', ['completion', shell, '--install'],
         files=[f'home/{rc}', f'home/.local/share/allegro-buddy/completion-bab.{shell}'])
case('install-bash-existing', ['completion', 'bash', '--install'],
     files=['home/.bashrc'], env={'BAB_GEN_RC': 'export FOO=1'})
case('install-zsh-zdotdir', ['completion', 'zsh', '--install'],
     env={'ZDOTDIR': '$ROOT//home/', 'XDG_DATA_HOME': '$ROOT/data/'},
     files=['home/.zshrc', 'data/allegro-buddy/completion-bab.zsh'])
case('install-fish', ['completion', '--install', '--prog', 'allegro-buddy'],
     env={'SHELL': '/usr/bin/fish'}, files=['config/fish/completions/allegro-buddy.fish'])
case('install-fish-home', ['completion', 'fish', '--install'],
     env={'XDG_CONFIG_HOME': ''}, files=['home/.config/fish/completions/bab.fish'])

# --- completion protocol ------------------------------------------------------------
COMPLETE = [
    ('bab ', 1), ('bab d', 1), ('bab -', 1), ('bab --', 1), ('bab --v', 1), ('bab q -', 2),
    ('bab q --', 2), ('bab q --all -', 3), ('bab free --kind ', 3), ('bab free --kind c', 3),
    ('bab free --kind=c', 2), ('bab free --kind=', 2), ('bab free -', 2), ('bab why ', 2),
    ('bab why 3', 2), ('bab why 333 ', 3), ('bab why --fix ', 3), ('bab why --fix a', 3),
    ('bab dev login --jobid 47', 4), ('bab dev stop --jobid ', 4), ('bab l --jobid ', 3),
    ('bab job output 1', 3), ('bab job output ', 3), ('bab job ', 2), ('bab completion ', 2),
    ('bab completion z', 2), ('bab dev ', 2), ('bab dev s', 2), ('bab q --watch ', 3),
    ('bab xyz ', 2), ('bab q -- -', 3), ('bab q -p ', 3), ('bab q -p gpu -', 4),
    ('bab dev start -', 3), ('bab dev start --gpu-type ', 4), ('bab info --all-partitions -', 3),
    ('bab free --kind bogus -', 4), ('bab why --nodes ', 3), ('bab dev start -p ', 4),
    ('bab "q" -', 2), ("bab 'dev' 'st", 2), ('bab q', 1), ('bab', 0), ('bab q -w ', 3),
    ('bab q -w 5 -', 4), ('bab completion bash --', 3), ('bab -h ', 2), ('bab q --user=', 2),
    ('bab q =', 2), ('bab l ', 2), ('bab l -', 2), ('bab gpualloc ', 2), ('bab g', 1),
    ('bab dev start -g 1 -', 5), ('bab why -y -', 3), ('bab config ', 2),
]
for words, cword in COMPLETE:
    for shell in ('bash', 'zsh'):
        case(f'complete-{shell}-{words!r}-{cword}', [],
             {'_BAB_COMPLETE': f'{shell}_complete', 'COMP_WORDS': words, 'COMP_CWORD': str(cword)})
FISH = [
    ('bab ', ''), ('bab d', 'd'), ('bab -', '-'), ('bab q --', '--'), ('bab why ', ''),
    ('bab dev login --jobid 47', '47'), ('bab free --kind c', 'c'), ('bab free --kind=c', '--kind=c'),
    ('bab completion ', ''), ('bab q q', 'q'),
]
for words, cword in FISH:
    case(f'complete-fish-{words!r}-{cword!r}', [],
         {'_BAB_COMPLETE': 'fish_complete', 'COMP_WORDS': words, 'COMP_CWORD': cword})
for instr in ('bash_source', 'zsh_source', 'fish_source', 'tcsh_complete', 'bash_bogus', 'bash'):
    case(f'complete-instr-{instr}', ['q'], {'_BAB_COMPLETE': instr})


def run_case(python: str, spec: dict) -> dict:
    with tempfile.TemporaryDirectory(dir=os.environ.get('BAB_GEN_TMP')) as tmp:
        root = Path(tmp)
        (root / 'home').mkdir()
        env = {
            'PATH': '/usr/bin:/bin',
            'HOME': str(root / 'home'),
            'XDG_CONFIG_HOME': str(root / 'config'),
            'XDG_CACHE_HOME': str(root / 'cache'),
            'AB_SITE_CONFIG': str(root / 'site' / 'config.ini'),
            'AB_CLUSTER': 'allegro',
            'USER': 'alice',
            'LOGNAME': 'alice',
            'LANG': 'C.UTF-8',
            'TZ': 'UTC',
            'PYTHONHASHSEED': '0',
            'PYTHONDONTWRITEBYTECODE': '1',
        }
        for key, value in spec['env'].items():
            env[key] = value.replace('$ROOT', str(root))
        if spec['stub']:
            env['BAB_REF_STUB'] = '1'
        rc = env.pop('BAB_GEN_RC', None)
        if rc is not None:
            (root / 'home' / '.bashrc').write_text(rc)
        if spec['config'] is not None:
            path = root / 'config' / 'allegro-buddy' / 'config.ini'
            path.parent.mkdir(parents=True)
            path.write_text(spec['config'])
        proc = subprocess.run(
            [python, str(REF), *spec['argv']],
            env=env,
            input=spec['stdin'].encode(),
            capture_output=True,
            cwd=root,
        )
        files = {}
        for rel in spec['files']:
            path = root / rel
            files[rel] = path.read_text() if path.is_file() else None

        def clean(text: str) -> str:
            return text.replace(str(root), '$ROOT')

        return {
            **spec,
            'stdout': clean(proc.stdout.decode()),
            'stderr': clean(proc.stderr.decode()),
            'code': proc.returncode,
            'files': {k: (clean(v) if v is not None else None) for k, v in files.items()},
        }


def main() -> None:
    python = os.environ.get('BAB_REF_PYTHON', sys.executable)
    names = [c['name'] for c in CASES]
    assert len(names) == len(set(names)), 'duplicate case names'
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda spec: run_case(python, spec), CASES))
    for r in results:
        if 'Traceback' in r['stderr']:
            print(f"warning: {r['name']} raised:\n{r['stderr']}", file=sys.stderr)
    out = HERE / 'cases.json'
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False) + '\n')
    print(f'wrote {len(results)} cases to {out}')


if __name__ == '__main__':
    main()
