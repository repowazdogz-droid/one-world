"""v0.3: canonical world structure blocks access to reality.

The claim under test is narrow and easy to fake, so each test also rules out the
cheap explanations: that Noah was further away, facing elsewhere, absent from
the scene, or handed a grade by an author.
"""

from __future__ import annotations

import inspect
import json
import os
import sqlite3
import subprocess
import sys

import pytest

from one_world import schema
from one_world.geometry import dist_sq
from one_world.minds import CharacterHistory
from one_world.perception import PerceptionRouter
from one_world.scenario import (
    BEINGS, BLOCKING_WALL, NOAH_CLEAR_OF_WALL, WALL_EVENT, WALL_ID,
    WALL_SCENE_POSES, seed_world, setup_wall_scene, wall_event,
)
from one_world.sensing import sense_event
from one_world.world import WorldStore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_phase(d, phase, *extra):
    return subprocess.run(
        [sys.executable, "-m", "one_world.scenario", "--dir", str(d), "--phase", phase, *extra],
        cwd=ROOT, capture_output=True, text=True,
    )


def build(tmp_path, *, with_wall, noah_pose=None):
    os.makedirs(tmp_path, exist_ok=True)
    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    schema.init_world(wc)
    mc = schema.open_minds(os.path.join(tmp_path, "minds.db"))
    schema.init_minds(mc)
    world = WorldStore(wc)
    seed_world(world)
    setup_wall_scene(world, with_wall=with_wall, noah_pose=noah_pose)
    event_id = wall_event(world, WALL_EVENT["occurred_at"])
    PerceptionRouter(world, mc).derive_pending()
    return world, CharacterHistory(mc), event_id


# -- the scene really is symmetric ---------------------------------------


def test_ava_and_noah_have_identical_relevant_visual_geometry():
    ax, ay, afx, afy = WALL_SCENE_POSES["ava"]
    nx, ny, nfx, nfy = WALL_SCENE_POSES["noah"]
    ex, ey = WALL_EVENT["event_x_cm"], WALL_EVENT["event_y_cm"]

    assert dist_sq(ax, ay, ex, ey) == dist_sq(nx, ny, ex, ey) == 40000  # 200 cm each
    # Each faces straight at the event: facing is the exact unit direction.
    assert (afx, afy) == (1, 0) and (ax, ay) == (-200, 0)
    assert (nfx, nfy) == (-1, 0) and (nx, ny) == (200, 0)


def test_without_walls_v02_gives_both_observers_clear():
    """The v0.2 model as an explicit control: distance and facing predict CLEAR
    for BOTH. Anything that separates them afterwards is world structure."""
    graded = sense_event(
        kind=WALL_EVENT["kind"], actor_id=WALL_EVENT["actor_id"],
        event_x_cm=WALL_EVENT["event_x_cm"], event_y_cm=WALL_EVENT["event_y_cm"],
        audio_mode=None, poses=WALL_SCENE_POSES, walls=(),
    )
    assert graded == {"warren": "CLEAR", "ava": "CLEAR", "noah": "CLEAR"}


def test_the_wall_alone_changes_the_outcome():
    """Same poses, same event, one variable: the wall."""
    kwargs = dict(
        kind=WALL_EVENT["kind"], actor_id=WALL_EVENT["actor_id"],
        event_x_cm=WALL_EVENT["event_x_cm"], event_y_cm=WALL_EVENT["event_y_cm"],
        audio_mode=None, poses=WALL_SCENE_POSES,
    )
    assert sense_event(**kwargs, walls=()) == {
        "warren": "CLEAR", "ava": "CLEAR", "noah": "CLEAR"}
    assert sense_event(**kwargs, walls=(BLOCKING_WALL,)) == {
        "warren": "CLEAR", "ava": "CLEAR"}


# -- the acceptance scenario, end to end ---------------------------------


def test_acceptance_only_noah_is_occluded(tmp_path):
    world, history, event_id = build(tmp_path, with_wall=True)
    event = world.load_event(event_id)

    assert event["observations"] == {"warren": "CLEAR", "ava": "CLEAR"}
    assert "noah" not in event["observations"]

    assert len(history.recall("ava")) == 1
    assert history.recall("ava")[0]["content"]["object"] == "red lighter"
    assert history.recall("noah") == []


