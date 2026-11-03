"""The dev handlers' calls into Slurm: what gets cancelled, submitted and executed."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from allegro_buddy.handlers import dev as dev_handler

RUNNING_DEV_JOB = {
    'JobId': '111',
    'JobName': 'ab-dev',
    'JobState': 'RUNNING',
    'NodeList': 'gpu001',
}


def start(**overrides):
    kwargs = {
        'partition': 'gpu',
        'time_limit': '08:00:00',
        'gpu': 2,
        'gpu_type': None,
        'cpus': 4,
        'mem': '8G',
        'account': None,
        'constraint': None,
        'exclude': None,
        'node': None,
        'replace': False,
        'no_wait': True,
        'login': False,
        'timeout': None,
        'poll_interval': 5.0,
        **overrides,
    }
    dev_handler.cmd_dev_start(**kwargs)


@pytest.fixture
def slurm(tmp_path):
    with (
        patch.object(dev_handler, 'dev_log_dir', return_value=tmp_path),
        patch.object(dev_handler, 'find_dev_jobs', return_value=[RUNNING_DEV_JOB]),
        patch.object(dev_handler, 'choose_partition', return_value='gpu'),
        patch.object(dev_handler, 'is_gpu_partition', return_value=True),
        patch.object(dev_handler, 'get_job_detail', return_value=None),
        patch.object(dev_handler, 'time'),
        patch.object(
            dev_handler, 'run', return_value=SimpleNamespace(stdout='222\n')
        ) as run,
    ):
        yield run


def test_replace_with_bad_partition_never_cancels(slurm):
    with (
        patch.object(dev_handler, 'choose_partition', side_effect=SystemExit(1)),
        pytest.raises(SystemExit),
    ):
        start(replace=True, partition='gpuu')
    slurm.assert_not_called()


def test_replace_cancels_then_submits(slurm):
    start(replace=True)
    argvs = [call.args[0] for call in slurm.call_args_list]
    assert argvs[0] == ['scancel', '111']
    assert argvs[1][0] == 'sbatch'


def test_sbatch_argv_for_gpu_request(slurm):
    with patch.object(dev_handler, 'find_dev_jobs', return_value=[]):
        start()
    argv = slurm.call_args.args[0]
    assert argv[:2] == ['sbatch', '--parsable']
    assert '--partition=gpu' in argv
    assert '--gres=gpu:2' in argv
    assert '--cpus-per-gpu=2' in argv
    assert '--time=08:00:00' in argv


def test_start_login_uses_dev_login(slurm):
    with (
        patch.object(dev_handler, 'find_dev_jobs', return_value=[]),
        patch.object(dev_handler, 'wait_for_job_running', return_value=RUNNING_DEV_JOB),
        patch.object(dev_handler, 'cmd_dev_login') as login,
    ):
        start(no_wait=False, login=True)
    assert login.call_args.kwargs['jobid'] == '222'


def test_login_command_is_one_quoted_remote_string():
    with (
        patch.object(dev_handler, 'pick_single_dev_job', return_value=RUNNING_DEV_JOB),
        patch.object(dev_handler, 'exec_replace', side_effect=SystemExit) as exec_,
        pytest.raises(SystemExit),
    ):
        dev_handler.cmd_dev_login(
            jobid=None,
            wait=False,
            timeout=None,
            poll_interval=5.0,
            srun=False,
            command='cd x && make',
        )
    assert exec_.call_args.args[0] == ['ssh', '-t', 'gpu001', "bash -lc 'cd x && make'"]


def test_login_to_pending_job_exits_nonzero():
    pending = RUNNING_DEV_JOB | {'JobState': 'PENDING', 'Reason': 'Priority'}
    with (
        patch.object(dev_handler, 'pick_single_dev_job', return_value=pending),
        patch.object(dev_handler, 'exec_replace') as exec_replace,
        pytest.raises(SystemExit) as exit_info,
    ):
        dev_handler.cmd_dev_login(
            jobid=None,
            wait=False,
            timeout=None,
            poll_interval=5.0,
            srun=False,
            command='make',
        )
    assert exit_info.value.code == 1
    exec_replace.assert_not_called()


def test_completing_dev_job_no_longer_counts():
    from allegro_buddy import core

    jobs = [
        RUNNING_DEV_JOB | {'JobState': 'COMPLETING'},
        RUNNING_DEV_JOB | {'JobId': '222'},
    ]
    with patch.object(core, 'get_user_jobs', return_value=jobs):
        assert [j['JobId'] for j in core.find_dev_jobs('alice')] == ['222']
