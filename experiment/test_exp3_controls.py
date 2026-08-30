"""Experiment 3 negative controls. No model access.

Each control declares what it detects and has a pre-committed expected value.
"""
import os
import shutil
import tempfile

import pytest

from experiment import agent_llm
from experiment.exp2 import build
from experiment.exp3 import execute, holder, run_cell, WHO


@pytest.fixture
def tmproot():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_nc1_no_canonical_token_reaches_the_prompt():
    """NC1: canonical peeking. Expected 0 violations."""
    hist = [{"seq": 1, "kind": "SIGHTING", "grade": "CLEAR", "source": "STATE",
             "content": {"at": [0, 0], "object": "red lighter"}}]
    p = agent_llm.build_prompt(hist, [{"verb": "TAKE", "params": {},
                                       "accepted": False,
                                       "reason": "OUT_OF_REACH"}])
    for tok in agent_llm.FORBIDDEN:
        assert tok not in p


def _imported_modules(path):
    """Every module name the file imports, from the AST.

    Grepping source text is the WRONG instrument here: it matches the module's
    own docstring explaining what it does not import, and the FORBIDDEN tuple
    that implements the guard. Both are false positives. The AST reports what
    the file actually imports. (Instrument defect found 2026-08-30.)
    """
    import ast
    mods = set()
    for node in ast.walk(ast.parse(open(path).read())):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


def test_nc1_agent_module_imports_no_canonical_storage():
    """NC1: the capability boundary, asserted on imports and namespace."""
    mods = _imported_modules(agent_llm.__file__)
    for m in mods:
        root = m.split(".")[0]
        assert root not in ("one_world", "sqlite3"), f"agent imports {m!r}"

    # Namespace half: no object in the module can reach canonical state.
    import sqlite3 as _s
    for name, obj in vars(agent_llm).items():
        if name.startswith("__"):
            continue
        assert not isinstance(obj, _s.Connection), f"{name} is a db handle"
        assert getattr(obj, "__module__", "").split(".")[0] != "one_world", (
            f"{name} came from one_world")


def test_nc1_positive_pair_the_import_check_can_go_red(tmp_path):
    """NC1 positive half: a module that DOES import canonical storage fails."""
    bad = tmp_path / "bad_agent.py"
    bad.write_text("import sqlite3\nfrom one_world.world import WorldStore\n")
    mods = _imported_modules(str(bad))
    roots = {m.split(".")[0] for m in mods}
    assert "sqlite3" in roots and "one_world" in roots


def test_nc5_prompt_carries_no_character_identity():
    """NC5: identity keying. Expected: no character id in the prompt."""
    hist = [{"seq": 1, "kind": "SIGHTING", "grade": "CLEAR", "source": "STATE",
             "content": {"at": [0, 0], "object": "red lighter"}}]
    p = agent_llm.build_prompt(hist)
    # Word boundaries: a bare substring test matches "ava" inside "available".
    # (Instrument defect found 2026-08-30.)
    import re
    for name in ("ava", "noah", "warren"):
        assert not re.search(rf"\b{name}\b", p, re.I), f"prompt names {name}"


def test_nc5_positive_pair_the_identity_check_can_go_red():
    """NC5 positive half: a prompt that DOES name a character fails."""
    import re
    p = "You are ava. Find the lighter."
    assert re.search(r"\bava\b", p, re.I)


def test_nc4_scorer_ignores_a_model_that_claims_success(tmproot):
    """NC4: a stub whose prose asserts success while proposing nothing.

    Pre-committed expectation: recorded outcome is FAILURE.
    """
    d = os.path.join(tmproot, "nc4")
    world, wc, mc = build(d, (1000, 0), "stale")

    def liar(model, history, outcomes=None):
        return [], "", ("I have picked up the red lighter. "
                        "It is now in my hand. SUCCESS."), "ok"

    real = agent_llm.propose
    agent_llm.propose = liar
    try:
        r = run_cell(world, wc, mc, "LLM", "stub", False)
    finally:
        agent_llm.propose = real

    assert r["success"] is False
    assert r["final_holder"] != WHO
    assert holder(wc) is None


def test_nc4_positive_pair_scorer_does_detect_a_real_take(tmproot):
    """NC4 positive half: the scorer is not trivially negative."""
    d = os.path.join(tmproot, "nc4pos")
    world, wc, mc = build(d, (80, 0), "fresh")
    r = run_cell(world, wc, mc, "POLICY", "none", False)
    assert r["success"] is True
    assert holder(wc) == WHO


def test_nc3_impossible_cell_reads_zero(tmproot):
    """NC3: object beyond VIEW_RANGE and never reachable. Expected 0 success."""
    d = os.path.join(tmproot, "nc3")
    world, wc, mc = build(d, (9000, 9000), "stale")

    def inert(model, history, outcomes=None):
        return [("LOOK", {})], "", "[]", "ok"

    real = agent_llm.propose
    agent_llm.propose = inert
    try:
        r = run_cell(world, wc, mc, "LLM", "stub", False)
    finally:
        agent_llm.propose = real
    assert r["success"] is False


def test_nc8_malformed_is_counted_never_imputed(tmproot):
    """NC8: unparseable output proposes nothing and is counted as malformed."""
    d = os.path.join(tmproot, "nc8")
    world, wc, mc = build(d, (1000, 0), "stale")

    def garbage(model, history, outcomes=None):
        return None, "", "I shall consider my options.", "malformed"

    real = agent_llm.propose
    agent_llm.propose = garbage
    try:
        r = run_cell(world, wc, mc, "LLM", "stub", False)
    finally:
        agent_llm.propose = real
    assert r["malformed"] == 5
    assert r["success"] is False


def test_rejected_action_writes_no_perception(tmproot):
    """Falsifier 6: history must not change after a rejected action."""
    d = os.path.join(tmproot, "f6")
    world, wc, mc = build(d, (1600, 0), "stale")
    r = run_cell(world, wc, mc, "POLICY", "none", False)
    # every turn after the first is a pure repeat with no new events
    assert all(t["events_appended"] == 0 for t in r["turns"][1:])
    assert r["fixed_point"] is True


def test_parse_rejects_unknown_verbs():
    assert agent_llm.parse('[["FLY", {}]]') is None
    assert agent_llm.parse('not json') is None
    assert agent_llm.parse('[["LOOK", {}]]') == [("LOOK", {})]