def test_noahs_blindness_is_not_explained_by_the_cheap_alternatives(tmp_path):
    """Falsify 'the wall did it' against every rival explanation."""
    world, history, event_id = build(tmp_path, with_wall=True)
    event = world.load_event(event_id)

    # Not absence: he is canonically present and pose-snapshotted.
    assert "noah" in event["presence"]
    assert event["poses"]["noah"] == WALL_SCENE_POSES["noah"]

    # Not distance: identical to Ava's, who perceived it.
    ex, ey = event["event_x_cm"], event["event_y_cm"]
    nx, ny, _, _ = event["poses"]["noah"]
    ax, ay, _, _ = event["poses"]["ava"]
    assert dist_sq(nx, ny, ex, ey) == dist_sq(ax, ay, ex, ey)

    # Not orientation: with the wall removed from the same poses, he is CLEAR.
    assert sense_event(
        kind=event["kind"], actor_id=event["actor_id"], event_x_cm=ex, event_y_cm=ey,
        audio_mode=None, poses=event["poses"], walls=(),
    )["noah"] == "CLEAR"

    # Not an authored grade: nothing supplies one, and the wall is canonical.
    assert event["walls"] == {WALL_ID: BLOCKING_WALL}
    assert history.recall("noah") == []


def test_nothing_about_the_hidden_event_reaches_noahs_stored_bytes(tmp_path):
    tmp = tmp_path / "w"
    build(tmp, with_wall=True)
    conn = sqlite3.connect(os.path.join(tmp, "minds.db"))
    rows = conn.execute(
        "SELECT perceived_json FROM perception WHERE character_id='noah'").fetchall()
    assert rows == []


# -- counterfactuals -----------------------------------------------------


def test_counterfactual_a_wall_removed(tmp_path):
    """ONE variable: the wall. Same people, same poses, new equivalent event."""
    _, blocked, _ = build(tmp_path / "walled", with_wall=True)
    _, open_, _ = build(tmp_path / "open", with_wall=False)

    assert blocked.recall("noah") == []
    seen = open_.recall("noah")
    assert len(seen) == 1
    assert seen[0]["grade"] == "CLEAR"
    assert seen[0]["content"]["object"] == "red lighter"


def test_counterfactual_b_noah_moved(tmp_path):
    """ONE variable: Noah's pose. The same wall still stands.

    (200,200) -> (0,0) crosses x=100 at y=100; the wall spans y in [-50,50].
    """
    _, blocked, _ = build(tmp_path / "at_200_0", with_wall=True)
    _, moved, event_id = build(
        tmp_path / "at_200_200", with_wall=True, noah_pose=NOAH_CLEAR_OF_WALL)

    assert blocked.recall("noah") == []
    seen = moved.recall("noah")
    assert len(seen) == 1
    assert seen[0]["grade"] == "CLEAR"


def test_moved_noah_still_faces_a_standing_wall(tmp_path):
    """Counterfactual B must not be an accident of the wall vanishing."""
    world, _, event_id = build(
        tmp_path, with_wall=True, noah_pose=NOAH_CLEAR_OF_WALL)
    assert world.load_event(event_id)["walls"] == {WALL_ID: BLOCKING_WALL}
    assert world.current_walls() == [(WALL_ID, *BLOCKING_WALL)]


# -- historical geometry -------------------------------------------------


def test_history_survives_demolition(tmp_path):
    """Wall blocks -> event -> wall removed -> crash recovery -> still blind.

    Then a NEW event under today's open geometry IS perceived, proving the
    system is not simply frozen.
    """
    assert run_phase(tmp_path, "wall-populate", "--wall", "yes",
                     "--crash-before-derive", "0").returncode == 9
    assert json.loads(run_phase(tmp_path, "recall").stdout)["noah"] == []

    assert run_phase(tmp_path, "wall-remove").returncode == 0
    conn = schema.open_world(os.path.join(tmp_path, "world.db"))
    assert conn.execute("SELECT COUNT(*) FROM wall").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM world_wall WHERE event_id='evt-000000'").fetchone()[0] == 1

    assert run_phase(tmp_path, "recover").returncode == 0
    after = json.loads(run_phase(tmp_path, "recall").stdout)
    assert after["noah"] == [], "demolition retroactively granted information"
    assert len(after["ava"]) == 1

    # A new event, now unobstructed, IS perceived.
    assert run_phase(tmp_path, "wall-event", "--at", "0002-01-01T01:00:00Z").returncode == 0
    final = json.loads(run_phase(tmp_path, "recall").stdout)
    assert len(final["noah"]) == 1
    assert final["noah"][0]["content"]["object"] == "red lighter"
    assert len(final["ava"]) == 2


