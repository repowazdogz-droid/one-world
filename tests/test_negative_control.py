"""Proves the acceptance contract can actually detect the failure it exists for.

The same behavioural checks run against both implementations. A suite that only
ever passes tells you nothing about its own detection power.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from one_world import schema
from one_world.minds import CharacterHistory
from one_world.world import WorldStore
from tests.contract import MUST_FAIL_AGAINST_UNSAFE, run_contract
from tests.unsafe import UnsafeCharacterHistory

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def populated(tmp_path):
    p = subprocess.run(
        [sys.executable, "-m", "one_world.scenario", "--dir", str(tmp_path), "--phase", "populate"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert p.returncode == 0, p.stderr
    return tmp_path


@pytest.fixture
def safe_results(populated):
    conn = schema.open_minds(os.path.join(populated, "minds.db"))
    return run_contract(CharacterHistory(conn))


@pytest.fixture
def unsafe_results(populated):
    conn = schema.open_world(os.path.join(populated, "world.db"))
    return run_contract(UnsafeCharacterHistory(WorldStore(conn)))


def test_safe_implementation_passes_everything(safe_results):
    failed = sorted(k for k, ok in safe_results.items() if not ok)
    assert failed == []


def test_unsafe_implementation_fails_the_information_flow_checks(unsafe_results):
    actually_failed = {k for k, ok in unsafe_results.items() if not ok}
    missing = MUST_FAIL_AGAINST_UNSAFE - actually_failed
    assert not missing, f"expected these to fail against unsafe but they passed: {sorted(missing)}"


def test_unsafe_leaks_red_lighter_to_noah(unsafe_results):
    """Explicitly named in the brief."""
    assert unsafe_results["noah_no_red_lighter"] is False


def test_unsafe_leaks_private_sentence_to_noah(unsafe_results):
    """Explicitly named in the brief."""
    assert unsafe_results["noah_no_private_sentence"] is False


def test_unsafe_makes_warren_omniscient(unsafe_results):
    assert unsafe_results["warren_not_omniscient"] is False


def test_unsafe_still_passes_avas_checks(safe_results, unsafe_results):
    """Expected, and correct.

    Ava perceived everything at CLEAR, so a canonical-reading implementation
    gets her right. A negative control that failed EVERY check would only show
    the harness can spot a broken program; failing exactly the information-flow
    checks shows it spots the failure we care about.
    """
    ava_checks = [k for k in safe_results if k.startswith("ava_")]
    assert ava_checks
    for k in ava_checks:
        assert unsafe_results[k] is True


def test_discrimination_is_non_trivial(safe_results, unsafe_results):
    """Some checks must differ, and some must agree."""
    differing = {k for k in safe_results if safe_results[k] != unsafe_results[k]}
    agreeing = {k for k in safe_results if safe_results[k] == unsafe_results[k]}
    assert differing == MUST_FAIL_AGAINST_UNSAFE
    assert agreeing, "a contract that flips entirely is not discriminating"
