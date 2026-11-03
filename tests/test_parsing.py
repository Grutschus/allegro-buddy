"""Tests for data parsing and formatting utilities in core.py.

These cover the functions most likely to break when Slurm output formats change
between cluster upgrades or configuration changes.
"""
from __future__ import annotations

import os
from datetime import datetime

import pytest

from allegro_buddy.core import (
    base_job_id,
    display_job_id,
    format_history_end,
    format_mem_value,
    format_pending_start,
    format_seconds,
    is_nullish,
    is_success_exit_code,
    iso_to_dt,
    job_state_is_finished,
    normalize_sacct_state,
    parse_int,
    parse_mb_to_gb,
    parse_pipe_rows,
    parse_prop_line,
    parse_slurm_time,
    remember_nodes,
    resolve_slurm_output_path,
    sort_partitions,
    truncate,
    user_from_userid,
)

# ---------------------------------------------------------------------------
# parse_prop_line — parses scontrol --oneliner output
# ---------------------------------------------------------------------------


class TestParsePropLine:
    def test_single_key_value(self):
        assert parse_prop_line('PartitionName=gpu') == {'PartitionName': 'gpu'}

    def test_multiple_key_values(self):
        result = parse_prop_line('PartitionName=gpu AllowGroups=ALL State=UP')
        assert result['PartitionName'] == 'gpu'
        assert result['AllowGroups'] == 'ALL'
        assert result['State'] == 'UP'

    def test_value_containing_equals(self):
        # TRESBillingWeights contains embedded = signs
        result = parse_prop_line(
            'PartitionName=gpu TRESBillingWeights=CPU=1.0,Mem=0.1G State=UP'
        )
        assert result['TRESBillingWeights'] == 'CPU=1.0,Mem=0.1G'

    def test_empty_value(self):
        result = parse_prop_line('PartitionName=gpu DenyUsers= State=UP')
        assert result['DenyUsers'] == ''

    def test_empty_string_returns_empty_dict(self):
        assert parse_prop_line('') == {}

    def test_whitespace_only_returns_empty_dict(self):
        assert parse_prop_line('   ') == {}

    def test_leading_trailing_whitespace_stripped(self):
        result = parse_prop_line('  PartitionName=gpu  ')
        assert result['PartitionName'] == 'gpu'

    def test_realistic_scontrol_partition_line(self):
        line = (
            'PartitionName=gpusmall AllowGroups=ALL AllowAccounts=ALL '
            'AllowQos=ALL AllocNodes=ALL Default=NO QoS=N/A '
            'DefaultTime=NONE DisableRootJobs=NO ExclusiveUser=NO GraceTime=0 '
            'Hidden=NO MaxNodes=UNLIMITED MaxTime=1-00:00:00 MinNodes=0 '
            'Nodes=gpu[001-100] PriorityJobFactor=1 PriorityTier=1 '
            'RootOnly=NO OverSubscribe=NO State=UP TotalCPUs=4800 TotalNodes=100 '
            'TRES=cpu=4800,mem=25600G,node=100'
        )
        result = parse_prop_line(line)
        assert result['PartitionName'] == 'gpusmall'
        assert result['MaxTime'] == '1-00:00:00'
        assert result['State'] == 'UP'
        assert result['TotalNodes'] == '100'

    def test_realistic_scontrol_node_line(self):
        line = (
            'NodeName=gpu001 Arch=x86_64 CoresPerSocket=24 '
            'CPUTot=48 CPUAlloc=0 '
            'State=IDLE+COMPLETING Gres=gpu:rtx_a5000:4 '
            'RealMemory=256000 AllocMem=0 '
            'Partitions=gpumicro,gpushort,gpusmall,gpu '
            'ActiveFeatures=a5000,rtx,nvlink,gpu4'
        )
        result = parse_prop_line(line)
        assert result['NodeName'] == 'gpu001'
        assert result['CPUTot'] == '48'
        assert result['CPUAlloc'] == '0'
        assert result['State'] == 'IDLE+COMPLETING'
        assert result['Gres'] == 'gpu:rtx_a5000:4'
        assert result['Partitions'] == 'gpumicro,gpushort,gpusmall,gpu'


# ---------------------------------------------------------------------------
# parse_pipe_rows — parses sacct/squeue --parsable2 --noheader output
# ---------------------------------------------------------------------------


