"""Tests for fit.py: pending-job requests, node capacity and the diagnosis.

Builders wrap the shared Slurm data in `slurm_records`.
"""

from __future__ import annotations

from typing import Any

import pytest
from slurm_records import ARRAY_JOB, CPU_JOB, PLAIN_GPU_JOB, a5000_dict, node_dict
from slurm_records import number as _n

from allegro_buddy.fit import (
    SKIP_DOWN,
    SKIP_EXCLUDED,
    SKIP_FEATURE,
    SKIP_GPU,
    SKIP_NOT_REQUESTED,
    SKIP_OUTSIDE_RESERVATION,
    Amount,
    Dim,
    JobRequest,
    NodeCapacity,
    Slot,
    diagnose,
    expand_hostlist,
    find_record,
    format_mem,
    mem_per_cpu_limits,
    mem_to_mb,
    queue_hint,
    round_down_mb,
    skip_reason,
    skip_summary,
)

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _record(base: dict[str, Any] = ARRAY_JOB, **overrides: object) -> dict[str, Any]:
    return {**base, **overrides}


def _request(base: dict[str, Any] = ARRAY_JOB, **overrides: object) -> JobRequest:
    return JobRequest.from_record(_record(base, **overrides))


def _node(name: str = 'gpu105', **overrides: Any) -> NodeCapacity:
    return NodeCapacity.from_node(node_dict(name, **overrides))


def _cpu_node(name: str = 'cmp221', **overrides: Any) -> NodeCapacity:
    defaults: dict[str, Any] = {
        'partitions': 'small,big',
        'gres': '(null)',
        'cpus': 48,
        'mem': 192000,
        'features': 'Intel',
    }
    return _node(name, **{**defaults, **overrides})


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    @pytest.mark.parametrize(
        ('token', 'mb'),
        [('40G', 40960), ('4096M', 4096), ('1.5G', 1536), ('2T', 2097152), ('512K', 1)],
    )
    def test_mem_to_mb(self, token: str, mb: int):
        assert mem_to_mb(token) == mb

    @pytest.mark.parametrize(
        ('mb', 'text'), [(40960, '40G'), (1536, '1536M'), (512, '512M')]
    )
    def test_format_mem_is_exact(self, mb: int, text: str):
        assert format_mem(mb) == text

    @pytest.mark.parametrize(
        ('mb', 'rounded'), [(10080, 9216), (13312, 13312), (800, 800)]
    )
    def test_round_down_mb_never_rounds_up(self, mb: int, rounded: int):
        assert round_down_mb(mb) == rounded

    def test_expand_hostlist(self):
        assert expand_hostlist('gpu[101-103,105],cmp001') == {
            'gpu101',
            'gpu102',
            'gpu103',
            'gpu105',
            'cmp001',
        }

    def test_expand_hostlist_keeps_zero_padding(self):
        assert expand_hostlist('gpu[060-061]') == {'gpu060', 'gpu061'}

    def test_expand_empty_hostlist(self):
        assert expand_hostlist('') == frozenset()

    def test_mem_per_cpu_limits(self):
        limits = mem_per_cpu_limits(
            [
                {'PartitionName': 'small', 'MaxMemPerCPU': '3000'},
                {'PartitionName': 'gpu', 'MaxMemPerCPU': '9223372036854775807'},
                {'PartitionName': 'big', 'MaxMemPerNode': 'UNLIMITED'},
            ]
        )
        assert limits == {'small': 3000, 'gpu': None, 'big': None}


# ---------------------------------------------------------------------------
# JobRequest.from_record
# ---------------------------------------------------------------------------


