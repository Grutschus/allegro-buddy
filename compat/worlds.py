"""The fake clusters ("worlds") the scenarios run against, as fake_slurm state dicts.

Ported from allegro-buddy 2.7's tests: FakeSlurm and its Allegro / "elsewhere" / Lise
(bhlrn4) variants (tests/test_cluster_output.py), DemoSlurm (tests/demo_cluster.py) and
the `ab why` records and nodes (tests/slurm_records.py, tests/test_why.py).

`@TMP@` in any string is replaced by the scenario's scratch directory when the state is
written. Every world is a fresh dict, so scenarios may change it freely.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from typing import Any

NOW = '2026-11-03T10:00:00'
USER = 'alice'


def number(value: int | None) -> dict[str, Any]:
    """Slurm's JSON wrapper for optional numbers."""
    if value is None:
        return {'set': False, 'infinite': False, 'number': 0}
    return {'set': True, 'infinite': False, 'number': value}


# ---------------------------------------------------------------------------
# tests/slurm_records.py
# ---------------------------------------------------------------------------

ARRAY_JOB: dict[str, Any] = {
    # 65177_[0-11]: 4 A5000, 4 CPU and 10G per GPU, as submitted on 2026-10-06.
    'job_id': 65177,
    'array_job_id': number(65177),
    'array_task_id': number(None),
    'array_task_string': '0-11',
    'user_name': 'alice',
    'job_state': ['PENDING'],
    'state_reason': 'Resources',
    'partition': 'gpu',
    'node_count': number(1),
    'tasks': number(1),
    'cpus': number(16),
    'minimum_cpus_per_node': number(1),
    'tres_per_node': 'gres/gpu:RTX-A5000:4',
    'tres_per_job': '',
    'tres_per_task': '',
    'cpus_per_tres': 'gres/gpu:4',
    'memory_per_tres': 'gres/gpu:10240',
    'memory_per_cpu': number(None),
    'memory_per_node': number(10240),
    'tres_req_str': 'cpu=16,mem=40G,node=1,billing=16',
    'features': '',
    'excluded_nodes': '',
    'required_nodes': '',
    'resv_name': '',
    'shared': [],
    'het_job_id': number(0),
    'scheduled_nodes': 'gpu127',
    'start_time': number(1791411962),
}

PLAIN_GPU_JOB: dict[str, Any] = {
    # 65160: one GPU typed via --constraint, 4 CPU, --mem=12G, pending on Priority.
    **ARRAY_JOB,
    'job_id': 65160,
    'array_job_id': number(0),
    'array_task_string': '',
    'state_reason': 'Priority',
    'cpus': number(4),
    'tres_per_node': 'gres/gpu:1',
    'cpus_per_tres': 'gres/gpu:4',
    'memory_per_tres': '',
    'memory_per_node': number(12288),
    'tres_req_str': 'cpu=4,mem=12G,node=1,billing=4',
    'features': 'RTX-A5000',
    'scheduled_nodes': '',
    'start_time': number(0),
}

CPU_JOB: dict[str, Any] = {
    # 64267_[50-142] on big: 4 CPU, --mem=56G, no GPUs.
    **ARRAY_JOB,
    'job_id': 64267,
    'array_job_id': number(64267),
    'array_task_string': '50-142',
    'partition': 'big',
    'cpus': number(4),
    'tres_per_node': '',
    'cpus_per_tres': '',
    'memory_per_tres': '',
    'memory_per_node': number(57344),
    'tres_req_str': 'cpu=4,mem=56G,node=1,billing=4',
    'scheduled_nodes': '',
    'start_time': number(0),
}


