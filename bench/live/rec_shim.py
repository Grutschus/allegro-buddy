#!/usr/bin/env python3
"""Recording shim for read-only Slurm commands (symlinked as squeue, scontrol, ...).

Runs the real binary from $REC_REAL_DIR (default /usr/bin), passes its stdout, stderr
and exit code through unchanged, and appends one JSON line to $REC_LOG:
{"cmd": $REC_CMD, "argv": [...], "exit": N, "stdout": ..., "stderr": ..., "t0", "t1"}
(stdout/stderr as UTF-8 text, or base64 under stdout_b64/stderr_b64 if not UTF-8).

Fails closed on anything that could change cluster state: only a fixed set of
read-only verbs is executed, everything else exits 1 and is logged as refused.
"""

import base64
import fcntl
import json
import os
import subprocess
import sys
import time

READ_ONLY = {'squeue', 'sinfo', 'sacct', 'sacctmgr', 'scontrol'}


def allowed(name: str, args: list[str]) -> bool:
    if name not in READ_ONLY:
        return False
    words = [a for a in args if not a.startswith('-')]
    if name == 'scontrol':
        return bool(words) and words[0] == 'show'
    if name == 'sacctmgr':
        return bool(words) and words[0] in {'show', 'list'}
    return True


def text_field(record: dict, key: str, data: bytes) -> None:
    try:
        record[key] = data.decode('utf-8')
    except UnicodeDecodeError:
        record[key + '_b64'] = base64.b64encode(data).decode()


def main() -> int:
    name = os.path.basename(sys.argv[0])
    args = sys.argv[1:]
    record: dict = {'cmd': os.environ.get('REC_CMD', ''), 'argv': [name, *args]}
    record['t0'] = time.time()
    if not allowed(name, args):
        record.update(exit=1, refused=True, stdout='', stderr='')
        code, out, err = 1, b'', f'rec_shim: refused {name} {args}\n'.encode()
    else:
        real = os.path.join(os.environ.get('REC_REAL_DIR', '/usr/bin'), name)
        proc = subprocess.run([real, *args], capture_output=True)
        code, out, err = proc.returncode, proc.stdout, proc.stderr
        record['exit'] = code
        text_field(record, 'stdout', out)
        text_field(record, 'stderr', err)
    record['t1'] = time.time()
    log = os.environ.get('REC_LOG')
    if log:
        with open(log, 'a', encoding='utf-8') as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.write(json.dumps(record) + '\n')
    sys.stdout.buffer.write(out)
    sys.stderr.buffer.write(err)
    return code


if __name__ == '__main__':
    sys.exit(main())
