"""BAB_TEST_* hooks for the *unmodified* allegro-buddy 2.7 console script (`venv/bin/ab`).

`make_ab_venv.sh` copies this module into the benchmark venv's site-packages together
with `ab_bench_hooks.pth`, whose single line runs ``install()`` at interpreter start-up
only when BAB_TEST_NOW is set (otherwise the cost is reading one .pth line).

``install()`` applies the same patches as ``compat/reference.py:_install_hooks`` (frozen
``core.datetime.now``, ``current_groups``, ``socket.gethostname``), but without the
reference's renaming copy of the package (sha256 over all its files on every run) and
without importing ``handlers.config`` eagerly. It imports ``allegro_buddy.cli`` itself:
the console script imports exactly that module (and with it every handler but
``handlers.config``) a moment later anyway, so the work moves, it is not added.
"""

from __future__ import annotations

import os
import sys


def install() -> None:
    import socket
    from datetime import datetime

    import allegro_buddy.cli  # noqa: F401  (what the console script imports next)
    from allegro_buddy import core

    frozen = datetime.fromisoformat(os.environ['BAB_TEST_NOW'])

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz is None else frozen.replace(tzinfo=tz)

    core.datetime = FrozenDatetime

    groups_text = os.environ.get('BAB_TEST_GROUPS')
    if groups_text is not None:
        groups = {g for g in groups_text.split(',') if g}

        def current_groups() -> set[str]:
            return set(groups)

        # handlers.config is imported later and picks up core's (patched) attribute
        for name, module in list(sys.modules.items()):
            if name.startswith('allegro_buddy') and hasattr(module, 'current_groups'):
                module.current_groups = current_groups

    hostname = os.environ.get('BAB_TEST_HOSTNAME')
    if hostname is not None:
        socket.gethostname = lambda: hostname
