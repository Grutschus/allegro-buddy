"""Tests for PartitionStats aggregation, node/partition state checks,
access control, reservation logic, and job history presentation.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from allegro_buddy.core import (
    active_reservations,
    build_dev_job_rows,
    build_job_history_rows,
    empty_partition_stats,
    node_is_idle,
    node_is_mixed,
    node_is_usable,
    partition_allowed,
    recent_active_reservations,
    reservation_blocked_pending_jobs,
    upcoming_reservations,
    user_can_use_reservation,
)

# ---------------------------------------------------------------------------
# PartitionStats creation and merging
# ---------------------------------------------------------------------------


class TestEmptyPartitionStats:
    def test_all_scalar_fields_are_zero(self):
        stats = empty_partition_stats()
        for key in ('nodes', 'idle_nodes', 'cpu_total', 'cpu_free',
                    'mem_total_gb', 'mem_free_gb', 'gpu_total', 'gpu_free', 'gpu_usable'):
            assert stats[key] == 0, f'field {key!r} should be 0'

    def test_all_dict_fields_are_empty(self):
        stats = empty_partition_stats()
        for key in ('gpu_total_by_type', 'gpu_free_by_type', 'gpu_usable_by_type'):
            assert stats[key] == {}, f'field {key!r} should be {{}}'


class TestNodeIsUsable:
    @pytest.mark.parametrize('state', ['IDLE', 'MIXED', 'ALLOCATED', 'COMPLETING'])
    def test_healthy_states_are_usable(self, state: str):
        assert node_is_usable({'State': state}) is True

    @pytest.mark.parametrize(
        'state',
        ['DOWN', 'IDLE+DRAIN', 'FAIL', 'MAINT', 'REBOOT', 'INVAL'],
    )
    def test_bad_flag_states_are_not_usable(self, state: str):
        assert node_is_usable({'State': state}) is False

    def test_down_flag_mixed_in_state_string(self):
        assert node_is_usable({'State': 'MIXED+DRAINING'}) is False

    def test_missing_state_key_treated_as_usable(self):
        # Empty state string has no bad flags
        assert node_is_usable({}) is True


class TestNodeIsIdle:
    def test_idle_state(self):
        assert node_is_idle({'State': 'IDLE'}) is True

    def test_idle_completing_contains_idle(self):
        assert node_is_idle({'State': 'IDLE+COMPLETING'}) is True

    def test_mixed_is_not_idle(self):
        assert node_is_idle({'State': 'MIXED'}) is False

    def test_allocated_is_not_idle(self):
        assert node_is_idle({'State': 'ALLOCATED'}) is False

    def test_down_is_not_idle(self):
        assert node_is_idle({'State': 'DOWN'}) is False


class TestNodeIsMixed:
    def test_mixed_state(self):
        assert node_is_mixed({'State': 'MIXED'}) is True

    def test_mixed_draining_contains_mixed(self):
        assert node_is_mixed({'State': 'MIXED+DRAINING'}) is True

    def test_idle_is_not_mixed(self):
        assert node_is_mixed({'State': 'IDLE'}) is False

    def test_allocated_is_not_mixed(self):
        assert node_is_mixed({'State': 'ALLOCATED'}) is False


# ---------------------------------------------------------------------------
# Partition access control
# ---------------------------------------------------------------------------


class TestPartitionAllowed:
    def test_all_groups_allows_everyone(self):
        partition = {'AllowGroups': 'ALL'}
        assert partition_allowed(partition, {'students', 'users'}) is True

    def test_user_group_in_allowed_list(self):
        partition = {'AllowGroups': 'gpu_users,researchers'}
        assert partition_allowed(partition, {'gpu_users', 'students'}) is True

    def test_user_group_not_in_allowed_list(self):
        partition = {'AllowGroups': 'gpu_users'}
        assert partition_allowed(partition, {'students'}) is False

    def test_empty_groups_denied(self):
        partition = {'AllowGroups': 'gpu_users'}
        assert partition_allowed(partition, set()) is False

    def test_missing_allow_groups_key_defaults_to_all(self):
        # get("AllowGroups", "ALL") — default is ALL
        assert partition_allowed({}, set()) is True

    def test_multiple_allowed_groups_any_match_sufficient(self):
        partition = {'AllowGroups': 'groupA,groupB,groupC'}
        assert partition_allowed(partition, {'groupB'}) is True


# ---------------------------------------------------------------------------
# Reservation access control
# ---------------------------------------------------------------------------


class TestUserCanUseReservation:
    def test_user_explicitly_listed(self):
        resv = {'Users': 'alice,bob,carol', 'Groups': ''}
        assert user_can_use_reservation(resv, 'alice', set()) is True

    def test_user_not_in_users_list(self):
        resv = {'Users': 'alice,bob', 'Groups': ''}
        assert user_can_use_reservation(resv, 'carol', set()) is False

    def test_group_access_when_no_users(self):
        resv = {'Users': '', 'Groups': 'researchers'}
        assert user_can_use_reservation(resv, 'alice', {'researchers'}) is True

    def test_group_not_allowed(self):
        resv = {'Users': '', 'Groups': 'researchers'}
        assert user_can_use_reservation(resv, 'alice', {'students'}) is False

    def test_null_users_falls_through_to_groups(self):
        resv = {'Users': '(null)', 'Groups': 'researchers'}
        assert user_can_use_reservation(resv, 'alice', {'researchers'}) is True

    def test_null_users_and_null_groups_denies_all(self):
        resv = {'Users': '(null)', 'Groups': '(null)'}
        assert user_can_use_reservation(resv, 'alice', {'everyone'}) is False


# ---------------------------------------------------------------------------
# Reservation filtering helpers
# ---------------------------------------------------------------------------


class TestActiveReservations:
    def test_active_reservation_included(self):
        resvs = [{'ReservationName': 'maint1', 'State': 'ACTIVE'}]
        assert len(active_reservations(resvs)) == 1

    def test_inactive_reservation_excluded(self):
        resvs = [{'ReservationName': 'future', 'State': 'INACTIVE'}]
        assert active_reservations(resvs) == []

    def test_case_insensitive_state_matching(self):
        resvs = [{'ReservationName': 'x', 'State': 'active'}]
        assert len(active_reservations(resvs)) == 1

    def test_mixed_list(self):
        resvs = [
            {'ReservationName': 'maint', 'State': 'ACTIVE'},
            {'ReservationName': 'future', 'State': 'INACTIVE'},
        ]
        result = active_reservations(resvs)
        assert len(result) == 1
        assert result[0]['ReservationName'] == 'maint'


class TestUpcomingReservations:
    def test_future_inactive_included(self):
        future = (datetime.now() + timedelta(days=1)).isoformat()
        resvs = [{'State': 'INACTIVE', 'StartTime': future}]
        assert len(upcoming_reservations(resvs)) == 1

    def test_past_inactive_excluded(self):
        past = (datetime.now() - timedelta(days=1)).isoformat()
        resvs = [{'State': 'INACTIVE', 'StartTime': past}]
        assert upcoming_reservations(resvs) == []

    def test_active_reservation_not_upcoming(self):
        future = (datetime.now() + timedelta(days=1)).isoformat()
        resvs = [{'State': 'ACTIVE', 'StartTime': future}]
        assert upcoming_reservations(resvs) == []


class TestRecentActiveReservations:
    def test_recent_active_included(self):
        # Started just now
        now_iso = datetime.now().isoformat()
        resvs = [{'State': 'ACTIVE', 'StartTime': now_iso}]
        assert len(recent_active_reservations(resvs)) == 1

    def test_very_old_active_excluded(self):
        old = (datetime.now() - timedelta(days=60)).isoformat()
        resvs = [{'State': 'ACTIVE', 'StartTime': old}]
        assert recent_active_reservations(resvs) == []

    def test_active_without_start_time_included(self):
        # No StartTime — treated as recent
        resvs = [{'State': 'ACTIVE', 'StartTime': ''}]
        assert len(recent_active_reservations(resvs)) == 1


class TestReservationBlockedPendingJobs:
    def test_job_blocked_by_maintenance_phrase(self):
        resvs: list[dict[str, str]] = []
        jobs = [{'JobID': '101', 'Reason': 'reserved for maintenance'}]
        result = reservation_blocked_pending_jobs(resvs, jobs)
        assert len(result) == 1

    def test_job_blocked_by_reservation_name_in_reason(self):
        resvs = [{'ReservationName': 'maint2025'}]
        jobs = [{'JobID': '102', 'Reason': 'ReqNodeNotAvail,maint2025'}]
        result = reservation_blocked_pending_jobs(resvs, jobs)
        assert len(result) == 1

    def test_unrelated_pending_job_not_included(self):
        resvs = [{'ReservationName': 'maintenance'}]
        jobs = [{'JobID': '103', 'Reason': 'Resources'}]
        assert reservation_blocked_pending_jobs(resvs, jobs) == []

    def test_empty_inputs(self):
        assert reservation_blocked_pending_jobs([], []) == []

    @pytest.mark.parametrize(
        ('name', 'reason'),
        [('res', 'Resources'), ('gpu', 'ReqNodeNotAvail, UnavailableNodes:gpu[101-102]')],
    )
    def test_name_inside_another_word_is_not_a_match(self, name, reason):
        resvs = [{'ReservationName': name}]
        jobs = [{'JobID': '104', 'Reason': reason}]
        assert reservation_blocked_pending_jobs(resvs, jobs) == []


# ---------------------------------------------------------------------------
# build_job_history_rows — constructs table rows for job history display
# ---------------------------------------------------------------------------


class TestBuildJobHistoryRows:
    def test_returns_one_row_per_job(
        self,
        job_history_completed,
        job_history_failed,
    ):
        rows = build_job_history_rows([job_history_completed, job_history_failed])
        assert len(rows) == 2

    def test_empty_list_returns_empty(self):
        assert build_job_history_rows([]) == []

    def test_row_has_expected_column_count(self, job_history_completed):
        rows = build_job_history_rows([job_history_completed])
        # JobID, Name, State, Exit, Ended
        assert len(rows[0]) == 5


# ---------------------------------------------------------------------------
# build_dev_job_rows — constructs table rows for dev job status display
# ---------------------------------------------------------------------------


class TestBuildDevJobRows:
    def test_returns_one_row_per_job(self, job_running):
        rows = build_dev_job_rows([job_running])
        assert len(rows) == 1

    def test_empty_list_returns_empty(self):
        assert build_dev_job_rows([]) == []

    def test_row_has_expected_column_count(self, job_running):
        rows = build_dev_job_rows([job_running])
        # JobID, State, Partition, Node, CPUs, Mem, GPUs, Detail — 8 columns
        assert len(rows[0]) == 8

    def test_pending_job_shows_reason_as_detail(self, job_pending):
        rows = build_dev_job_rows([job_pending])
        assert len(rows) == 1
        # Last column is detail; for pending jobs it should be the Reason
        detail = rows[0][-1]
        assert detail == 'Resources' or str(detail) == 'Resources'
