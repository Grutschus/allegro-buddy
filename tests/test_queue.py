"""Tests for the `ab queue` table: which columns appear and what they show.

squeue is replaced by a fake that honours the requested --format fields, so the
handler's real parsing and rendering run against controlled jobs. The same fake answers
the `scontrol --json` calls behind the bottleneck hints.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any
from unittest.mock import patch

import pytest
from rich.console import Console
from slurm_records import ARRAY_JOB, number

from allegro_buddy import core
from allegro_buddy.handlers import why
from allegro_buddy.handlers.resources import cmd_queue

RUNNING_JOB = {
    'i': '64612',
    'A': '64612',
    'u': 'bob',
    'j': 'train',
    'T': 'RUNNING',
    'P': 'gpu',
    'M': '1:02:03',
    'L': '6:57:57',
    'S': '2026-10-05T12:34:00',
    'R': 'gpu081',
}
PENDING_JOB = {
    'i': '64613',
    'A': '64613',
    'u': 'carol',
    'j': 'eval',
    'T': 'PENDING',
    'P': 'gpu',
    'M': '0:00',
    'L': '8:00:00',
    'S': '2099-01-01T08:00:00',
    'R': '(Resources)',
}
PENDING_NO_ESTIMATE_JOB = {
    **PENDING_JOB,
    'i': '64614',
    'A': '64614',
    'j': 'post',
    'S': 'N/A',
    'R': '(Dependency)',
}

# scontrol's view of PENDING_JOB: 4 A5000, 4 CPU and 10G per GPU.
PENDING_RECORD = {
    **ARRAY_JOB,
    'job_id': 64613,
    'array_job_id': number(0),
    'array_task_string': '',
    'user_name': 'carol',
}
# An A5000 node with 2 GPUs, 12 CPUs and 10080 MB free, as `scontrol --json show nodes`.
NODE_JSON = {
    'name': 'gpu106',
    'state': ['MIXED'],
    'cpus': 16,
    'alloc_cpus': 4,
    'real_memory': 92000,
    'alloc_memory': 81920,
    'gres': 'gpu:RTX-A5000:4',
    'gres_used': 'gpu:RTX-A5000:2(IDX:0-1)',
    'partitions': ['gpu'],
    'active_features': ['Intel', 'RTX-A5000'],
    'features': ['Intel', 'RTX-A5000'],
}


def _fake_slurm(
    jobs: list[dict[str, str]],
    records: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    calls: list[list[str]],
    scontrol_returncode: int,
):
    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if argv[0] == 'scontrol':
            if scontrol_returncode:
                return subprocess.CompletedProcess(argv, scontrol_returncode, '', 'down')
            if argv[-1] == 'job':
                payload = json.dumps({'jobs': records})
            elif argv[-1] == 'nodes':
                payload = json.dumps({'nodes': nodes})
            else:
                payload = ''
            return subprocess.CompletedProcess(argv, 0, stdout=payload, stderr='')
        fmt = next(arg for arg in argv if arg.startswith('--format='))
        codes = [field.lstrip('%') for field in fmt.removeprefix('--format=').split('|')]
        stdout = ''.join('|'.join(job[code] for code in codes) + '\n' for job in jobs)
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr='')

    return run


def _render_queue(
    jobs: list[dict[str, str]],
    *,
    records: list[dict[str, Any]] | None = None,
    nodes: list[dict[str, Any]] | None = None,
    calls: list[list[str]] | None = None,
    scontrol_returncode: int = 0,
    **options: Any,
) -> list[str]:
    console = Console(record=True, width=200)
    kwargs = {'all_users': False, 'user': None, 'partition': None, **options}
    fake = _fake_slurm(
        jobs,
        [PENDING_RECORD] if records is None else records,
        [NODE_JSON] if nodes is None else nodes,
        [] if calls is None else calls,
        scontrol_returncode,
    )
    with (
        patch.object(core, 'run', fake),
        patch.object(core, 'CONSOLE', console),
        patch('allegro_buddy.handlers.resources.CONSOLE', console),
        patch('allegro_buddy.handlers.resources.current_user', return_value='alice'),
    ):
        cmd_queue(**kwargs)
    return console.export_text().splitlines()


def _headers(lines: list[str]) -> list[str]:
    return next(line for line in lines if 'JobID' in line).split()


def _row(lines: list[str], job_id: str) -> str:
    return next(line for line in lines if line.lstrip().startswith(job_id))


class TestUserColumn:
    def test_all_users_view_shows_user_after_job_id(self):
        lines = _render_queue([RUNNING_JOB], all_users=True)
        assert _headers(lines)[:2] == ['JobID', 'User']
        assert 'bob' in _row(lines, '64612')

    @pytest.mark.parametrize(
        'options',
        [{}, {'user': 'bob'}],
        ids=['own-jobs', 'user-filter'],
    )
    def test_single_user_views_have_no_user_column(self, options: dict[str, Any]):
        lines = _render_queue([RUNNING_JOB], **options)
        assert 'User' not in _headers(lines)


class TestStartColumn:
    def test_running_only_queue_has_no_start_column(self):
        lines = _render_queue([RUNNING_JOB])
        assert 'Start' not in _headers(lines)

    def test_start_column_sits_before_node_reason(self):
        lines = _render_queue([RUNNING_JOB, PENDING_JOB])
        assert _headers(lines)[-2:] == ['Start', 'Node/Reason']

    def test_pending_job_shows_estimated_start(self):
        lines = _render_queue([PENDING_JOB])
        row = _row(lines, '64613')
        assert 'in ' in row
        assert '(Jan 01' not in row  # relative only, no clock

    def test_pending_job_without_estimate_shows_dash(self):
        lines = _render_queue([PENDING_NO_ESTIMATE_JOB])
        assert '-' in _row(lines, '64614').split()

    def test_running_job_start_cell_stays_blank(self):
        # squeue reports the actual start for running jobs; it must not leak in
        lines = _render_queue([RUNNING_JOB, PENDING_JOB])
        assert '12:34' not in _row(lines, '64612')

    def test_all_users_with_pending_job_shows_both_columns(self):
        lines = _render_queue([RUNNING_JOB, PENDING_JOB], all_users=True)
        assert _headers(lines) == [
            'JobID',
            'User',
            'Name',
            'State',
            'Partition',
            'Elapsed',
            'Time',
            'left',
            'Start',
            'Node/Reason',
        ]


class TestBottleneckHints:
    def test_resources_row_gets_its_hint(self):
        lines = _render_queue([PENDING_JOB])
        row = _row(lines, '64613')
        assert 'GPU-bound · max 2/4 free' in row
        assert 'Resources' not in row  # the hint replaces Slurm's reason code

    def test_footer_points_at_ab_why(self):
        lines = _render_queue([PENDING_JOB])
        assert lines[-1].startswith('ⓘ `ab why`')

    def test_other_reasons_get_no_hint_and_no_scontrol_call(self):
        calls: list[list[str]] = []
        lines = _render_queue([RUNNING_JOB, PENDING_NO_ESTIMATE_JOB], calls=calls)
        assert 'bound' not in _row(lines, '64614')
        assert not any('ab why' in line for line in lines)
        assert all(argv[0] == 'squeue' for argv in calls)

    def test_scontrol_failure_keeps_the_table(self):
        lines = _render_queue([PENDING_JOB], scontrol_returncode=1)
        assert 'Resources' in _row(lines, '64613')
        assert any('bottleneck hints unavailable' in line for line in lines)

    def test_diagnosis_error_keeps_the_table(self):
        with patch.object(why, 'diagnose', side_effect=RuntimeError('boom')):
            lines = _render_queue([PENDING_JOB])
        assert 'Resources' in _row(lines, '64613')
        assert any('hints unavailable: RuntimeError: boom' in line for line in lines)

    def test_job_that_left_scontrol_gets_no_hint(self):
        lines = _render_queue([PENDING_JOB], records=[])
        assert 'bound' not in _row(lines, '64613')


class TestDurations:
    def test_slurm_times_read_as_human_durations(self):
        assert _row(_render_queue([RUNNING_JOB]), '64612').split()[-2] == '6h57m'
        assert _row(_render_queue([PENDING_JOB]), '64613').split()[4] == '8h'

    def test_under_an_hour_is_minutes_not_hours(self):
        # squeue prints times under an hour as M:SS
        row = _row(_render_queue([{**RUNNING_JOB, 'L': '40:00'}]), '64612').split()
        assert row[-2] == '40m'

    def test_running_job_shows_elapsed_time(self):
        assert _row(_render_queue([RUNNING_JOB]), '64612').split()[-3] == '1h2m'

    def test_pending_only_queue_has_no_elapsed_column(self):
        assert 'Elapsed' not in _headers(_render_queue([PENDING_JOB]))


class TestEmptyQueue:
    def test_own_queue(self):
        assert _render_queue([]) == ['No jobs in the queue.']

    def test_other_user(self):
        assert _render_queue([], user='bob') == ['No jobs for bob in the queue.']