class TestRequestFromRecord:
    def test_per_gpu_job(self):
        request = _request()
        assert (request.gpus, request.gpu_type, request.gpu_kind) == (
            4,
            'RTX-A5000',
            'rtx_a5000',
        )
        assert (request.cpus, request.cpus_per_gpu) == (16, 4)
        assert (request.mem_mode, request.mem_value) == ('gpu', 10240)
        assert request.amount == Amount(4, 16, 40960)

    def test_array_ids(self):
        request = _request()
        assert request.job_id == '65177'
        assert request.display_id == '65177_[0-11]'
        assert request.update_id == '65177'
        assert request.pending_tasks == 12

    def test_split_array_task_ids(self):
        request = _request(
            job_id=64268,
            array_job_id=_n(64267),
            array_task_id=_n(3),
            array_task_string='',
        )
        assert request.display_id == request.update_id == '64267_3'
        assert request.pending_tasks == 1

    def test_plain_job_ids(self):
        request = _request(PLAIN_GPU_JOB)
        assert request.display_id == request.update_id == '65160'

    def test_gpu_type_from_feature_constraint(self):
        request = _request(PLAIN_GPU_JOB)
        assert request.gpu_type is None
        assert request.gpu_kind == 'rtx_a5000'
        assert (request.mem_mode, request.mem_value) == ('node', 12288)

    def test_stale_tres_req_str_is_ignored_for_mem_per_cpu(self):
        # NumCPUs 4 -> 2 on a --mem-per-cpu=2G job left tres_req_str at mem=8G.
        request = _request(
            CPU_JOB,
            cpus=_n(2),
            memory_per_node=_n(None),
            memory_per_cpu=_n(2048),
            tres_req_str='cpu=2,mem=8G,node=1,billing=2',
        )
        assert request.mem_mode == 'cpu'
        assert request.amount == Amount(0, 2, 4096)

    def test_cpu_only_job(self):
        request = _request(CPU_JOB)
        assert (request.gpus, request.gpu_kind) == (0, None)
        assert request.amount == Amount(0, 4, 57344)

    def test_memory_falls_back_to_tres_req_str(self):
        request = _request(CPU_JOB, memory_per_node=_n(None))
        assert request.amount.mem == 57344

    def test_gpus_per_job(self):
        request = _request(tres_per_node='', tres_per_job='gres/gpu:2', cpus=_n(8))
        assert request.gpus == 2
        assert request.gpus_per_job

    def test_exclusive_and_het(self):
        assert _request(shared=['none']).exclusive
        assert not _request().exclusive
        assert _request(het_job_id=_n(77)).het
        assert not _request().het

    def test_partitions_reason_and_plan(self):
        request = _request(partition='gpu,gpushort')
        assert request.partitions == ('gpu', 'gpushort')
        assert request.reason == 'Resources'
        assert request.state == 'PENDING'
        assert (request.planned_nodes, request.planned_start) == ('gpu127', 1791411962)
        assert _request(PLAIN_GPU_JOB).planned_start is None

    def test_reservation_and_node_lists(self):
        request = _request(
            resv_name='lab',
            excluded_nodes='gpu[101-102]',
            required_nodes='gpu105',
        )
        assert request.reservation == 'lab'
        assert request.excluded == {'gpu101', 'gpu102'}
        assert request.required == {'gpu105'}

    @pytest.mark.parametrize(
        ('spec', 'parsed'),
        [
            ('', ()),
            ('Intel&RTX-A5000', (frozenset({'Intel', 'RTX-A5000'}),)),
            (
                'RTX-A5000|GTX-1080ti',
                (frozenset({'RTX-A5000'}), frozenset({'GTX-1080ti'})),
            ),
            ('[RTX-A5000|GTX-1080ti]*2', None),
            ('a&b|c', None),
        ],
    )
    def test_feature_expressions(self, spec: str, parsed: object):
        assert _request(features=spec).features == parsed

    def test_or_constraint_does_not_pin_a_gpu_type(self):
        request = _request(PLAIN_GPU_JOB, features='RTX-A5000|GTX-1080ti')
        assert request.gpu_kind is None


# ---------------------------------------------------------------------------
# Knobs and update commands
# ---------------------------------------------------------------------------


