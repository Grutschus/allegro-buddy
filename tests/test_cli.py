"""CLI integration tests using Click's CliRunner.

Tests verify command routing, option handling, and that each subcommand
calls the expected handler.  Handlers are patched so no Slurm calls are made.
"""

from __future__ import annotations

from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner
from slurm_records import node_dict

from allegro_buddy.cli import main
from allegro_buddy.core import remember_nodes


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# Help text — every command must produce usage text with exit 0
# ---------------------------------------------------------------------------


class TestHelpText:
    def test_main_help(self, runner: CliRunner):
        result = runner.invoke(main, ['--help'])
        assert result.exit_code == 0
        assert 'Usage' in result.output

    def test_version(self, runner: CliRunner):
        result = runner.invoke(main, ['--version'])
        assert result.exit_code == 0
        assert 'version' in result.output

    def test_main_short_help_flag(self, runner: CliRunner):
        result = runner.invoke(main, ['-h'])
        assert result.exit_code == 0

    def test_info_help(self, runner: CliRunner):
        result = runner.invoke(main, ['info', '--help'])
        assert result.exit_code == 0
        assert '--all-partitions' in result.output

    def test_queue_help(self, runner: CliRunner):
        result = runner.invoke(main, ['queue', '--help'])
        assert result.exit_code == 0
        assert '--all' in result.output

    def test_q_alias_help(self, runner: CliRunner):
        result = runner.invoke(main, ['q', '--help'])
        assert result.exit_code == 0

    def test_free_help(self, runner: CliRunner):
        result = runner.invoke(main, ['free', '--help'])
        assert result.exit_code == 0
        assert '--nodes' in result.output

    def test_node_help(self, runner: CliRunner):
        result = runner.invoke(main, ['node', '--help'])
        assert result.exit_code == 0

    def test_gpualloc_is_a_hidden_alias_of_node(self, runner: CliRunner):
        assert 'gpualloc' not in runner.invoke(main, ['-h']).output
        with patch('allegro_buddy.cli.cmd_node') as mock:
            runner.invoke(main, ['gpualloc', 'gpu042'])
            mock.assert_called_once_with(node='gpu042')

    def test_job_group_help(self, runner: CliRunner):
        result = runner.invoke(main, ['job', '--help'])
        assert result.exit_code == 0
        assert 'history' in result.output
        assert 'output' in result.output

    def test_job_history_help(self, runner: CliRunner):
        result = runner.invoke(main, ['job', 'history', '--help'])
        assert result.exit_code == 0
        assert '--limit' in result.output

    def test_job_output_help(self, runner: CliRunner):
        result = runner.invoke(main, ['job', 'output', '--help'])
        assert result.exit_code == 0
        assert '--stderr' in result.output

    def test_dev_group_help(self, runner: CliRunner):
        result = runner.invoke(main, ['dev', '--help'])
        assert result.exit_code == 0
        assert 'start' in result.output
        assert 'login' in result.output
        assert 'stop' in result.output

    def test_dev_start_help(self, runner: CliRunner):
        result = runner.invoke(main, ['dev', 'start', '--help'])
        assert result.exit_code == 0
        assert '--partition' in result.output
        assert '--gpu' in result.output

    def test_dev_status_help(self, runner: CliRunner):
        result = runner.invoke(main, ['dev', 'status', '--help'])
        assert result.exit_code == 0

    def test_dev_login_help(self, runner: CliRunner):
        result = runner.invoke(main, ['dev', 'login', '--help'])
        assert result.exit_code == 0
        assert '--wait' in result.output

    def test_dev_stop_help(self, runner: CliRunner):
        result = runner.invoke(main, ['dev', 'stop', '--help'])
        assert result.exit_code == 0

    def test_l_shortcut_help(self, runner: CliRunner):
        result = runner.invoke(main, ['l', '--help'])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Command routing — verify each command calls its handler
# ---------------------------------------------------------------------------