class TestParsePipeRows:
    def test_single_row(self):
        output = '12345|training|COMPLETED|0:0|2024-01-01T10:00:00|None'
        headers = ['JobIDRaw', 'JobName', 'State', 'ExitCode', 'End', 'Reason']
        rows = parse_pipe_rows(output, headers)
        assert len(rows) == 1
        assert rows[0]['JobIDRaw'] == '12345'
        assert rows[0]['State'] == 'COMPLETED'
        assert rows[0]['ExitCode'] == '0:0'

    def test_multiple_rows(self):
        output = (
            '12345|job1|COMPLETED|0:0|2024-01-01T10:00:00|None\n'
            '12346|job2|FAILED|1:0|2024-01-02T11:00:00|None'
        )
        headers = ['JobIDRaw', 'JobName', 'State', 'ExitCode', 'End', 'Reason']
        rows = parse_pipe_rows(output, headers)
        assert len(rows) == 2
        assert rows[0]['JobIDRaw'] == '12345'
        assert rows[1]['JobIDRaw'] == '12346'

    def test_empty_output_returns_empty_list(self):
        assert parse_pipe_rows('', ['A', 'B', 'C']) == []

    def test_blank_lines_are_skipped(self):
        output = '\n\n12345|job|COMPLETED|0:0\n\n'
        rows = parse_pipe_rows(output, ['A', 'B', 'C', 'D'])
        assert len(rows) == 1

    def test_fewer_columns_than_headers_fills_with_empty_string(self):
        output = 'val1|val2'
        rows = parse_pipe_rows(output, ['A', 'B', 'C', 'D'])
        assert rows[0]['A'] == 'val1'
        assert rows[0]['B'] == 'val2'
        assert rows[0]['C'] == ''
        assert rows[0]['D'] == ''

    def test_empty_pipe_field(self):
        output = 'val1||val3'
        rows = parse_pipe_rows(output, ['A', 'B', 'C'])
        assert rows[0]['B'] == ''

    def test_realistic_sacct_output(self):
        output = (
            '12345|12345|training|COMPLETED|0:0|2024-05-01T10:00:00|None\n'
            '12346|12346|inference|FAILED|137:0|2024-05-02T11:30:00|None\n'
            '12347|12347|data_prep|CANCELLED by 12000|0:9|2024-05-03T09:00:00|None\n'
        )
        headers = ['JobIDRaw', 'JobID', 'JobName', 'State', 'ExitCode', 'End', 'Reason']
        rows = parse_pipe_rows(output, headers)
        assert len(rows) == 3
        assert rows[2]['State'] == 'CANCELLED by 12000'


# ---------------------------------------------------------------------------
# parse_int / parse_mb_to_gb
# ---------------------------------------------------------------------------


class TestParseInt:
    def test_normal_integer(self):
        assert parse_int('42') == 42

    def test_float_string_truncated(self):
        assert parse_int('3.7') == 3

    def test_none_returns_default(self):
        assert parse_int(None) == 0
        assert parse_int(None, default=99) == 99

    def test_empty_string_returns_default(self):
        assert parse_int('') == 0

    def test_null_literal_returns_default(self):
        assert parse_int('(null)') == 0

    def test_na_returns_default(self):
        assert parse_int('N/A') == 0

    def test_negative_integer(self):
        assert parse_int('-5') == -5

    def test_invalid_string_returns_default(self):
        assert parse_int('abc') == 0
        assert parse_int('abc', default=7) == 7

    def test_zero(self):
        assert parse_int('0') == 0


class TestParseMbToGb:
    def test_1024_mb_is_1_gb(self):
        assert parse_mb_to_gb('1024') == 1

    def test_256000_mb(self):
        assert parse_mb_to_gb('256000') == 250

    def test_none_returns_zero(self):
        assert parse_mb_to_gb(None) == 0

    def test_zero_mb(self):
        assert parse_mb_to_gb('0') == 0

    def test_large_memory(self):
        # 1 TB = 1048576 MB → 1024 GB
        assert parse_mb_to_gb('1048576') == 1024


# ---------------------------------------------------------------------------
# parse_slurm_time / format_seconds
# ---------------------------------------------------------------------------


