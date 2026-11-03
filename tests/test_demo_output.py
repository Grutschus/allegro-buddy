"""Whole-command snapshots on the busy demo cluster (see demo_cluster.py).

Set ``UPDATE_SNAPSHOTS=1`` to rewrite tests/snapshots/allegro-<name>.txt.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from demo_cluster import FAILING, INPUTS, SCENARIOS, demo_cluster, scrub
from test_cluster_output import check_snapshot

from allegro_buddy.cli import main
from allegro_buddy.handlers import why


def invoke(args: list[str], *, ok: bool, input: str | None = None) -> str:
    with (
        patch.dict(os.environ, {'COLUMNS': '160'}),
        patch.object(why, '_interactive', lambda: input is not None),
    ):
        result = CliRunner().invoke(
            main, args, prog_name='ab', input=input, catch_exceptions=False
        )
    assert (result.exit_code == 0) == ok, result.output
    return result.output  # stdout and stderr, in order


@pytest.mark.parametrize(
    'name,args,setup', SCENARIOS, ids=[name for name, _, _ in SCENARIOS]
)
def test_demo_output_unchanged(tmp_path, name, args, setup):
    with demo_cluster(tmp_path / 'demo') as fake:
        if setup:
            setup(fake)
        output = invoke(args, ok=name not in FAILING, input=INPUTS.get(name))
    check_snapshot(f'allegro-{name}', scrub(output, tmp_path / 'demo'))


def _node_gpu102(tmp_path, **node_changes) -> str:
    with demo_cluster(tmp_path / 'demo') as fake:
        fake.jobs = []
        for node in fake.nodes:
            if node['NodeName'] == 'gpu102':
                node.update(node_changes)
        return invoke(['node', 'gpu102'], ok=True)


def test_node_drained_node_is_not_free(tmp_path):
    output = _node_gpu102(tmp_path, State='IDLE+DRAIN')
    assert 'IDLE+DRAIN  idle 2/4' in output.splitlines()[0]
    assert ' free' not in output


def test_node_counts_used_gpus_without_indices(tmp_path):
    output = _node_gpu102(tmp_path, GresUsed='gpu:RTX-A5000:2(IDX:N/A)')
    assert 'free 2/4' in output
    assert '2 GPUs in use, owner unknown' in output


def test_node_lists_each_jobs_share_of_a_shared_node(tmp_path):
    with demo_cluster(tmp_path / 'demo'):
        output = invoke(['node', 'gpu201'], ok=True)
    rows = [line.split() for line in output.splitlines() if line.startswith('701')]
    # JobID User Name GPUs CPU Mem Left
    assert [row[:6] for row in rows] == [
        ['70102', 'bob', 'sweep', '0,1', '8', '32G'],
        ['70103', 'bob', 'sweep', '2,3', '8', '32G'],
    ]
    assert 'free GPUs' not in output


def test_node_shows_only_this_nodes_share_of_a_multi_node_job(tmp_path, monkeypatch):
    with demo_cluster(tmp_path / 'demo') as fake:
        job = next(j for j in fake.jobs if j.id == '70104')
        job.node = 'gpu[101-102]'
        line = job.detail_line()
        output_line = line.replace(
            'Nodes=gpu[101-102] CPU_IDs=0-7 Mem=32768 GRES=gpu:RTX-A5000:2(IDX:0-1)',
            'Nodes=gpu101 CPU_IDs=0-1 Mem=8192 GRES=gpu:RTX-A5000:1(IDX:1) '
            'Nodes=gpu102 CPU_IDs=0-5 Mem=24576 GRES=gpu:RTX-A5000:1(IDX:3)',
        )
        assert output_line != line
        monkeypatch.setattr(job, 'detail_line', lambda: output_line)
        output = invoke(['node', 'gpu102'], ok=True)
    row = next(line.split() for line in output.splitlines() if line.startswith('70104'))
    assert row[3:6] == ['3', '6', '24G']


def test_free_counts_idle_gpus_on_a_full_node_before_the_total(tmp_path):
    with demo_cluster(tmp_path / 'demo') as fake:
        for node in fake.nodes:
            if node['NodeName'] == 'gpu102':
                node.update(CPUAlloc=node['CPUTot'], State='ALLOCATED')
        output = invoke(['free'], ok=True)
    assert 'all         3+2/8' in output
    assert '+n idle, but on full or drained nodes' in output
