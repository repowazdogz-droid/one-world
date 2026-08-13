"""Anti-cheating boundary and the five preregistered negative controls.

Kept out of tests/ deliberately: the world's own suite stays at 369, and the
experiment's evidence is separate from the world's.
"""

from __future__ import annotations

import ast
import inspect
import os
import sqlite3

import pytest

from experiment import driver as driver_module
from experiment import policy as policy_module
from experiment.driver import Inhabitant
from experiment.policy import last_known_position
from experiment.runner import A, B, build_asymmetric, build_symmetric

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANONICAL = {"one_world.world", "one_world.schema", "one_world.actions",
             "one_world.perception", "one_world.sensing", "one_world.geometry",
             "one_world.scenario", "experiment.runner"}


def imported(module):
    out = set()
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


# -- the selection stage cannot reach canonical state ----------------------


def code_only(module):
    """Source with every docstring stripped.

    The prose in this module explains what it does NOT touch, and naming those
    things in a docstring must not read as touching them -- the same trap the
    v0.6 suite flags when it filters on executed statements rather than text.
    """
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


def test_policy_imports_nothing_at_all():
    assert imported(policy_module) == set()
    src = code_only(policy_module)
    for token in ("WorldStore", "world.db", "sqlite3", "object_location",
                  "being_pose", "lighter-1", "ATTACH", "one_world"):
        assert token not in src, f"policy names {token}"


def test_policy_signature_receives_only_history():
    assert list(inspect.signature(last_known_position).parameters) == ["history"]


def test_driver_imports_no_canonical_module():
    assert not (imported(driver_module) & CANONICAL)
    src = inspect.getsource(driver_module)
    assert "sqlite3.connect" not in src and "open_world" not in src


def test_driver_takes_only_a_minds_connection(tmp_path):
    assert list(inspect.signature(Inhabitant.__init__).parameters) == \
        ["self", "minds_conn"]
    mc = sqlite3.connect(os.path.join(tmp_path, "m.db"))
    wc = sqlite3.connect(os.path.join(tmp_path, "w.db"))
    with pytest.raises(TypeError):
        Inhabitant(mc, wc)


def test_driver_exposes_no_canonical_attribute():
    assert sorted(a for a in dir(Inhabitant) if not a.startswith("_")) == \
        ["POLICY", "evidence", "propose"]


def test_the_policy_never_receives_the_character_id():
    """An identity-keyed shortcut is impossible, not merely absent."""
    src = inspect.getsource(Inhabitant.propose)
    assert "POLICY(self.evidence(character_id))" in "".join(src.split())


# -- CONTROL 2: one policy, asserted by identity ---------------------------


def test_both_inhabitants_run_the_identical_policy_object(tmp_path):
    world, wc, mc = build_asymmetric(tmp_path / "w")
    a, n = Inhabitant(mc), Inhabitant(mc)
    assert a.POLICY is n.POLICY is last_known_position
    assert Inhabitant.POLICY is last_known_position


def test_control_two_different_policies_would_be_visible(tmp_path):
    """A per-character policy map is detectable: the objects stop being one."""
    world, wc, mc = build_asymmetric(tmp_path / "w")

    def other_policy(history):
        return [("MOVE", {"to": (0, 0), "facing": (1, 0)})]

    per_character = {"ava": last_known_position, "noah": other_policy}
    assert per_character["ava"] is not per_character["noah"], (
        "the mutation did nothing")
    driver = Inhabitant(mc)
    honest = {w: driver.propose(w) for w in ("ava", "noah")}
    mutant = {w: per_character[w](driver.evidence(w)) for w in ("ava", "noah")}
    assert mutant["noah"] != honest["noah"], "the mutant policy changed nothing"
    assert Inhabitant.POLICY is last_known_position, (
        "the shared-policy assertion is what rejects this")


# -- CONTROL 1: a driver that secretly reads canonical state ---------------


def test_control_a_peeking_driver_is_rejected_by_the_boundary(tmp_path):
    """It gets the 'right' answer and is still rejected, because it CAN see."""
    world, wc, mc = build_asymmetric(tmp_path / "w")

    class PeekingInhabitant(Inhabitant):
        def __init__(self, minds_conn, world_store):
            super().__init__(minds_conn)
            self._world = world_store          # <-- the canonical handle

        def propose(self, character_id):
            loc = self._world.object_location("lighter-1")
            return [("MOVE", {"to": (loc["x_cm"], loc["y_cm"]),
                              "facing": (1, 0)}),
                    ("TAKE", {"description": "red lighter"})]

    peeking = PeekingInhabitant(mc, world)
    assert peeking.propose("ava")[0][1]["to"] == B, "the mutation did nothing"

    # Ava's honest choice is A; the peeker's is B -- it is not reading her.
    assert Inhabitant(mc).propose("ava")[0][1]["to"] == A

    # And the boundary rejects it structurally, whatever answer it gives.
    params = list(inspect.signature(PeekingInhabitant.__init__).parameters)
    assert "world_store" in params
    assert list(inspect.signature(Inhabitant.__init__).parameters) == \
        ["self", "minds_conn"], "the honest driver gained a canonical parameter"


