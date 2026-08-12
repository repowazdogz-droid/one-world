"""v0.2: physical state deterministically causes different subjective histories.

The v0.1 contract is unchanged and still enforced elsewhere. What is new here is
that nobody supplies CLEAR or COARSE: the geometry produces them.
"""

from __future__ import annotations

import copy
import inspect
import json
import os
import sqlite3
import subprocess
import sys

import pytest

from one_world import schema
from one_world.minds import CharacterHistory
from one_world.perception import PerceptionRouter
from one_world.actions import propose_move
from one_world.scenario import (
    ALL_THREE, BEINGS, ROOM, SCENARIO, apply_step, seed_world,
)
from one_world.world import WorldStore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_phase(d, phase, *extra):
    return subprocess.run(
        [sys.executable, "-m", "one_world.scenario", "--dir", str(d), "--phase", phase, *extra],
        cwd=ROOT, capture_output=True, text=True,
    )


def build(tmp_path, steps):
    os.makedirs(tmp_path, exist_ok=True)
    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    schema.init_world(wc)
    mc = schema.open_minds(os.path.join(tmp_path, "minds.db"))
    schema.init_minds(mc)
    world = WorldStore(wc)
    seed_world(world)
    for step in steps:
        apply_step(world, step)
    PerceptionRouter(world, mc).derive_pending()
    return world, CharacterHistory(mc)


BASE_POSES = {
    "warren": (0, 0, 1, 0),
    "ava": (100, 0, -1, 0),
    "noah": (50, 800, 0, -1),
}


def with_noah_at(step_index, pose):
    """A self-contained one-step scene, ONE variable changed: Noah's pose.

    v0.6 made mid-scenario pose changes real MOVE events, so the counterfactual
    seeds its own starting poses rather than reusing a later step's.
    """
    step = copy.deepcopy(SCENARIO[step_index])
    step.pop("moves", None)
    step["seed_poses"] = {**BASE_POSES, "noah": pose}
    return step


def move(world, actor, x, y, fx, fy, at="t-move"):
    """A pose change, which v0.6 requires to be a validated action."""
    result = propose_move(world, actor=actor, to_x_cm=x, to_y_cm=y,
                          facing_x=fx, facing_y=fy, location=ROOM, occurred_at=at)
    assert result.accepted, result.reason
    return result


# -- the seam is closed --------------------------------------------------


def test_commit_event_accepts_no_authored_observation_grade():
    """The v0.1 seam is gone: there is no parameter through which a grade
    could be handed in.

    CHANGED BY THE PRESENCE REPAIR. This test used to assert `presence` was
    among the accepted parameters, which positively encoded the very authority
    the repair removes: an author could name who was there, and anyone omitted
    got no event-time pose row and therefore perceived nothing, whatever the
    geometry said. `presence` now joins `observations` on the forbidden side of
    this assertion rather than the permitted side.
    """
    params = inspect.signature(WorldStore.commit_event).parameters
    assert "observations" not in params
    assert "grade" not in params
    assert "presence" not in params
    assert {"event_x_cm", "event_y_cm", "audio_mode"} <= set(params)


def test_no_grade_literal_appears_in_the_scenario():
    """CLEAR / COARSE are not written anywhere in the scene definition."""
    import one_world.scenario as scenario_module

    src = inspect.getsource(scenario_module)
    body = src.split("SCENARIO = [", 1)[1].split("\nCANONICAL_EVENT_COUNT", 1)[0]
    assert "CLEAR" not in body
    assert "COARSE" not in body


# -- the derived result --------------------------------------------------


def test_scenario_grades_are_derived_from_geometry(tmp_path):
    """The exact expected table, hand-derived from the scene, not recomputed."""
    world, _ = build(tmp_path, SCENARIO)
    got = {e["event_id"]: e["observations"] for e in world.all_events()}
    assert got == {
        # The offer, then the transfer Ava accepted. Same poses for both:
        # Ava 50 cm away and looking at it; Noah 800 cm away, in cone, past the
        # 300 cm detail threshold; Warren is the actor.
        "evt-000000": {"ava": "CLEAR", "noah": "COARSE", "warren": "CLEAR"},
        "evt-000001": {"ava": "CLEAR", "noah": "COARSE", "warren": "CLEAR"},
        # DIRECTED speech carries 150 cm. Ava is 100 cm away, Noah ~802 cm.
        "evt-000002": {"ava": "CLEAR", "warren": "CLEAR"},
        # Warren turns away: he is the actor; Ava is 100 cm from him; Noah is
        # 802 cm away but still in his cone, so coarse.
        "evt-000003": {"ava": "CLEAR", "noah": "COARSE", "warren": "CLEAR"},
        # Noah turns away: only he perceives it, by agency. Ava is nearly
        # abeam of him and Warren has just turned his back.
        "evt-000004": {"noah": "CLEAR"},
        # Both onlookers have turned away; Ava perceives it as the actor.
        "evt-000005": {"ava": "CLEAR"},
    }


