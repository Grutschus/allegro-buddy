"""Tests for `ab why`: the overview, the per-job breakdown and --fix.

The Slurm loaders are replaced in `allegro_buddy.handlers.why`, so rendering and the fix
flow run against controlled jobs and nodes.
"""

from __future__ import annotations

import subprocess
from typing import Any, NamedTuple
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console
from slurm_records import (
    ARRAY_JOB,
    CPU_JOB,
    PLAIN_GPU_JOB,
    a5000_dict,
    node_dict,
    number,
)

from allegro_buddy import core
from allegro_buddy.handlers import why

LIVE_NODES = [
    a5000_dict('gpu105', gpus_free=2, cpus_free=10, mem_free=4960),
    a5000_dict(
        'gpu106', gpus_free=2, cpus_free=12, mem_free=10080, state='MIXED+PLANNED'
    ),
    a5000_dict('gpu103', gpus_free=0, cpus_free=0, mem_free=36704, state='ALLOCATED'),
    node_dict('gpu061', state='IDLE+RESERVED+MAINTENANCE', reservation='maint'),
    node_dict(
        'cmp238',
        partitions='small,big',
        gres='(null)',
        cpus=40,
        cpus_alloc=20,
        mem=320000,
        mem_alloc=286720,
        features='Intel',
    ),
]
PARTITIONS = [
    {'PartitionName': 'gpu'},
    {'PartitionName': 'big'},
    {'PartitionName': 'small', 'MaxMemPerCPU': '3000'},
]


def _run_why(
    records: list[dict[str, Any]],
    nodes: list[dict[str, str]] = LIVE_NODES,
    *,
    user: str = 'alice',
    **options: Any,
) -> str:
    console = Console(record=True, width=160)
    kwargs = {
        'jobid': None,
        'show_nodes': False,
        'fix': None,
        'assume_yes': False,
        **options,
    }
    with (
        patch.object(why, 'load_job_records', return_value=records),
        patch.object(why, 'load_nodes', return_value=nodes),
        patch.object(why, 'load_partitions', return_value=PARTITIONS),
        patch.object(why, 'current_user', return_value=user),
        patch.object(core, 'CONSOLE', console),
        patch.object(why, 'CONSOLE', console),
    ):
        why.cmd_why(**kwargs)
    return console.export_text()


# ---------------------------------------------------------------------------
# ab why (no job id)
# ---------------------------------------------------------------------------


class TestOverview:
    def test_lists_own_jobs_waiting_on_resources_or_priority(self):
        records = [
            ARRAY_JOB,
            {**PLAIN_GPU_JOB, 'user_name': 'bob'},
            {**CPU_JOB, 'state_reason': 'Dependency'},
        ]
        output = _run_why(records)
        assert '65177_[0-11]' in output
        assert '65160' not in output
        assert '64267' not in output

    def test_summary_of_the_live_array_job(self):
        output = _run_why([ARRAY_JOB])
        assert '(12 tasks)' in output
        assert 'waiting for GPUs, CPUs and memory to free up · start' in output
        assert 'no single change starts it now' in output
        assert 'Resources' not in output
        assert 'biggest free slot' not in output

    def test_summary_points_at_the_fix(self):
        output = _run_why([CPU_JOB])
        assert 'starts now with --mem 56G → 32G\n  ⓘ `ab why 64267 --fix`' in output

    def test_nothing_waiting(self):
        output = _run_why([{**ARRAY_JOB, 'user_name': 'bob'}])
        assert 'None of your pending jobs' in output


# ---------------------------------------------------------------------------
# ab why JOBID
# ---------------------------------------------------------------------------


