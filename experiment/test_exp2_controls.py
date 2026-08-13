"""The eight preregistered Experiment 2 controls, run unchanged."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import sqlite3

import pytest

from one_world.actions import INTERACTION_RANGE_CM as REACH
from one_world.geometry import dist_sq
from one_world.sensing import DETAIL_RANGE_CM as DETAIL, _visual_grade
from experiment import exp2
from experiment.driver import Inhabitant
from experiment.policy import last_known_position

PINNED = "3e4484df67b652a1a4703e0df68c489e7b203c717e7c25f0d2c2ab4ad1115a00"
A = (0, 0)


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    root = tmp_path_factory.mktemp("exp2")
    out = {}
    for bearing, offset, label in exp2.cells():
        key = f"{bearing}/{label}"
        out[key] = {"offset": offset}
        for arm in ("stale", "fresh"):
            d = os.path.join(root, bearing, label.replace("=", ""), arm)
            world, wc, mc = exp2.build(d, offset, arm)
            out[key][arm] = exp2.run_turns(world, wc, mc)
            out[key][arm]["db"] = d
            out[key][arm + "_world"] = world
    return out


def traps(results):
    return {k: v for k, v in results.items() if not v["stale"]["success"]}


# -- 3: accidental policy differences --------------------------------------


def test_control3_one_pinned_policy_everywhere():
    digest = hashlib.sha256(
        open(inspect.getsourcefile(last_known_position), "rb").read()).hexdigest()
    assert digest == PINNED, "the pinned policy changed; preregistration void"
    assert Inhabitant.POLICY is last_known_position
    assert list(inspect.signature(last_known_position).parameters) == ["history"]


# -- 1: canonical-state peeking --------------------------------------------


def test_control1_selection_holds_no_canonical_handle(tmp_path):
    assert list(inspect.signature(Inhabitant.__init__).parameters) == \
        ["self", "minds_conn"]
    mc = sqlite3.connect(os.path.join(tmp_path, "m.db"))
    wc = sqlite3.connect(os.path.join(tmp_path, "w.db"))
    with pytest.raises(TypeError):
        Inhabitant(mc, wc)
    src = inspect.getsource(last_known_position)
    for token in ("WorldStore", "object_location", "sqlite3", "one_world"):
        assert token not in src


# -- 2: current-state substitution ------------------------------------------


def test_control2_current_state_substitution_would_succeed_everywhere(results):
    """If selection had used the world, every trap cell would have succeeded."""
    trapped = traps(results)
    assert trapped, "no trap cells; the control would be vacuous"
    for key, v in trapped.items():
        proposed = v["stale"]["turns"][0]["proposal"][0][1]["to"]
        assert proposed == list(A), f"{key}: did not go to the REMEMBERED point"
        assert proposed != list(v["offset"]), (
            f"{key}: proposal equals the CURRENT position -- substitution")


# -- 4: identity-keyed behaviour --------------------------------------------


def test_control4_swapping_histories_swaps_the_choices(results):
    v = results["0deg/d=1000"]
    stale_hist = v["stale"]["turns"][0]["history_in"]
    fresh_hist = v["fresh"]["turns"][0]["history_in"]
    assert last_known_position(stale_hist)[0][1]["to"] == A
    assert last_known_position(fresh_hist)[0][1]["to"] == tuple(v["offset"])
    assert "who" not in inspect.signature(last_known_position).parameters


# -- 5: sequential-world contamination --------------------------------------


def test_control5_every_cell_and_arm_has_its_own_world(results):
    paths = [v[arm]["db"] for v in results.values() for arm in ("stale", "fresh")]
    assert len(paths) == 28
    assert len(set(paths)) == 28, "worlds were shared between cells or arms"
    for p in paths:
        assert os.path.exists(os.path.join(p, "world.db"))


def test_control5_turn0_canonical_state_is_equivalent_across_arms(results):
    """Both arms face the same objective world before turn 1."""
    for key, v in results.items():
        for arm in ("stale", "fresh"):
            w = v[arm + "_world"]
            loc = w.object_location("lighter-1")
            assert (loc["x_cm"], loc["y_cm"]) == tuple(v["offset"]) or \
                v[arm]["success"], key
        # decision pose identical across arms at turn 0
        assert v["stale"]["turns"][0]["proposal"][0][1]["facing"] == [1, 0]
        assert v["fresh"]["turns"][0]["proposal"][0][1]["facing"] == [1, 0]


# -- 6: unintended arrival-scan reacquisition -------------------------------


def test_control6_no_clear_sighting_leaked_into_a_trap_cell(results):
    for key, v in traps(results).items():
        for turn in v["stale"]["turns"]:
            for m in turn["new_state_perceptions"]:
                assert m["grade"] != "CLEAR", (
                    f"{key} turn {turn['turn']}: unexpected CLEAR reacquisition")


# -- 7: bearing / facing confounding ----------------------------------------


def test_control7_bearing_alone_decides_two_in_range_cells(results):
    """90deg/d=100 and 180deg/d=100 are INSIDE detail range and still yield
    nothing. Distance cannot explain it; bearing can."""
    for key in ("90deg/d=100", "180deg/d=100"):
        off = results[key]["offset"]
        assert dist_sq(*A, *off) <= DETAIL * DETAIL, "cell is not inside detail range"
        assert dist_sq(*A, *off) > REACH * REACH, "cell is within reach"
        assert _visual_grade(0, 0, 1, 0, off[0], off[1], ()) is None
        assert results[key]["stale"]["turns"][0]["new_state_perceptions"] == []
        assert not results[key]["stale"]["success"]
    # ...while an in-cone cell at comparable distance escapes.
    assert results["0deg/d=81"]["stale"]["success"]


# -- 8: rejected actions producing decision-relevant evidence ---------------


def test_control8_all_rejected_turns_leave_history_byte_identical(results):
    checked = 0
    for key, v in results.items():
        for arm in ("stale", "fresh"):
            for turn in v[arm]["turns"]:
                if all(not r["accepted"] for r in turn["results"]):
                    checked += 1
                    assert turn["history_unchanged"], (
                        f"{key}/{arm} turn {turn['turn']}: rejection changed history")
                    assert turn["events_appended"] == 0
                    assert turn["new_event_perceptions"] == []
                    assert turn["new_state_perceptions"] == []
    assert checked > 0, "no all-rejected turns; the control would be vacuous"


# -- the preregistered predictions ------------------------------------------


def test_all_fourteen_cells_match_prediction(results):
    for key, v in results.items():
        off = v["offset"]
        grade = _visual_grade(0, 0, 1, 0, off[0], off[1], ())
        reach = dist_sq(*A, *off) <= REACH * REACH
        if reach:
            expected = ("success", 1)
        elif grade == "CLEAR":
            expected = ("success", 2)
        else:
            expected = ("fixed", 2)
        stale = v["stale"]
        if expected[0] == "success":
            assert stale["success"] and stale["success_turn"] == expected[1], key
        else:
            assert not stale["success"], key
            assert stale["fixed_point"] and stale["first_fixed_turn"] == 2, key
        assert v["fresh"]["success"] and v["fresh"]["success_turn"] == 1, key


def test_fixed_point_persists_to_the_budget(results):
    for key, v in traps(results).items():
        turns = v["stale"]["turns"]
        assert len(turns) == exp2.TURN_BUDGET
        assert all(t["fixed_point"] for t in turns[1:]), key
