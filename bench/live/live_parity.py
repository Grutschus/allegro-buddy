#!/usr/bin/env python3
"""Live parity on a real cluster: the Python reference vs bab, back to back (read-only).

    live_parity.py --ref-python VENV/bin/python --reference reference.py --bab BIN/bab
                   --out FILE.jsonl [--commands commands.txt] [--as-user USER] [--sleep 1]

For every command (placeholders as in record.py, filled from one `squeue` call) runs
the reference (allegro-buddy 2.7 renamed to bab by compat/reference.py, no test hooks
set: real clock, groups, hostname) and then bab, at most ~2 s apart, with COLUMNS=160
and the default TZ, private XDG_CONFIG_HOME/AB_SITE_CONFIG and a shared private cache
dir. A differing pair is rerun once (after a pause). Writes one JSON line per attempt.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import discover  # noqa: E402


def run(argv: list[str], env: dict[str, str]) -> dict:
    t0 = time.time()
    try:
        proc = subprocess.run(argv, capture_output=True, env=env, stdin=subprocess.DEVNULL,
                              timeout=120)
        code, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        code, out, err = 124, b'', b'timeout\n'
    return {'exit': code, 'stdout': out.decode('utf-8', 'replace'),
            'stderr': err.decode('utf-8', 'replace'), 't0': t0, 't1': time.time()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--ref-python', required=True)
    ap.add_argument('--reference', required=True, help='compat/reference.py')
    ap.add_argument('--bab', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--commands', default=str(Path(__file__).resolve().parent / 'commands.txt'))
    ap.add_argument('--as-user')
    ap.add_argument('--sleep', type=float, default=1.0)
    args = ap.parse_args()

    scratch = Path(args.out).resolve().parent / f'.scratch-{os.getpid()}'
    (scratch / 'cache').mkdir(parents=True)
    (scratch / 'config').mkdir()
    env = dict(os.environ)
    for key in ('FORCE_COLOR', 'NO_COLOR', 'AB_CLUSTER', 'RICH_CLICK_THEME', 'TZ',
                'BAB_TEST_NOW', 'BAB_TEST_GROUPS', 'BAB_TEST_HOSTNAME', 'BAB_TEST_INTERACTIVE'):
        env.pop(key, None)
    env.update(COLUMNS='160', XDG_CACHE_HOME=str(scratch / 'cache'),
               XDG_CONFIG_HOME=str(scratch / 'config'),
               AB_SITE_CONFIG=str(scratch / 'site.ini'))
    if args.as_user:
        env.update(USER=args.as_user, LOGNAME=args.as_user)
    values = discover({**env, 'REC_CMD': ''})
    time.sleep(args.sleep)
    ref = [args.ref_python, args.reference, 'run']
    with open(args.out, 'w', encoding='utf-8') as fh:
        for line in Path(args.commands).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            cmd = shlex.split(line.format(**values))
            for attempt in (1, 2):
                r = run([*ref, *cmd], env)
                b = run([args.bab, *cmd], env)
                same = all(r[k] == b[k] for k in ('exit', 'stdout', 'stderr'))
                fh.write(json.dumps({'args': cmd, 'attempt': attempt, 'same': same,
                                     'as_user': args.as_user, 'ref': r, 'bab': b}) + '\n')
                fh.flush()
                print(f'{"same" if same else "DIFF"} #{attempt} gap={b["t0"] - r["t1"]:.2f}s'
                      f' ref={r["t1"] - r["t0"]:.2f}s bab={b["t1"] - b["t0"]:.2f}s'
                      f' {shlex.join(cmd)}', file=sys.stderr)
                time.sleep(args.sleep * (2 if not same else 1))
                if same:
                    break
    shutil.rmtree(scratch)
    return 0


if __name__ == '__main__':
    sys.exit(main())