class TestDetail:
    def test_summary(self):
        output = _run_why([ARRAY_JOB], jobid='65177')
        assert '65177_[0-11]  gpu  4x A5000 · 16 CPU (4/GPU) · 40G (10G/GPU)' in output
        assert 'waiting for GPUs, CPUs and memory to free up · start' in output
        assert ') on gpu127' in output  # where Slurm plans to start it
        assert 'reservation' not in output

    def test_nodes_of_another_gpu_type_are_not_reported_unavailable(self):
        gtx = node_dict('gpu084', gres='gpu:GTX-1080ti:4', features='Intel,GTX-1080ti')
        output = _run_why([ARRAY_JOB], [*LIVE_NODES, gtx], jobid='65177', show_nodes=True)
        assert 'Not counted: 1 in reservation maint.' in output
        assert 'no matching GPU' not in output

    def test_no_matching_nodes_names_the_mismatch(self):
        gtx = node_dict('gpu084', gres='gpu:GTX-1080ti:4', features='Intel,GTX-1080ti')
        output = _run_why([ARRAY_JOB], [gtx], jobid='65177')
        assert 'no usable nodes: 1 no matching GPU' in output

    def test_short_resource_is_named(self):
        output = _run_why([CPU_JOB], jobid='64267')
        assert 'waiting for memory to free up' in output

    def test_no_fix_and_biggest_slots(self):
        output = _run_why([ARRAY_JOB], jobid='65177')
        assert 'no single change starts it now' in output
        assert 'Biggest free slots' in output
        assert 'gpu106*' in output
        assert '* held for another job' in output
        assert 'next:' not in output

    def test_fix_points_at_fix(self):
        output = _run_why([CPU_JOB], jobid='64267')
        assert 'starts now with --mem 56G → 32G' in output
        assert output.rstrip().endswith('ⓘ `ab why 64267 --fix` changes the job so it starts now')
        assert 'scontrol' not in output
        assert 'Biggest free slots' not in output

    def test_gpu_fix_spells_out_the_coupled_change(self):
        node = a5000_dict('gpu110', gpus_free=2, cpus_free=8, mem_free=20480)
        output = _run_why([ARRAY_JOB], [node], jobid='65177')
        assert 'starts now with GPUs 4 → 2 (→ 8 CPU, 20G)' in output
        assert '`ab why 65177 --fix gpus`' in output

    def test_fix_without_an_in_place_command_says_resubmit(self):
        record = {**ARRAY_JOB, 'tres_per_node': '', 'tres_per_job': 'gres/gpu:4'}
        node = a5000_dict('gpu110', gpus_free=2, cpus_free=8, mem_free=20480)
        output = _run_why([record], [node], jobid='65177')
        assert 'resubmit' in output
        assert 'next:' not in output

    def test_fits_now(self):
        node = node_dict('gpu110', state='IDLE')
        output = _run_why([PLAIN_GPU_JOB], [node], jobid='65160')
        assert 'fits now on gpu110, held for higher-priority jobs' in output
        assert 'starts now with' not in output

    def test_never_fits(self):
        record = {**CPU_JOB, 'cpus': {'set': True, 'infinite': False, 'number': 64}}
        output = _run_why([record], jobid='64267')
        assert 'never fits: max 40 CPUs/node' in output

    def test_nodes_table(self):
        output = _run_why([ARRAY_JOB], jobid='65177', show_nodes=True)
        assert 'Eligible nodes' in output
        assert '2/4' in output
        assert '10/16' in output
        assert 'free/total, red is short' in output

    def test_dependency_job_gets_a_note(self):
        output = _run_why([{**ARRAY_JOB, 'state_reason': 'Dependency'}], jobid='65177')
        assert 'Dependency first, then waiting for' in output

    def test_dependency_job_is_not_promised_a_start(self):
        output = _run_why([{**CPU_JOB, 'state_reason': 'Dependency'}], jobid='64267')
        assert 'would fit now with --mem' in output
        assert '--fix' not in output

    def test_running_job(self):
        output = _run_why([{**ARRAY_JOB, 'job_state': ['RUNNING']}], jobid='65177')
        assert '65177_[0-11] is RUNNING, not waiting.' in output

    def test_unknown_job_exits(self):
        with pytest.raises(SystemExit):
            _run_why([ARRAY_JOB], jobid='99999')


class TestOptionChecks:
    def test_fix_needs_a_job_id(self):
        with pytest.raises(SystemExit):
            _run_why([ARRAY_JOB], fix='auto')

    def test_yes_needs_fix(self):
        with pytest.raises(SystemExit):
            _run_why([ARRAY_JOB], jobid='65177', assume_yes=True)


# ---------------------------------------------------------------------------
# ab why JOBID --fix
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ab why JOBID --fix
# ---------------------------------------------------------------------------

UPDATED_CPU_JOB = {**CPU_JOB, 'memory_per_node': number(32768)}
# 64267 as it is live: -c 4, so MinCPUsNode and CPUsPerTask are 4 as well.
CPUS_PER_TASK_JOB = {
    **CPU_JOB,
    'minimum_cpus_per_node': number(4),
    'cpus_per_task': number(4),
    'tres_per_task': 'cpu=4',
}
# A big node with 3 free CPUs: a CPU cut to 3 (25%) would start the job.
THREE_FREE_CPUS = node_dict(
    'cmp240',
    partitions='small,big',
    gres='(null)',
    cpus=48,
    cpus_alloc=45,
    mem=192000,
    features='Intel',
)


