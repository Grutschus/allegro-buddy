#!/usr/bin/env python3
"""Time commands on the replay fake Slurm with hyperfine (median wall time per command).

    bench.py --data bench/data/allegro/snapshot --bin bab=target/release/bab [--bin old=...]
             [--ref] [--realtime | --delay-ms 50] [-k REGEX] [--runs 10 --rounds 5]
             [--cold-cache] [--json out.json] [--export-dir DIR]

Every implementation sees the same environment as `parity.py` (warm cluster-name cache,
frozen clock and groups via the BAB_TEST_* hooks, so time `--features test-hooks` builds),
COLUMNS=160, stdout/stderr to /dev/null. Reported: the median wall time over `--rounds`
hyperfine runs of `--runs` each (all implementations in every round, in rotated order, so
bursts of load on a shared host hit all of them). `--realtime` makes every fake Slurm call take as long
as it took on the cluster when recorded (REPLAY_REALTIME), `--delay-ms N` N ms per call
(REPLAY_DELAY_MS); without either a call costs ~1 ms (sh + cat). `--ref` adds the Python
reference (allegro-buddy 2.7, `compat/reference.py run`; for the final comparison use
`--bin ab=VENV/bin/ab` from `make_ab_venv.sh` instead: the console script itself, no
renaming wrapper). `--cold-cache` deletes the cluster-name cache before every timed run
(hyperfine --prepare). `--export-dir` keeps every hyperfine JSON export; `--json` gets
mean/stddev/median/min/max over all rounds per command and implementation. `--calls`
prints the Slurm calls of each command once instead of timing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import build as replay_build  # noqa: E402
from parity import default_python  # noqa: E402

COMMANDS = [
    ['--version'], ['-h'], ['info'], ['free'], ['free', '--nodes'], ['queue'], ['q', '--all'],
    ['why'], ['why', '{pending}'], ['why', '--nodes'], ['node', 'gpu062'], ['job', 'history'],
    ['dev', 'status'], ['config', 'show'],
]


def find_run(index: dict, args: list[str]) -> dict | None:
    return next((run for run in index['runs'] if run['args'] == args), None)


def environment(replay: Path, meta: dict, run: dict, work: Path, delay: int,
                realtime: bool) -> dict:
    shutil.rmtree(work, ignore_errors=True)
    for sub in ('home', 'config', 'cache/allegro-buddy', 'site'):
        (work / sub).mkdir(parents=True)
    host = meta['hostname']
    cluster = meta['scontrol_config'].get('ClusterName', '')
    (work / 'cache/allegro-buddy' / f'cluster-name.{host}').write_text(cluster + '\n')
    env = {
        'PATH': f'{replay}/bin:/usr/bin:/bin',
        'HOME': str(work / 'home'),
        'USER': meta['user'],
        'LOGNAME': meta['user'],
        'TZ': meta['tz'],
        'LANG': 'C.UTF-8',
        'XDG_CONFIG_HOME': str(work / 'config'),
        'XDG_CACHE_HOME': str(work / 'cache'),
        'AB_SITE_CONFIG': str(work / 'site/config.ini'),
        'BAB_TEST_NOW': run['now'],
        'BAB_TEST_GROUPS': ','.join(meta['groups']),
        'BAB_TEST_HOSTNAME': host,
        'REPLAY_RUN': str(replay / 'runs' / run['id']),
        'REPLAY_COMMON': str(replay / 'common'),
        'COLUMNS': '160',
    }
    if delay:
        env['REPLAY_DELAY_MS'] = str(delay)
    if realtime:
        env['REPLAY_REALTIME'] = '1'
    return env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', type=Path, default=REPO / 'bench/data/allegro/snapshot')
    ap.add_argument('--bin', action='append', default=[], metavar='NAME=PATH')
    ap.add_argument('--ref', action='store_true', help='also time the Python reference')
    ap.add_argument('--ref-python', default=default_python())
    ap.add_argument('--delay-ms', type=int, default=0)
    ap.add_argument('--realtime', action='store_true')
    ap.add_argument('-k', default='')
    ap.add_argument('--runs', type=int, default=10)
    ap.add_argument('--rounds', type=int, default=5)
    ap.add_argument('--warmup', type=int, default=3)
    ap.add_argument('--calls', action='store_true')
    ap.add_argument('--json', type=Path)
    ap.add_argument('--export-dir', type=Path, help='keep every hyperfine JSON export here')
    ap.add_argument('--cold-cache', action='store_true',
                    help='no cluster-name cache: deleted before every run')
    ap.add_argument('--cpus', help='taskset CPU list for hyperfine and everything it runs')
    ap.add_argument('--out', type=Path, default=REPO / 'bench/replay/.work')
    args = ap.parse_args()

    out = args.out.resolve()
    replay = out / 'replay'
    replay_build.build(args.data.resolve(), replay)
    index = json.loads((replay / 'runs.json').read_text())
    meta = index['meta']
    impls = [(name, [str(Path(path).resolve())]) for name, path in
             (b.split('=', 1) for b in args.bin)]
    if args.ref:
        impls.append(('ab', [args.ref_python, str(REPO / 'compat/reference.py'), 'run']))
    hyperfine = shutil.which('hyperfine') or '/srv/public/plainer/rust/cargo/bin/hyperfine'

    results: dict[str, dict[str, dict]] = {}
    if args.export_dir:
        args.export_dir.mkdir(parents=True, exist_ok=True)
    for template in COMMANDS:
        cmd = [a.format(**meta['placeholders']) for a in template]
        label = ' '.join(template)
        run = find_run(index, cmd)
        if run is None or (args.k and not re.search(args.k, label)):
            continue
        work = out / 'bench'
        env = environment(replay, meta, run, work, args.delay_ms, args.realtime)
        if args.calls:
            log = work / 'calls.log'
            env['REPLAY_LOG'] = str(log)
            subprocess.run([*impls[0][1], *cmd], env=env, cwd=work / 'home',
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            calls = log.read_text().splitlines() if log.exists() else []
            print(f'{label}: {len(calls)} calls')
            for c in calls:
                print('   ', c.split('\t', 1)[1][:110])
            continue
        export = work / 'hf.json'
        cache = work / 'cache/allegro-buddy' / f"cluster-name.{meta['hostname']}"
        times: dict[str, list[dict]] = {name: [] for name, _ in impls}
        for i in range(args.rounds):
            # interleaved rounds (bursts of load hit all impls), rotated (no position bias)
            hf = ['taskset', '-c', args.cpus] if args.cpus else []
            hf += [hyperfine, '-N', '--style', 'none', '-w', str(args.warmup),
                  '-r', str(args.runs), '--export-json', str(export)]
            if args.cold_cache:
                hf += ['--prepare', f'rm -f {cache}']
            for name, impl in impls[i % len(impls):] + impls[:i % len(impls)]:
                hf += ['-n', name, ' '.join([*impl, *(_q(a) for a in cmd)])]
            subprocess.run(hf, env=env, cwd=work / 'home', stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=True)
            data = json.loads(export.read_text())
            if args.export_dir:
                slug = re.sub(r'[^\w.-]+', '_', label).strip('_-')
                shutil.copy(export, args.export_dir / f'{slug}.round{i}.json')
            for r in data['results']:
                times[r['name']] += r['measurements']
        results[label] = {name: _stats(t) for name, t in times.items()}
        row = '  '.join(f"{n}={results[label][n]['median']:8.2f}" for n, _ in impls)
        print(f'{label:<16} {row}  (ms, median)', flush=True)
    if args.json:
        args.json.write_text(json.dumps(results, indent=1) + '\n')
    return 0


def _stats(measurements: list[dict]) -> dict:
    """Wall time stats in ms, plus mean CPU time (user+sys, ms) and median peak RSS (MiB)."""
    ms = [m['time_wall_clock']['value'] * 1000 for m in measurements]
    cpu = [m['time_cpu']['value'] * 1000 for m in measurements]
    rss = [m['memory_peak_resident']['value'] / 2**20 for m in measurements]
    return {'n': len(ms), 'mean': statistics.fmean(ms), 'stddev': statistics.stdev(ms),
            'median': statistics.median(ms), 'min': min(ms), 'max': max(ms),
            'cpu_mean': statistics.fmean(cpu), 'rss_median_mib': statistics.median(rss),
            'times_ms': ms}


def _q(arg: str) -> str:
    return arg if re.fullmatch(r'[\w.,=/%:|-]+', arg) else "'" + arg.replace("'", "'\\''") + "'"


if __name__ == '__main__':
    sys.exit(main())