class TestKnobs:
    def test_fewer_gpus_rescale_cpus_and_memory(self):
        assert _request().with_knob('gpus', 2).amount == Amount(2, 8, 20480)

    def test_cpus_knob_is_per_gpu_when_cpus_per_gpu_is_set(self):
        request = _request()
        assert request.knob_value('cpus') == 4
        assert request.with_knob('cpus', 3).amount == Amount(4, 12, 40960)

    def test_cpus_knob_rescales_mem_per_cpu(self):
        request = _request(CPU_JOB, memory_per_node=_n(None), memory_per_cpu=_n(2048))
        assert request.with_knob('cpus', 2).amount == Amount(0, 2, 4096)

    def test_mem_knob_uses_the_submitted_unit(self):
        assert _request().with_knob('mem', 2048).amount == Amount(4, 16, 8192)
        assert _request(PLAIN_GPU_JOB).with_knob('mem', 9216).amount.mem == 9216

    def test_knob_flags(self):
        per_gpu = _request()
        assert [per_gpu.knob_flag(k) for k in ('mem', 'cpus', 'gpus')] == [
            '--mem-per-gpu',
            '--cpus-per-gpu',
            'GPUs',
        ]
        plain = _request(PLAIN_GPU_JOB, cpus_per_tres='')
        assert [plain.knob_flag(k) for k in ('mem', 'cpus')] == ['--mem', 'CPUs']
        per_cpu = _request(CPU_JOB, memory_per_node=_n(None), memory_per_cpu=_n(2048))
        assert per_cpu.knob_flag('mem') == '--mem-per-cpu'


class TestUpdateCommand:
    @pytest.mark.parametrize(
        ('record', 'knob', 'value', 'field'),
        [
            (ARRAY_JOB, 'mem', 2048, 'MemPerTres=gres/gpu:2048'),
            (ARRAY_JOB, 'cpus', 3, 'CpusPerTres=gres/gpu:3'),
            (ARRAY_JOB, 'gpus', 2, 'TresPerNode=gres/gpu:RTX-A5000:2'),
            (PLAIN_GPU_JOB, 'mem', 9216, 'MinMemoryNode=9216'),
            (
                {**CPU_JOB, 'memory_per_node': _n(None), 'memory_per_cpu': _n(2048)},
                'mem',
                1024,
                'MinMemoryCPU=1024',
            ),
        ],
    )
    def test_field_matches_how_the_job_was_submitted(
        self, record: dict[str, Any], knob: Dim, value: int, field: str
    ):
        command = JobRequest.from_record(record).update_command(knob, value)
        assert command is not None
        assert command[:2] == ['scontrol', 'update']
        assert command[3] == field

    def test_array_job_is_updated_through_its_array_id(self):
        command = _request().update_command('mem', 2048)
        assert command is not None
        assert command[2] == 'JobId=65177'

    def test_other_gres_survive_a_gpu_change(self):
        request = _request(tres_per_node='gres/gpu:RTX-A5000:4,gres/tmp:10G')
        command = request.update_command('gpus', 2)
        assert command is not None
        assert command[3] == 'TresPerNode=gres/gpu:RTX-A5000:2,gres/tmp:10G'

    def test_jobs_with_gpus_per_job_get_no_gpu_command(self):
        request = _request(tres_per_node='', tres_per_job='gres/gpu:4')
        assert request.update_command('gpus', 2) is None

    @pytest.mark.parametrize(
        'record',
        [
            # -c 4: NumCPUs leaves MinCPUsNode and CPUsPerTask at 4, and CPUsPerTask
            # leaves NumCPUs at 4 (held probes 65192, 65241, 65242).
            {
                **CPU_JOB,
                'minimum_cpus_per_node': _n(4),
                'cpus_per_task': _n(4),
                'tres_per_task': 'cpu=4',
            },
            {**PLAIN_GPU_JOB, 'cpus_per_tres': '', 'node_count': _n(2), 'cpus': _n(8)},
        ],
        ids=['cpus-per-task', 'plain'],
    )
    def test_cpu_changes_without_cpus_per_gpu_have_no_command(
        self, record: dict[str, Any]
    ):
        assert JobRequest.from_record(record).update_command('cpus', 2) is None