def node_dict(
    name: str = 'gpu105',
    *,
    state: str = 'MIXED',
    partitions: str = 'gpu',
    gres: str = 'gpu:RTX-A5000:4',
    gpus_used: int = 0,
    gres_used: str | None = None,
    cpus: int = 16,
    cpus_alloc: int = 0,
    mem: int = 92000,
    mem_alloc: int = 0,
    spec_mem: int = 0,
    features: str = 'Intel,X4112,RTX-A5000',
    reservation: str = '',
) -> dict[str, str]:
    """A node as `core.load_nodes()` returns it; defaults to an empty A5000 node."""
    if gres_used is None:
        gres_used = (
            '' if gres == '(null)' else f'{gres.rsplit(":", 1)[0]}:{gpus_used}(IDX:N/A)'
        )
    return {
        'NodeName': name,
        'State': state,
        'CPUTot': str(cpus),
        'CPUAlloc': str(cpus_alloc),
        'RealMemory': str(mem),
        'AllocMem': str(mem_alloc),
        'SpecMem': str(spec_mem),
        'Gres': gres,
        'GresUsed': gres_used,
        'Partitions': partitions,
        'ActiveFeatures': features,
        'Features': features,
        'Reservation': reservation,
    }


def a5000_dict(
    name: str,
    *,
    gpus_free: int,
    cpus_free: int,
    mem_free: int,
    state: str = 'MIXED',
    gpus: int = 4,
) -> dict[str, str]:
    return node_dict(
        name,
        state=state,
        gres=f'gpu:RTX-A5000:{gpus}',
        gpus_used=gpus - gpus_free,
        cpus_alloc=16 - cpus_free,
        mem_alloc=92000 - mem_free,
    )


# ---------------------------------------------------------------------------
# tests/test_cluster_output.py: FakeSlurm
# ---------------------------------------------------------------------------

PARTITIONS = {
    # name: (MaxTime, Default)
    'gpumicro': ('01:00:00', 'NO'),
    'gpushort': ('04:00:00', 'NO'),
    'gpusmall': ('1-00:00:00', 'NO'),
    'gpu': ('2-00:00:00', 'NO'),
    'micro': ('01:00:00', 'NO'),
    'small': ('2-02:00:00', 'YES'),
    'amd': ('2-00:00:00', 'NO'),
    'big': ('7-00:00:00', 'NO'),
}
GPU_PARTS = 'gpumicro,gpushort,gpusmall,gpu'
CPU_PARTS = 'micro,small,big'


def partition_props(partitions: dict[str, tuple[str, str]]) -> list[dict[str, str]]:
    return [
        {
            'PartitionName': name,
            'AllowGroups': 'ALL',
            'AllowAccounts': 'ALL',
            'Default': default,
            'MaxTime': max_time,
            'State': 'UP',
        }
        for name, (max_time, default) in partitions.items()
    ]


def allegro_nodes() -> list[dict[str, str]]:
    return [
        node_dict('gpu101', partitions=GPU_PARTS, gpus_used=1, cpus_alloc=4),
        node_dict('gpu102', partitions=GPU_PARTS, state='IDLE'),
        node_dict(
            'gpu201',
            partitions=GPU_PARTS,
            gres='gpu:GTX-1080ti:4',
            gpus_used=4,
            cpus_alloc=16,
            state='ALLOCATED',
            features='Intel,GTX-1080ti',
        ),
        node_dict('cmp201', partitions=CPU_PARTS, gres='(null)', features='Intel'),
        node_dict('cmp301', partitions='amd', gres='(null)', features='AMD', state='IDLE'),
    ]


def plain() -> dict[str, Any]:
    """FakeSlurm: the Allegro-shaped cluster with nodes and partitions but no jobs."""
    return {
        'now': NOW,
        'user': USER,
        'cluster_name': 'allegro',
        'json_ok': True,
        'nodes': allegro_nodes(),
        'partitions': partition_props(PARTITIONS),
        'sacctmgr': 'ml-lab|ml-lab|normal\nml-lab|teaching|long,normal\n',
        'jobs': [],
        'finished': [],
        'sacct_rows': [],
        'reservations': [],
        'sbatch': {'next_id': '4242'},
        'uids': {'alice': 1000, 'bob': 1001},
        'record_base': PLAIN_GPU_JOB,
    }


OTHER_PARTITIONS = {'cpu': ('1-00:00:00', 'YES'), 'a100': ('2-00:00:00', 'NO')}