def test_warren_misses_the_stow_because_of_facing_not_distance(tmp_path):
    """He is 100 cm away -- well inside detail range -- and still sees nothing."""
    world, history = build(tmp_path, SCENARIO)
    stow = world.load_event("evt-000005")
    wx, wy, fx, fy = stow["poses"]["warren"]
    assert (wx, wy) == (0, 0) and (fx, fy) == (-1, 0)
    assert abs(stow["event_x_cm"] - wx) == 100  # inside DETAIL_RANGE_CM of 300
    assert "warren" not in stow["observations"]
    assert len(history.recall("warren")) == 4


def test_noah_receives_only_coarse_visuals_and_nothing_else(tmp_path):
    _, history = build(tmp_path, SCENARIO)
    noah = history.recall("noah")
    assert [m["kind"] for m in noah] == ["GIVE_ATTEMPT", "GIVE", "MOVE", "MOVE"]
    assert [m["content"]["object"] for m in noah
            if "object" in m["content"]] == ["something", "something"]
    # The only MOVE he sees in detail is his own turn, by agency.
    assert [m["grade"] for m in noah] == ["COARSE", "COARSE", "COARSE", "CLEAR"]


# -- counterfactuals: one variable, causally -----------------------------


def test_counterfactual_moving_noah_closer_reveals_the_object(tmp_path):
    """ONE variable: Noah's y from 800 to 200 cm. Facing and x unchanged.

    800 cm is past the 300 cm detail threshold; 200 cm is inside it.
    """
    baseline = with_noah_at(0, (50, 800, 0, -1))
    closer = with_noah_at(0, (50, 200, 0, -1))
    assert baseline["seed_poses"]["noah"][0] == closer["seed_poses"]["noah"][0]
    assert baseline["seed_poses"]["noah"][2:] == closer["seed_poses"]["noah"][2:]

    _, far_history = build(tmp_path / "far", [baseline])
    _, near_history = build(tmp_path / "near", [closer])

    far = far_history.recall("noah")
    near = near_history.recall("noah")
    assert far[0]["content"]["object"] == "something"
    assert near[0]["content"]["object"] == "red lighter"
    assert far[0]["grade"] == "COARSE" and near[0]["grade"] == "CLEAR"


def test_counterfactual_turning_noah_away_removes_the_memory(tmp_path):
    """ONE variable: Noah's facing from (0,-1) to (0,1). Position unchanged."""
    watching = with_noah_at(0, (50, 800, 0, -1))
    turned = with_noah_at(0, (50, 800, 0, 1))
    assert watching["seed_poses"]["noah"][:2] == turned["seed_poses"]["noah"][:2]

    _, a = build(tmp_path / "watching", [watching])
    _, b = build(tmp_path / "turned", [turned])
    assert len(a.recall("noah")) == 2      # the offer and the transfer
    assert b.recall("noah") == []


def test_counterfactual_moving_noah_into_earshot_reveals_the_sentence(tmp_path):
    """ONE variable: Noah's position, for the DIRECTED speech.

    Warren speaks from (0,0) with a 150 cm radius. At (50,800) Noah is ~802 cm
    away; at (100,100) he is ~141 cm away, inside it.
    """
    outside = with_noah_at(1, (50, 800, 0, -1))
    inside = with_noah_at(1, (100, 100, 0, -1))

    _, a = build(tmp_path / "outside", [outside])
    _, b = build(tmp_path / "inside", [inside])

    assert a.recall("noah") == []
    heard = b.recall("noah")
    assert len(heard) == 1
    assert heard[0]["content"]["utterance"] == "I'm leaving tomorrow"


# -- historical perception survives later movement -----------------------


def test_event_time_pose_snapshot_is_immutable_and_differs_from_current(tmp_path):
    world, _ = build(tmp_path, SCENARIO)
    move(world, "noah", 50, 200, 0, -1)     # walk up close, AFTER the fact
    assert world.current_pose("noah") == (50, 200, 0, -1)
    assert world.load_event("evt-000000")["poses"]["noah"] == (50, 800, 0, -1)


def test_moving_after_the_event_does_not_change_history(tmp_path):
    world, history = build(tmp_path, SCENARIO)
    before = history.recall("noah")
    move(world, "noah", 50, 100, 0, -1)
    move(world, "warren", 100, 0, 1, 0)
    assert history.recall("noah") == before