class TestCpuFloor:
    def test_cpus_per_gpu_raises_a_lower_cpu_count(self):
        # 64665: cpus 2 with 4 CPUs per GPU; its running twin was allocated 4.
        request = _request(PLAIN_GPU_JOB, cpus=_n(2), minimum_cpus_per_node=_n(2))
        assert request.amount.cpus == 4

    def test_fewer_gpus_keep_the_minimum_cpus_per_node(self):
        request = _request(
            cpus_per_tres='gres/gpu:1', cpus=_n(4), minimum_cpus_per_node=_n(4)
        )
        assert request.with_knob('gpus', 2).amount.cpus == 4

    def test_fewer_cpus_per_gpu_keep_the_minimum_cpus_per_node(self):
        request = _request(minimum_cpus_per_node=_n(12))
        assert request.with_knob('cpus', 2).amount.cpus == 12


# ---------------------------------------------------------------------------
# find_record
# ---------------------------------------------------------------------------


SPLIT_TASK = {
    # 64267_3 already split off the pending array record and running.
    **CPU_JOB,
    'job_id': 64268,
    'array_task_id': _n(3),
    'array_task_string': '',
    'job_state': ['RUNNING'],
}
RECORDS = [PLAIN_GPU_JOB, ARRAY_JOB, SPLIT_TASK, CPU_JOB]


class TestFindRecord:
    @pytest.mark.parametrize('jobid', ['65177', '65177_[0-11]', '65177_3', ' 65177 '])
    def test_array_job_by_any_spelling(self, jobid: str):
        assert find_record(RECORDS, jobid) is ARRAY_JOB

    def test_split_task_by_its_task_id(self):
        assert find_record(RECORDS, '64267_3') is SPLIT_TASK

    def test_task_still_inside_the_pending_record(self):
        assert find_record(RECORDS, '64267_60') is CPU_JOB

    def test_task_outside_every_record(self):
        assert find_record(RECORDS, '64267_999') is None

    def test_plain_job(self):
        assert find_record(RECORDS, '65160') is PLAIN_GPU_JOB

    def test_unknown_job(self):
        assert find_record(RECORDS, '99999') is None


# ---------------------------------------------------------------------------
# NodeCapacity.from_node
# ---------------------------------------------------------------------------


class TestNodeCapacity:
    def test_free_resources(self):
        node = _node(gpus_used=3, cpus_alloc=6, mem_alloc=87040)
        assert (node.cpus_free, node.mem_free) == (10, 4960)
        assert node.gpus('rtx_a5000', free=True) == 1
        assert node.gpus(None, free=False) == 4
        assert node.gpus('gtx_1080ti', free=False) == 0

    def test_specialized_memory_is_not_schedulable(self):
        node = _node(spec_mem=2048)
        assert (node.mem_total, node.mem_free) == (89952, 89952)

    def test_untyped_gres_used_counts_against_the_only_type(self):
        node = _node(gres_used='gpu:2')
        assert node.gpus('rtx_a5000', free=True) == 2

    def test_planned_flag(self):
        assert _node(state='MIXED+PLANNED').planned
        assert not _node().planned

    def test_cpu_node_has_no_gpus(self):
        assert _cpu_node().gpus(None, free=False) == 0


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def _a5000(name: str, **free: Any) -> NodeCapacity:
    return NodeCapacity.from_node(a5000_dict(name, **free))