class TestParseSlurmTime:
    def test_hms_format(self):
        assert parse_slurm_time('1:30:00') == 5400

    def test_two_fields_are_minutes_seconds(self):
        # Slurm reads "MM:SS" without a day part, so 30:00 is 30 minutes.
        assert parse_slurm_time('1:30') == 90
        assert parse_slurm_time('30:00') == 30 * 60

    def test_days_with_two_fields_are_hours_minutes(self):
        assert parse_slurm_time('1-1:30') == 86400 + 3600 + 30 * 60

    def test_days_hms_format(self):
        assert parse_slurm_time('1-00:00:00') == 86400

    def test_days_hms_complex(self):
        expected = 2 * 86400 + 12 * 3600 + 30 * 60
        assert parse_slurm_time('2-12:30:00') == expected

    def test_zero_days_and_hours(self):
        assert parse_slurm_time('0-5') == 5 * 3600

    def test_unlimited_returns_none(self):
        assert parse_slurm_time('UNLIMITED') is None
        assert parse_slurm_time('unlimited') is None

    def test_infinite_variants_return_none(self):
        assert parse_slurm_time('INFINITE') is None
        assert parse_slurm_time('INFINITY') is None

    def test_na_returns_none(self):
        assert parse_slurm_time('N/A') is None

    def test_single_value_is_minutes(self):
        # Single integer treated as minutes
        assert parse_slurm_time('30') == 30 * 60

    def test_zero_time(self):
        assert parse_slurm_time('0:00:00') == 0

    def test_strips_leading_trailing_whitespace(self):
        assert parse_slurm_time('  1:00:00  ') == 3600

    def test_common_partition_max_times(self):
        # Typical partition MaxTime values seen on real clusters
        assert parse_slurm_time('08:00:00') == 8 * 3600
        assert parse_slurm_time('1-00:00:00') == 86400
        assert parse_slurm_time('7-00:00:00') == 7 * 86400

    def test_non_numeric_returns_none(self):
        # Malformed input no longer terminates the process; it returns None
        # so callers can decide how to handle it.
        assert parse_slurm_time('not-a-time') is None

    def test_too_many_colon_parts_returns_none(self):
        # More than 3 colon-separated parts is not a valid Slurm time spec.
        assert parse_slurm_time('1:2:3:4') is None

    def test_empty_string_returns_none(self):
        assert parse_slurm_time('') is None

    @pytest.mark.parametrize(
        'value',
        ['abc:def:ghi', '1-abc:00:00', 'foo-bar', '::', '1:2:foo'],
    )
    def test_various_malformed_inputs_return_none(self, value: str):
        assert parse_slurm_time(value) is None


class TestFormatSeconds:
    def test_none_returns_unlimited(self):
        assert format_seconds(None) == 'unlimited'

    def test_seconds_only(self):
        assert format_seconds(45) == '45s'

    def test_seconds_dropped_above_a_minute(self):
        assert format_seconds(90) == '1m'

    def test_hours_and_minutes(self):
        assert format_seconds(3600 + 30 * 60) == '1h30m'

    def test_days(self):
        assert format_seconds(86400) == '1d'

    def test_days_with_hours_minutes(self):
        assert format_seconds(2 * 86400 + 3 * 3600 + 15 * 60) == '2d3h15m'

    def test_negative_clamps_to_zero(self):
        assert format_seconds(-100) == '0s'

    def test_zero(self):
        assert format_seconds(0) == '0s'

    def test_exactly_one_minute(self):
        assert format_seconds(60) == '1m'

    def test_exactly_one_hour(self):
        assert format_seconds(3600) == '1h'


# ---------------------------------------------------------------------------
# iso_to_dt / format_history_end
# ---------------------------------------------------------------------------


class TestIsoToDt:
    def test_valid_iso_datetime(self):
        result = iso_to_dt('2024-01-15T10:30:00')
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10

    def test_unknown_returns_none(self):
        assert iso_to_dt('Unknown') is None

    def test_none_string_returns_none(self):
        assert iso_to_dt('None') is None

    def test_na_returns_none(self):
        assert iso_to_dt('N/A') is None

    def test_empty_string_returns_none(self):
        assert iso_to_dt('') is None

    def test_invalid_format_returns_none(self):
        assert iso_to_dt('not-a-date') is None
        assert iso_to_dt('2024/01/15') is None


