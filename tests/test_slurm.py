"""Tests for functions that call Slurm commands, using mocked subprocess.

These tests verify that our parsers correctly interpret the output formats
produced by scontrol, sacct, squeue, etc.  If Slurm output format changes
after a cluster upgrade, these tests will pinpoint which parser broke.
"""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from allegro_buddy.core import (
    expand_nodelist,
    get_user_jobs,
    job_gres_on_node,
    load_job_details,
    load_job_history,
    load_job_records,
    load_nodes,
    load_partitions,
    node_free,
    resolve_job_output_path,
    run,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _proc(stdout: str = '', stderr: str = '', returncode: int = 0):
    """Build a minimal mock subprocess.CompletedProcess."""
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = returncode
    return proc


# Realistic scontrol --oneliner show partition output
SCONTROL_PARTITION_OUTPUT = (
    'PartitionName=gpusmall AllowGroups=ALL AllowAccounts=ALL '
    'AllowQos=ALL AllocNodes=ALL Default=NO QoS=N/A '
    'MaxTime=1-00:00:00 MinNodes=0 Nodes=gpu[001-050] '
    'State=UP TotalCPUs=2400 TotalNodes=50\n'
    'PartitionName=gpu AllowGroups=ALL AllowAccounts=ALL '
    'AllowQos=ALL AllocNodes=ALL Default=NO QoS=N/A '
    'MaxTime=7-00:00:00 MinNodes=0 Nodes=gpu[001-100] '
    'State=UP TotalCPUs=4800 TotalNodes=100\n'
    'PartitionName=gpumicro AllowGroups=gpu_users AllowAccounts=ALL '
    'AllowQos=ALL AllocNodes=ALL Default=NO QoS=N/A '
    'MaxTime=08:00:00 MinNodes=0 Nodes=gpu[001-010] '
    'State=UP TotalCPUs=480 TotalNodes=10\n'
)

# Realistic scontrol --json show nodes output
SCONTROL_NODE_OUTPUT = """{
  "nodes": [
    {
      "name": "gpu001", "cpus": 48, "alloc_cpus": 0,
      "state": ["IDLE"],
      "gres": "gpu:rtx_a5000:4", "gres_used": "gpu:rtx_a5000:0(IDX:N/A)",
      "real_memory": 256000, "alloc_memory": 0,
      "partitions": ["gpumicro", "gpushort", "gpusmall", "gpu"],
      "active_features": ["a5000", "rtx", "nvlink", "gpu4"],
      "features": ["a5000", "rtx", "nvlink", "gpu4"]
    },
    {
      "name": "gpu002", "cpus": 48, "alloc_cpus": 16,
      "state": ["MIXED"],
      "gres": "gpu:rtx_a5000:4", "gres_used": "gpu:rtx_a5000:2(IDX:0,1)",
      "real_memory": 256000, "alloc_memory": 65536,
      "partitions": ["gpusmall", "gpu"],
      "active_features": ["a5000", "rtx", "nvlink"],
      "features": ["a5000", "rtx", "nvlink"]
    },
    {
      "name": "cmp001", "cpus": 64, "alloc_cpus": 0,
      "state": ["IDLE"],
      "gres": "", "gres_used": "",
      "real_memory": 512000, "alloc_memory": 0,
      "partitions": ["small", "big"],
      "active_features": ["amd", "zen3"],
      "features": ["amd", "zen3"]
    }
  ]
}"""

SCONTROL_NODE_EMPTY = '{"nodes": []}'

# Realistic sacct --parsable2 --noheader output
SACCT_HISTORY_OUTPUT = (
    '12345|12345|training|COMPLETED|0:0|2024-05-01T10:00:00|None\n'
    '12346|12346|inference|FAILED|1:0|2024-05-02T11:30:00|None\n'
    '12347|12347|data_prep|CANCELLED by 12000|0:9|2024-05-03T09:00:00|None\n'
    '12348|12348|ab-dev|COMPLETED|0:0|2024-05-04T08:00:00|None\n'
)


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------


class TestRun:
    def test_returns_completed_process_on_success(self):
        with patch('subprocess.run', return_value=_proc(stdout='ok')):
            result = run(['scontrol', 'show', 'partition'])
        assert result.stdout == 'ok'

    def test_nonzero_returncode_raises_system_exit_by_default(self):
        with (
            patch('subprocess.run', return_value=_proc(stderr='bad', returncode=1)),
            pytest.raises(SystemExit),
        ):
            run(['scontrol', 'show', 'bad'])

    def test_check_false_allows_nonzero_returncode(self):
        with patch('subprocess.run', return_value=_proc(returncode=1)):
            result = run(['sacct'], check=False)
        assert result.returncode == 1

    def test_file_not_found_raises_system_exit(self):
        with (
            patch('subprocess.run', side_effect=FileNotFoundError),
            pytest.raises(SystemExit),
        ):
            run(['nonexistent_command'])


# ---------------------------------------------------------------------------
# expand_nodelist — expands bracket ranges in-process
# ---------------------------------------------------------------------------


class TestExpandNodelist:
    def test_plain_node_name_returned_as_is(self):
        assert expand_nodelist('gpu001') == ['gpu001']

    def test_comma_separated_nodes_split_without_scontrol(self):
        result = expand_nodelist('gpu001,gpu002,gpu003')
        assert result == ['gpu001', 'gpu002', 'gpu003']

    def test_empty_string_returns_empty(self):
        assert expand_nodelist('') == []

    def test_null_literal_returns_empty(self):
        assert expand_nodelist('(null)') == []

    def test_none_literal_returns_empty(self):
        assert expand_nodelist('None') == []

    def test_bracket_range_expands_without_subprocess(self):
        with patch('subprocess.run') as m:
            result = expand_nodelist('gpu[001-003]')
        assert result == ['gpu001', 'gpu002', 'gpu003']
        m.assert_not_called()


# ---------------------------------------------------------------------------
# load_partitions — parses scontrol --oneliner show partition
# ---------------------------------------------------------------------------


class TestLoadPartitions:
    def test_parses_all_partitions(self):
        with patch('subprocess.run', return_value=_proc(stdout=SCONTROL_PARTITION_OUTPUT)):
            partitions = load_partitions()
        assert len(partitions) == 3

    def test_partition_names_extracted(self):
        with patch('subprocess.run', return_value=_proc(stdout=SCONTROL_PARTITION_OUTPUT)):
            partitions = load_partitions()
        names = {p['PartitionName'] for p in partitions}
        assert 'gpusmall' in names
        assert 'gpu' in names
        assert 'gpumicro' in names

    def test_partition_fields_present(self):
        with patch('subprocess.run', return_value=_proc(stdout=SCONTROL_PARTITION_OUTPUT)):
            partitions = load_partitions()
        gpusmall = next(p for p in partitions if p['PartitionName'] == 'gpusmall')
        assert gpusmall['MaxTime'] == '1-00:00:00'
        assert gpusmall['State'] == 'UP'
        assert gpusmall['TotalNodes'] == '50'

    def test_restricted_partition_has_allow_groups(self):
        with patch('subprocess.run', return_value=_proc(stdout=SCONTROL_PARTITION_OUTPUT)):
            partitions = load_partitions()
        gpumicro = next(p for p in partitions if p['PartitionName'] == 'gpumicro')
        assert gpumicro['AllowGroups'] == 'gpu_users'

    def test_empty_output_returns_empty_list(self):
        with patch('subprocess.run', return_value=_proc(stdout='')):
            assert load_partitions() == []


# ---------------------------------------------------------------------------
# load_nodes — parses scontrol --json show nodes
# ---------------------------------------------------------------------------


class TestLoadNodes:
    def test_parses_all_nodes(self):
        with patch('subprocess.run', return_value=_proc(stdout=SCONTROL_NODE_OUTPUT)):
            nodes = load_nodes()
        assert len(nodes) == 3

    def test_node_names_extracted(self):
        with patch('subprocess.run', return_value=_proc(stdout=SCONTROL_NODE_OUTPUT)):
            nodes = load_nodes()
        names = {n['NodeName'] for n in nodes}
        assert 'gpu001' in names
        assert 'gpu002' in names
        assert 'cmp001' in names

    def test_node_fields_present(self):
        with patch('subprocess.run', return_value=_proc(stdout=SCONTROL_NODE_OUTPUT)):
            nodes = load_nodes()
        gpu001 = next(n for n in nodes if n['NodeName'] == 'gpu001')
        assert gpu001['CPUTot'] == '48'
        assert gpu001['CPUAlloc'] == '0'
        assert gpu001['State'] == 'IDLE'
        assert gpu001['Gres'] == 'gpu:rtx_a5000:4'
        assert gpu001['GresUsed'] == 'gpu:rtx_a5000:0(IDX:N/A)'
        assert gpu001['Partitions'] == 'gpumicro,gpushort,gpusmall,gpu'

    def test_mixed_node_fields(self):
        with patch('subprocess.run', return_value=_proc(stdout=SCONTROL_NODE_OUTPUT)):
            nodes = load_nodes()
        gpu002 = next(n for n in nodes if n['NodeName'] == 'gpu002')
        assert gpu002['State'] == 'MIXED'
        assert gpu002['CPUAlloc'] == '16'
        assert gpu002['GresUsed'] == 'gpu:rtx_a5000:2(IDX:0,1)'

    def test_cpu_only_node_has_empty_gres(self):
        with patch('subprocess.run', return_value=_proc(stdout=SCONTROL_NODE_OUTPUT)):
            nodes = load_nodes()
        cmp001 = next(n for n in nodes if n['NodeName'] == 'cmp001')
        assert cmp001['Gres'] == '(null)'  # empty string normalized to (null)

    def test_empty_nodes_list_returns_empty_list(self):
        with patch('subprocess.run', return_value=_proc(stdout=SCONTROL_NODE_EMPTY)):
            assert load_nodes() == []

    def test_reservation_and_specialized_memory(self):
        output = (
            '{"nodes": [{"name": "gpu061", "state": ["IDLE", "RESERVED"],'
            ' "reservation": "maint", "specialized_memory": 2048}]}'
        )
        with patch('subprocess.run', return_value=_proc(stdout=output)):
            (node,) = load_nodes()
        assert node['Reservation'] == 'maint'
        assert node['SpecMem'] == '2048'

    def test_reservation_and_specialized_memory_default_to_empty(self):
        with patch('subprocess.run', return_value=_proc(stdout=SCONTROL_NODE_OUTPUT)):
            gpu001 = load_nodes()[0]
        assert gpu001['Reservation'] == ''
        assert gpu001['SpecMem'] == '0'

    def test_non_strict_failure_returns_empty(self):
        with patch('subprocess.run', return_value=_proc(stderr='down', returncode=1)):
            assert load_nodes(strict=False) == []


class TestLoadPartitionsNonStrict:
    def test_non_strict_failure_returns_empty(self):
        with patch('subprocess.run', return_value=_proc(stderr='down', returncode=1)):
            assert load_partitions(strict=False) == []


# ---------------------------------------------------------------------------
# load_job_records — parses scontrol --json show job
# ---------------------------------------------------------------------------


class TestLoadJobRecords:
    def test_returns_json_job_records(self):
        output = '{"jobs": [{"job_id": 65177, "job_state": ["PENDING"]}]}'
        with patch('subprocess.run', return_value=_proc(stdout=output)) as mock:
            records = load_job_records()
        assert records == [{'job_id': 65177, 'job_state': ['PENDING']}]
        assert mock.call_args[0][0] == ['scontrol', '--json', 'show', 'job']

    def test_strict_failure_exits(self):
        with (
            patch('subprocess.run', return_value=_proc(stderr='down', returncode=1)),
            pytest.raises(SystemExit),
        ):
            load_job_records()

    def test_non_strict_failure_returns_empty(self):
        with patch('subprocess.run', return_value=_proc(stderr='down', returncode=1)):
            assert load_job_records(strict=False) == []


# ---------------------------------------------------------------------------
# load_job_history — parses sacct --parsable2 output
# ---------------------------------------------------------------------------


class TestLoadJobHistory:
    def test_parses_all_history_rows(self):
        with patch('subprocess.run', return_value=_proc(stdout=SACCT_HISTORY_OUTPUT)):
            history = load_job_history('alice')
        assert len(history) == 4

    def test_job_ids_present(self):
        with patch('subprocess.run', return_value=_proc(stdout=SACCT_HISTORY_OUTPUT)):
            history = load_job_history('alice')
        job_ids = {job['JobId'] for job in history}
        assert '12345' in job_ids
        assert '12346' in job_ids
        assert '12347' in job_ids

    def test_state_tokens_normalized(self):
        with patch('subprocess.run', return_value=_proc(stdout=SACCT_HISTORY_OUTPUT)):
            history = load_job_history('alice')
        cancelled = next(j for j in history if j['JobId'] == '12347')
        # "CANCELLED by 12000" → StateToken should be "CANCELLED"
        assert cancelled['StateToken'] == 'CANCELLED'

    def test_sorted_descending_by_end_time(self):
        with patch('subprocess.run', return_value=_proc(stdout=SACCT_HISTORY_OUTPUT)):
            history = load_job_history('alice')
        # 12348 ended last (2024-05-04), should be first in descending order
        assert history[0]['JobId'] == '12348'

    def test_deduplication_keeps_unique_ids(self):
        # Feed duplicate rows for the same job
        duplicate_output = SACCT_HISTORY_OUTPUT + '12345|12345|training|COMPLETED|0:0|2024-05-01T10:00:00|None\n'
        with patch('subprocess.run', return_value=_proc(stdout=duplicate_output)):
            history = load_job_history('alice')
        ids = [j['JobId'] for j in history]
        assert ids.count('12345') == 1

    def test_empty_output_returns_empty_list(self):
        with patch('subprocess.run', return_value=_proc(stdout='')):
            assert load_job_history('alice') == []

    def test_sacct_failure_strict_raises_system_exit(self):
        with (
            patch('subprocess.run', return_value=_proc(stderr='slurmdbd down', returncode=1)),
            pytest.raises(SystemExit),
        ):
            load_job_history('alice', strict=True)

    def test_sacct_failure_non_strict_returns_empty(self):
        with patch('subprocess.run', return_value=_proc(returncode=1)):
            result = load_job_history('alice', strict=False)
        assert result == []

    def test_history_source_tagged(self):
        with patch('subprocess.run', return_value=_proc(stdout=SACCT_HISTORY_OUTPUT)):
            history = load_job_history('alice')
        assert all(j['HistorySource'] == 'sacct' for j in history)

    def test_history_window_is_bounded(self):
        with patch('subprocess.run', return_value=_proc(stdout='')) as m:
            load_job_history('alice')
        assert '--starttime=now-30days' in m.call_args.args[0]


# ---------------------------------------------------------------------------
# Multi-node jobs: one GRES block per node with --details
# ---------------------------------------------------------------------------


class TestJobGresOnNode:
    LINE = (
        'JobId=7 JobName=big UserId=alice(1000) JobState=RUNNING NodeList=gpu[081-082] '
        'Nodes=gpu081 CPU_IDs=0-7 Mem=1000 GRES=gpu:a100:2(IDX:0-1) '
        'Nodes=gpu082 CPU_IDs=0-7 Mem=1000 GRES=gpu:a100:2(IDX:2-3) '
        'MinCPUsNode=1'
    )

    def test_picks_the_block_for_each_node(self):
        with patch('subprocess.run', return_value=_proc(stdout=self.LINE + '\n')):
            (job,) = load_job_details()
        assert job_gres_on_node(job, 'gpu081') == 'gpu:a100:2(IDX:0-1)'
        assert job_gres_on_node(job, 'gpu082') == 'gpu:a100:2(IDX:2-3)'

    def test_job_without_blocks_falls_back_to_gres(self):
        assert job_gres_on_node({'GRES': 'gpu:1(IDX:0)'}, 'gpu001') == 'gpu:1(IDX:0)'


class TestNodeFree:
    def test_spec_mem_is_reserved(self):
        free = node_free(
            {'CPUTot': '8', 'CPUAlloc': '2', 'RealMemory': '512000',
             'SpecMem': '10240', 'AllocMem': '0', 'Gres': 'gpu:a100:4',
             'GresUsed': 'gpu:a100:1(IDX:0)'}
        )
        assert free['cpu_free'] == 6
        assert free['mem_free_mb'] == 512000 - 10240
        assert free['gpu_free_by_type'] == {'a100': 3}


class TestJobOutputFallsBackToSacct:
    def test_finished_job_path_comes_from_sacct(self):
        def fake_run(argv, **_kwargs):
            if argv[0] == 'scontrol':
                return _proc(returncode=1)
            return _proc(stdout='alice|/home/alice/out-%j.txt|/home/alice/err-%j.txt\n')

        with patch('subprocess.run', side_effect=fake_run):
            path = resolve_job_output_path('42', stream='stdout', user='alice')
        assert str(path) == '/home/alice/out-42.txt'

    def test_array_task_j_is_the_tasks_own_id(self):
        # Allegro sacct row for 71485_0: StdOut is the raw pattern, JobIDRaw is 71512
        def fake_run(argv, **_kwargs):
            if argv[0] == 'scontrol':
                return _proc(returncode=1)
            return _proc(stdout='alice|/logs/out-%j.log||71512|train\n')

        with patch('subprocess.run', side_effect=fake_run):
            path = resolve_job_output_path('71485_0', stream='stdout', user='alice')
        assert str(path) == '/logs/out-71512.log'

    def test_job_name_and_user_patterns(self):
        def fake_run(argv, **_kwargs):
            if argv[0] == 'scontrol':
                return _proc(returncode=1)
            return _proc(stdout='alice|/logs/%u/%x-%j.out||42|train\n')

        with patch('subprocess.run', side_effect=fake_run):
            path = resolve_job_output_path('42', stream='stdout', user='alice')
        assert str(path) == '/logs/alice/train-42.out'

    def test_raw_id_from_history_still_fills_array_patterns(self):
        # ab job history lists 130, the raw id of task 123_7
        def fake_run(argv, **_kwargs):
            if argv[0] == 'scontrol':
                return _proc(returncode=1)
            return _proc(stdout='alice|/h/%x-%A_%a.out||130|train|123_7\n')

        with patch('subprocess.run', side_effect=fake_run):
            path = resolve_job_output_path('130', stream='stdout', user='alice')
        assert str(path) == '/h/train-123_7.out'

    def test_forgotten_task_never_borrows_a_sibling_tasks_log(self):
        def fake_run(argv, **_kwargs):
            if argv[0] == 'scontrol':
                if argv[-1] == '123':  # the array is still alive through task 7
                    return _proc(stdout='JobId=130 UserId=alice(1) StdOut=/h/out-123_7.log\n')
                return _proc(returncode=1)
            return _proc(stdout='alice|/h/out-%A_%a.log||128|train|123_5\n')

        with patch('subprocess.run', side_effect=fake_run):
            path = resolve_job_output_path('123_5', stream='stdout', user='alice')
        assert str(path) == '/h/out-123_5.log'

    def test_other_users_job_is_refused(self):
        def fake_run(argv, **_kwargs):
            if argv[0] == 'scontrol':
                return _proc(returncode=1)
            return _proc(stdout='bob|/home/bob/out.txt|\n')

        with patch('subprocess.run', side_effect=fake_run):
            assert resolve_job_output_path('42', stream='stdout', user='alice') is None


class TestUserJobsAskOnlyForTheUser:
    def test_squeue_filters_then_one_scontrol_per_job(self):
        calls = []

        def fake_run(argv, **_kwargs):
            calls.append(argv)
            if argv[0] == 'squeue':
                return _proc(stdout='71485\n71485\n42\n')
            return _proc(stdout=f'JobId={argv[-1]} UserId=alice(1) JobState=RUNNING\n')

        with patch('subprocess.run', side_effect=fake_run):
            jobs = get_user_jobs('alice')
        assert [job['JobId'] for job in jobs] == ['71485', '42']
        # never the whole cluster's job table
        assert ['scontrol', '--oneliner', '--details', 'show', 'job'] not in calls
        assert '--user=alice' in calls[0]

    def test_job_that_ended_meanwhile_is_skipped(self):
        def fake_run(argv, **_kwargs):
            if argv[0] == 'squeue':
                return _proc(stdout='42\n')
            return _proc(returncode=1, stderr='Invalid job id specified')

        with patch('subprocess.run', side_effect=fake_run):
            assert get_user_jobs('alice') == []

    def test_one_job_record_and_unknown_id_is_empty(self):
        with patch('subprocess.run', return_value=_proc(returncode=1)) as mock:
            assert load_job_records('999999') == []
        assert mock.call_args.args[0] == ['scontrol', '--json', 'show', 'job', '999999']