class TestEligibility:
    def test_usable_node(self):
        assert skip_reason(_request(), _node()) is None

    def test_reserved_node(self):
        node = _node(state='IDLE+RESERVED+MAINTENANCE', reservation='maint')
        assert skip_reason(_request(), node) == 'reservation maint'

    def test_down_node(self):
        node = _node(state='DOWN+DRAIN+NOT_RESPONDING')
        assert skip_reason(_request(), node) == SKIP_DOWN

    def test_wrong_gpu_type(self):
        node = _node(gres='gpu:GTX-1080ti:4', features='Intel,GTX-1080ti')
        assert skip_reason(_request(), node) == SKIP_GPU

    def test_cpu_node_for_a_gpu_job(self):
        node = _cpu_node(partitions='big')
        assert skip_reason(_request(partition='gpu,big'), node) == SKIP_GPU

    def test_missing_feature(self):
        request = _request(PLAIN_GPU_JOB, features='Intel&X4112')
        assert skip_reason(request, _node(features='Intel,RTX-A5000')) == SKIP_FEATURE
        assert skip_reason(request, _node()) is None

    def test_unevaluated_feature_expression_is_ignored(self):
        request = _request(PLAIN_GPU_JOB, features='[Intel|AMD]*2')
        assert skip_reason(request, _node(features='')) is None

    def test_excluded_and_required_nodes(self):
        assert skip_reason(_request(excluded_nodes='gpu105'), _node()) == SKIP_EXCLUDED
        assert (
            skip_reason(_request(required_nodes='gpu106'), _node()) == SKIP_NOT_REQUESTED
        )

    def test_job_in_a_reservation_uses_only_its_nodes(self):
        request = _request(resv_name='lab')
        assert skip_reason(request, _node()) == SKIP_OUTSIDE_RESERVATION
        node = _node(state='IDLE+RESERVED+MAINTENANCE', reservation='lab')
        assert skip_reason(request, node) is None

    def test_wrong_kind_of_node_is_skipped_but_not_unavailable(self):
        gtx = _node('gpu084', gres='gpu:GTX-1080ti:4', features='Intel,GTX-1080ti')
        diagnosis = diagnose(_request(), [gtx, _node('gpu061', reservation='maint')])
        assert dict(diagnosis.skipped) == {SKIP_GPU: 1, 'reservation maint': 1}
        assert diagnosis.unavailable == (('reservation maint', 1),)

    def test_other_partitions_are_neither_rows_nor_skipped(self):
        diagnosis = diagnose(_request(), [_node(), _cpu_node()])
        assert [row.node.name for row in diagnosis.rows] == ['gpu105']
        assert diagnosis.skipped == ()

    def test_skipped_nodes_are_counted_by_reason(self):
        nodes = [
            _node('gpu061', reservation='maint'),
            _node('gpu064', reservation='maint'),
            _node('gpu067', state='DOWN'),
        ]
        diagnosis = diagnose(_request(), nodes)
        assert diagnosis.skipped == (('reservation maint', 2), (SKIP_DOWN, 1))
        assert diagnosis.unavailable == diagnosis.skipped
        assert skip_summary(diagnosis.skipped, short=True) == '2 reserved, 1 down'
        assert skip_summary(diagnosis.skipped, short=False) == (
            '2 in reservation maint, 1 down or drained'
        )


# ---------------------------------------------------------------------------
# Diagnosis
# ---------------------------------------------------------------------------

# Free resources on three A5000 nodes on 2026-10-06 (GPU, CPU, MB).
LIVE_A5000 = [
    _a5000('gpu105', gpus_free=2, cpus_free=10, mem_free=4960),
    _a5000('gpu106', gpus_free=2, cpus_free=12, mem_free=10080, state='MIXED+PLANNED'),
    _a5000('gpu103', gpus_free=0, cpus_free=0, mem_free=36704, state='ALLOCATED'),
]


