"""The Python reference oracle: allegro-buddy 2.7 (from PyPI), presented as `bab`.

`build()` copies the installed `allegro_buddy` package into ``compat/.cache/`` and applies
an audited list of textual substitutions so the reference names itself `bab` exactly
where the Rust tool does. `run()` (used by the ``compat/ref-bab`` executable) imports
that copy, patches in the test hooks the Rust binary reads from the environment, and
runs the click entry point as ``bab``. Slurm commands run for real (as subprocesses),
so they hit whatever is first on $PATH: the fake Slurm in ``compat/fake_slurm/``.

Test hooks (unset: the real behaviour):

  BAB_TEST_NOW          ISO naive local datetime, e.g. 2026-11-03T10:00:00: the frozen
                        wall clock. Replaces ``core.datetime.now()`` (every "now" the
                        package reads) and ``time.strftime`` in the `--watch` header.
  BAB_TEST_GROUPS       comma-separated group names ("" = no groups): replaces
                        ``current_groups()`` (os.getgroups + grp) in every module.
  BAB_TEST_INTERACTIVE  1/0: whether stdin counts as a terminal for the
                        `why --fix` confirmation (``why._interactive``).
  BAB_TEST_HOSTNAME     replaces ``socket.gethostname()`` (cluster-name cache file
                        name, `node` without an argument).
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
from pathlib import Path

COMPAT = Path(__file__).resolve().parent
CACHE = COMPAT / '.cache'

# (file, old, new, expected count). Every user-visible "ab" the package prints; the
# audit below proves nothing else that reaches the user still says "ab".
SUBSTITUTIONS: list[tuple[str, str, str, int]] = [
    # the program name in every hint, error and `completion --prog` default
    ('core.py', 'CLI_NAME = "ab"', 'CLI_NAME = "bab"', 1),
    # `dev start --help` docstring
    (
        'cli.py',
        'Flags override the [dev] config (ab config show).',
        'Flags override the [dev] config (bab config show).',
        1,
    ),
    # `l` in the command list of `bab -h`
    (
        'cli.py',
        "'join a running dev job (short for ab dev login)'",
        "'join a running dev job (short for bab dev login)'",
        1,
    ),
]

# Every other standalone "ab" left in the package, all in comments or in docstrings
# of internal functions that are never shown. Kept on purpose:
#   DEV_JOB_NAME = "ab-dev" (shared dev jobs), 'allegro-buddy' paths and package name,
#   AB_* environment variables, and the `_AB_COMPLETE` fallback of `_completion_var`
#   (only reached for a --prog without any alphanumeric character).
ALLOWED_LEFTOVERS: dict[str, int] = {
    'cli.py': 2,  # comment in _install_completion
    'clusters/allegro.ini': 2,  # comment
    'clusters/bhlrn4.ini': 2,  # comment
    'core.py': 6,  # comments and the node_free docstring
    'fit.py': 5,  # comments and internal docstrings
    'handlers/resources.py': 3,  # internal docstrings
    'handlers/why.py': 6,  # comments and an internal docstring
    'settings.py': 2,  # module docstring and a comment
}
STANDALONE_AB = re.compile(r'(?<![A-Za-z0-9_./-])ab(?![A-Za-z0-9_-])')


def installed_package() -> Path:
    import importlib.util

    spec = importlib.util.find_spec('allegro_buddy')
    if spec is None or spec.origin is None:
        raise SystemExit('allegro_buddy is not installed; run `uv sync --project compat`')
    return Path(spec.origin).parent


def _fingerprint(package: Path) -> str:
    digest = hashlib.sha256(Path(__file__).read_bytes())
    for path in sorted(package.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            digest.update(str(path.relative_to(package)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def audit(package: Path) -> None:
    """Fail unless the only "ab" left are the known, never-printed ones."""
    found: dict[str, int] = {}
    for path in sorted(package.rglob('*')):
        if path.suffix not in {'.py', '.ini'} or '__pycache__' in path.parts:
            continue
        rel = str(path.relative_to(package))
        count = len(STANDALONE_AB.findall(path.read_text()))
        if count:
            found[rel] = count
    if found != ALLOWED_LEFTOVERS:
        raise SystemExit(f'reference audit failed: standalone "ab" per file {found}')


def build() -> Path:
    """The renamed copy of the package (cached); returns the directory to put on sys.path."""
    source = installed_package()
    root = CACHE / f'ref-{_fingerprint(source)}'
    if (root / 'allegro_buddy' / '.complete').exists():
        return root
    staging = CACHE / f'.staging-{os.getpid()}'
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(
        source, staging / 'allegro_buddy', ignore=shutil.ignore_patterns('__pycache__')
    )
    for name, old, new, expected in SUBSTITUTIONS:
        path = staging / 'allegro_buddy' / name
        text = path.read_text()
        if text.count(old) != expected:
            raise SystemExit(f'substitution {old!r} in {name}: found {text.count(old)}')
        path.write_text(text.replace(old, new))
    audit(staging / 'allegro_buddy')
    (staging / 'allegro_buddy' / '.complete').write_text('')
    try:
        staging.rename(root)
    except OSError:  # another process won the race
        shutil.rmtree(staging, ignore_errors=True)
    return root


def _install_hooks() -> None:
    import socket
    from datetime import datetime

    import allegro_buddy.cli as cli
    import allegro_buddy.handlers.config  # noqa: F401  (imported lazily by `config show`)
    from allegro_buddy import core
    from allegro_buddy.handlers import why

    modules = [m for n, m in sys.modules.items() if n.startswith('allegro_buddy') and m]

    now_text = os.environ.get('BAB_TEST_NOW')
    if now_text:
        frozen = datetime.fromisoformat(now_text)

        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return frozen if tz is None else frozen.replace(tzinfo=tz)

        core.datetime = FrozenDatetime

        class FrozenTime:
            def __getattr__(self, name):
                import time

                return getattr(time, name)

            @staticmethod
            def strftime(fmt, t=None):
                import time

                return time.strftime(fmt, t) if t is not None else frozen.strftime(fmt)

        cli.time = FrozenTime()

    groups_text = os.environ.get('BAB_TEST_GROUPS')
    if groups_text is not None:
        groups = {g for g in groups_text.split(',') if g}
        for module in modules:
            if hasattr(module, 'current_groups'):
                module.current_groups = lambda: set(groups)

    interactive = os.environ.get('BAB_TEST_INTERACTIVE')
    if interactive is not None:
        why._interactive = lambda: interactive == '1'

    hostname = os.environ.get('BAB_TEST_HOSTNAME')
    if hostname is not None:
        socket.gethostname = lambda: hostname


def run(argv: list[str]) -> None:
    sys.path.insert(0, str(build()))
    _install_hooks()
    from allegro_buddy.cli import main

    main(args=argv, prog_name='bab')


if __name__ == '__main__':
    if sys.argv[1:2] == ['build']:
        print(build())
    elif sys.argv[1:2] == ['run']:
        run(sys.argv[2:])
    else:
        raise SystemExit('usage: reference.py build | run [ARGS...]')
