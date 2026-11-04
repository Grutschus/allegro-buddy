"""pytest entry point of the differential harness, for CI.

    BAB_BIN=target/release/bab uv run --project compat pytest compat -q

Runs every scenario of compat/scenarios.py with $BAB_BIN (default: the Python reference,
compat/ref-bab, as a self-check) and compares it with compat/golden/<scenario>/ exactly
like `run.py check`. Set $BAB_COMPAT_WORK if ~/.cache/bab-compat is too long a path.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

COMPAT = Path(__file__).resolve().parent
sys.path.insert(0, str(COMPAT))

import harness  # noqa: E402
import run  # noqa: E402
from scenarios import SCENARIOS, Scenario  # noqa: E402

BINARY = os.environ.get('BAB_BIN') or str(COMPAT / 'ref-bab')


@pytest.mark.parametrize('scenario', SCENARIOS, ids=[s.name for s in SCENARIOS])
def test_scenario(scenario: Scenario) -> None:
    expected = run.read_golden(scenario)
    assert expected is not None, f'no golden for {scenario.name}; run `run.py golden`'
    problems = run.compare(expected, harness.run(scenario, BINARY))
    assert not problems, f'bab {" ".join(scenario.argv)}\n' + ''.join(problems)