def other_nodes() -> list[dict[str, str]]:
    return [
        node_dict('n01', partitions='cpu', gres='(null)', features='amd', state='IDLE'),
        node_dict('n02', partitions='a100', gres='gpu:nvidia_a100:4', gpus_used=1, features='amd'),
    ]


def other() -> dict[str, Any]:
    """Another cluster: GPU partition not named gpu*, CPU default, no shipped preset."""
    world = plain()
    world.update(
        cluster_name='elsewhere',
        nodes=other_nodes(),
        partitions=partition_props(OTHER_PARTITIONS),
    )
    return world


def cpuonly() -> dict[str, Any]:
    world = other()
    world['nodes'] = other_nodes()[:1]
    return world


def nodefault() -> dict[str, Any]:
    world = other()
    world['partitions'] = partition_props(
        {'cpu': ('1-00:00:00', 'NO'), 'a100': ('2-00:00:00', 'NO')}
    )
    return world


LISE_PARTITIONS = {
    'cpu-clx': ('12:00:00', 'YES'),
    'cpu-clx:test': ('01:00:00', 'NO'),
    'gpu-a100': ('1-00:00:00', 'NO'),
    'gpu-a100:shared:mig': ('1-00:00:00', 'NO'),
    'gpu-a100:test': ('01:00:00', 'NO'),
    'gpu-h200': ('1-00:00:00', 'NO'),
    'gpu-pvc': ('1-00:00:00', 'NO'),
}


def lise_nodes() -> list[dict[str, str]]:
    def node(name: str, partitions: str, gres: str, cpus: int) -> dict[str, str]:
        used = re.sub(r':\d+(\(.*\))?$', ':0(IDX:N/A)', gres) if gres != '(null)' else ''
        return node_dict(
            name, partitions=partitions, gres=gres, gres_used=used, cpus=cpus, features=''
        )

    return [
        node('cpu01', 'cpu-clx', '(null)', 192),
        node('cpu02', 'cpu-clx:test', '(null)', 192),
        node('a100-01', 'gpu-a100', 'gpu:A100:4', 144),
        node('mig-01', 'gpu-a100:shared:mig', 'gpu:1g.10gb:28(S:0-1)', 144),
        node('a100-02', 'gpu-a100:test', 'gpu:A100:4', 144),
        node('h200-01', 'gpu-h200', 'gpu:H200:4', 256),
        node('pvc-01', 'gpu-pvc', 'gpu:intel:4(S:0-1)', 224),
    ]


def lise() -> dict[str, Any]:
    """Lise (ClusterName bhlrn4), from its scontrol output of 2026-11-03."""
    world = plain()
    world.update(
        cluster_name='bhlrn4',
        nodes=lise_nodes(),
        partitions=partition_props(LISE_PARTITIONS),
    )
    return world


def nojson() -> dict[str, Any]:
    """Slurm without `--json` (no data_parser plugin): the oneliner fallback."""
    world = plain()
    world['json_ok'] = False
    return world


def empty() -> dict[str, Any]:
    """Slurm answers, but knows no nodes, partitions or jobs."""
    world = plain()
    world.update(nodes=[], partitions=[], cluster_name='allegro')
    return world


def down() -> dict[str, Any]:
    """slurmctld unreachable: every scontrol / squeue / sacct call fails."""
    world = plain()
    error = 'slurm_load_partitions: Unable to contact slurm controller (connect failure)\n'
    world['fail'] = [
        {'argv': [cmd], 'exit': 1, 'stderr': error}
        for cmd in ('scontrol', 'squeue', 'sacct', 'sacctmgr', 'sbatch', 'scancel')
    ]
    return world


def noname() -> dict[str, Any]:
    """`scontrol show config` without a ClusterName line."""
    world = plain()
    world['cluster_name'] = None
    return world


def groups() -> dict[str, Any]:
    """Partitions restricted by AllowGroups / DenyGroups (BAB_TEST_GROUPS decides)."""
    world = plain()
    for part in world['partitions']:
        if part['PartitionName'] == 'big':
            part['AllowGroups'] = 'hpc,admins'
        if part['PartitionName'] == 'gpumicro':
            part['DenyGroups'] = 'students'
        if part['PartitionName'] == 'amd':
            part['AllowGroups'] = 'amd-users'
    return world


