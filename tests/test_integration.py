"""Optional integration tests that run against a real Slurm cluster.

These tests are SKIPPED by default.  Run them with:

    pytest --cluster

They submit lightweight, near-instant jobs to verify the tool is compatible
with the cluster's current Slurm version and configuration.

Requirements:
- A working Slurm installation (scontrol, sacct, squeue, sbatch, scancel)
- At least one accessible partition
- The running user must have permission to submit jobs
"""
from __future__ import annotations

import shutil
import subprocess
import time

import pytest

import allegro_buddy.core as core
from allegro_buddy.core import (
    expand_nodelist,
    get_accessible_partitions,
    get_user_job_history,
    load_nodes,
    load_partitions,
    load_reservations,
)

# All tests in this module require --cluster
pytestmark = pytest.mark.cluster


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slurm_cmd_available(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _require_cmd(cmd: str):
    if not _slurm_cmd_available(cmd):
        pytest.skip(f'{cmd} not found — not on a Slurm cluster')


def _scontrol(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['scontrol', *args],
        capture_output=True,
        text=True,
        timeout=15,
    )


def _squeue(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['squeue', *args],
        capture_output=True,
        text=True,
        timeout=15,
    )


def _sacct(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['sacct', *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _sbatch_test_job(partition: str, extra_args: list[str] | None = None) -> str:
    """Submit a minimal sleep job and return the job ID."""
    cmd = [
        'sbatch',
        '--parsable',
        f'--partition={partition}',
        '--job-name=ab-compat-test',
        '--ntasks=1',
        '--cpus-per-task=1',
        '--mem=512M',
        '--time=00:02:00',
        '--output=/dev/null',
        '--error=/dev/null',
        '--wrap=sleep 5',
    ]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        pytest.skip(f'sbatch failed: {result.stderr.strip()} — cannot run cluster tests')
    job_id = result.stdout.strip().split(';')[0]
    assert job_id.isdigit(), f'unexpected sbatch output: {result.stdout!r}'
    return job_id


def _scancel(job_id: str) -> None:
    subprocess.run(['scancel', job_id], capture_output=True, timeout=10)


# ---------------------------------------------------------------------------
# Slurm command availability
# ---------------------------------------------------------------------------


class TestSlurmCommandAvailability:
    """Verify that all required Slurm commands are present on the cluster."""

    @pytest.mark.parametrize(
        'cmd',
        ['scontrol', 'squeue', 'sacct', 'sacctmgr', 'sbatch', 'scancel', 'srun', 'sshare'],
    )
    def test_command_available(self, cmd: str):
        assert shutil.which(cmd) is not None, (
            f'{cmd} not found in PATH — is Slurm installed?'
        )

    def test_scontrol_version_parseable(self):
        _require_cmd('scontrol')
        result = _scontrol('--version')
        assert result.returncode == 0
        assert 'slurm' in result.stdout.lower()


# ---------------------------------------------------------------------------
# scontrol output format compatibility
# ---------------------------------------------------------------------------


class TestScontrolPartitionOutput:
    """scontrol --oneliner show partition output format."""

    def setup_method(self):
        _require_cmd('scontrol')

    def test_load_partitions_returns_nonempty_list(self):
        partitions = load_partitions()
        assert len(partitions) > 0, 'no partitions found — is the cluster configured?'

    def test_each_partition_has_required_fields(self):
        partitions = load_partitions()
        required_fields = ['PartitionName', 'State', 'MaxTime', 'AllowGroups']
        for partition in partitions:
            for field in required_fields:
                assert field in partition, (
                    f'partition {partition.get("PartitionName", "?")} missing field {field!r}'
                )

    def test_partition_names_are_nonempty(self):
        for p in load_partitions():
            assert p['PartitionName'], 'empty PartitionName in scontrol output'

    def test_max_time_parseable(self):
        for p in load_partitions():
            max_time = p.get('MaxTime', '')
            result = core.parse_slurm_time(max_time)
            # Should be either an int (seconds) or None (unlimited)
            assert result is None or isinstance(result, int), (
                f'MaxTime={max_time!r} in partition {p.get("PartitionName")} is not parseable'
            )

    def test_accessible_partitions_nonempty(self):
        partitions = get_accessible_partitions()
        assert len(partitions) > 0, (
            'no accessible partitions found for current user'
        )


class TestScontrolNodeOutput:
    """scontrol --oneliner show node output format."""

    def setup_method(self):
        _require_cmd('scontrol')

    def test_load_nodes_returns_nonempty_list(self):
        nodes = load_nodes()
        assert len(nodes) > 0, 'no nodes found — is the cluster populated?'

    def test_each_node_has_required_fields(self):
        nodes = load_nodes()
        required_fields = ['NodeName', 'State', 'CPUTot', 'RealMemory']
        for node in nodes:
            for field in required_fields:
                assert field in node, (
                    f'node {node.get("NodeName", "?")} missing field {field!r}'
                )

    def test_cpu_tot_is_parseable_int(self):
        for node in load_nodes():
            val = node.get('CPUTot', '0')
            parsed = core.parse_int(val)
            assert isinstance(parsed, int)
            assert parsed >= 0, f'CPUTot={val!r} parsed to negative number'

    def test_real_memory_is_parseable_mb(self):
        for node in load_nodes():
            val = node.get('RealMemory', '0')
            parsed_gb = core.parse_mb_to_gb(val)
            assert parsed_gb >= 0

    def test_node_state_classification(self):
        for node in load_nodes():
            core.node_is_usable(node)
            core.node_is_idle(node)
            core.node_is_mixed(node)

    def test_gpu_nodes_have_parseable_gres(self):
        for node in load_nodes():
            gres = node.get('Gres', '')
            if not gres or gres in {'(null)', 'N/A'}:
                continue
            if 'gpu' not in gres.lower():
                continue
            counts = core.parse_gpu_type_counts(gres)
            total = sum(counts.values())
            assert total > 0, (
                f'node {node["NodeName"]} has Gres={gres!r} but parsed 0 GPUs'
            )


# ---------------------------------------------------------------------------
# sacct output format compatibility
# ---------------------------------------------------------------------------


class TestSacctOutput:
    """sacct job history output format."""

    def setup_method(self):
        _require_cmd('sacct')

    def test_load_job_history_does_not_raise(self):
        # May return empty list for a fresh user, but must not error
        history = get_user_job_history(finished_only=False, strict=False)
        assert isinstance(history, list)

    def test_job_history_fields_present(self):
        history = get_user_job_history(finished_only=False, strict=False)
        if not history:
            pytest.skip('no job history available for current user')
        required_fields = ['JobId', 'JobName', 'State', 'ExitCode', 'End']
        for job in history[:5]:
            for field in required_fields:
                assert field in job, f'job {job.get("JobId", "?")} missing {field!r}'

    def test_job_state_tokens_normalized(self):
        history = get_user_job_history(finished_only=False, strict=False)
        for job in history:
            token = job.get('StateToken', '')
            # StateToken must not contain spaces (raw "CANCELLED by 1234" not allowed)
            assert ' ' not in token, f'StateToken {token!r} not normalized'

    def test_history_sorted_newest_first(self):
        history = get_user_job_history(finished_only=True, strict=False)
        if len(history) < 2:
            pytest.skip('need at least 2 finished jobs to test sort order')
        for i in range(len(history) - 1):
            end_a = core.iso_to_dt(history[i].get('End', ''))
            end_b = core.iso_to_dt(history[i + 1].get('End', ''))
            if end_a is not None and end_b is not None:
                assert end_a >= end_b, 'job history is not sorted newest-first'


# ---------------------------------------------------------------------------
# Live job submission (lightweight, cleans up after itself)
# ---------------------------------------------------------------------------


class TestLiveJobSubmission:
    """Submit a minimal job, verify tool can observe it, then cancel it."""

    def setup_method(self):
        for cmd in ('sbatch', 'scontrol', 'squeue', 'scancel'):
            _require_cmd(cmd)
        self._submitted_job_ids: list[str] = []

    def teardown_method(self):
        for job_id in self._submitted_job_ids:
            _scancel(job_id)

    def _submit(self, partition: str) -> str:
        job_id = _sbatch_test_job(partition)
        self._submitted_job_ids.append(job_id)
        return job_id

    def _first_accessible_partition(self) -> str:
        partitions = get_accessible_partitions()
        if not partitions:
            pytest.skip('no accessible partition found')
        return partitions[0]['PartitionName']

    def test_submitted_job_visible_in_scontrol(self):
        partition = self._first_accessible_partition()
        job_id = self._submit(partition)

        detail = core.get_job_detail(job_id)
        assert detail is not None, f'scontrol could not find job {job_id}'

    def test_submitted_job_has_correct_name(self):
        partition = self._first_accessible_partition()
        job_id = self._submit(partition)

        detail = core.get_job_detail(job_id)
        assert detail is not None
        assert detail.get('JobName') == 'ab-compat-test', (
            f'expected JobName=ab-compat-test, got {detail.get("JobName")!r}'
        )

    def test_submitted_job_state_parseable(self):
        partition = self._first_accessible_partition()
        job_id = self._submit(partition)

        detail = core.get_job_detail(job_id)
        assert detail is not None
        state = detail.get('JobState', '')
        assert state in core.NON_TERMINAL_JOB_STATES | {'RUNNING', 'PENDING', 'COMPLETING'}, (
            f'unexpected job state {state!r} for freshly submitted job'
        )

    def test_submitted_job_squeue_format_parseable(self):
        partition = self._first_accessible_partition()
        job_id = self._submit(partition)

        # Verify squeue output for this job is parseable
        result = _squeue(
            '-h',
            f'--job={job_id}',
            '--format=%i|%j|%P|%l|%R',
        )
        assert result.returncode == 0
        rows = core.parse_pipe_rows(result.stdout, ['JobID', 'Name', 'Partition', 'TimeLimit', 'Reason'])
        # Job might have already completed, so allow empty
        for row in rows:
            assert row['JobID'] == job_id

    def test_cancel_removes_job_from_active(self):
        partition = self._first_accessible_partition()
        job_id = self._submit(partition)

        _scancel(job_id)
        self._submitted_job_ids.remove(job_id)

        # Brief wait for Slurm state propagation
        time.sleep(2)
        detail = core.get_job_detail(job_id)
        if detail is not None:
            state = detail.get('JobState', '')
            # After cancel, job should be in a terminal or cancelling state
            assert state not in {'PENDING', 'RUNNING'}, (
                f'job {job_id} still active after scancel: state={state!r}'
            )

    def test_sacct_records_completed_job(self):
        _require_cmd('sacct')
        partition = self._first_accessible_partition()
        job_id = self._submit(partition)
        _scancel(job_id)
        self._submitted_job_ids.remove(job_id)

        # Wait a few seconds for sacct to record the job
        time.sleep(5)
        result = _sacct(
            '--parsable2',
            '--noheader',
            '-X',
            f'--jobs={job_id}',
            '--format=JobIDRaw,JobName,State,ExitCode,End',
        )
        # sacct may fail if slurmdbd is unavailable — that's a skip, not a failure
        if result.returncode != 0:
            pytest.skip(f'sacct failed: {result.stderr.strip()}')

        rows = core.parse_pipe_rows(
            result.stdout,
            ['JobIDRaw', 'JobName', 'State', 'ExitCode', 'End'],
        )
        assert any(r['JobIDRaw'] == job_id for r in rows), (
            f'job {job_id} not found in sacct output after cancellation'
        )


# ---------------------------------------------------------------------------
# Reservation format compatibility
# ---------------------------------------------------------------------------


class TestReservationOutput:
    """scontrol show reservation output format."""

    def setup_method(self):
        _require_cmd('scontrol')

    def test_load_reservations_does_not_raise(self):
        resvs = load_reservations()
        assert isinstance(resvs, list)

    def test_reservation_fields_present(self):
        resvs = load_reservations()
        if not resvs:
            pytest.skip('no reservations configured on this cluster')
        required_fields = ['ReservationName', 'State', 'StartTime', 'EndTime']
        for resv in resvs:
            for field in required_fields:
                assert field in resv, f'reservation missing field {field!r}'

    def test_reservation_nodes_expandable(self):
        resvs = load_reservations()
        for resv in resvs:
            nodes_str = resv.get('Nodes', '')
            if not nodes_str or core.is_nullish(nodes_str):
                continue
            # expand_nodelist must not raise
            nodes = expand_nodelist(nodes_str)
            assert isinstance(nodes, list)