class TestInfoCommand:
    def test_info_calls_cmd_info(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_info') as mock:
            runner.invoke(main, ['info'])
        mock.assert_called_once()

    def test_info_default_all_partitions_false(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_info') as mock:
            runner.invoke(main, ['info'])
        mock.assert_called_once_with(all_partitions=False)

    def test_info_all_partitions_flag(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_info') as mock:
            runner.invoke(main, ['info', '--all-partitions'])
        mock.assert_called_once_with(all_partitions=True)

    def test_bare_invocation_calls_info(self, runner: CliRunner):
        # Running `ab` with no subcommand invokes info
        with patch('allegro_buddy.cli.cmd_info') as mock:
            runner.invoke(main, [])
        mock.assert_called_once()


class TestQueueCommand:
    def test_queue_calls_cmd_queue(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_queue') as mock:
            runner.invoke(main, ['queue'])
        mock.assert_called_once()

    def test_queue_default_options(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_queue') as mock:
            runner.invoke(main, ['queue'])
        mock.assert_called_once_with(all_users=False, user=None, partition=None)

    def test_queue_all_flag(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_queue') as mock:
            runner.invoke(main, ['queue', '--all'])
        mock.assert_called_once_with(all_users=True, user=None, partition=None)

    def test_queue_user_option(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_queue') as mock:
            runner.invoke(main, ['queue', '--user', 'alice'])
        mock.assert_called_once_with(all_users=False, user='alice', partition=None)

    def test_queue_partition_option(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_queue') as mock:
            runner.invoke(main, ['queue', '-p', 'gpusmall'])
        mock.assert_called_once_with(all_users=False, user=None, partition='gpusmall')

    def test_q_alias_calls_same_handler(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_queue') as mock:
            runner.invoke(main, ['q'])
        mock.assert_called_once()


class TestFreeCommand:
    def test_free_calls_cmd_free(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_free') as mock:
            runner.invoke(main, ['free'])
        mock.assert_called_once()

    def test_free_default_options(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_free') as mock:
            runner.invoke(main, ['free'])
        mock.assert_called_once_with(
            kind='gpu', show_nodes=False, partition_filter=None, gpu_type=None
        )

    def test_free_nodes_flag(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_free') as mock:
            runner.invoke(main, ['free', '--nodes'])
        _, kwargs = mock.call_args
        assert kwargs.get('show_nodes') is True

    def test_free_kind_cpu(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_free') as mock:
            runner.invoke(main, ['free', '--kind', 'cpu'])
        _, kwargs = mock.call_args
        assert kwargs.get('kind') == 'cpu'

    def test_free_invalid_kind_rejected(self, runner: CliRunner):
        result = runner.invoke(main, ['free', '--kind', 'nvme'])
        assert result.exit_code != 0

    def test_free_gpu_type_option(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_free') as mock:
            runner.invoke(main, ['free', '--gpu-type', 'A100'])
        _, kwargs = mock.call_args
        assert kwargs.get('gpu_type') == 'a100'

    def test_free_gpu_type_short_option_G(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_free') as mock:
            runner.invoke(main, ['free', '-G', 'A5000'])
        _, kwargs = mock.call_args
        assert kwargs.get('gpu_type') == 'rtx_a5000'


class TestWhyCommand:
    def test_why_help(self, runner: CliRunner):
        result = runner.invoke(main, ['why', '-h'])
        assert result.exit_code == 0
        assert '--fix' in result.output
        assert '--nodes' in result.output

    def test_why_defaults(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_why') as mock:
            result = runner.invoke(main, ['why'])
        assert result.exit_code == 0
        mock.assert_called_once_with(
            jobid=None, show_nodes=False, fix=None, assume_yes=False
        )

    def test_why_fix_alone_means_auto(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_why') as mock:
            result = runner.invoke(main, ['why', '65177', '--fix'])
        assert result.exit_code == 0
        assert mock.call_args.kwargs['fix'] == 'auto'
        assert mock.call_args.kwargs['jobid'] == '65177'

    def test_why_fix_with_a_knob(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_why') as mock:
            result = runner.invoke(main, ['why', '65177', '--fix', 'mem'])
        assert result.exit_code == 0
        assert mock.call_args.kwargs['fix'] == 'mem'

    def test_why_rejects_unknown_knob(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_why') as mock:
            result = runner.invoke(main, ['why', '65177', '--fix', 'disk'])
        assert result.exit_code != 0
        mock.assert_not_called()

    def test_why_nodes_and_yes(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_why') as mock:
            result = runner.invoke(
                main, ['why', '65177', '--nodes', '--fix', 'cpus', '-y']
            )
        assert result.exit_code == 0
        mock.assert_called_once_with(
            jobid='65177', show_nodes=True, fix='cpus', assume_yes=True
        )


class TestGpuallocCommand:
    def test_node_calls_cmd_node(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_node') as mock:
            runner.invoke(main, ['node'])
        mock.assert_called_once()

    def test_node_passes_node_argument(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_node') as mock:
            runner.invoke(main, ['node', 'gpu042'])
        mock.assert_called_once_with(node='gpu042')

    def test_node_no_node_passes_none(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_node') as mock:
            runner.invoke(main, ['node'])
        mock.assert_called_once_with(node=None)


class TestJobCommands:
    def test_job_history_calls_handler(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_job_history') as mock:
            runner.invoke(main, ['job', 'history'])
        mock.assert_called_once()

    def test_job_history_default_limit(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_job_history') as mock:
            runner.invoke(main, ['job', 'history'])
        mock.assert_called_once_with(limit=50)

    def test_job_history_custom_limit(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_job_history') as mock:
            runner.invoke(main, ['job', 'history', '--limit', '100'])
        mock.assert_called_once_with(limit=100)

    def test_job_output_calls_handler(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_job_output') as mock:
            runner.invoke(main, ['job', 'output', '12345'])
        mock.assert_called_once()

    def test_job_output_stderr_flag(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_job_output') as mock:
            runner.invoke(main, ['job', 'output', '--stderr', '12345'])
        mock.assert_called_once_with(jobid='12345', stderr=True)

    def test_job_output_missing_jobid_fails(self, runner: CliRunner):
        result = runner.invoke(main, ['job', 'output'])
        assert result.exit_code != 0


class TestDevCommands:
    def test_dev_start_calls_handler(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_dev_start') as mock:
            runner.invoke(main, ['dev', 'start'])
        mock.assert_called_once()

    def test_dev_start_default_kwargs(self, runner: CliRunner):
        """Canonical full-kwargs check: pins the dev-start handler contract."""
        with patch('allegro_buddy.cli.cmd_dev_start') as mock:
            runner.invoke(main, ['dev', 'start'])
        mock.assert_called_once_with(
            partition='gpu',
            time_limit='08:00:00',
            gpu=1,
            gpu_type=None,
            cpus=2,
            mem='8G',
            account=None,
            constraint=None,
            exclude=None,
            node=None,
            replace=False,
            no_wait=False,
            login=False,
            timeout=None,
            poll_interval=5.0,
        )

    def test_dev_start_default_partition(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_dev_start') as mock:
            runner.invoke(main, ['dev', 'start'])
        _, kwargs = mock.call_args
        assert kwargs.get('partition') == 'gpu'

    def test_dev_start_custom_partition(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_dev_start') as mock:
            runner.invoke(main, ['dev', 'start', '-p', 'gpusmall'])
        _, kwargs = mock.call_args
        assert kwargs.get('partition') == 'gpusmall'

    def test_dev_start_gpu_count(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_dev_start') as mock:
            runner.invoke(main, ['dev', 'start', '-g', '2'])
        _, kwargs = mock.call_args
        assert kwargs.get('gpu') == 2

    def test_dev_start_invalid_gpu_type_rejected(self, runner: CliRunner):
        """A type no node has is refused before sbatch, listing what exists."""
        from allegro_buddy.handlers import dev as dev_handler

        nodes = [node_dict('gpu101'), node_dict('gpu201', gres='gpu:GTX-1080ti:4')]
        remember_nodes(nodes)  # what load_nodes() records for is_gpu_partition()
        with (
            patch.object(dev_handler, 'find_dev_jobs', return_value=[]),
            patch.object(dev_handler, 'choose_partition', return_value='gpu'),
            patch.object(dev_handler, 'load_nodes', return_value=nodes),
            patch.object(dev_handler, 'run') as mock_run,
        ):
            result = runner.invoke(main, ['dev', 'start', '--gpu-type', 'h100'])
        assert result.exit_code != 0
        assert 'this cluster has: a5000, gtx1080' in result.output
        mock_run.assert_not_called()

    @pytest.mark.parametrize(
        'cli_value,expected',
        [
            ('a5000', 'rtx_a5000'),
            ('gtx1080', 'gtx_1080ti'),
            ('A5000', 'rtx_a5000'),  # case-insensitive
            ('RTX-A5000', 'rtx_a5000'),  # the GRES spelling works without an alias
        ],
    )
    def test_dev_start_valid_gpu_type_accepted(
        self, runner: CliRunner, cli_value: str, expected: str
    ):
        with patch('allegro_buddy.cli.cmd_dev_start') as mock:
            result = runner.invoke(main, ['dev', 'start', '--gpu-type', cli_value])
        assert result.exit_code == 0, result.output
        mock.assert_called_once()
        _, kwargs = mock.call_args
        assert kwargs.get('gpu_type') == expected

    def test_dev_status_calls_handler(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_dev_status') as mock:
            runner.invoke(main, ['dev', 'status'])
        mock.assert_called_once()

    def test_dev_login_calls_handler(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_dev_login') as mock:
            runner.invoke(main, ['dev', 'login'])
        mock.assert_called_once()

    def test_dev_stop_calls_handler(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_dev_stop') as mock:
            runner.invoke(main, ['dev', 'stop'])
        mock.assert_called_once()

    def test_l_shortcut_calls_dev_login(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_dev_login') as mock:
            runner.invoke(main, ['l'])
        mock.assert_called_once()

    def test_l_shortcut_default_kwargs(self, runner: CliRunner):
        """`ab l` is a true alias for `ab dev login`: same defaults, ssh path."""
        with patch('allegro_buddy.cli.cmd_dev_login') as mock:
            runner.invoke(main, ['l'])
        mock.assert_called_once_with(
            jobid=None,
            wait=False,
            timeout=None,
            poll_interval=5.0,
            srun=False,
            command=None,
        )

    def test_l_shortcut_command_option(self, runner: CliRunner):
        """`ab l --command X` reaches cmd_dev_login with command set."""
        with patch('allegro_buddy.cli.cmd_dev_login') as mock:
            runner.invoke(main, ['l', '--command', 'nvidia-smi'])
        mock.assert_called_once()
        _, kwargs = mock.call_args
        assert kwargs.get('command') == 'nvidia-smi'
        assert kwargs.get('srun') is False

    def test_dev_login_wait_flag(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_dev_login') as mock:
            runner.invoke(main, ['dev', 'login', '--wait'])
        _, kwargs = mock.call_args
        assert kwargs.get('wait') is True

    def test_dev_login_default_is_ssh_path(self, runner: CliRunner):
        """Default `ab dev login` (no flags) propagates srun=False (ssh path)."""
        with patch('allegro_buddy.cli.cmd_dev_login') as mock:
            runner.invoke(main, ['dev', 'login'])
        mock.assert_called_once_with(
            jobid=None,
            wait=False,
            timeout=None,
            poll_interval=5.0,
            srun=False,
            command=None,
        )

    def test_dev_login_srun_flag_propagates(self, runner: CliRunner):
        """`ab dev login --srun` opts into the srun --overlap path."""
        with patch('allegro_buddy.cli.cmd_dev_login') as mock:
            runner.invoke(main, ['dev', 'login', '--srun'])
        _, kwargs = mock.call_args
        assert kwargs.get('srun') is True

    def test_dev_login_command_option(self, runner: CliRunner):
        with patch('allegro_buddy.cli.cmd_dev_login') as mock:
            runner.invoke(main, ['dev', 'login', '--command', 'nvidia-smi'])
        _, kwargs = mock.call_args
        assert kwargs.get('command') == 'nvidia-smi'
        assert kwargs.get('srun') is False

    @pytest.mark.parametrize(
        'gpu_type,expected_gres',
        [
            # These must be the GRES type strings Slurm actually knows, exactly
            # as configured on the nodes (`sinfo -N -o %G` -> gpu:RTX-A5000:4,
            # gpu:GTX-1080ti:4). Slurm matches GRES types case-sensitively, so
            # a canonicalized/display name here makes sbatch reject the request
            # with "Requested node configuration is not available".
            ('a5000', 'gpu:RTX-A5000:1'),
            ('gtx1080', 'gpu:GTX-1080ti:1'),
        ],
    )
    def test_dev_start_gpu_type_uses_real_slurm_gres_names(
        self, gpu_type: str, expected_gres: str
    ):
        from types import SimpleNamespace

        from allegro_buddy.handlers import dev as dev_handler

        nodes = [node_dict('gpu101'), node_dict('gpu201', gres='gpu:GTX-1080ti:4')]
        remember_nodes(nodes)  # what load_nodes() records for is_gpu_partition()
        with (
            patch.object(dev_handler, 'find_dev_jobs', return_value=[]),
            patch.object(dev_handler, 'choose_partition', return_value='gpu'),
            patch.object(dev_handler, 'load_nodes', return_value=nodes),
            patch.object(
                dev_handler,
                'run',
                return_value=SimpleNamespace(stdout='99999\n'),
            ) as mock_run,
            patch.object(dev_handler, 'get_job_detail', return_value=None),
        ):
            dev_handler.cmd_dev_start(
                partition='gpu',
                time_limit='08:00:00',
                gpu=1,
                gpu_type=gpu_type,
                cpus=2,
                mem='8G',
                account=None,
                constraint=None,
                exclude=None,
                node=None,
                replace=False,
                no_wait=True,
                login=False,
                timeout=None,
                poll_interval=5.0,
            )
        argv = mock_run.call_args[0][0]
        assert f'--gres={expected_gres}' in argv, argv

    def test_dev_start_cpus_not_divisible_by_gpu_warning_emitted(self):
        """`dev start --cpus 3 --gpu 2` writes a warning to ERROR_CONSOLE and
        the handler proceeds past it (does not raise / die)."""
        from io import StringIO
        from types import SimpleNamespace

        from rich.console import Console

        from allegro_buddy.handlers import dev as dev_handler

        captured = StringIO()
        replacement = Console(file=captured, force_terminal=False, width=200)
        remember_nodes([node_dict('gpu101')])
        with (
            patch('allegro_buddy.core.ERROR_CONSOLE', replacement),
            patch.object(dev_handler, 'find_dev_jobs', return_value=[]),
            patch.object(
                dev_handler,
                'choose_partition',
                return_value='gpu',
            ),
            patch.object(
                dev_handler,
                'run',
                return_value=SimpleNamespace(stdout='99999\n'),
            ),
            patch.object(
                dev_handler,
                'get_job_detail',
                return_value=None,
            ),
        ):
            dev_handler.cmd_dev_start(
                partition='gpu',
                time_limit='08:00:00',
                gpu=2,
                gpu_type=None,
                cpus=3,
                mem='8G',
                account=None,
                constraint=None,
                exclude=None,
                node=None,
                replace=False,
                no_wait=True,
                login=False,
                timeout=None,
                poll_interval=5.0,
            )
        out = captured.getvalue()
        assert 'warning' in out.lower()
        assert 'not divisible' in out


class TestDevConfigDefaults:
    def _write(self, path, text: str) -> None:
        path.parent.mkdir(parents=True)
        path.write_text(text)

    def test_config_presets_dev_start(self, runner: CliRunner, isolated_config):
        self._write(
            isolated_config,
            '[dev]\ngpu = 2\ngpu-type = RTX_A5000\nmem = 32G\ntime = 04:00:00\n',
        )
        with patch('allegro_buddy.cli.cmd_dev_start') as mock:
            result = runner.invoke(main, ['dev', 'start', '-g', '1'])
        assert result.exit_code == 0, result.output
        kwargs = mock.call_args.kwargs
        assert kwargs['gpu'] == 1  # explicit flag beats the config
        assert kwargs['gpu_type'] == 'rtx_a5000'
        assert kwargs['mem'] == '32G'
        assert kwargs['time_limit'] == '04:00:00'
        assert kwargs['cpus'] == 2

    def test_config_shown_in_help(self, runner: CliRunner, isolated_config):
        self._write(isolated_config, '[dev]\nmem = 32G\n')
        result = runner.invoke(main, ['dev', 'start', '--help'])
        assert '32G' in result.output

    def test_unknown_key_rejected(self, runner: CliRunner, isolated_config):
        self._write(isolated_config, '[dev]\ngpus = 2\n')
        with patch('allegro_buddy.cli.cmd_dev_start') as mock:
            result = runner.invoke(main, ['dev', 'start'])
        assert result.exit_code != 0
        assert "unknown key 'gpus'" in result.output
        mock.assert_not_called()

    @pytest.mark.parametrize(
        'text,message',
        [
            ('[cluster]\nnode-login = mosh\n', 'node-login must be one of'),
            ('[dev]\nmax-allocations = 0\n', 'max-allocations must be'),
            ('[cluster]\npreset = nowhere\n', "unknown cluster preset 'nowhere'"),
            ('[Dev]\ngpu = 1\n', 'unknown section [Dev]'),
        ],
    )
    def test_invalid_value_rejected(
        self, runner: CliRunner, isolated_config, monkeypatch, text: str, message: str
    ):
        monkeypatch.delenv('AB_CLUSTER')
        self._write(isolated_config, text)
        with patch('allegro_buddy.cli.cmd_dev_start') as mock:
            result = runner.invoke(main, ['dev', 'start'])
        assert result.exit_code != 0
        assert message in result.output
        mock.assert_not_called()


class TestWatchOption:
    def test_watch_defaults_to_interval(self, runner: CliRunner):
        with patch('allegro_buddy.cli.run_watched') as mock:
            runner.invoke(main, ['q', '-w'])
        assert mock.call_args.args[1] == 10.0

    def test_watch_custom_interval(self, runner: CliRunner):
        with patch('allegro_buddy.cli.run_watched') as mock:
            runner.invoke(main, ['free', '--watch', '30', '--nodes'])
        assert mock.call_args.args[1] == 30.0

    def test_watch_rejects_tiny_interval(self, runner: CliRunner):
        # Below 10 s polling would load slurmctld for every user on the cluster.
        result = runner.invoke(main, ['q', '--watch', '5'])
        assert result.exit_code != 0

    def test_watch_flag_before_other_options(self, runner: CliRunner):
        with (
            patch('allegro_buddy.cli.cmd_queue'),
            patch('allegro_buddy.cli.run_watched') as mock,
        ):
            runner.invoke(main, ['q', '-w', '-p', 'gpusmall'])
        assert mock.call_args.args[1] == 10.0

    def test_watch_rerenders_until_interrupted(self, runner: CliRunner):
        sleeps = [None, KeyboardInterrupt]
        with (
            patch('allegro_buddy.cli.cmd_queue') as mock,
            patch('allegro_buddy.cli.time.sleep', side_effect=sleeps),
        ):
            result = runner.invoke(main, ['q', '-w', '10'])
        assert result.exit_code == 0
        assert mock.call_count == 2

    def test_watch_survives_slurm_errors(self, runner: CliRunner):
        with (
            patch(
                'allegro_buddy.cli.cmd_free', side_effect=[SystemExit(1), None]
            ) as mock,
            patch('allegro_buddy.cli.time.sleep', side_effect=[None, KeyboardInterrupt]),
        ):
            result = runner.invoke(main, ['free', '-w'])
        assert result.exit_code == 0
        assert mock.call_count == 2

    def test_watch_error_survives_screen_clear(self, capsys):
        from allegro_buddy.cli import run_watched
        from allegro_buddy.core import die

        def render():
            die('slurmctld timed out')

        before_clear = []
        with (
            patch(
                'allegro_buddy.cli.CONSOLE.clear',
                side_effect=lambda: before_clear.append(capsys.readouterr().err),
            ),
            patch('allegro_buddy.cli.time.sleep', side_effect=KeyboardInterrupt),
        ):
            run_watched(render, 10.0)
        # the error must come out after the clear, or the clear wipes it
        assert before_clear == ['']
        assert 'slurmctld timed out' in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Shell completion
# ---------------------------------------------------------------------------


class TestCompletion:
    def test_prints_script_for_detected_shell(self, runner: CliRunner):
        result = runner.invoke(main, ['completion'], env={'SHELL': '/bin/zsh'})
        assert result.exit_code == 0
        assert '#compdef ab' in result.output

    def test_unknown_shell_is_usage_error(self, runner: CliRunner):
        result = runner.invoke(main, ['completion'], env={'SHELL': '/bin/tcsh'})
        assert result.exit_code == 2
        assert 'tcsh' in result.output

    @pytest.mark.parametrize(('shell', 'rc'), [('bash', '.bashrc'), ('zsh', '.zshrc')])
    def test_install_writes_script_and_sources_it_once(
        self, runner: CliRunner, tmp_path, monkeypatch, shell: str, rc: str
    ):
        monkeypatch.setenv('HOME', str(tmp_path))
        monkeypatch.delenv('XDG_DATA_HOME', raising=False)
        monkeypatch.delenv('ZDOTDIR', raising=False)
        (tmp_path / rc).write_text('export FOO=1')  # no trailing newline
        for _ in range(2):
            result = runner.invoke(main, ['completion', shell, '--install'])
            assert result.exit_code == 0, result.output
        script = tmp_path / f'.local/share/allegro-buddy/completion-ab.{shell}'
        assert '_AB_COMPLETE' in script.read_text()
        # zsh's compdef needs compinit, which many .zshrc files never run
        assert ('compinit' in script.read_text()) == (shell == 'zsh')
        lines = (tmp_path / rc).read_text().splitlines()
        assert lines == ['export FOO=1', f"[ -f '{script}' ] && . '{script}'"]
        assert 'already sources it' in result.output

    @pytest.mark.parametrize('cmd', [['l'], ['dev', 'start']])
    def test_poll_interval_below_one_second_is_rejected(self, runner: CliRunner, cmd):
        result = runner.invoke(main, [*cmd, '--poll-interval', '0'])
        assert result.exit_code == 2

    def test_install_fish_writes_completions_dir(
        self, runner: CliRunner, tmp_path, monkeypatch
    ):
        monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
        result = runner.invoke(
            main,
            ['completion', '--install', '--prog', 'allegro-buddy'],
            env={'SHELL': '/usr/bin/fish'},
        )
        assert result.exit_code == 0, result.output
        script = tmp_path / 'fish/completions/allegro-buddy.fish'
        assert '_ALLEGRO_BUDDY_COMPLETE' in script.read_text()


CTX = click.Context(main)
PARAM = click.Argument(['jobid'])


class TestJobIdCompletion:
    def test_dev_jobid_completes_from_active_dev_jobs(self):
        from allegro_buddy import cli

        jobs = [{'JobId': '111'}, {'JobId': '222'}]
        with patch.object(cli, 'find_dev_jobs', return_value=jobs):
            assert cli.complete_dev_jobid(CTX, PARAM, '1') == ['111']

    def test_why_completes_from_pending_jobs(self):
        from allegro_buddy import cli

        jobs = [{'JobID': '333'}, {'JobID': '444'}]
        with patch.object(cli, 'load_user_pending_jobs', return_value=jobs):
            assert cli.complete_pending_jobid(CTX, PARAM, '') == ['333', '444']