class FixRun(NamedTuple):
    output: str
    scontrol: MagicMock
    exit_code: object


def _run_fix(
    before: dict[str, Any],
    after: dict[str, Any] | None = None,
    nodes: list[dict[str, str]] = LIVE_NODES,
    *,
    nodes_after: list[dict[str, str]] | None = None,
    records_after: list[dict[str, Any]] | None = None,
    fix: str = 'auto',
    assume_yes: bool = True,
    interactive: bool = True,
    answer: bool = False,
    user: str = 'alice',
    result: subprocess.CompletedProcess[str] | None = None,
) -> FixRun:
    """Run `ab why <before> --fix`; the second loads return the `*_after` data.

    `exit_code` is None when the command returned normally.
    """
    console = Console(record=True, width=160)
    scontrol = MagicMock(
        return_value=result or subprocess.CompletedProcess([], 0, stdout='', stderr='')
    )
    exit_code: object = None
    with (
        patch.object(
            why,
            'load_job_records',
            side_effect=[
                [before],
                [after or before] if records_after is None else records_after,
            ],
        ),
        patch.object(why, 'load_nodes', side_effect=[nodes, nodes_after or nodes]),
        patch.object(why, 'load_partitions', return_value=PARTITIONS),
        patch.object(why, 'current_user', return_value=user),
        patch.object(why, 'run', scontrol),
        patch.object(why, '_interactive', return_value=interactive),
        patch.object(why.click, 'confirm', return_value=answer),
        patch.object(core, 'CONSOLE', console),
        patch.object(why, 'CONSOLE', console),
    ):
        try:
            why.cmd_why(
                jobid=str(before['job_id']),
                show_nodes=False,
                fix=fix,
                assume_yes=assume_yes,
            )
        except SystemExit as exc:
            exit_code = exc.code
    return FixRun(console.export_text(), scontrol, exit_code)


class TestFix:
    def test_yes_applies_the_fix_and_verifies_it(self):
        run = _run_fix(CPU_JOB, UPDATED_CPU_JOB)
        run.scontrol.assert_called_once_with(
            ['scontrol', 'update', 'JobId=64267', 'MinMemoryNode=32768'], check=False
        )
        assert run.exit_code is None
        assert '--mem 56G → 32G starts 64267_[50-142] now' in run.output
        assert '$ scontrol update JobId=64267 MinMemoryNode=32768' in run.output
        assert 'applies to all 93 pending tasks' in run.output
        assert (
            'Updated; 64267_[50-142] now asks for 4 CPU · 32G and fits on 1 node.'
            in run.output
        )

    def test_held_job_is_not_shrunk(self):
        run = _run_fix({**CPU_JOB, 'state_reason': 'JobHeldUser'})
        run.scontrol.assert_not_called()
        assert run.exit_code == 1

    def test_confirmed_prompt_applies_the_fix(self):
        run = _run_fix(CPU_JOB, UPDATED_CPU_JOB, assume_yes=False, answer=True)
        run.scontrol.assert_called_once()

    def test_declined_prompt_leaves_the_job_alone(self):
        run = _run_fix(CPU_JOB, assume_yes=False, answer=False)
        run.scontrol.assert_not_called()
        assert 'Left unchanged.' in run.output


class TestFixRefusals:
    """Every refusal exits non-zero and never runs `scontrol update`."""

    @staticmethod
    def _refused(run: FixRun) -> None:
        assert run.exit_code not in (None, 0)
        run.scontrol.assert_not_called()

    def test_no_terminal_and_no_yes(self):
        self._refused(_run_fix(CPU_JOB, assume_yes=False, interactive=False))

    def test_other_users_job(self, capsys: pytest.CaptureFixture[str]):
        self._refused(_run_fix(CPU_JOB, user='bob'))
        assert 'only changes your own jobs' in capsys.readouterr().err

    def test_multi_node_job(self):
        self._refused(_run_fix({**CPU_JOB, 'node_count': number(2), 'cpus': number(8)}))

    def test_heterogeneous_job(self):
        self._refused(_run_fix({**CPU_JOB, 'het_job_id': number(64267)}))

    def test_only_a_gpu_fix_points_at_fix_gpus(self, capsys: pytest.CaptureFixture[str]):
        node = a5000_dict('gpu110', gpus_free=2, cpus_free=8, mem_free=20480)
        self._refused(_run_fix(ARRAY_JOB, nodes=[node]))
        assert '--fix gpus' in capsys.readouterr().err

    def test_requested_knob_without_a_fix(self):
        self._refused(_run_fix(CPU_JOB, fix='cpus'))

    def test_gpu_fix_without_in_place_command(self, capsys: pytest.CaptureFixture[str]):
        record = {**ARRAY_JOB, 'tres_per_node': '', 'tres_per_job': 'gres/gpu:4'}
        node = a5000_dict('gpu110', gpus_free=2, cpus_free=8, mem_free=20480)
        self._refused(_run_fix(record, nodes=[node], fix='gpus'))
        assert 'resubmit' in capsys.readouterr().err

    def test_auto_with_only_advice_fixes(self, capsys: pytest.CaptureFixture[str]):
        self._refused(_run_fix(CPUS_PER_TASK_JOB, nodes=[THREE_FREE_CPUS]))
        assert 'resubmit' in capsys.readouterr().err

    def test_already_fitting_job_is_left_alone(self):
        run = _run_fix(PLAIN_GPU_JOB, nodes=[node_dict('gpu110', state='IDLE')])
        run.scontrol.assert_not_called()
        assert 'nothing to change' in run.output


