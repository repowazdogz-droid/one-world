"""The presence repair: eligibility for sensing is canonical, not authored.

The post-v0.9 audit found that an author could omit a canonically placed
inhabitant from an action's `presence` list and thereby suppress their
perception entirely -- 10 cm from the event, facing it, no wall -- because the
omission removed their event-time pose row, which is the sole input to sensing.
Every threshold, cone and occlusion rule in the project sat downstream of that
list.

This suite pins the repair. It asserts BOTH halves:

  * behavioural -- the discovered counterexample now perceives;
  * structural  -- there is no parameter through which anyone could omit them
                   again, so the repair is not merely a well-behaved default.

The structural half matters because a purely behavioural test would still pass
against a version that re-added the capability and simply did not use it yet.
"""

from __future__ import annotations

import inspect
import json
import os
import sqlite3

import pytest

from one_world import actions as actions_module
from one_world import schema
from one_world.actions import propose_look, propose_move, propose_place
from one_world.minds import CharacterHistory
from one_world.perception import PerceptionRouter
from one_world.scenario import ROOM, seed_world
from one_world.world import WorldStore

# The exact geometry from the audit: Noah is 10 cm from the drop point, facing
# it, with nothing in the way. Nothing physical can justify his ignorance.
COUNTEREXAMPLE = {
    "warren": (0, 0, 1, 0),
    "noah": (50, 0, -1, 0),      # 10 cm from the event at (40,0), looking at it
    "ava": (60, 0, -1, 0),       # 20 cm, also looking at it
}
DROP = (40, 0)


def fresh(tmp_path, poses):
    os.makedirs(tmp_path, exist_ok=True)
    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    schema.init_world(wc)
    mc = schema.open_minds(os.path.join(tmp_path, "minds.db"))
    schema.init_minds(mc)
    world = WorldStore(wc)
    seed_world(world)
    for being_id, pose in sorted(poses.items()):
        world.seed_pose(being_id, *pose)
    return world, wc, mc


def derive(world, mc):
    PerceptionRouter(world, mc).derive_pending()
    return CharacterHistory(mc)


def public_actions():
    return [
        getattr(actions_module, n) for n in dir(actions_module)
        if n.startswith(("propose_", "attempt_", "respond_"))
        and callable(getattr(actions_module, n))
    ]


# -- the discovered counterexample -----------------------------------------


def test_the_audit_counterexample_now_perceives(tmp_path):
    """Noah is 10 cm away, facing it, unoccluded. He perceives it. Full stop.

    Before the repair this same scene produced `Noah perceived: []` whenever the
    author left him out of the presence list.
    """
    world, wc, mc = fresh(tmp_path, COUNTEREXAMPLE)
    assert propose_place(world, actor="warren", object_id="lighter-1",
                         x_cm=DROP[0], y_cm=DROP[1], location=ROOM,
                         occurred_at="t1").accepted
    history = derive(world, mc)

    noah = history.recall("noah")
    assert noah, "the counterexample still suppresses Noah"
    assert noah[0]["kind"] == "PLACE" and noah[0]["grade"] == "CLEAR"

    # He is in the canonical record of who was there, and in the pose snapshot.
    event = world.load_event("evt-000000")
    assert "noah" in event["presence"]
    assert "noah" in event["poses"]
    assert event["observations"]["noah"] == "CLEAR"


def test_no_author_controlled_input_can_omit_a_placed_inhabitant(tmp_path):
    """Structural: there is no parameter left through which to try.

    Checked across every public entry point rather than the one used above, so
    re-adding the capability anywhere fails here even before anyone uses it.
    """
    for fn in public_actions():
        params = set(inspect.signature(fn).parameters)
        assert "presence" not in params, f"{fn.__name__} accepts presence"
        assert not (params & {"observers", "witnesses", "present", "audience"}), (
            f"{fn.__name__} accepts a presence-shaped parameter")

    from one_world.world import WorldStore as WS
    for method in (WS.commit_event, WS._append_event_locked):
        assert "presence" not in inspect.signature(method).parameters