class TestFormatHistoryEnd:
    @pytest.mark.parametrize(
        ('end', 'expected'),
        [
            ('2024-03-15T14:30:00', 'today 14:30'),
            ('2024-03-13T09:05:00', 'Wed 09:05'),
            ('2024-01-02T08:00:00', 'Jan 02 08:00'),
            ('2023-12-31T23:59:00', '2023-12-31'),
        ],
    )
    def test_valid_datetime_formatted(self, end, expected):
        now = datetime(2024, 3, 15, 18, 0)
        assert format_history_end(end, now=now) == expected

    def test_nullish_value_returns_dash(self):
        assert format_history_end('Unknown') == '-'
        assert format_history_end('None') == '-'
        assert format_history_end('') == '-'

    def test_non_nullish_unparseable_returned_as_is(self):
        # A non-nullish value that fails iso_to_dt is returned unchanged
        result = format_history_end('some-other-format')
        assert result == 'some-other-format'


class TestFormatPendingStart:
    # Tuesday afternoon
    NOW = datetime(2026, 10, 6, 14, 30)

    def test_later_today_shows_relative_and_weekday(self):
        result = format_pending_start('2026-10-06T16:40:00', now=self.NOW)
        assert result == 'in 2h10m (Tue 16:40)'

    def test_later_this_week_shows_weekday(self):
        result = format_pending_start('2026-10-12T09:15:00', now=self.NOW)
        assert result == 'in 5d18h45m (Mon 09:15)'

    def test_same_weekday_next_week_shows_date(self):
        # A bare "Tue" would be indistinguishable from today
        result = format_pending_start('2026-10-13T09:00:00', now=self.NOW)
        assert result == 'in 6d18h30m (Oct 13 09:00)'

    def test_weeks_away_shows_date(self):
        result = format_pending_start('2026-11-03T08:56:51', now=self.NOW)
        assert result == 'in 27d18h26m (Nov 03 08:56)'

    def test_estimate_in_the_past_is_due(self):
        result = format_pending_start('2026-10-06T14:05:00', now=self.NOW)
        assert result == 'due (Tue 14:05)'

    @pytest.mark.parametrize('value', ['N/A', 'Unknown', '', 'None'])
    def test_no_estimate_returns_none(self, value: str):
        assert format_pending_start(value, now=self.NOW) is None


# ---------------------------------------------------------------------------
# truncate
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_short_string_unchanged(self):
        assert truncate('hello', 10) == 'hello'

    def test_exact_length_unchanged(self):
        assert truncate('hello', 5) == 'hello'

    def test_truncates_with_ellipsis(self):
        result = truncate('hello world', 8)
        assert result == 'hello w…'
        assert len(result) == 8

    def test_zero_width_returns_original(self):
        assert truncate('hello', 0) == 'hello'

    def test_tiny_width_still_marks_the_cut(self):
        assert truncate('hello', 1) == '…'
        assert truncate('hello', 3) == 'he…'

    def test_empty_string_unchanged(self):
        assert truncate('', 5) == ''


# ---------------------------------------------------------------------------
# user_from_userid / is_nullish
# ---------------------------------------------------------------------------


class TestUserFromUserid:
    def test_with_uid_in_parens(self):
        assert user_from_userid('alice(1000)') == 'alice'

    def test_without_uid(self):
        assert user_from_userid('alice') == 'alice'

    def test_empty_string(self):
        assert user_from_userid('') == ''


class TestIsNullish:
    def test_empty_string(self):
        assert is_nullish('') is True

    def test_null_literal(self):
        assert is_nullish('(null)') is True

    def test_none_value(self):
        assert is_nullish(None) is True

    def test_none_string(self):
        assert is_nullish('None') is True

    def test_na(self):
        assert is_nullish('N/A') is True

    def test_unknown(self):
        assert is_nullish('Unknown') is True

    def test_valid_strings_are_not_nullish(self):
        assert is_nullish('gpu001') is False
        assert is_nullish('0') is False
        assert is_nullish('RUNNING') is False
        assert is_nullish('alice') is False

    def test_whitespace_only_is_nullish(self):
        assert is_nullish('   ') is True

    def test_nullish_token_with_surrounding_whitespace(self):
        assert is_nullish('  (null)  ') is True