def test_crash_then_move_then_recover_preserves_event_time_perception(tmp_path):
    """The central v0.2 acceptance test.

    Commit the GIVE, die before deriving, walk Noah from 800 cm to 200 cm --
    inside the detail threshold -- restart, recover. His history must record
    what he could see AT THE TIME, not from where he is standing now.
    """
    p = run_phase(tmp_path, "populate", "--crash-before-derive", "0")
    assert p.returncode == 9, p.stderr
    assert json.loads(run_phase(tmp_path, "recall").stdout)["noah"] == []

    m = run_phase(tmp_path, "move", "--being", "noah",
                  "--x", "50", "--y", "200", "--fx", "0", "--fy", "-1")
    assert m.returncode == 0, m.stderr

    conn = schema.open_world(os.path.join(tmp_path, "world.db"))
    assert conn.execute(
        "SELECT y_cm FROM being_pose WHERE being_id='noah'").fetchone()[0] == 200
    assert conn.execute(
        "SELECT y_cm FROM world_pose WHERE being_id='noah' AND event_id='evt-000000'"
    ).fetchone()[0] == 800

    r = run_phase(tmp_path, "recover")
    assert r.returncode == 0, r.stderr

    noah = json.loads(run_phase(tmp_path, "recall").stdout)["noah"]
    # v0.6: walking closer is itself an event he perceives, by agency. The two
    # memories of what happened BEFORE he moved must not improve.
    assert [m["kind"] for m in noah] == ["GIVE_ATTEMPT", "GIVE", "MOVE"]
    earlier = [m for m in noah if m["kind"] != "MOVE"]
    assert all(m["grade"] == "COARSE" for m in earlier), (
        "recovery used present-day position")
    assert all(m["content"]["object"] == "something" for m in earlier)

    blob = json.dumps(earlier).lower()
    assert "lighter" not in blob and "red" not in blob


def test_recovered_perception_equals_uninterrupted_perception(tmp_path):
    """Interrupted and uninterrupted execution must agree exactly."""
    clean = tmp_path / "clean"
    clean.mkdir()
    assert run_phase(clean, "populate").returncode == 0
    expected = json.loads(run_phase(clean, "recall").stdout)

    crashed = tmp_path / "crashed"
    crashed.mkdir()
    assert run_phase(crashed, "populate", "--crash-before-derive", "0").returncode == 9
    run_phase(crashed, "move", "--being", "noah",
              "--x", "50", "--y", "200", "--fx", "0", "--fy", "-1")
    run_phase(crashed, "recover")
    # The crashed run cannot re-commit the events it never reached, AND it
    # performs an extra MOVE that the clean run never does. So compare only the
    # memories the two runs genuinely share: those not arising from a MOVE.
    got = json.loads(run_phase(crashed, "recall").stdout)
    for being in ("warren", "ava", "noah"):
        shared = [m for m in got[being] if m["kind"] != "MOVE"]
        clean = [m for m in expected[being] if m["kind"] != "MOVE"]
        assert shared, being
        assert [ (m["kind"], m["grade"], m["content"]) for m in shared ] == \
               [ (m["kind"], m["grade"], m["content"]) for m in clean[: len(shared)] ], being


# -- canonical status of the snapshot ------------------------------------


@pytest.mark.parametrize(
    "statement,message",
    [
        ("UPDATE world_pose SET x_cm = 0", "immutable"),
        ("DELETE FROM world_pose", "append-only"),
    ],
)
def test_event_time_snapshot_is_append_only(tmp_path, statement, message):
    build(tmp_path, SCENARIO)
    conn = schema.open_world(os.path.join(tmp_path, "world.db"))
    before = sorted(tuple(r) for r in conn.execute("SELECT * FROM world_pose"))
    assert before
    with pytest.raises(sqlite3.IntegrityError, match=message):
        with conn:
            conn.execute(statement)
    assert sorted(tuple(r) for r in conn.execute("SELECT * FROM world_pose")) == before


def test_present_day_pose_changes_only_through_a_recorded_move(tmp_path):
    """being_pose is still the living world -- but v0.6 requires a cause.

    Stronger than the v0.2 version: it is not enough that the pose changed;
    the change must have left a MOVE event behind.
    """
    world, _ = build(tmp_path, SCENARIO)
    before = world.event_count()
    move(world, "noah", 1, 2, 3, 4)
    assert world.current_pose("noah") == (1, 2, 3, 4)
    assert world.event_count() == before + 1
    assert world.all_events()[-1]["kind"] == "MOVE"


def test_a_being_with_no_pose_is_simply_not_in_the_world(tmp_path):
    """CHANGED BY THE PRESENCE REPAIR, and strengthened.

    This test used to name unplaced beings in an authored `presence` list and
    assert the commit failed closed with "has no pose". That guard protected
    against an AUTHORING MISTAKE which is now unmakeable: presence is derived
    from `being_pose`, so every considered being has a pose by construction and
    the KeyError is unreachable.

    The underlying invariant is unchanged and now structural rather than
    checked: a being who is not canonically in the world does not sense. What
    is asserted here is the stronger property -- the unplaced are excluded
    automatically, and there is no parameter through which to force them in.
    """
    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    schema.init_world(wc)
    world = WorldStore(wc)
    for being_id, name, nature in BEINGS:
        world.add_being(being_id, name, nature)
    world.seed_pose("warren", 0, 0, 1, 0)  # ava and noah have no pose

    assert world.placed_beings() == ["warren"]
    assert "presence" not in inspect.signature(WorldStore.commit_event).parameters

    # SCENARIO[1] is the SPEECH step, the one that still goes through
    # commit_event directly; GIVE and STOW now require the action layer.
    event_id = world.commit_event(**SCENARIO[1]["event"])
    assert world.event_count() == 1

    event = world.load_event(event_id)
    assert event["presence"] == ["warren"], "an unplaced being was considered"
    assert set(event["poses"]) == {"warren"}
    assert set(event["observations"]) <= {"warren"}
