#!/usr/bin/env python3
"""Replay parity: the Python reference vs bab on a recorded world (deterministic).

    parity.py --data DATASET [--bin BAB] [--ref-python PY] [--out DIR]
              [--widths 80,160,200] [-k REGEX] [-j N]

Builds the replay tree (build.py) from DATASET, then runs every recorded command with
both implementations against the `fake` Slurm, at each width, without color and with
FORCE_COLOR=1 (plus one cold-cache run at 160 columns), and compares stdout, stderr,
exit code and the multiset of Slurm calls. Environment per case (nothing inherited):
PATH=<replay>/bin:/usr/bin:/bin, fresh HOME/XDG dirs, USER=LOGNAME=<recorded user>,
TZ=<recorded TZ>, LANG=C.UTF-8, BAB_TEST_NOW=<recorded start of the command>,
BAB_TEST_GROUPS=<recorded `id -Gn`>, BAB_TEST_HOSTNAME=<recorded host>.
Diffs go to OUT/diffs/, a summary to OUT/summary.json; exit 1 on any mismatch.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import build as replay_build  # noqa: E402


def run_case(impl: list[str], case: dict, replay: Path, meta: dict, work: Path) -> dict:
    if work.exists():
        shutil.rmtree(work)
    home = work / 'home'
    for sub in ('home', 'config', 'cache/allegro-buddy', 'site'):
        (work / sub).mkdir(parents=True)
    host = meta['hostname']
    if case['cache'] == 'warm':
        cluster = meta['scontrol_config'].get('ClusterName', '')
        (work / 'cache/allegro-buddy' / f'cluster-name.{host}').write_text(cluster + '\n')
    log = work / 'calls.log'
    env = {
        'PATH': f'{replay}/bin:/usr/bin:/bin',
        'HOME': str(home),
        'USER': meta['user'],
        'LOGNAME': meta['user'],
        'TZ': meta['tz'],
        'LANG': 'C.UTF-8',
        'XDG_CONFIG_HOME': str(work / 'config'),
        'XDG_CACHE_HOME': str(work / 'cache'),
        'AB_SITE_CONFIG': str(work / 'site/config.ini'),
        'BAB_TEST_NOW': case['now'],
        'BAB_TEST_GROUPS': ','.join(meta['groups']),
        'BAB_TEST_HOSTNAME': host,
        'REPLAY_RUN': str(replay / 'runs' / case['id']),
        'REPLAY_COMMON': str(replay / 'common'),
        'REPLAY_LOG': str(log),
        'COLUMNS': str(case['columns']),
    }
    if case['color']:
        env['FORCE_COLOR'] = '1'
    try:
        proc = subprocess.run(
            [*impl, *case['args']], cwd=home, env=env, capture_output=True,
            stdin=subprocess.DEVNULL, timeout=120,
        )
        code, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        code, out, err = 124, b'', b'timeout\n'
    calls = sorted(log.read_text().splitlines()) if log.exists() else []
    return {
        'exit': code,
        'stdout': out.decode('utf-8', 'replace'),
        'stderr': err.decode('utf-8', 'replace'),
        'calls': [c.split('\t', 1)[1] for c in calls],
        'misses': [c for c in calls if c.startswith('MISS')],
    }


def show(text: str) -> list[str]:
    return [line.replace('\x1b', '\\x1b') for line in text.splitlines(keepends=True)]


def compare(case: dict, ref: dict, bab: dict) -> str:
    parts = []
    for key in ('stdout', 'stderr'):
        if ref[key] != bab[key]:
            parts.extend(difflib.unified_diff(
                show(ref[key]), show(bab[key]), f'ref/{key}', f'bab/{key}', n=2))
    if ref['exit'] != bab['exit']:
        parts.append(f'exit: ref {ref["exit"]} bab {bab["exit"]}\n')
    if ref['calls'] != bab['calls']:
        parts.extend(difflib.unified_diff(
            [c + '\n' for c in ref['calls']], [c + '\n' for c in bab['calls']],
            'ref/calls', 'bab/calls', n=0))
    for name, result in (('ref', ref), ('bab', bab)):
        for miss in result['misses']:
            parts.append(f'{name}: {miss}\n')
    return ''.join(p if p.endswith('\n') else p + '\n' for p in parts)


def default_python() -> str:
    venv = os.environ.get('UV_PROJECT_ENVIRONMENT') or str(REPO / 'compat/.venv')
    return str(Path(venv) / 'bin/python')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True, type=Path)
    ap.add_argument('--bin', default=os.environ.get('BAB_BIN', str(REPO / 'target/release/bab')))
    ap.add_argument('--ref-python', default=default_python(),
                    help='python of the compat venv (allegro-buddy 2.7 installed)')
    ap.add_argument('--out', type=Path, default=REPO / 'bench/replay/.work')
    ap.add_argument('--widths', default='80,160,200')
    ap.add_argument('-k', default='', help='regex on "<id> <args> c<width> [color]"')
    ap.add_argument('-j', type=int, default=os.cpu_count() or 4)
    ap.add_argument('--groups', help='BAB_TEST_GROUPS instead of the recorded groups')
    ap.add_argument('--tz', help='TZ instead of the recorded one')
    ap.add_argument('--now-shift', type=int, default=0,
                    help='seconds added to the recorded BAB_TEST_NOW')
    args = ap.parse_args()

    out = args.out.resolve()
    replay = out / 'replay'
    replay_build.build(args.data.resolve(), replay)
    index = json.loads((replay / 'runs.json').read_text())
    meta = index['meta']
    if args.groups is not None:
        meta['groups'] = [g for g in args.groups.split(',') if g]
    if args.tz:
        meta['tz'] = args.tz
    if args.now_shift:
        for run in index['runs']:
            now = datetime.fromisoformat(run['now']) + timedelta(seconds=args.now_shift)
            run['now'] = now.isoformat(timespec='seconds')

    cases = []
    for run in index['runs']:
        variants = [(int(w), color, 'warm') for w in args.widths.split(',') for color in (0, 1)]
        variants.append((160, 0, 'cold'))
        for width, color, cache in variants:
            label = (f'{run["id"]} {" ".join(run["args"])} c{width}'
                     f'{" color" if color else ""}{" cold" if cache == "cold" else ""}')
            if args.k and not re.search(args.k, label):
                continue
            cases.append({**run, 'columns': width, 'color': color, 'cache': cache,
                          'label': label, 'n': len(cases)})

    diffs = out / 'diffs'
    shutil.rmtree(diffs, ignore_errors=True)
    diffs.mkdir(parents=True)
    work_root = out / 'w'

    def one(case: dict) -> dict:
        work = work_root / f'{case["n"]:04d}'
        ref = run_case([args.ref_python, str(REPO / 'compat/reference.py'), 'run'], case, replay, meta, work)
        bab = run_case([str(Path(args.bin).resolve())], case, replay, meta, work)
        shutil.rmtree(work, ignore_errors=True)
        diff = compare(case, ref, bab)
        if diff:
            name = re.sub(r'[^A-Za-z0-9_.-]+', '_', case['label'])
            (diffs / f'{name}.diff').write_text(diff)
        return {'label': case['label'], 'ok': not diff, 'ref_exit': ref['exit'],
                'bab_exit': bab['exit']}

    with ThreadPoolExecutor(args.j) as pool:
        results = list(pool.map(one, cases))
    shutil.rmtree(work_root, ignore_errors=True)
    failed = [r for r in results if not r['ok']]
    for r in results:
        print(f'{"ok  " if r["ok"] else "FAIL"} {r["label"]}')
    print(f'\n{len(results) - len(failed)}/{len(results)} cases identical'
          f' (diffs in {diffs})')
    (out / 'summary.json').write_text(json.dumps(results, indent=1) + '\n')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
