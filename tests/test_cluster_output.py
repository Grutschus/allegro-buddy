"""Regression guard: whole-command output on a recorded Allegro-shaped cluster.

Every Slurm call goes through ``core.subprocess.run``; ``FakeSlurm`` answers it from
canned output, so `ab info`, `ab free` and `ab dev start` run end to end. The expected
output lives in ``tests/snapshots/``; set ``UPDATE_SNAPSHOTS=1`` to rewrite it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from slurm_records import node_dict

from allegro_buddy import settings
from allegro_buddy.cli import main

SNAPSHOTS = Path(__file__).parent / 'snapshots'

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
        node_dict(
            'cmp301', partitions='amd', gres='(null)', features='AMD', state='IDLE'
        ),
    ]


def nodes_json(nodes: list[dict[str, str]]) -> str:
    """Turn ``node_dict`` records back into `scontrol --json show nodes` output."""
    return json.dumps(
        {
            'nodes': [
                {
                    'name': n['NodeName'],
                    'state': n['State'].split('+'),
                    'cpus': int(n['CPUTot']),
                    'alloc_cpus': int(n['CPUAlloc']),
                    'real_memory': int(n['RealMemory']),
                    'alloc_memory': int(n['AllocMem']),
                    'gres': '' if n['Gres'] == '(null)' else n['Gres'],
                    'gres_used': n['GresUsed'],
                    'partitions': n['Partitions'].split(','),
                    'active_features': n['ActiveFeatures'].split(','),
                    'features': n['Features'].split(','),
                    'reservation': n['Reservation'],
                    'specialized_memory': int(n['SpecMem']),
                }
                for n in nodes
            ]
        }
    )


def node_lines(nodes: list[dict[str, str]]) -> str:
    """The same nodes as `scontrol --oneliner show node` prints them."""
    return '\n'.join(
        f'NodeName={n["NodeName"]} AvailableFeatures={n["Features"]} '
        f'ActiveFeatures={n["ActiveFeatures"]} Gres={n["Gres"]} CPUAlloc={n["CPUAlloc"]} '
        f'CPUTot={n["CPUTot"]} RealMemory={n["RealMemory"]} AllocMem={n["AllocMem"]} '
        f'State={n["State"]} Partitions={n["Partitions"]} GresUsed={n["GresUsed"]}'
        for n in nodes
    )


def partition_lines(partitions: dict[str, tuple[str, str]]) -> str:
    return '\n'.join(
        f'PartitionName={name} AllowGroups=ALL AllowAccounts=ALL Default={default} '
        f'MaxTime={max_time} State=UP'
        for name, (max_time, default) in partitions.items()
    )


class FakeSlurm:
    def __init__(
        self,
        cluster_name: str = 'allegro',
        nodes: list[dict[str, str]] | None = None,
        partitions: dict[str, tuple[str, str]] | None = None,
        *,
        json_ok: bool = True,
    ) -> None:
        self.nodes = allegro_nodes() if nodes is None else nodes
        self.partitions = PARTITIONS if partitions is None else partitions
        self.cluster_name = cluster_name
        self.json_ok = json_ok
        self.calls: list[list[str]] = []
        self.output = ''

    def answer(self, argv: list[str]) -> tuple[int, str]:
        joined = ' '.join(argv)
        if joined == 'scontrol --json show nodes':
            return (0, nodes_json(self.nodes)) if self.json_ok else (1, '')
        if joined == 'scontrol --oneliner show node':
            return 0, node_lines(self.nodes)
        if joined == 'scontrol --oneliner show partition':
            return 0, partition_lines(self.partitions)
        if joined == 'scontrol show config':
            return 0, f'ClusterName             = {self.cluster_name}\n'
        if argv[0] == 'sbatch':
            return 0, '4242\n'
        if argv[:3] == ['sacctmgr', '-nP', 'show']:  # alice's associations
            return 0, 'ml-lab|ml-lab|normal\nml-lab|teaching|long,normal\n'
        if joined.startswith(
            (
                'scontrol --oneliner show reservation',
                'scontrol --oneliner --details',
                'squeue',
            )
        ):
            return 0, ''
        if joined == 'scontrol --json show job':
            return 0, '{"jobs": []}'
        return 1, ''

    def __call__(self, argv, **_kwargs):
        self.calls.append(list(argv))
        code, out = self.answer(list(argv))
        return subprocess.CompletedProcess(argv, code, stdout=out, stderr='')


@pytest.fixture
def slurm(monkeypatch):
    fake = FakeSlurm()
    monkeypatch.delenv('AB_CLUSTER')  # pick the preset from ClusterName, as on Allegro
    monkeypatch.setattr('allegro_buddy.core.subprocess.run', fake)
    for module in ('core', 'handlers.resources'):
        monkeypatch.setattr(f'allegro_buddy.{module}.current_groups', lambda: {'users'})
        monkeypatch.setattr(f'allegro_buddy.{module}.current_user', lambda: 'alice')
    return fake


def invoke(args: list[str], *, ok: bool = True) -> str:
    runner = CliRunner()
    with patch.dict(os.environ, {'COLUMNS': '160'}):
        result = runner.invoke(main, args, catch_exceptions=False)
    assert (result.exit_code == 0) == ok, result.output
    return result.output


def check_snapshot(name: str, output: str) -> None:
    path = SNAPSHOTS / f'{name}.txt'
    if os.environ.get('UPDATE_SNAPSHOTS'):
        path.parent.mkdir(exist_ok=True)
        path.write_text(output)
    assert output == path.read_text()


@pytest.mark.parametrize(
    'name,args',
    [
        ('info', ['info']),
        ('free', ['free']),
        ('free-nodes', ['free', '--nodes']),
        ('free-cpu', ['free', '--kind', 'cpu', '--nodes']),
        ('free-a5000', ['free', '-G', 'a5000', '--nodes']),
    ],
)
def test_allegro_output_unchanged(slurm, name: str, args: list[str]):
    check_snapshot(f'allegro-{name}', invoke(args))


@pytest.mark.parametrize(
    'args,expected',
    [
        ([], ['--partition=gpu', '--gres=gpu:1', '--cpus-per-gpu=2', '--mem=8G']),
        (['--gpu-type', 'a5000'], ['--partition=gpu', '--gres=gpu:RTX-A5000:1']),
        (['--gpu-type', 'gtx1080', '-g', '2'], ['--gres=gpu:GTX-1080ti:2']),
        (
            ['-p', 'small', '-g', '0', '-c', '4'],
            ['--partition=small', '--cpus-per-task=4'],
        ),
    ],
)
def test_allegro_dev_start_argv(slurm, args: list[str], expected: list[str]):
    sbatch = dev_start(slurm, args)
    for flag in expected:
        assert flag in sbatch, sbatch


def dev_start(slurm: FakeSlurm, args: list[str], *, ok: bool = True) -> list[str]:
    """Run `ab dev start --no-wait`; return the sbatch argv ([] if none was sent)."""
    with (
        patch('allegro_buddy.handlers.dev.find_dev_jobs', return_value=[]),
        patch('allegro_buddy.handlers.dev.get_job_detail', return_value=None),
        patch('allegro_buddy.handlers.dev.dev_log_dir', return_value=Path('/tmp')),
    ):
        slurm.output = invoke(['dev', 'start', '--no-wait', *args], ok=ok)
    return next((call for call in slurm.calls if call[0] == 'sbatch'), [])


# ---------------------------------------------------------------------------
# Another cluster: GPU partition not named gpu*, CPU default, no shipped preset
# ---------------------------------------------------------------------------

OTHER_PARTITIONS = {'cpu': ('1-00:00:00', 'YES'), 'a100': ('2-00:00:00', 'NO')}


def other_nodes() -> list[dict[str, str]]:
    return [
        node_dict('n01', partitions='cpu', gres='(null)', features='amd', state='IDLE'),
        node_dict(
            'n02',
            partitions='a100',
            gres='gpu:nvidia_a100:4',
            gpus_used=1,
            features='amd',
        ),
    ]


@pytest.fixture
def other(slurm):
    slurm.cluster_name = 'elsewhere'
    slurm.nodes = other_nodes()
    slurm.partitions = OTHER_PARTITIONS
    return slurm


def test_other_cluster_finds_gpu_partition_by_its_nodes(other):
    info = invoke(['info'])
    table = info.split('Resource overview', 1)[1].split('\n', 1)[1]
    gpu_cells = {line.split()[0]: line.split()[3] for line in table.splitlines()[2:] if len(line.split()) == 6}
    assert gpu_cells['a100'] == '3/4', info  # GPU column
    assert gpu_cells['cpu'] == '-', info
    free = invoke(['free'])
    assert 'a100' in free
    assert '3/4' in free


def test_other_cluster_dev_start_uses_slurm_default_partition(other):
    sbatch = dev_start(other, [])
    assert '--partition=cpu' in sbatch
    assert '--cpus-per-task=2' in sbatch
    assert not any(flag.startswith('--gres') for flag in sbatch)


def test_other_cluster_dev_start_gpu_partition_and_type(other):
    sbatch = dev_start(other, ['-p', 'a100', '--gpu-type', 'A100'])
    assert '--gres=gpu:nvidia_a100:1' in sbatch


def test_other_cluster_unknown_gpu_type_lists_real_ones(other):
    assert dev_start(other, ['-p', 'a100', '--gpu-type', 'a5000'], ok=False) == []
    assert 'this cluster has: a100' in other.output


def test_cpu_only_cluster_points_free_at_cpu(other):
    other.nodes = other_nodes()[:1]
    assert 'try `ab free --kind cpu`' in invoke(['free'], ok=False)
    assert 'n01' in invoke(['free', '--kind', 'cpu', '--nodes'])


def test_no_default_partition_asks_for_one(other):
    other.partitions = {'cpu': ('1-00:00:00', 'NO'), 'a100': ('2-00:00:00', 'NO')}
    assert dev_start(other, [], ok=False) == []
    assert 'no default partition' in other.output
    assert 'you can use: a100, cpu' in other.output


def test_slurm_without_json_falls_back_to_oneliner(slurm):
    slurm.json_ok = False
    check_snapshot('allegro-free-nodes', invoke(['free', '--nodes']))


# ---------------------------------------------------------------------------
# Layers: preset < site file < user file, and `ab config show`
# ---------------------------------------------------------------------------


def test_config_show_names_preset_and_sources(
    slurm, isolated_config, monkeypatch, tmp_path
):
    site = tmp_path / 'site.ini'
    site.write_text('[dev]\ncpus = 4\nmem = 16G\n')
    monkeypatch.setenv('AB_SITE_CONFIG', str(site))
    isolated_config.parent.mkdir(parents=True)
    isolated_config.write_text('[dev]\nmem = 32G\n')

    out = invoke(['config', 'show'])
    assert 'Preset: allegro (Slurm ClusterName is allegro)' in out
    rows = {
        line.split()[1]: line.split()[2:] for line in out.splitlines() if '] ' in line
    }
    assert rows['partition'] == ['gpu', 'preset', 'allegro']
    assert rows['cpus'] == ['4', 'site', 'file']
    assert rows['mem'] == ['32G', 'user', 'file']
    assert 'Default partition   small' in out

    sbatch = dev_start(slurm, [])
    assert '--mem=32G' in sbatch
    assert '--cpus-per-gpu=4' in sbatch


def test_ab_cluster_none_disables_preset(slurm, monkeypatch):
    monkeypatch.setenv('AB_CLUSTER', 'none')
    assert 'Preset: none (disabled by $AB_CLUSTER)' in invoke(['config', 'show'])
    assert '--partition=small' in dev_start(slurm, ['-g', '0'])


# ---------------------------------------------------------------------------
# Lise (ClusterName bhlrn4), from its `sinfo` / `scontrol` output of 2026-11-03
# ---------------------------------------------------------------------------

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
        # Real GresUsed drops the socket suffix: gpu:intel:0(IDX:N/A)
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


@pytest.fixture
def lise(slurm):
    slurm.cluster_name = 'bhlrn4'
    slurm.nodes = lise_nodes()
    slurm.partitions = LISE_PARTITIONS
    return slurm


def test_lise_dev_start_defaults(lise):
    sbatch = dev_start(lise, [])
    for flag in ('--partition=gpu-a100:test', '--time=01:00:00', '--mem=8G'):
        assert flag in sbatch
    assert '--gres=gpu:1' in sbatch
    assert '--cpus-per-gpu=8' in sbatch


def test_lise_gpu_types(lise):
    assert '--gres=gpu:H200:1' in dev_start(
        lise, ['-p', 'gpu-h200', '--gpu-type', 'h200']
    )
    header = next(line for line in invoke(['free']).splitlines() if 'Partition' in line)
    assert header.split() == ['Partition', 'A100', 'A100-MIG', 'H200', 'PVC']


def test_lise_partition_order(lise):
    rows = [
        line.split()[0]
        for line in invoke(['info']).split('Resource overview', 1)[1].split('\n', 1)[1].splitlines()[3:]  # past header, rule, `all`
        if len(line.split()) == 6 and line.split()[3] != '-'
    ]
    # A family stays together, shortest MaxTime first.
    assert rows == [
        'gpu-a100:test',
        'gpu-a100',
        'gpu-a100:shared:mig',
        'gpu-h200',
        'gpu-pvc',
    ]


def test_cluster_name_probed_once_per_host(slurm):
    invoke(['free'])
    settings.load.cache_clear()  # a new `ab` process
    invoke(['free'])
    probes = [call for call in slurm.calls if call == ['scontrol', 'show', 'config']]
    assert len(probes) == 1
    assert settings.cluster_name_cache_path().read_text() == 'allegro\n'


@pytest.mark.parametrize('name', settings.preset_names())
def test_shipped_presets_parse(name: str):
    settings.parse_layer(settings.preset_text(name), name)


@pytest.mark.parametrize(
    'limit,expected',
    [('01:00:00', '1h'), ('2-02:00:00', '2d2h'), ('7-00:00:00', '7d'), ('30', '30m'), ('UNLIMITED', 'unlimited')],
)
def test_info_time_limit_is_short(limit: str, expected: str):
    from allegro_buddy.handlers.resources import _short_limit

    assert _short_limit(limit).plain == expected


def test_inline_comments_are_not_part_of_the_value():
    layer = settings.parse_layer(
        '[dev]\npartition = gpu  # mine\ntime = 8:00:00 ; 8h\n', 't'
    )
    assert layer[('dev', 'partition')] == 'gpu'
    assert layer[('dev', 'time')] == '8:00:00'


def test_info_shows_accounts_default_first(slurm):
    info = invoke(['info'])
    assert 'ml-lab (default), teaching' in info, info
    assert 'long, normal' in info, info
    assert 'groups' not in info, info