class TestFitsNow:
    def test_idle_node_fits(self):
        diagnosis = diagnose(_request(), [_node('gpu110', state='IDLE')])
        assert diagnosis.fits == ('gpu110',)
        assert diagnosis.fits_now
        assert diagnosis.fixes == ()
        assert queue_hint(diagnosis) == 'fits now on gpu110'

    def test_hint_counts_further_nodes(self):
        nodes = [_node(f'gpu11{i}', state='IDLE') for i in range(3)]
        assert queue_hint(diagnose(_request(), nodes)) == 'fits now on gpu110 +2'

    def test_priority_job_that_fits_is_held(self):
        diagnosis = diagnose(_request(PLAIN_GPU_JOB), [_node(state='IDLE')])
        assert queue_hint(diagnosis) == 'fits now · held for higher prio'

    def test_multi_node_job_needs_enough_fitting_nodes(self):
        request = _request(PLAIN_GPU_JOB, node_count=_n(2), cpus=_n(8))
        full = _a5000('gpu111', gpus_free=0, cpus_free=16, mem_free=92000)
        assert not diagnose(request, [_node('gpu110', state='IDLE'), full]).fits_now
        idle = [_node('gpu110', state='IDLE'), _node('gpu111', state='IDLE')]
        assert diagnose(request, idle).fits_now

    def test_exclusive_job_needs_a_node_big_enough(self):
        request = _request(CPU_JOB, shared=['none'], cpus=_n(56))
        small_idle = _cpu_node('cmp201', partitions='big', cpus=16, mem=126000)
        diagnosis = diagnose(request, [small_idle])
        assert not diagnosis.fits_now
        assert diagnosis.never_fits

    def test_exclusive_job_needs_an_idle_node(self):
        request = _request(PLAIN_GPU_JOB, shared=['none'])
        busy = _a5000('gpu105', gpus_free=3, cpus_free=12, mem_free=80000)
        assert not diagnose(request, [busy]).fits_now
        assert diagnose(request, [busy]).fixes == ()
        assert diagnose(request, [_node('gpu110', state='IDLE')]).fits_now


class TestShortfall:
    def test_counts_and_best_free_for_the_live_array_job(self):
        diagnosis = diagnose(_request(), LIVE_A5000)
        assert [diagnosis.short_count(dim) for dim in ('gpus', 'cpus', 'mem')] == [
            3,
            3,
            3,
        ]
        assert [diagnosis.best_free(dim) for dim in ('gpus', 'cpus', 'mem')] == [
            2,
            12,
            36704,
        ]
        assert diagnosis.bottleneck == 'gpus'
        assert diagnosis.fixes == ()
        assert queue_hint(diagnosis) == 'GPU-bound · max 2/4 free'

    def test_mem_bound_hint(self):
        nodes = [
            _a5000('gpu105', gpus_free=2, cpus_free=16, mem_free=5000),
            _a5000('gpu110', gpus_free=4, cpus_free=8, mem_free=10080),
        ]
        diagnosis = diagnose(_request(), nodes)
        assert diagnosis.fixes == ()
        assert diagnosis.bottleneck == 'mem'
        assert queue_hint(diagnosis) == 'mem-bound · max 9G/40G free'

    def test_planned_nodes(self):
        assert diagnose(_request(), LIVE_A5000).planned == {'gpu106'}

    def test_cpu_jobs_have_no_gpu_dimension(self):
        diagnosis = diagnose(_request(CPU_JOB), [_cpu_node(partitions='big')])
        assert diagnosis.dims == ('cpus', 'mem')


class TestNeverFits:
    def test_more_cpus_than_any_node_has(self):
        request = _request(CPU_JOB, cpus=_n(20))
        nodes = [
            _cpu_node(partitions='big', cpus=16),
            _cpu_node('cmp222', partitions='big', cpus=16),
        ]
        diagnosis = diagnose(request, nodes)
        assert diagnosis.never_fits
        assert queue_hint(diagnosis) == 'never fits: max 16 CPUs/node'
        fix = diagnosis.fix_for('cpus')
        assert fix is not None
        assert fix.new == 16

    def test_no_usable_nodes(self):
        nodes = [
            _node('gpu061', reservation='maint'),
            _node('gpu064', reservation='maint'),
            _node('gpu067', state='DOWN'),
        ]
        hint = queue_hint(diagnose(_request(), nodes))
        assert hint == 'no usable nodes (2 reserved, 1 down)'

    def test_no_nodes_in_the_partition(self):
        assert queue_hint(diagnose(_request(), [])) == 'no usable nodes'


