from __future__ import annotations

import os

import pytest

# rich-click reads these once at import and then forces colour into help output;
# GitHub Actions sets GITHUB_ACTIONS, which broke the plain-text help snapshot.
for _var in ('FORCE_COLOR', 'PY_COLORS', 'GITHUB_ACTIONS'):
    os.environ.pop(_var, None)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        '--cluster',
        action='store_true',
        default=False,
        help='run integration tests that require a running Slurm cluster',
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption('--cluster'):
        return
    skip_cluster = pytest.mark.skip(
        reason='pass --cluster to run cluster integration tests'
    )
    for item in items:
        if 'cluster' in item.keywords:
            item.add_marker(skip_cluster)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Keep the developer's own config, the site file and any cached state out.

    Tests run as Allegro (the shipped preset) unless they change $AB_CLUSTER.
    """
    from allegro_buddy import core, settings

    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    monkeypatch.setenv('AB_SITE_CONFIG', str(tmp_path / 'site' / 'config.ini'))
    monkeypatch.setenv('AB_CLUSTER', 'allegro')
    settings.load.cache_clear()
    monkeypatch.setattr(core, '_NODE_FACTS', None)
    yield tmp_path / 'config' / 'allegro-buddy' / 'config.ini'
    settings.load.cache_clear()


# ---------------------------------------------------------------------------
# Shared job fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def job_running() -> dict[str, str]:
    return {
        'JobId': '12345',
        'JobName': 'training',
        'JobState': 'RUNNING',
        'UserId': 'alice(1000)',
        'NodeList': 'gpu001',
        'TresPerNode': 'gres/gpu:rtx_a5000:2',
        'JOB_GRES': '',
        'GRES': '',
        'NumCPUs': '8',
        'Mem': '32768',
        'EndTime': '2030-01-01T12:00:00',
        'Partition': 'gpusmall',
        'ArrayJobId': 'N/A',
        'ArrayTaskId': 'N/A',
        'SubmitTime': '2030-01-01T08:00:00',
    }


@pytest.fixture
def job_pending() -> dict[str, str]:
    return {
        'JobId': '12346',
        'JobName': 'inference',
        'JobState': 'PENDING',
        'UserId': 'alice(1000)',
        'NodeList': '(None)',
        'TresPerNode': 'gres/gpu:rtx_a5000:1',
        'JOB_GRES': '',
        'GRES': '',
        'NumCPUs': '4',
        'Mem': '16384',
        'StartTime': '2030-01-01T10:00:00',
        'Partition': 'gpusmall',
        'Reason': 'Resources',
        'ArrayJobId': 'N/A',
        'ArrayTaskId': 'N/A',
    }


@pytest.fixture
def job_history_completed() -> dict[str, str]:
    return {
        'JobId': '11111',
        'JobIDRaw': '11111',
        'JobName': 'myjob',
        'State': 'COMPLETED',
        'StateToken': 'COMPLETED',
        'ExitCode': '0:0',
        'End': '2024-03-15T14:30:00',
        'Reason': '',
    }


@pytest.fixture
def job_history_failed() -> dict[str, str]:
    return {
        'JobId': '11112',
        'JobIDRaw': '11112',
        'JobName': 'badjob',
        'State': 'FAILED',
        'StateToken': 'FAILED',
        'ExitCode': '1:0',
        'End': '2024-03-16T09:00:00',
        'Reason': '',
    }