def test_presence_cannot_be_smuggled_through_the_payload(tmp_path):
    """The other author-controlled channel that reaches the appender.

    `payload` is author-supplied for SPEECH. If the appender ever consulted it
    for presence, the seam would be back under a different name.
    """
    world, wc, mc = fresh(tmp_path, COUNTEREXAMPLE)
    world.commit_event(
        kind="SPEECH", location=ROOM, actor_id="warren",
        payload={"speaker": "warren", "addressee": "ava",
                 "utterance": "hello",
                 # a hostile author trying every shape of the old authority
                 "presence": ["warren"], "observers": ["warren"],
                 "witnesses": ["warren"]},
        event_x_cm=0, event_y_cm=0, audio_mode="PUBLIC", occurred_at="t")

    event = world.load_event("evt-000000")
    assert set(event["presence"]) == {"ava", "noah", "warren"}
    assert set(event["poses"]) == {"ava", "noah", "warren"}
    # Noah is 50 cm away and PUBLIC carries 1000 cm: he hears it.
    assert event["observations"]["noah"] == "CLEAR"


def test_an_author_cannot_invent_a_present_inhabitant(tmp_path):
    """The converse: nobody may be added either, placed or otherwise."""
    world, wc, mc = fresh(tmp_path, {"warren": (0, 0, 1, 0)})
    world.commit_event(
        kind="SPEECH", location=ROOM, actor_id="warren",
        payload={"speaker": "warren", "addressee": "nobody",
                 "utterance": "hello", "presence": ["warren", "ghost", "ava"]},
        event_x_cm=0, event_y_cm=0, audio_mode="PUBLIC", occurred_at="t")

    event = world.load_event("evt-000000")
    assert event["presence"] == ["warren"], "an unplaced being was conjured in"
    assert "ghost" not in json.dumps(event["presence"])
    # ava exists as a being but has no pose, so she is not in the world.
    assert world.placed_beings() == ["warren"]


# -- geometry still decides everything downstream --------------------------


def test_being_considered_is_not_the_same_as_perceiving(tmp_path):
    """The repair widens ELIGIBILITY only. It must not make anyone omniscient.

    Everyone placed now gets a pose row; what they actually perceive is still
    range, facing and occlusion, and this asserts all three still bite.
    """
    poses = {
        "warren": (0, 0, 1, 0),        # actor
        "ava": (200, 0, -1, 0),        # 200 cm, looking at it: CLEAR
        "noah": (-200, 0, -1, 0),      # 200 cm, looking AWAY: nothing
    }
    world, wc, mc = fresh(tmp_path, poses)
    assert propose_place(world, actor="warren", object_id="lighter-1",
                         x_cm=0, y_cm=0, location=ROOM, occurred_at="t").accepted
    history = derive(world, mc)

    event = world.load_event("evt-000000")
    assert set(event["presence"]) == {"ava", "noah", "warren"}, (
        "all three must be CONSIDERED")
    assert "noah" not in event["observations"], "facing stopped mattering"
    assert event["observations"]["ava"] == "CLEAR"
    assert history.recall("noah") == []


def test_a_wall_still_blocks_a_considered_inhabitant(tmp_path):
    poses = {
        "warren": (0, 0, 1, 0),
        "ava": (-200, 0, 1, 0),
        "noah": (200, 0, -1, 0),
    }
    world, wc, mc = fresh(tmp_path, poses)
    world.add_wall("w1", 100, -50, 100, 50)
    assert propose_place(world, actor="warren", object_id="lighter-1",
                         x_cm=0, y_cm=0, location=ROOM, occurred_at="t").accepted
    history = derive(world, mc)

    event = world.load_event("evt-000000")
    assert "noah" in event["presence"], "the wall removed him from the record"
    assert "noah" not in event["observations"], "the wall stopped blocking"
    assert history.recall("noah") == []
    assert history.recall("ava")


def test_range_still_bites(tmp_path):
    poses = dict(COUNTEREXAMPLE, noah=(0, 3000, 0, 1))    # 30 m away
    world, wc, mc = fresh(tmp_path, poses)
    assert propose_place(world, actor="warren", object_id="lighter-1",
                         x_cm=DROP[0], y_cm=DROP[1], location=ROOM,
                         occurred_at="t").accepted
    event = world.load_event("evt-000000")
    assert "noah" in event["presence"]
    assert "noah" not in event["observations"]