class TestFixChoice:
    def test_auto_skips_a_cpu_fix_that_has_no_command(self):
        # The CPU cut (4 -> 3) gives up less than the memory cut (56G -> 32G), but
        # only the memory change can be made in place.
        nodes = [*LIVE_NODES, THREE_FREE_CPUS]
        after = {**CPUS_PER_TASK_JOB, 'memory_per_node': number(32768)}
        run = _run_fix(CPUS_PER_TASK_JOB, after, nodes)
        assert run.scontrol.call_args.args[0][-1] == 'MinMemoryNode=32768'

    def test_explicit_gpu_fix_rescales_the_job(self):
        node = a5000_dict('gpu110', gpus_free=2, cpus_free=8, mem_free=20480)
        after = {**ARRAY_JOB, 'tres_per_node': 'gres/gpu:RTX-A5000:2', 'cpus': number(8)}
        run = _run_fix(ARRAY_JOB, after, [node], fix='gpus')
        assert run.scontrol.call_args.args[0][-1] == 'TresPerNode=gres/gpu:RTX-A5000:2'
        assert 'Updated; 65177_[0-11] now asks for' in run.output


class TestFixVerification:
    def test_failed_update_shows_slurm_and_exits(
        self, capsys: pytest.CaptureFixture[str]
    ):
        failed = subprocess.CompletedProcess([], 1, stdout='', stderr='Access denied')
        run = _run_fix(CPU_JOB, result=failed)
        assert run.exit_code == 1
        err = capsys.readouterr().err
        assert 'warning: scontrol: Access denied' in err
        assert 'Slurm now reports 4 CPU · 56G' in err

    def test_partial_array_update_is_verified_not_fatal(
        self, capsys: pytest.CaptureFixture[str]
    ):
        # Running tasks of an array refuse the update while the pending ones take it.
        partial = subprocess.CompletedProcess(
            [], 1, stdout='', stderr='64267_[0-49]: Job is no longer pending execution'
        )
        run = _run_fix(CPU_JOB, UPDATED_CPU_JOB, result=partial)
        assert run.exit_code is None
        assert 'no longer pending execution' in capsys.readouterr().err
        assert 'Updated; 64267_[50-142] now asks for' in run.output

    def test_mismatch_after_the_update_exits(self, capsys: pytest.CaptureFixture[str]):
        run = _run_fix(CPU_JOB, CPU_JOB)
        assert run.exit_code == 1
        assert 'Slurm now reports 4 CPU · 56G' in capsys.readouterr().err

    def test_cluster_changed_after_the_update(self, capsys: pytest.CaptureFixture[str]):
        full = node_dict(
            'cmp238', partitions='small,big', gres='(null)', cpus=40, cpus_alloc=40
        )
        _run_fix(CPU_JOB, UPDATED_CPU_JOB, nodes_after=[full])
        assert 'no longer fits' in capsys.readouterr().err

    def test_job_gone_from_scontrol_after_the_update(self):
        run = _run_fix(CPU_JOB, PLAIN_GPU_JOB)
        assert run.exit_code is None
        assert 'no longer listed' in run.output

    def test_scontrol_failing_after_the_update_exits(
        self, capsys: pytest.CaptureFixture[str]
    ):
        run = _run_fix(CPU_JOB, records_after=[])
        assert run.exit_code == 1
        assert 'could not re-read the job' in capsys.readouterr().err
