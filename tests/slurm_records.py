"""Slurm data shared by the `ab why` tests.

Job records follow `scontrol --json show job` (Slurm 24.11) as observed on the cluster on
2026-10-06; nodes follow the dicts `core.load_nodes()` returns.
"""

from __future__ import annotations

from typing import Any


def number(value: int | None) -> dict[str, Any]:
    """Slurm's JSON wrapper for optional numbers."""
    if value is None:
        return {'set': False, 'infinite': False, 'number': 0}
    return {'set': True, 'infinite': False, 'number': value}


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
    """An A5000 node with 16 CPUs and 92000 MB, described by what is still free."""
    return node_dict(
        name,
        state=state,
        gres=f'gpu:RTX-A5000:{gpus}',
        gpus_used=gpus - gpus_free,
        cpus_alloc=16 - cpus_free,
        mem_alloc=92000 - mem_free,
    )