# ---------------------------------------------------------------------------
# tests/demo_cluster.py: DemoSlurm
# ---------------------------------------------------------------------------


def demo_job(
    id: str, user: str, name: str, state: str, partition: str, limit: int, cpus: int,
    mem: int, gpus: int = 0, gpu_type: str = '', node: str = '', gpu_idx: str = '',
    *, started: int = 0, reason: str = 'None', start_estimate: int | None = None,
    stdout: str = '',
) -> dict[str, Any]:  # fmt: skip
    return {
        'id': id, 'user': user, 'name': name, 'state': state, 'partition': partition,
        'limit': limit, 'cpus': cpus, 'mem': mem, 'gpus': gpus, 'gpu_type': gpu_type,
        'node': node, 'gpu_idx': gpu_idx, 'started': started, 'reason': reason,
        'start_estimate': start_estimate, 'stdout': stdout,
    }  # fmt: skip


def demo_jobs() -> list[dict[str, Any]]:
    a5000, gtx = 'RTX-A5000', 'GTX-1080ti'
    return [
        demo_job('70110', 'alice', 'ab-dev', 'RUNNING', 'gpu', 480, 4, 16384,
                 1, a5000, 'gpu101', '0', started=-85),
        demo_job('70102', 'bob', 'sweep', 'RUNNING', 'gpu', 1440, 8, 32768,
                 2, gtx, 'gpu201', '0-1', started=-300),
        demo_job('70103', 'bob', 'sweep', 'RUNNING', 'gpu', 1440, 8, 32768,
                 2, gtx, 'gpu201', '2-3', started=-130),
        demo_job('70104', 'bob', 'finetune', 'RUNNING', 'gpu', 2880, 8, 32768,
                 2, a5000, 'gpu102', '0-1', started=-40),
        demo_job('70130', 'bob', 'preprocess', 'RUNNING', 'small', 120, 8, 32768,
                 node='cmp201', started=-15),
        demo_job('70120', 'alice', 'train-large', 'PENDING', 'gpu', 1440, 16, 40960,
                 4, a5000, reason='Resources', start_estimate=130),
        demo_job('70121', 'alice', 'eval-1080', 'PENDING', 'gpusmall', 240, 2, 8192,
                 1, gtx, reason='Priority'),
        # 80G is more than any GPU node has free; 73G fits on gpu101 now (why --fix)
        demo_job('70122', 'alice', 'finetune-xl', 'PENDING', 'gpu', 720, 8, 81920,
                 2, a5000, reason='Resources'),
        demo_job('70131', 'bob', 'merge', 'PENDING', 'big', 4320, 32, 128000,
                 reason='Dependency'),
    ]  # fmt: skip


def demo_nodes() -> list[dict[str, str]]:
    return [
        node_dict('gpu101', partitions=GPU_PARTS, gres_used='gpu:RTX-A5000:1(IDX:0)',
                  cpus_alloc=4, mem_alloc=16384),
        node_dict('gpu102', partitions=GPU_PARTS, gres_used='gpu:RTX-A5000:2(IDX:0-1)',
                  cpus_alloc=8, mem_alloc=32768),
        node_dict('gpu201', partitions=GPU_PARTS, gres='gpu:GTX-1080ti:4',
                  gres_used='gpu:GTX-1080ti:4(IDX:0-3)', cpus_alloc=16, mem_alloc=65536,
                  state='ALLOCATED', features='Intel,GTX-1080ti'),
        node_dict('cmp201', partitions=CPU_PARTS, gres='(null)', features='Intel',
                  cpus_alloc=8, mem_alloc=32768),
        node_dict('cmp301', partitions='amd', gres='(null)', features='AMD', state='IDLE'),
    ]  # fmt: skip


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
DEMO_STDOUT = '@TMP@/demo/slurm-70090.out'
DEMO_FILES = {'demo/slurm-70090.out': STDOUT_TEXT}


