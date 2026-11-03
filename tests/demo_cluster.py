"""A made-up, busy Allegro-shaped cluster that answers every Slurm call `ab` makes.

``FakeSlurm`` (test_cluster_output) knows nodes and partitions but no jobs. ``DemoSlurm``
adds a handful of running and pending jobs for alice and bob, alice's finished history,
an upcoming maintenance reservation, and a stdout file for `ab job output`. It is shared
by the whole-command snapshots (test_demo_output) and the output gallery script.

Times are relative to ``NOW``; ``demo_cluster()`` freezes ``core.datetime.now`` there.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from slurm_records import PLAIN_GPU_JOB, node_dict, number
from test_cluster_output import CPU_PARTS, GPU_PARTS, FakeSlurm

from allegro_buddy import core, settings

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

NOW = datetime(2026, 11, 3, 10, 0, 0)
USER = 'alice'
UIDS = {'alice': 1000, 'bob': 1001}


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz is None else NOW.replace(tzinfo=tz)


def at(minutes: int) -> str:
    return (NOW + timedelta(minutes=minutes)).isoformat(timespec='seconds')


def slurm_duration(minutes: int) -> str:
    """Minutes as squeue prints them: 1-02:03:00, 2:03:00 or 3:00."""
    days, rest = divmod(minutes * 60, 86400)
    hours, rest = divmod(rest, 3600)
    mins, secs = divmod(rest, 60)
    if days:
        return f'{days}-{hours:02d}:{mins:02d}:{secs:02d}'
    if hours:
        return f'{hours}:{mins:02d}:{secs:02d}'
    return f'{mins}:{secs:02d}'


@dataclass
class Job:
    id: str
    user: str
    name: str
    state: str
    partition: str
    limit: int  # minutes
    cpus: int
    mem: int  # MB
    gpus: int = 0
    gpu_type: str = ''
    node: str = ''
    gpu_idx: str = ''
    started: int = 0  # minutes from NOW (negative: already running)
    reason: str = 'None'
    start_estimate: int | None = None  # minutes from NOW, pending only
    stdout: str = ''

    @property
    def gres(self) -> str:
        if not self.gpus:
            return ''
        return f'gpu:{self.gpu_type}:{self.gpus}' if self.gpu_type else f'gpu:{self.gpus}'

    def squeue(self) -> dict[str, str]:
        running = self.state == 'RUNNING'
        return {
            'i': self.id,
            'A': self.id,
            'F': self.id,
            'u': self.user,
            'j': self.name,
            'T': self.state,
            'P': self.partition,
            'M': slurm_duration(-self.started) if running else '0:00',
            'L': slurm_duration(self.limit + self.started if running else self.limit),
            'l': slurm_duration(self.limit),
            'S': at(self.started)
            if running
            else (at(self.start_estimate) if self.start_estimate is not None else 'N/A'),
            'R': self.node if running else f'({self.reason})',
        }

    def detail_line(self) -> str:
        """The job as `scontrol --oneliner --details show job` prints it."""
        running = self.state == 'RUNNING'
        start = at(self.started) if running else 'Unknown'
        end = at(self.started + self.limit) if running else 'Unknown'
        fields = [
            f'JobId={self.id}',
            f'JobName={self.name}',
            f'UserId={self.user}({UIDS[self.user]})',
            f'JobState={self.state}',
            f'Reason={self.reason}',
            f'SubmitTime={at(min(self.started, 0) - 5)}',
            f'StartTime={start}',
            f'EndTime={end}',
            f'Partition={self.partition}',
            f'NodeList={self.node or "(null)"}',
            f'NumCPUs={self.cpus}',
            f'MinMemoryNode={self.mem // 1024}G',
        ]
        if self.gpus:
            fields += [f'TresPerNode=gres/{self.gres}', f'JOB_GRES={self.gres}']
        if running:
            gres = f' GRES={self.gres}(IDX:{self.gpu_idx})' if self.gpus else ''
            fields.append(
                f'Nodes={self.node} CPU_IDs=0-{self.cpus - 1} Mem={self.mem}{gres}'
            )
        out = self.stdout or f'/home/{self.user}/slurm-{self.id}.out'
        fields += [f'StdErr={out}', f'StdOut={out}']
        return ' '.join(fields)

    def record(self) -> dict[str, Any]:
        """The job as `scontrol --json show job` reports it."""
        planned = self.start_estimate is not None
        return {
            **PLAIN_GPU_JOB,
            'job_id': int(self.id),
            'user_name': self.user,
            'name': self.name,
            'job_state': [self.state],
            'state_reason': self.reason,
            'partition': self.partition,
            'cpus': number(self.cpus),
            'tres_per_node': f'gres/{self.gres}' if self.gpus else '',
            'cpus_per_tres': '',
            'memory_per_node': number(self.mem),
            'tres_req_str': f'cpu={self.cpus},mem={self.mem}M,node=1,billing={self.cpus}',
            'features': '',
            'scheduled_nodes': 'gpu101' if planned else '',
            'start_time': number(
                int((NOW + timedelta(minutes=self.start_estimate)).timestamp())
                if planned
                else 0
            ),
        }


def demo_jobs() -> list[Job]:
    a5000, gtx = 'RTX-A5000', 'GTX-1080ti'
    return [
        Job('70110', 'alice', core.DEV_JOB_NAME, 'RUNNING', 'gpu', 480, 4, 16384,
            1, a5000, 'gpu101', '0', started=-85),
        Job('70102', 'bob', 'sweep', 'RUNNING', 'gpu', 1440, 8, 32768,
            2, gtx, 'gpu201', '0-1', started=-300),
        Job('70103', 'bob', 'sweep', 'RUNNING', 'gpu', 1440, 8, 32768,
            2, gtx, 'gpu201', '2-3', started=-130),
        Job('70104', 'bob', 'finetune', 'RUNNING', 'gpu', 2880, 8, 32768,
            2, a5000, 'gpu102', '0-1', started=-40),
        Job('70130', 'bob', 'preprocess', 'RUNNING', 'small', 120, 8, 32768,
            node='cmp201', started=-15),
        Job('70120', 'alice', 'train-large', 'PENDING', 'gpu', 1440, 16, 40960,
            4, a5000, reason='Resources', start_estimate=130),
        Job('70121', 'alice', 'eval-1080', 'PENDING', 'gpusmall', 240, 2, 8192,
            1, gtx, reason='Priority'),
        # 80G is more than any GPU node has free; 73G fits on gpu101 now (ab why --fix)
        Job('70122', 'alice', 'finetune-xl', 'PENDING', 'gpu', 720, 8, 81920,
            2, a5000, reason='Resources'),
        Job('70131', 'bob', 'merge', 'PENDING', 'big', 4320, 32, 128000,
            reason='Dependency'),
    ]  # fmt: skip


def demo_nodes() -> list[dict[str, str]]:
    """The FakeSlurm nodes, loaded to match ``demo_jobs()``."""
    return [
        node_dict('gpu101', partitions=GPU_PARTS, gres_used='gpu:RTX-A5000:1(IDX:0)',
                  cpus_alloc=4, mem_alloc=16384),
        node_dict('gpu102', partitions=GPU_PARTS, gres_used='gpu:RTX-A5000:2(IDX:0-1)',
                  cpus_alloc=8, mem_alloc=32768),
        node_dict('gpu201', partitions=GPU_PARTS, gres='gpu:GTX-1080ti:4',
                  gres_used='gpu:GTX-1080ti:4(IDX:0-3)', cpus_alloc=16, mem_alloc=65536, state='ALLOCATED',
                  features='Intel,GTX-1080ti'),
        node_dict('cmp201', partitions=CPU_PARTS, gres='(null)', features='Intel',
                  cpus_alloc=8, mem_alloc=32768),
        node_dict('cmp301', partitions='amd', gres='(null)', features='AMD',
                  state='IDLE'),
    ]  # fmt: skip


# JobIDRaw|JobID|JobName|State|ExitCode|End|Reason, as `sacct --parsable2 -X` prints it
SACCT_ROWS = [
    '70110|70110|ab-dev|RUNNING|0:0|Unknown|None',
    '70120|70120|train-large|PENDING|0:0|Unknown|Resources',
    '70090|70090|prep-data|COMPLETED|0:0|2026-11-03T08:41:12|None',
    '70085|70085|train-small|FAILED|1:0|2026-11-02T23:17:40|None',
    '70080_3|70080_3|sweep|TIMEOUT|0:0|2026-11-02T18:00:05|None',
    '70077|70077|notebook|CANCELLED by 1000|0:0|2026-11-02T12:30:00|None',
    '70070|70070|eval|OUT_OF_MEMORY|0:125|2026-11-01T16:02:51|None',
    '70060|70060|ab-dev|TIMEOUT|0:0|2026-11-01T09:00:00|None',
]

RESERVATION = (
    'ReservationName=maint-nov StartTime=2026-11-10T08:00:00 '
    'EndTime=2026-11-10T18:00:00 Duration=10:00:00 Nodes=gpu101,gpu102,gpu201 '
    'NodeCnt=3 CoreCnt=48 Features=(null) PartitionName=(null) '
    'Flags=MAINT,IGNORE_JOBS,SPEC_NODES TRES=cpu=48 Users=root Groups=(null) '
    'Accounts=(null) Licenses=(null) State=INACTIVE BurstBuffer=(null) '
    'MaxStartDelay=(null)'
)

STDOUT_TEXT = """\
loading shards 0-63 from /scratch/alice/corpus
shard 16/64 done (1.2M rows)
shard 32/64 done (2.5M rows)
shard 48/64 done (3.7M rows)
shard 64/64 done (5.0M rows)
wrote /scratch/alice/corpus/clean.parquet (5.0M rows, 1.8G)
"""


class DemoSlurm(FakeSlurm):
    """FakeSlurm plus jobs: squeue, scontrol job views, sacct, sbatch and scancel."""

    def __init__(self, out_dir: Path) -> None:
        super().__init__(nodes=demo_nodes())
        self.jobs = demo_jobs()
        stdout = out_dir / 'slurm-70090.out'
        stdout.write_text(STDOUT_TEXT)
        # Finished but still known to slurmctld, as for a few minutes after the end.
        self.finished = [
            Job('70090', 'alice', 'prep-data', 'COMPLETED', 'small', 120, 4, 8192,
                node='cmp201', stdout=str(stdout)),
        ]  # fmt: skip

    def cancel(self, *job_ids: str) -> None:
        self.jobs = [job for job in self.jobs if job.id not in job_ids]

    def squeue(self, argv: list[str]) -> str:
        options = dict(itertools.pairwise(argv))
        user = options.get('-u') or next(
            (a.split('=', 1)[1] for a in argv if a.startswith('--user=')), None
        )
        partition = options.get('-p')
        fmt = next(a for a in argv if a.startswith('--format='))
        codes = [f.lstrip('%') for f in fmt.removeprefix('--format=').split('|')]
        rows = []
        for job in self.jobs:
            if user and job.user != user:
                continue
            if partition and job.partition != partition:
                continue
            if '--state=PD' in argv and job.state != 'PENDING':
                continue
            if f'--name={job.name}' not in argv and any(a.startswith('--name=') for a in argv):
                continue
            row = job.squeue()
            rows.append('|'.join(row[code] for code in codes) + '\n')
        return ''.join(rows)

    def submit(self, argv: list[str]) -> str:
        flags = dict(a.split('=', 1) for a in argv if a.startswith('--') and '=' in a)
        gres = flags.get('--gres', '')
        gpus = int(gres.rsplit(':', 1)[1]) if gres else 0
        cpus = int(flags.get('--cpus-per-task', 0)) or int(
            flags.get('--cpus-per-gpu', 1)
        ) * max(gpus, 1)
        mem = int(flags.get('--mem', '8G').rstrip('G')) * 1024
        gpu_type = gres.split(':')[1] if gres.count(':') == 2 else ''
        job = Job('70140', USER, flags['--job-name'], 'PENDING',
                  flags['--partition'], 480, cpus, mem, gpus, gpu_type,
                  reason='Priority')  # fmt: skip
        self.jobs.append(job)
        return f'{job.id}\n'

    def answer(self, argv: list[str]) -> tuple[int, str]:
        joined = ' '.join(argv)
        known = self.jobs + self.finished
        if argv[0] == 'squeue':
            return 0, self.squeue(argv)
        if argv[0] == 'sbatch':
            return 0, self.submit(argv)
        if argv[0] == 'scancel':
            self.cancel(*argv[1:])
            return 0, ''
        if argv[0] == 'sacct':
            return 0, ''.join(f'{row}\n' for row in SACCT_ROWS)
        if joined == 'scontrol --json show job':
            return 0, json.dumps({'jobs': [job.record() for job in self.jobs]})
        if joined.startswith('scontrol --json show job '):
            records = [job.record() for job in self.jobs if job.id == argv[-1]]
            return (0 if records else 1), json.dumps({'jobs': records})
        if joined == 'scontrol --oneliner --details show job':
            return 0, ''.join(f'{job.detail_line()}\n' for job in known)
        if joined.startswith('scontrol --oneliner --details show job '):
            wanted = argv[-1]
            for job in known:
                if job.id == wanted:
                    return 0, job.detail_line() + '\n'
            return 1, ''
        if joined == 'scontrol --oneliner show reservation':
            return 0, RESERVATION + '\n'
        return super().answer(argv)


def _ab_modules() -> list[Any]:
    import allegro_buddy.cli  # noqa: F401  (loads every handler module)

    return [m for n, m in sys.modules.items() if n.startswith('allegro_buddy') and m]


@contextlib.contextmanager
def demo_cluster(tmp: Path) -> Iterator[DemoSlurm]:
    """Run `ab` as alice on the demo cluster: fake Slurm, frozen clock, scratch config."""
    tmp.mkdir(parents=True, exist_ok=True)
    fake = DemoSlurm(tmp)
    env = {
        'XDG_CONFIG_HOME': str(tmp / 'config'),
        'XDG_CACHE_HOME': str(tmp / 'cache'),
        'AB_SITE_CONFIG': str(tmp / 'site' / 'config.ini'),
    }
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, env))  # restores AB_CLUSTER too
        os.environ.pop('AB_CLUSTER', None)  # pick the preset from ClusterName
        stack.enter_context(patch.object(core.subprocess, 'run', fake))
        stack.enter_context(patch.object(core, 'datetime', FrozenDatetime))
        stack.enter_context(patch.object(core, '_NODE_FACTS', None))
        for module in _ab_modules():
            if hasattr(module, 'current_user'):
                stack.enter_context(patch.object(module, 'current_user', lambda: USER))
            if hasattr(module, 'current_groups'):
                stack.enter_context(
                    patch.object(module, 'current_groups', lambda: {'users'})
                )
            if hasattr(module, 'dev_log_dir'):
                stack.enter_context(
                    patch.object(module, 'dev_log_dir', lambda: tmp / 'slurm-output')
                )
        settings.load.cache_clear()
        try:
            yield fake
        finally:
            settings.load.cache_clear()


def scrub(text: str, tmp: Path) -> str:
    """Show paths under the scratch dir as ~/..., padded so table and panel edges hold."""
    pad = ' ' * (len(str(tmp)) - 1)
    # the lost width goes into the next run of spaces (column gap, panel padding or the
    # single space before a fitted panel's edge)
    return re.sub(
        re.escape(str(tmp)) + r'(/.*?)( {2,}| (?=│)|$)',
        lambda m: f'~{m[1]}{m[2] and pad + m[2]}',
        text,
        flags=re.MULTILINE,
    )


# name, `ab` arguments, setup on the DemoSlurm before the run
SCENARIOS: list[tuple[str, list[str], Any]] = [
    ('help', ['-h'], None),
    ('queue', ['queue'], None),
    ('queue-all', ['q', '--all'], None),
    ('why', ['why'], None),
    ('why-job', ['why', '70120'], None),
    ('why-nodes', ['why', '70120', '--nodes'], None),
    ('why-fix', ['why', '70122'], None),
    ('why-fix-confirm', ['why', '70122', '--fix'], None),
    ('node', ['node', 'gpu102'], None),
    ('node-shared', ['node', 'gpu201'], None),
    ('node-cpu', ['node', 'cmp201'], None),
    ('job-history', ['job', 'history'], None),
    ('job-output', ['job', 'output', '70090'], None),
    ('dev-status', ['dev', 'status'], None),
    ('dev-start', ['dev', 'start', '--no-wait'], lambda fake: fake.cancel('70110')),
    ('dev-stop', ['dev', 'stop'], None),
    ('config-show', ['config', 'show'], None),
    ('error-unknown-job', ['why', '999999'], None),
]
FAILING = {'error-unknown-job'}
# what the user types at a prompt; the run sees a terminal
INPUTS = {'why-fix-confirm': 'n\n'}
