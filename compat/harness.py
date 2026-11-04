"""Run one scenario against one `bab` binary in a sealed scratch environment.

Each run gets a fresh scratch directory T of a fixed path length (so output that
wraps around a path wraps the same way on every machine), a fake Slurm world in
T/slurm-state.json, a call log in T/slurm-calls.jsonl, HOME=T/home and so on. Every
occurrence of T in the captured bytes is replaced by `PLACEHOLDER` (same length).

Scratch root: $BAB_COMPAT_WORK, else $XDG_CACHE_HOME/bab-compat (~/.cache/bab-compat).
It must be short: T is `TMP_LEN` characters long.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import pty
import re
import secrets
import shlex
import select
import shutil
import signal
import stat
import struct
import subprocess
import sys
import termios
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import worlds

if TYPE_CHECKING:
    from scenarios import Scenario

COMPAT = Path(__file__).resolve().parent
FAKE_BIN = COMPAT / 'fake_slurm' / 'bin'
TMP_LEN = 40
PLACEHOLDER = '@TMP@'.ljust(TMP_LEN, '_')
SYSTEM_PATH = '/usr/bin:/bin'
MUTATING = {'sbatch', 'scancel', 'ssh', 'srun'}


def work_root() -> Path:
    root = os.environ.get('BAB_COMPAT_WORK')
    if not root:
        cache = os.environ.get('XDG_CACHE_HOME') or str(Path.home() / '.cache')
        root = f'{cache}/bab-compat'
    path = Path(root).absolute()
    if len(str(path)) > TMP_LEN - 10:
        raise SystemExit(
            f'scratch root {path} is too long (max {TMP_LEN - 10} characters); '
            'set BAB_COMPAT_WORK to a shorter directory'
        )
    path.mkdir(parents=True, exist_ok=True)
    return path


def scratch_dir() -> Path:
    root = str(work_root())
    token = secrets.token_hex(4)
    pad = TMP_LEN - len(root) - 1 - len(token)
    path = Path(f'{root}/{token}{"_" * pad}')
    assert len(str(path)) == TMP_LEN
    path.mkdir()
    return path


def is_mutating(argv: list[str]) -> bool:
    return argv[0] in MUTATING or argv[:2] == ['scontrol', 'update']


@dataclass
class Result:
    stdout: bytes
    stderr: bytes
    exit_code: str  # "0", "2", "-2" (signal), "timeout"
    calls: list[dict[str, Any]]
    files: dict[str, bytes | None] = field(default_factory=dict)  # None: missing

    def calls_jsonl(self) -> str:
        return ''.join(json.dumps(call) + '\n' for call in self.calls)


def _scrub(data: bytes, tmp: Path) -> bytes:
    return data.replace(str(tmp).encode(), PLACEHOLDER.encode())


def _materialize(value: Any, tmp: Path) -> Any:
    text = json.dumps(value)
    return json.loads(text.replace('@TMP@', str(tmp)))


def build_world(scenario: Scenario) -> dict[str, Any]:
    world = scenario.world
    state = worlds.WORLDS[world]() if isinstance(world, str) else world()
    if scenario.tweak is not None:
        scenario.tweak(state)
    return state


def environment(scenario: Scenario, tmp: Path) -> dict[str, str]:
    env = {
        'PATH': f'{FAKE_BIN}:{SYSTEM_PATH}',
        'HOME': f'{tmp}/home',
        'USER': worlds.USER,
        'LOGNAME': worlds.USER,
        'TZ': 'UTC',
        'LANG': 'C.UTF-8',
        'XDG_CONFIG_HOME': f'{tmp}/config',
        'XDG_CACHE_HOME': f'{tmp}/cache',
        'AB_SITE_CONFIG': f'{tmp}/site/config.ini',
        'BAB_TEST_NOW': worlds.NOW,
        'BAB_TEST_GROUPS': 'users',
        'BAB_TEST_HOSTNAME': 'login1',
        'FAKE_SLURM_STATE': f'{tmp}/slurm-state.json',
        'FAKE_SLURM_LOG': f'{tmp}/slurm-calls.jsonl',
        'FAKE_SLURM_PYTHON': sys.executable,
        'PYTHONDONTWRITEBYTECODE': '1',
    }
    if scenario.tty == 'pty':
        env['TERM'] = 'xterm-256color'
    for key, value in scenario.env.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value.replace('@TMP@', str(tmp))
    if scenario.path_without_slurm:
        env['PATH'] = SYSTEM_PATH
    return env


def _setup(scenario: Scenario, tmp: Path) -> None:
    for sub in ('home', 'config', 'cache', 'site'):
        (tmp / sub).mkdir()
    world = build_world(scenario)
    files = {**world.pop('_files', {}), **scenario.files}
    state = _materialize(world, tmp)
    (tmp / 'slurm-state.json').write_text(json.dumps(state, indent=1))
    (tmp / 'slurm-calls.jsonl').write_text('')
    for rel, content in files.items():
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content.replace(b'@TMP@', str(tmp).encode()))
        else:
            path.write_text(content.replace('@TMP@', str(tmp)))
    for rel, mode in scenario.modes.items():
        path = tmp / rel
        if not path.exists():
            path.mkdir(parents=True)
        path.chmod(mode)


def _run_pipe(argv: list[str], env: dict[str, str], cwd: Path, scenario: Scenario):
    proc = subprocess.Popen(
        argv,
        env=env,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdin = (scenario.stdin or '').encode()
    if scenario.sigint_after is not None:
        proc.stdin.write(stdin)
        proc.stdin.close()
        proc.stdin = None
        time.sleep(scenario.sigint_after)
        proc.send_signal(signal.SIGINT)
        stdin = None
    try:
        out, err = proc.communicate(stdin, timeout=scenario.timeout)
        code = str(proc.returncode)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        code = 'timeout'
    return out, err, code


def _run_pty(argv: list[str], env: dict[str, str], cwd: Path, scenario: Scenario):
    """stdin, stdout and stderr on one terminal (no echo), its output merged into stdout."""
    master, slave = pty.openpty()
    attrs = termios.tcgetattr(slave)
    attrs[3] &= ~termios.ECHO
    termios.tcsetattr(slave, termios.TCSANOW, attrs)
    cols = int(scenario.winsize[1] if scenario.winsize else env.get('COLUMNS', 80))
    rows = int(scenario.winsize[0] if scenario.winsize else 25)
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))

    proc = subprocess.Popen(
        argv,
        env=env,
        cwd=cwd,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
        close_fds=True,
    )
    os.close(slave)
    if scenario.stdin:
        os.write(master, scenario.stdin.encode())
    chunks: list[bytes] = []
    deadline = time.monotonic() + scenario.timeout
    sigint_at = (
        time.monotonic() + scenario.sigint_after if scenario.sigint_after is not None else None
    )
    code = None
    while True:
        if sigint_at is not None and time.monotonic() >= sigint_at:
            proc.send_signal(signal.SIGINT)
            sigint_at = None
        if time.monotonic() > deadline:
            proc.kill()
            code = 'timeout'
        ready, _, _ = select.select([master], [], [], 0.05)
        if ready:
            try:
                data = os.read(master, 65536)
            except OSError as exc:
                if exc.errno != errno.EIO:
                    raise
                data = b''
            if not data:
                break
            chunks.append(data)
    os.close(master)
    proc.wait()
    return b''.join(chunks), b'', code or str(proc.returncode)


def _tree(tmp: Path) -> bytes:
    lines = []
    skip = {'slurm-state.json', 'slurm-calls.jsonl'}
    for path in sorted(tmp.rglob('*')):
        rel = path.relative_to(tmp)
        if str(rel) in skip:
            continue
        mode = path.lstat().st_mode
        kind = 'd' if stat.S_ISDIR(mode) else 'l' if stat.S_ISLNK(mode) else 'f'
        lines.append(f'{kind} {rel}\n')
    return ''.join(lines).encode()


def _cleanup(tmp: Path) -> None:
    for path in [tmp, *tmp.rglob('*')]:
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o755)
    shutil.rmtree(tmp, ignore_errors=True)


def run(scenario: Scenario, binary: str, *, keep: bool = False) -> Result:
    """Run the scenario (and its `then` runs) with `binary`; T is removed afterwards."""
    tmp = scratch_dir()
    try:
        _setup(scenario, tmp)
        env = environment(scenario, tmp)
        runner = _run_pty if scenario.tty == 'pty' else _run_pipe
        runs = [scenario.argv, *scenario.then]
        outs, errs, codes = [], [], []
        for i, args in enumerate(runs):
            argv = [str(Path(binary).absolute()), *args]
            out, err, code = runner(argv, env, tmp / 'home', scenario if i == 0 else
                                    replace(scenario, stdin=None, sigint_after=None))
            if len(runs) > 1:
                header = f'=== run {i + 1}: bab {shlex.join(args)} ===\n'.encode()
                out, err = header + out, header + err
            outs.append(out)
            errs.append(err)
            codes.append(code)
        calls = [
            json.loads(_scrub(line.encode(), tmp))
            for line in (tmp / 'slurm-calls.jsonl').read_text().splitlines()
            if line.strip()
        ]
        files: dict[str, bytes | None] = {'.tree': _tree(tmp)}
        for rel in scenario.capture:
            path = tmp / rel
            files[rel] = _scrub(path.read_bytes(), tmp) if path.is_file() else None
        out, err = _scrub(b''.join(outs), tmp), _scrub(b''.join(errs), tmp)
        for pattern, replacement in scenario.normalize:
            out = re.sub(pattern, lambda _: replacement, out, flags=re.S)
            err = re.sub(pattern, lambda _: replacement, err, flags=re.S)
        return Result(out, err, ' '.join(codes), calls, files)
    finally:
        if not keep:
            _cleanup(tmp)