class TestFixes:
    def test_memory_fix_rounds_down(self):
        # 12G asked, 10080 MB free: 10G would not fit, 9G does.
        diagnosis = diagnose(_request(PLAIN_GPU_JOB), [LIVE_A5000[1]])
        fix = diagnosis.fix_for('mem')
        assert fix is not None
        assert (fix.old, fix.new, fix.nodes) == (12288, 9216, ('gpu106',))
        assert fix.command == ['scontrol', 'update', 'JobId=65160', 'MinMemoryNode=9216']
        assert queue_hint(diagnosis) == 'starts now w/ mem ≤ 9G'

    def test_coupled_gpu_fix(self):
        node = _a5000('gpu110', gpus_free=2, cpus_free=8, mem_free=20480)
        diagnosis = diagnose(_request(), [node])
        fix = diagnosis.fix_for('gpus')
        assert fix is not None
        assert fix.new == 2
        assert fix.request.amount == Amount(2, 8, 20480)
        assert fix.command == [
            'scontrol',
            'update',
            'JobId=65177',
            'TresPerNode=gres/gpu:RTX-A5000:2',
        ]
        assert diagnosis.lead_fix() is fix
        assert queue_hint(diagnosis) == 'starts now w/ ≤ 2 GPUs'

    def test_mem_per_gpu_fix(self):
        node = _a5000('gpu110', gpus_free=4, cpus_free=16, mem_free=9000)
        diagnosis = diagnose(_request(), [node])
        fix = diagnosis.fix_for('mem')
        assert fix is not None
        assert fix.new == 2048
        assert fix.command is not None
        assert fix.command[-1] == 'MemPerTres=gres/gpu:2048'
        assert queue_hint(diagnosis) == 'starts now w/ mem ≤ 2G/GPU'

    def test_cpus_per_gpu_fix(self):
        node = _a5000('gpu110', gpus_free=4, cpus_free=12, mem_free=92000)
        fix = diagnose(_request(), [node]).fix_for('cpus')
        assert fix is not None
        assert fix.new == 3
        assert fix.command is not None
        assert fix.command[-1] == 'CpusPerTres=gres/gpu:3'

    def test_plain_cpu_fix_is_advice_only(self):
        request = _request(PLAIN_GPU_JOB, cpus_per_tres='')
        node = _a5000('gpu110', gpus_free=1, cpus_free=2, mem_free=92000)
        diagnosis = diagnose(request, [node])
        fix = diagnosis.fix_for('cpus')
        assert fix is not None
        assert fix.new == 2
        assert fix.command is None
        assert queue_hint(diagnosis) == 'starts now w/ ≤ 2 CPUs'

    def test_cpus_per_task_job_drops_its_cpu_floor_in_the_advice(self):
        # 64267 as it is live: -c 4, so MinCPUsNode and CPUsPerTask are 4 too.
        request = _request(
            CPU_JOB,
            minimum_cpus_per_node=_n(4),
            cpus_per_task=_n(4),
            tres_per_task='cpu=4',
            memory_per_node=_n(8192),
        )
        node = _cpu_node(partitions='big', cpus=48, cpus_alloc=46)
        fix = diagnose(request, [node]).fix_for('cpus')
        assert fix is not None
        assert (fix.new, fix.command) == (2, None)

    def test_cpus_per_gpu_floor_blocks_a_false_fit(self):
        request = _request(PLAIN_GPU_JOB, cpus=_n(2), minimum_cpus_per_node=_n(2))
        node = _a5000('gpu110', gpus_free=1, cpus_free=2, mem_free=92000)
        assert not diagnose(request, [node]).fits_now

    def test_lead_fix_gives_up_the_least(self):
        request = _request(PLAIN_GPU_JOB, cpus_per_tres='', cpus=_n(8))
        nodes = [
            _a5000('gpu110', gpus_free=1, cpus_free=8, mem_free=10080),  # mem 12G -> 9G
            _a5000('gpu111', gpus_free=1, cpus_free=2, mem_free=92000),  # CPUs 8 -> 2
        ]
        fix = diagnose(request, nodes).lead_fix()
        assert fix is not None
        assert fix.knob == 'mem'

    def test_lead_fix_prefers_what_slurm_can_apply(self):
        # ab q and ab why must name the same fix: a smaller CPU cut that needs a
        # resubmit loses to a memory cut scontrol can apply in place
        request = _request(PLAIN_GPU_JOB, cpus_per_tres='', cpus=_n(8))
        nodes = [
            _a5000('gpu110', gpus_free=1, cpus_free=8, mem_free=6144),
            _a5000('gpu111', gpus_free=1, cpus_free=6, mem_free=92000),
        ]
        diagnosis = diagnose(request, nodes)
        cpu_fix, lead = diagnosis.fix_for('cpus'), diagnosis.lead_fix()
        assert cpu_fix is not None
        assert cpu_fix.command is None
        assert lead is not None
        assert lead.knob == 'mem'
        assert cpu_fix.cut < lead.cut
        assert 'CPU' not in queue_hint(diagnosis)

    def test_gpu_fix_is_never_the_default(self):
        nodes = [
            _a5000('gpu110', gpus_free=4, cpus_free=16, mem_free=30000),  # 10G/GPU -> 7G
            _a5000('gpu111', gpus_free=3, cpus_free=12, mem_free=30720),  # GPUs 4 -> 3
        ]
        diagnosis = diagnose(_request(), nodes)
        gpu_fix, default = diagnosis.fix_for('gpus'), diagnosis.lead_fix()
        assert gpu_fix is not None
        assert default is not None
        assert gpu_fix.cut < default.cut
        assert default.knob == 'mem'

    def test_multi_node_fix_needs_enough_nodes(self):
        request = _request(PLAIN_GPU_JOB, node_count=_n(2), cpus=_n(8))
        nodes = [
            _a5000('gpu110', gpus_free=1, cpus_free=8, mem_free=10080),
            _a5000('gpu111', gpus_free=1, cpus_free=8, mem_free=8000),
        ]
        fix = diagnose(request, nodes).fix_for('mem')
        assert fix is not None
        assert fix.new == 7168

    def test_gpus_per_job_fix_has_no_command(self):
        request = _request(tres_per_node='', tres_per_job='gres/gpu:4')
        node = _a5000('gpu110', gpus_free=2, cpus_free=8, mem_free=20480)
        fix = diagnose(request, [node]).fix_for('gpus')
        assert fix is not None
        assert fix.command is None

    def test_whole_node_memory_gets_no_memory_fix(self):
        request = _request(PLAIN_GPU_JOB, memory_per_node=_n(0))
        node = _a5000('gpu110', gpus_free=4, cpus_free=16, mem_free=80000)
        diagnosis = diagnose(request, [node])
        assert diagnosis.rows[0].short == ('mem',)
        assert diagnosis.fix_for('mem') is None

    def test_max_mem_per_cpu_raises_the_cpu_need(self):
        # small: MaxMemPerCPU=3000, so 16G needs at least 6 CPUs.
        request = _request(CPU_JOB, partition='small', memory_per_node=_n(16384))
        node = _cpu_node(cpus=48, cpus_alloc=44)
        assert diagnose(request, [node]).fits_now
        diagnosis = diagnose(request, [node], {'small': 3000})
        assert diagnosis.rows[0].need.cpus == 6
        assert diagnosis.rows[0].short == ('cpus',)


class TestSlots:
    def test_only_undominated_free_amounts_remain(self):
        nodes = [
            _a5000('a', gpus_free=2, cpus_free=12, mem_free=10080),
            _a5000('b', gpus_free=2, cpus_free=10, mem_free=4960),
            _a5000('c', gpus_free=1, cpus_free=12, mem_free=10080),
            _a5000('d', gpus_free=0, cpus_free=0, mem_free=36704),
            _a5000('e', gpus_free=2, cpus_free=12, mem_free=10200),
        ]
        slots = diagnose(_request(), nodes).slots
        assert slots == (Slot(Amount(2, 12, 9216), ('a', 'e')),)

    def test_slots_are_sorted_by_gpus_then_cpus(self):
        nodes = [
            _a5000('a', gpus_free=1, cpus_free=16, mem_free=90000),
            _a5000('b', gpus_free=2, cpus_free=4, mem_free=8000),
            _a5000('c', gpus_free=3, cpus_free=1, mem_free=2000),
        ]
        slots = diagnose(_request(), nodes).slots
        assert [slot.free.gpus for slot in slots] == [3, 2, 1]