def test_history_survives_construction(tmp_path):
    """The inverse: unobstructed event -> wall built later -> still perceived."""
    assert run_phase(tmp_path, "wall-populate", "--wall", "no",
                     "--crash-before-derive", "0").returncode == 9
    assert run_phase(tmp_path, "wall-add").returncode == 0

    conn = schema.open_world(os.path.join(tmp_path, "world.db"))
    assert conn.execute("SELECT COUNT(*) FROM wall").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM world_wall WHERE event_id='evt-000000'").fetchone()[0] == 0

    assert run_phase(tmp_path, "recover").returncode == 0
    noah = json.loads(run_phase(tmp_path, "recall").stdout)["noah"]
    assert len(noah) == 1, "construction retroactively removed information"
    assert noah[0]["content"]["object"] == "red lighter"


def test_recovered_perception_matches_uninterrupted(tmp_path):
    clean, crashed = tmp_path / "clean", tmp_path / "crashed"
    clean.mkdir(), crashed.mkdir()
    assert run_phase(clean, "wall-populate", "--wall", "yes").returncode == 0
    assert run_phase(crashed, "wall-populate", "--wall", "yes",
                     "--crash-before-derive", "0").returncode == 9
    run_phase(crashed, "wall-remove")
    run_phase(crashed, "recover")
    assert json.loads(run_phase(crashed, "recall").stdout) == \
           json.loads(run_phase(clean, "recall").stdout)


# -- the snapshot is canonical -------------------------------------------


@pytest.mark.parametrize(
    "statement,message",
    [
        ("UPDATE world_wall SET x1_cm = 0", "immutable"),
        ("DELETE FROM world_wall", "append-only"),
    ],
)
def test_event_time_geometry_is_append_only(tmp_path, statement, message):
    build(tmp_path, with_wall=True)
    conn = schema.open_world(os.path.join(tmp_path, "world.db"))
    before = sorted(tuple(r) for r in conn.execute("SELECT * FROM world_wall"))
    assert before
    with pytest.raises(sqlite3.IntegrityError, match=message):
        with conn:
            conn.execute(statement)
    assert sorted(tuple(r) for r in conn.execute("SELECT * FROM world_wall")) == before


def test_current_walls_are_mutable_by_contrast(tmp_path):
    world, _, _ = build(tmp_path, with_wall=True)
    world.remove_wall(WALL_ID)
    assert world.current_walls() == []


def test_zero_length_wall_is_rejected_at_the_door(tmp_path):
    os.makedirs(tmp_path, exist_ok=True)
    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    schema.init_world(wc)
    world = WorldStore(wc)
    with pytest.raises(ValueError, match="zero-length wall"):
        world.add_wall("bad", 10, 10, 10, 10)
    assert world.current_walls() == []


def test_omitting_event_time_geometry_fails_closed():
    """Omission must be an error, not a silent fallback to unoccluded v0.2.

    `walls=()` is an explicit canonical fact -- this snapshot contained no
    walls. Omitting `walls` is a programmer error. A default would collapse the
    second into the first and quietly reinstate sight through solid matter.
    """
    kwargs = dict(
        kind=WALL_EVENT["kind"], actor_id=WALL_EVENT["actor_id"],
        event_x_cm=WALL_EVENT["event_x_cm"], event_y_cm=WALL_EVENT["event_y_cm"],
        audio_mode=None, poses=WALL_SCENE_POSES,
    )
    with pytest.raises(TypeError, match="walls"):
        sense_event(**kwargs)                     # required input not supplied

    explicit = sense_event(**kwargs, walls=())    # canonical fact: no walls
    assert explicit == {"warren": "CLEAR", "ava": "CLEAR", "noah": "CLEAR"}


def test_sensing_entry_points_declare_no_wall_default():
    """Neither the public nor the internal visual path may default `walls`."""
    from one_world import sensing

    for fn in (sensing.sense_event, sensing._see):
        param = inspect.signature(fn).parameters["walls"]
        assert param.default is inspect.Parameter.empty, (
            f"{fn.__name__} defaults `walls`, so omission would silently mean "
            f"'no walls' instead of failing")


def test_walls_do_not_block_sound(tmp_path):
    """Explicit scope boundary: a wall is a VISUAL barrier only."""
    heard = sense_event(
        kind="SPEECH", actor_id="warren", event_x_cm=0, event_y_cm=0,
        audio_mode="PUBLIC",
        poses={"warren": (0, 0, 1, 0), "noah": (200, 0, -1, 0)},
        walls=(BLOCKING_WALL,),
    )
    assert heard["noah"] == "CLEAR"


def test_the_original_scenario_has_no_walls(tmp_path):
    """v0.1/v0.2 behaviour is untouched because that scene builds no walls."""
    assert run_phase(tmp_path, "populate").returncode == 0
    conn = schema.open_world(os.path.join(tmp_path, "world.db"))
    assert conn.execute("SELECT COUNT(*) FROM wall").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM world_wall").fetchone()[0] == 0
