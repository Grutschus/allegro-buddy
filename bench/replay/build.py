#!/usr/bin/env python3
"""Build a replay tree for the `fake` Slurm from a recorded dataset (bench/live/record.py).

    build.py DATASET OUT

DATASET has calls.jsonl[.gz], runs.jsonl[.gz] and meta.json. OUT gets:

  bin/{squeue,scontrol,sinfo,sacct,sacctmgr,sbatch,scancel,srun,salloc,sstat}
                       symlinks to `fake` (absolute)
  runs/<id>/           the Slurm calls of recorded command <id>: index.sh + N.out/N.err
  common/              fallback: the first recording of every argv (incl. the probe
                       `scontrol show config`)
  runs.json            [{"id", "args", "now", "exit"}], plus "meta" (copied meta.json)

The same argv recorded twice within one command keeps the first answer.
"""

from __future__ import annotations

import base64
import gzip
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAMES = ('squeue', 'scontrol', 'sinfo', 'sacct', 'sacctmgr', 'sbatch', 'scancel', 'srun',
         'salloc', 'sstat')


def read_jsonl(dataset: Path, name: str) -> list[dict]:
    plain = dataset / name
    if plain.exists():
        text = plain.read_text(encoding='utf-8')
    else:
        text = gzip.decompress((dataset / (name + '.gz')).read_bytes()).decode('utf-8')
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def field(record: dict, key: str) -> bytes:
    if key + '_b64' in record:
        return base64.b64decode(record[key + '_b64'])
    return record.get(key, '').encode('utf-8')


def sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def write_dir(directory: Path, calls: list[dict]) -> None:
    directory.mkdir(parents=True)
    seen: dict[str, int] = {}
    lines = ['case $key in']
    for call in calls:
        key = ' '.join(call['argv'])
        if key in seen or call.get('refused'):
            continue
        n = seen[key] = len(seen)
        out, err = field(call, 'stdout'), field(call, 'stderr')
        flags = f'e={int(call["exit"])} o={"1" if out else ""} x={"1" if err else ""}'
        if out:
            (directory / f'{n}.out').write_bytes(out)
        if err:
            (directory / f'{n}.err').write_bytes(err)
        lines.append(f'{sh_quote(key)}) n={n} {flags};;')
    lines.append('esac')
    (directory / 'index.sh').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def build(dataset: Path, out: Path) -> None:
    calls = read_jsonl(dataset, 'calls.jsonl')
    runs = read_jsonl(dataset, 'runs.jsonl')
    meta = json.loads((dataset / 'meta.json').read_text())
    if out.exists():
        shutil.rmtree(out)
    (out / 'bin').mkdir(parents=True)
    for name in NAMES:
        (out / 'bin' / name).symlink_to(HERE / 'fake')
    by_run: dict[str, list[dict]] = {}
    for call in calls:
        by_run.setdefault(call['cmd'], []).append(call)
    for run in runs:
        write_dir(out / 'runs' / run['id'], by_run.get(run['id'], []))
    write_dir(out / 'common', calls)
    index = {
        'meta': meta,
        'runs': [
            {'id': r['id'], 'args': r['args'], 'now': r['now'], 'exit': r['exit']}
            for r in runs
        ],
    }
    (out / 'runs.json').write_text(json.dumps(index, indent=1) + '\n')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit('usage: build.py DATASET OUT')
    build(Path(sys.argv[1]), Path(sys.argv[2]))
