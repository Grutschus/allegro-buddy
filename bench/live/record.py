#!/usr/bin/env python3
"""Record a "world snapshot" of real Slurm outputs on a live cluster (read-only).

Runs the Python reference once per command of COMMANDS (see commands.txt) with the
recording shims (rec_shim.py, symlinked as squeue/scontrol/sinfo/sacct/sacctmgr) first
on $PATH, and writes OUT/:

  meta.json    host, time, TZ, user, groups, versions, `scontrol show config` keys
  calls.jsonl  every Slurm call: {"cmd", "argv", "exit", "stdout", "stderr", "t0", "t1"}
  runs.jsonl   every reference run: {"id", "args", "now", "columns", "exit", "stdout",
               "stderr", "t0", "t1"}; "now" is the local wall clock at the start
               (BAB_TEST_NOW for a replay)

Usage: record.py --ref VENV/bin/allegro-buddy --out DIR [--commands FILE] [--sleep 1]
                 [--as-user USER]

Every run gets a private XDG_CONFIG_HOME and AB_SITE_CONFIG (no user/site config); the
cache dir is shared, so only the first run probes `scontrol show config` (as a user's
warm cache would). Placeholders in commands ({pending}, {running}, ...) are filled
from one `squeue` call (recorded as cmd "_discover").
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHIMS = ('squeue', 'scontrol', 'sinfo', 'sacct', 'sacctmgr')


def sh(argv: list[str]) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ''


def discover(env: dict[str, str]) -> dict[str, str]:
    out = subprocess.run(
        ['squeue', '-h', '-o', '%i|%T|%u|%P|%r'],
        capture_output=True, text=True, env={**env, 'REC_CMD': '_discover'}, timeout=60,
    ).stdout
    rows = [line.split('|') for line in out.splitlines() if line.count('|') == 4]
    me = env.get('USER', '')
    pending = [r for r in rows if r[1] == 'PENDING' and '[' not in r[0]]
    arrays = [r for r in rows if r[1] == 'PENDING' and '[' in r[0]]
    running = [r for r in rows if r[1] == 'RUNNING' and '_' not in r[0]]
    running_array = [r for r in rows if r[1] == 'RUNNING' and '_' in r[0]]
    mine = [r for r in rows if r[2] == me]
    my_pending = [r for r in mine if r[1] == 'PENDING']
    my_running = [r for r in mine if r[1] == 'RUNNING']
    others = sorted({r[2] for r in rows if r[2] != me})
    values = {
        'pending': (pending or running or [['1']])[0][0],
        'pending2': (pending[1:] or pending or running or [['1']])[0][0],
        'array_pending': (arrays or pending or [['1']])[0][0].split('_')[0],
        'array_task': (running_array or running or [['1']])[0][0],
        'running': (running or [['1']])[0][0],
        'other_user': (pending or rows or [['', '', me]])[0][2],
        'other_user2': (others[1:] or others or [me])[0],
        'my_pending': (my_pending or mine or [['999999999']])[0][0].split('_')[0],
        'my_running': (my_running or mine or [['999999999']])[0][0],
    }
    return values


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--ref', required=True, help='the reference executable (allegro-buddy)')
    ap.add_argument('--out', required=True)
    ap.add_argument('--commands', default=str(HERE / 'commands.txt'))
    ap.add_argument('--sleep', type=float, default=1.0)
    ap.add_argument('--columns', default='160')
    ap.add_argument('--as-user', help='USER/LOGNAME for the runs (the user-centric views of '
                    'another user; all queries stay read-only, groups stay the real ones)')
    args = ap.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True)
    shims = out / '.shims'
    shims.mkdir()
    for name in SHIMS:
        (shims / name).symlink_to(HERE / 'rec_shim.py')
    scratch = out / '.scratch'
    (scratch / 'cache').mkdir(parents=True)

    env = dict(os.environ)
    env.update(
        PATH=f'{shims}:{env.get("PATH", "/usr/bin:/bin")}',
        REC_LOG=str(out / 'calls.jsonl'),
        XDG_CACHE_HOME=str(scratch / 'cache'),
        COLUMNS=args.columns,
    )
    if args.as_user:
        env.update(USER=args.as_user, LOGNAME=args.as_user)
    for key in ('FORCE_COLOR', 'NO_COLOR', 'AB_CLUSTER', 'RICH_CLICK_THEME', 'SLURM_TIME_FORMAT'):
        env.pop(key, None)

    started = datetime.now().astimezone()
    tz = os.environ.get('TZ') or os.path.realpath('/etc/localtime').split('zoneinfo/')[-1]
    config = subprocess.run(
        ['scontrol', 'show', 'config'], capture_output=True, text=True,
        env={**env, 'REC_CMD': '_config'}, timeout=60,
    ).stdout
    config_keys = {}
    for line in config.splitlines():
        key, sep, value = line.partition('=')
        if sep and key.strip() in {
            'ClusterName', 'SLURM_VERSION', 'SelectType', 'SelectTypeParameters',
            'AccountingStorageType', 'PriorityType', 'SchedulerType', 'GresTypes',
            'AccountingStorageTRES', 'MaxArraySize', 'DefMemPerNode', 'PreemptMode',
        }:
            config_keys[key.strip()] = value.strip()
    time.sleep(args.sleep)
    values = discover(env)
    time.sleep(args.sleep)

    commands = []
    for line in Path(args.commands).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            commands.append(shlex.split(line.format(**values)))

    with open(out / 'runs.jsonl', 'w', encoding='utf-8') as runs:
        for i, cmd in enumerate(commands):
            run_id = f'{i:03d}'
            home = scratch / run_id
            (home / 'config').mkdir(parents=True)
            run_env = {
                **env,
                'REC_CMD': run_id,
                'XDG_CONFIG_HOME': str(home / 'config'),
                'AB_SITE_CONFIG': str(home / 'site.ini'),
            }
            now = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
            t0 = time.time()
            try:
                proc = subprocess.run(
                    [args.ref, *cmd], capture_output=True, env=run_env,
                    stdin=subprocess.DEVNULL, timeout=120,
                )
                code, so, se = proc.returncode, proc.stdout, proc.stderr
            except subprocess.TimeoutExpired:
                code, so, se = 124, b'', b'timeout\n'
            t1 = time.time()
            record = {
                'id': run_id, 'args': cmd, 'now': now, 'columns': args.columns,
                'exit': code, 'stdout': so.decode('utf-8', 'replace'),
                'stderr': se.decode('utf-8', 'replace'), 't0': t0, 't1': t1,
            }
            runs.write(json.dumps(record) + '\n')
            runs.flush()
            print(f'{run_id} {t1 - t0:6.2f}s exit={code} {shlex.join(cmd)}', file=sys.stderr)
            time.sleep(args.sleep)

    meta = {
        'hostname': socket.gethostname(),
        'started': started.isoformat(timespec='seconds'),
        'finished': datetime.now().astimezone().isoformat(timespec='seconds'),
        'date_iseconds': sh(['date', '-Iseconds']),
        'tz': tz,
        'user': args.as_user or sh(['id', '-un']),
        'real_user': sh(['id', '-un']),
        'groups': sh(['id', '-Gn']).split(),
        'python_groups': sorted(
            g for g in (_group(gid) for gid in os.getgroups()) if g
        ),
        'columns': args.columns,
        'placeholders': values,
        'scontrol_config': config_keys,
        'versions': {
            'sinfo': sh(['/usr/bin/sinfo', '--version']),
            'python': sys.version.split()[0],
            'uname': sh(['uname', '-srm']),
            'glibc': sh(['getconf', 'GNU_LIBC_VERSION']),
            'reference': sh([args.ref, '--version']),
        },
        'commands': len(commands),
    }
    (out / 'meta.json').write_text(json.dumps(meta, indent=2) + '\n')
    for path in sorted(scratch.rglob('*'), reverse=True):
        path.rmdir() if path.is_dir() else path.unlink()
    scratch.rmdir()
    for name in SHIMS:
        (shims / name).unlink()
    shims.rmdir()
    return 0


def _group(gid: int) -> str | None:
    import grp

    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return None


if __name__ == '__main__':
    sys.exit(main())