# ---------------------------------------------------------------------------
# normalize_sacct_state / job_state_is_finished
# ---------------------------------------------------------------------------


class TestNormalizeSacctState:
    def test_simple_state_unchanged(self):
        assert normalize_sacct_state('COMPLETED') == 'COMPLETED'

    def test_state_with_reason_stripped(self):
        assert normalize_sacct_state('CANCELLED by 12345') == 'CANCELLED'

    def test_trailing_plus_stripped(self):
        assert normalize_sacct_state('RUNNING+') == 'RUNNING'

    def test_whitespace_stripped(self):
        assert normalize_sacct_state('  FAILED  ') == 'FAILED'

    def test_node_fail_state(self):
        assert normalize_sacct_state('NODE_FAIL') == 'NODE_FAIL'


class TestJobStateIsFinished:
    @pytest.mark.parametrize(
        'state',
        [
            'COMPLETED',
            'FAILED',
            'CANCELLED',
            'TIMEOUT',
            'OUT_OF_MEMORY',
            'NODE_FAIL',
            'PREEMPTED',
        ],
    )
    def test_terminal_states_are_finished(self, state: str):
        assert job_state_is_finished(state) is True

    @pytest.mark.parametrize('state', ['RUNNING', 'PENDING', 'SUSPENDED', 'COMPLETING'])
    def test_active_states_are_not_finished(self, state: str):
        assert job_state_is_finished(state) is False

    def test_empty_string_is_not_finished(self):
        assert job_state_is_finished('') is False

    def test_cancelled_by_user_format_is_finished(self):
        assert job_state_is_finished('CANCELLED by 12345') is True


# ---------------------------------------------------------------------------
# base_job_id / display_job_id
# ---------------------------------------------------------------------------


class TestBaseJobId:
    def test_simple_job_id(self):
        assert base_job_id('12345') == '12345'

    def test_array_job_id(self):
        assert base_job_id('12345_3') == '12345'

    def test_array_job_with_multi_digit_task(self):
        assert base_job_id('12345_100') == '12345'


class TestDisplayJobId:
    def test_simple_job_no_array(self):
        job = {'JobId': '12345', 'ArrayJobId': 'N/A', 'ArrayTaskId': 'N/A'}
        assert display_job_id(job) == '12345'

    def test_array_job_shown_as_base_task(self):
        job = {'JobId': '12345_3', 'ArrayJobId': '12345', 'ArrayTaskId': '3'}
        assert display_job_id(job) == '12345_3'

    def test_null_array_task_falls_back_to_job_id(self):
        job = {'JobId': '12345', 'ArrayJobId': '12345', 'ArrayTaskId': '(null)'}
        assert display_job_id(job) == '12345'

    def test_na_array_task_falls_back_to_job_id(self):
        job = {'JobId': '12345', 'ArrayJobId': '12345', 'ArrayTaskId': 'N/A'}
        assert display_job_id(job) == '12345'


# ---------------------------------------------------------------------------
# is_success_exit_code / format_mem_value
# ---------------------------------------------------------------------------


class TestIsSuccessExitCode:
    def test_zero_zero_is_success(self):
        assert is_success_exit_code('0:0') is True

    def test_nonzero_status_is_failure(self):
        assert is_success_exit_code('1:0') is False

    def test_nonzero_signal_is_failure(self):
        assert is_success_exit_code('0:9') is False

    def test_empty_string_is_failure(self):
        assert is_success_exit_code('') is False

    def test_no_colon_is_failure(self):
        assert is_success_exit_code('0') is False

    def test_nullish_is_failure(self):
        assert is_success_exit_code('(null)') is False

    @pytest.mark.parametrize('code', ['1:0', '2:0', '127:0', '137:0'])
    def test_nonzero_exit_codes(self, code: str):
        assert is_success_exit_code(code) is False


class TestFormatMemValue:
    def test_numeric_mb_string_converted(self):
        assert format_mem_value('2048') == '2G'

    def test_value_with_unit_suffix_returned_as_is(self):
        assert format_mem_value('16G') == '16G'
        assert format_mem_value('1T') == '1T'

    def test_null_returns_dash(self):
        assert format_mem_value('(null)') == '-'
        assert format_mem_value(None) == '-'
        assert format_mem_value('') == '-'
        assert format_mem_value('N/A') == '-'