# -- the historical snapshot is still event-time ---------------------------


def test_the_snapshot_records_who_was_there_then_not_who_is_here_now(tmp_path):
    """Derivation happens AT COMMIT. Later arrivals do not join a past event."""
    world, wc, mc = fresh(tmp_path, {"warren": (0, 0, 1, 0)})
    assert propose_place(world, actor="warren", object_id="lighter-1",
                         x_cm=DROP[0], y_cm=DROP[1], location=ROOM,
                         occurred_at="t1").accepted
    first = world.load_event("evt-000000")
    assert first["presence"] == ["warren"]

    # Ava and Noah enter the world afterwards.
    world.seed_pose("ava", 60, 0, -1, 0)
    world.seed_pose("noah", 50, 0, -1, 0)
    assert world.placed_beings() == ["ava", "noah", "warren"]

    assert world.load_event("evt-000000")["presence"] == ["warren"], (
        "a past event gained a witness who was not yet in the world")
    assert set(world.load_event("evt-000000")["poses"]) == {"warren"}


def test_a_later_departure_cannot_edit_a_past_snapshot(tmp_path):
    """world_presence is append-only and event-time, unchanged by the repair."""
    world, wc, mc = fresh(tmp_path, COUNTEREXAMPLE)
    assert propose_place(world, actor="warren", object_id="lighter-1",
                         x_cm=DROP[0], y_cm=DROP[1], location=ROOM,
                         occurred_at="t1").accepted
    before = sorted(tuple(r) for r in wc.execute("SELECT * FROM world_presence"))
    assert before

    assert propose_move(world, actor="noah", to_x_cm=0, to_y_cm=9000,
                        facing_x=0, facing_y=1, location=ROOM,
                        occurred_at="t2").accepted
    assert sorted(tuple(r) for r in wc.execute(
        "SELECT * FROM world_presence WHERE event_id='evt-000000'")) == [
        r for r in before if r[0] == "evt-000000"]

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with wc:
            wc.execute("DELETE FROM world_presence")


# -- LOOK and MOVE go through the same derivation --------------------------


def test_look_and_move_both_derive_presence(tmp_path):
    world, wc, mc = fresh(tmp_path, COUNTEREXAMPLE)
    assert propose_look(world, actor="ava", location=ROOM,
                        occurred_at="t1").accepted
    assert propose_move(world, actor="ava", to_x_cm=70, to_y_cm=0, facing_x=-1,
                        facing_y=0, location=ROOM, occurred_at="t2").accepted

    for event_id in ("evt-000000", "evt-000001"):
        event = world.load_event(event_id)
        assert set(event["presence"]) == {"ava", "noah", "warren"}, event_id

    # LOOK remains AGENCY-sensed: considered by all, perceived by the actor.
    assert world.load_event("evt-000000")["observations"] == {"ava": "CLEAR"}


# -- recovery is unaffected -------------------------------------------------


def test_crash_recovery_semantics_are_unchanged(tmp_path):
    """Presence is derived at COMMIT and snapshotted; replay re-reads the row."""
    world, wc, mc = fresh(tmp_path, COUNTEREXAMPLE)
    assert propose_place(world, actor="warren", object_id="lighter-1",
                         x_cm=DROP[0], y_cm=DROP[1], location=ROOM,
                         occurred_at="t1").accepted
    assert mc.execute("SELECT COUNT(*) FROM perception").fetchone()[0] == 0

    # The world moves on before anything is projected.
    assert propose_move(world, actor="noah", to_x_cm=0, to_y_cm=9000,
                        facing_x=0, facing_y=1, location=ROOM,
                        occurred_at="t2").accepted
    history = derive(world, mc)

    noah = [m for m in history.recall("noah") if m["kind"] == "PLACE"]
    assert len(noah) == 1, "the delayed projection lost his perception"
    assert noah[0]["grade"] == "CLEAR", (
        "projection re-derived presence from where he is NOW")