def demo() -> dict[str, Any]:
    """DemoSlurm: FakeSlurm plus running and pending jobs, history and a reservation."""
    world = plain()
    world.update(
        nodes=demo_nodes(),
        jobs=demo_jobs(),
        finished=[
            demo_job('70090', 'alice', 'prep-data', 'COMPLETED', 'small', 120, 4, 8192,
                     node='cmp201', stdout=DEMO_STDOUT),
        ],  # fmt: skip
        sacct_rows=list(SACCT_ROWS),
        reservations=[RESERVATION],
        sbatch={'next_id': '70140', 'add': True},
        _files=dict(DEMO_FILES),
    )
    return world


def busy() -> dict[str, Any]:
    """Demo plus 24 running jobs of alice: more than USER_JOB_DETAIL_LIMIT (20)."""
    world = demo()
    for i in range(24):
        world['jobs'].append(
            demo_job(f'{71000 + i}', 'alice', f'task-{i:02d}', 'RUNNING', 'small', 600,
                     1, 1024, node='cmp201', started=-(i * 7 + 3))
        )  # fmt: skip
    return world


# ---------------------------------------------------------------------------
# tests/test_why.py: `why` against controlled records and nodes
# ---------------------------------------------------------------------------

LIVE_NODES = [
    a5000_dict('gpu105', gpus_free=2, cpus_free=10, mem_free=4960),
    a5000_dict('gpu106', gpus_free=2, cpus_free=12, mem_free=10080, state='MIXED+PLANNED'),
    a5000_dict('gpu103', gpus_free=0, cpus_free=0, mem_free=36704, state='ALLOCATED'),
    node_dict('gpu061', state='IDLE+RESERVED+MAINTENANCE', reservation='maint'),
    node_dict('cmp238', partitions='small,big', gres='(null)', cpus=40, cpus_alloc=20,
              mem=320000, mem_alloc=286720, features='Intel'),
]  # fmt: skip
WHY_PARTITIONS = [
    {'PartitionName': 'gpu'},
    {'PartitionName': 'big'},
    {'PartitionName': 'small', 'MaxMemPerCPU': '3000'},
]
UPDATED_CPU_JOB = {**CPU_JOB, 'memory_per_node': number(32768)}
CPUS_PER_TASK_JOB = {
    **CPU_JOB,
    'minimum_cpus_per_node': number(4),
    'cpus_per_task': number(4),
    'tres_per_task': 'cpu=4',
}
THREE_FREE_CPUS = node_dict(
    'cmp240', partitions='small,big', gres='(null)', cpus=48, cpus_alloc=45, mem=192000,
    features='Intel',
)  # fmt: skip
GPU110 = a5000_dict('gpu110', gpus_free=2, cpus_free=8, mem_free=20480)


def why_world(
    records: list[dict[str, Any]],
    nodes: list[dict[str, str]] | None = None,
    *,
    after: list[dict[str, Any]] | None = None,
    nodes_after: list[dict[str, str]] | None = None,
    update_exit: int = 0,
    update_stderr: str = '',
    records_filter: bool = True,
) -> dict[str, Any]:
    """`scontrol --json show job` answers `records`; `scontrol update` swaps in `after`."""
    world = plain()
    world.update(
        nodes=copy.deepcopy(LIVE_NODES if nodes is None else nodes),
        partitions=copy.deepcopy(WHY_PARTITIONS),
        records=copy.deepcopy(records),
        records_filter=records_filter,
    )
    then: dict[str, Any] = {}
    if after is not None:
        then['records'] = copy.deepcopy(after)
    if nodes_after is not None:
        then['nodes'] = copy.deepcopy(nodes_after)
    world['update'] = {'exit': update_exit, 'stderr': update_stderr, 'then': then}
    return world


WORLDS: dict[str, Callable[[], dict[str, Any]]] = {
    'plain': plain,
    'demo': demo,
    'busy': busy,
    'other': other,
    'cpuonly': cpuonly,
    'nodefault': nodefault,
    'lise': lise,
    'nojson': nojson,
    'empty': empty,
    'down': down,
    'noname': noname,
    'groups': groups,
}