# ---------------------------------------------------------------------------
# sort_partitions
# ---------------------------------------------------------------------------


class TestSortPartitions:
    @staticmethod
    def _sorted(*parts: tuple[str, str]) -> list[str]:
        partitions = [{'PartitionName': n, 'MaxTime': t} for n, t in parts]
        remember_nodes([{'NodeName': 'g1', 'Gres': 'gpu:4', 'Partitions': 'gpumicro,gpushort,gpusmall,gpu,gpu-a100,gpu-a100:test,gpu-h200,gpu-h200:test'}])
        return [p['PartitionName'] for p in sort_partitions(partitions)]

    def test_allegro_order(self):
        allegro = [
            ('big', '7-00:00:00'), ('gpu', '2-00:00:00'), ('micro', '01:00:00'),
            ('small', '2-02:00:00'), ('gpushort', '04:00:00'), ('amd', '2-00:00:00'),
            ('gpumicro', '01:00:00'), ('gpusmall', '1-00:00:00'),
        ]
        assert self._sorted(*allegro) == [
            'gpumicro', 'gpushort', 'gpusmall', 'gpu', 'micro', 'amd', 'small', 'big'
        ]

    def test_family_stays_together(self):
        assert self._sorted(
            ('gpu-h200', '2-00:00:00'), ('gpu-a100', '2-00:00:00'),
            ('gpu-h200:test', '01:00:00'), ('gpu-a100:test', '01:00:00'),
            ('forever', 'UNLIMITED'),
        ) == ['gpu-a100:test', 'gpu-a100', 'gpu-h200:test', 'gpu-h200', 'forever']


# ---------------------------------------------------------------------------
# resolve_slurm_output_path — path template substitution
# ---------------------------------------------------------------------------


class TestResolveSlurmOutputPath:
    def test_path_without_substitution(self):
        path = resolve_slurm_output_path('/home/user/output.txt', '12345')
        assert path is not None
        assert str(path) == '/home/user/output.txt'

    def test_capital_J_substituted_with_full_job_id(self):
        path = resolve_slurm_output_path('/home/user/job-%J.out', '12345')
        assert path is not None
        assert str(path) == '/home/user/job-12345.out'

    def test_lowercase_j_substituted_with_base_job_id(self):
        path = resolve_slurm_output_path('/home/user/job-%j.out', '12345_3')
        assert path is not None
        assert str(path) == '/home/user/job-12345.out'

    def test_A_substituted_with_base_job_id(self):
        path = resolve_slurm_output_path('/home/user/job-%A_%a.out', '12345_3')
        assert path is not None
        assert str(path) == '/home/user/job-12345_3.out'

    def test_null_template_returns_none(self):
        assert resolve_slurm_output_path('(null)', '12345') is None
        assert resolve_slurm_output_path('', '12345') is None

    def test_tilde_expanded(self):
        path = resolve_slurm_output_path('~/slurm-output/job-%j.out', '12345')
        assert path is not None
        home = os.path.expanduser('~')
        assert str(path).startswith(home)

    def test_percent_escape_padding_and_unknown_patterns(self):
        path = resolve_slurm_output_path('/out/100%%-%4a-%N.out', '7_3')
        assert str(path) == '/out/100%-0003-%N.out'

    def test_non_array_job_a_substituted_with_zero(self):
        # For non-array jobs, %a should resolve to "0"
        path = resolve_slurm_output_path('/out/%A_%a.out', '12345')
        assert path is not None
        assert str(path) == '/out/12345_0.out'


def test_old_slurm_string_node_state_keeps_its_flags():
    from allegro_buddy.core import node_is_usable, nodes_from_json

    raw = '{"nodes": [{"name": "n1", "state": "down", "state_flags": ["DRAIN"]}]}'
    node = nodes_from_json(raw)[0]
    assert node['State'] == 'DOWN+DRAIN'
    assert not node_is_usable(node)


def test_history_shows_array_task_ids_like_ab_q():
    from allegro_buddy.core import build_job_history_rows

    row = build_job_history_rows([{'JobId': '130', 'JobID': '123_7', 'State': 'COMPLETED'}])[0]
    assert str(row[0]) == '123_7'