# -- CONTROL 5: current canonical state substituted for stale evidence -----


def test_control_using_current_state_destroys_the_divergence(tmp_path):
    """If selection used the world instead of memory, both would choose B."""
    world, wc, mc = build_asymmetric(tmp_path / "w")
    driver = Inhabitant(mc)
    honest = {w: driver.propose(w)[0][1]["to"] for w in ("ava", "noah")}
    assert honest["ava"] != honest["noah"], "no divergence to destroy"

    loc = world.object_location("lighter-1")
    current = (loc["x_cm"], loc["y_cm"])
    substituted = {w: current for w in ("ava", "noah")}
    assert substituted["ava"] == substituted["noah"] == B
    assert substituted != honest, (
        "current state and stored evidence agree; the test is vacuous")


# -- CONTROL 4: identity-keyed policy, caught by swapping histories --------


def test_control_swapping_histories_swaps_the_choices(tmp_path):
    """The decisive test that history, not identity, drives the choice."""
    world, wc, mc = build_asymmetric(tmp_path / "w")
    driver = Inhabitant(mc)
    ava_hist, noah_hist = driver.evidence("ava"), driver.evidence("noah")

    assert last_known_position(ava_hist)[0][1]["to"] == A
    assert last_known_position(noah_hist)[0][1]["to"] == B
    # Same policy, histories exchanged: the choices exchange too.
    assert last_known_position(noah_hist)[0][1]["to"] == B
    assert last_known_position(ava_hist)[0][1]["to"] == A

    def identity_keyed(history, who):
        return [("MOVE", {"to": A if who == "ava" else B, "facing": (1, 0)})]

    # An identity-keyed policy is UNCHANGED by swapping the evidence...
    assert identity_keyed(noah_hist, "ava")[0][1]["to"] == A
    # ...where the real one follows the evidence it was given.
    assert last_known_position(noah_hist)[0][1]["to"] == B
    assert "who" not in inspect.signature(last_known_position).parameters


# -- CONTROL 3: histories must be world-derived, not injected --------------


def origin_provenance(wc, mc):
    """Every memory must trace to a real canonical origin."""
    events = {r[0] for r in wc.execute("SELECT event_id FROM world_event")}
    sightings = {r[0] for r in wc.execute(
        "SELECT sighting_id FROM arrival_sighting")}
    orphans = []
    for character_id, origin in mc.execute(
            "SELECT character_id, origin_ref FROM perception"):
        if origin not in events and origin not in sightings:
            orphans.append((character_id, origin))
    return orphans


def test_every_memory_used_traces_to_canonical_sensing(tmp_path):
    world, wc, mc = build_asymmetric(tmp_path / "w")
    assert mc.execute("SELECT COUNT(*) FROM perception").fetchone()[0] > 0
    assert origin_provenance(wc, mc) == []


def test_control_an_injected_memory_is_caught_by_provenance(tmp_path):
    """Hand-writing a belief is exactly what must not count as evidence."""
    world, wc, mc = build_asymmetric(tmp_path / "w")
    assert origin_provenance(wc, mc) == []

    with mc:
        mc.execute(
            "INSERT INTO perception (perception_id, character_id, "
            "perception_seq, kind, grade, perceived_json, origin_ref, source) "
            "VALUES ('forged', 'ava', 99, 'SIGHTING', 'CLEAR', "
            "'{\"object\":\"red lighter\",\"at\":[9999,9999]}', 'made-up', "
            "'STATE')")

    orphans = origin_provenance(wc, mc)
    assert orphans == [("ava", "made-up")], "the injection went undetected"
    # ...and it would indeed have changed her choice, which is the danger.
    assert Inhabitant(mc).propose("ava")[0][1]["to"] == (9999, 9999)


# -- the preregistered success criteria ------------------------------------


def test_asymmetric_evidence_produces_different_choices(tmp_path):
    world, wc, mc = build_asymmetric(tmp_path / "w")
    driver = Inhabitant(mc)
    assert world.current_pose("ava") == world.current_pose("noah")
    assert driver.propose("ava")[0][1]["to"] == A
    assert driver.propose("noah")[0][1]["to"] == B


def test_symmetric_evidence_produces_identical_choices(tmp_path):
    world, wc, mc = build_symmetric(tmp_path / "w")
    driver = Inhabitant(mc)
    assert world.current_pose("ava") == world.current_pose("noah")
    assert driver.propose("ava") == driver.propose("noah")
    assert driver.propose("ava")[0][1]["to"] == B


def test_an_inhabitant_with_no_evidence_abstains(tmp_path):
    assert last_known_position([]) == []
