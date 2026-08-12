"""v0.8: an inhabitant can perceive world state that predates their arrival.

The hazard this suite is written against is a sighting test that passes because
the observer secretly witnessed the PLACE. Every scenario here therefore proves
the NEGATIVE first -- that the observer has no event perception of how the
object got there -- before asserting the positive.

The second hazard is a scan that produced nothing and an assertion that is
vacuously true about it. Every emptiness check is paired with a non-emptiness
check on the same data.
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
from one_world.actions import (
    propose_move, propose_pickup, propose_place,
)
from one_world.minds import CharacterHistory
from one_world.perception import PerceptionRouter, project
from one_world.scenario import ALL_THREE, ROOM, seed_world
from one_world.world import STATE_CHANGING_KINDS, WorldStore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The lighter lies at (100, 0). Warren is 60 cm from it, so he can reach it;
# Ava and Noah both start 30 m away, which is beyond VIEW_RANGE_CM (1500) at
# any facing, so neither can perceive the PLACE by any route.
START = {
    "warren": (40, 0, 1, 0),
    "ava": (0, 3000, 0, 1),
    "noah": (0, -3000, 0, -1),
}
LIGHTER = (100, 0)

AVA_SEES = (250, 0, -1, 0)        # 150 cm from it: inside DETAIL_RANGE_CM
AVA_AGAIN = (280, 0, -1, 0)       # 180 cm: a second, distinct arrival
AVA_COARSE = (700, 0, -1, 0)      # 600 cm: seen, not resolved
AVA_REACH = (160, 0, -1, 0)       # 60 cm: within INTERACTION_RANGE_CM
NOAH_BLOCKED = (-150, 0, 1, 0)    # 250 cm, but the wall stands between
NOAH_CLEAR = (-140, 0, 1, 0)      # 240 cm, wall gone
BLOCKING_WALL = ("w1", 0, -50, 0, 50)


def run_phase(d, phase, *extra):
    return subprocess.run(
        [sys.executable, "-m", "one_world.scenario", "--dir", str(d),
         "--phase", phase, *extra],
        cwd=ROOT, capture_output=True, text=True,
    )


def fresh(tmp_path, poses=None):
    os.makedirs(tmp_path, exist_ok=True)
    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    schema.init_world(wc)
    mc = schema.open_minds(os.path.join(tmp_path, "minds.db"))
    schema.init_minds(mc)
    world = WorldStore(wc)
    seed_world(world)
    for being_id, pose in sorted((poses or START).items()):
        world.seed_pose(being_id, *pose)
    return world, wc, mc


def place(world, actor, x, y, at="t"):
    return propose_place(world, actor=actor, object_id="lighter-1", x_cm=x,
                         y_cm=y, presence=ALL_THREE, location=ROOM,
                         occurred_at=at)


def pickup(world, actor, at="t"):
    return propose_pickup(world, actor=actor, object_id="lighter-1",
                          presence=ALL_THREE, location=ROOM, occurred_at=at)


def move(world, actor, pose, at="t"):
    return propose_move(world, actor=actor, to_x_cm=pose[0], to_y_cm=pose[1],
                        facing_x=pose[2], facing_y=pose[3],
                        presence=ALL_THREE, location=ROOM, occurred_at=at)


def derive(world, mc):
    PerceptionRouter(world, mc).derive_pending()
    return CharacterHistory(mc)


def snapshot(wc):
    """Canonical state INCLUDING the v0.8 arrival tables.

    Omitting them here would let a rejected action leave an arrival scan behind
    unnoticed, which is exactly the regression this helper exists to catch.
    """
    def rows(t):
        return sorted(tuple(r) for r in wc.execute(f"SELECT * FROM {t}"))
    return {t: rows(t) for t in (
        "object_location", "being_pose", "world_event", "world_pose",
        "world_observation", "world_presence", "projection_outbox",
        "world_seq_counter", "arrival_scan", "arrival_sighting",
        "arrival_scan_outbox")}


def sightings(history, character_id):
    return [m for m in history.recall(character_id) if m["kind"] == "SIGHTING"]


def scan_rows(wc, character_id=None):
    sql = "SELECT scan_id, being_id, x_cm, y_cm FROM arrival_scan ORDER BY world_seq"
    return [tuple(r) for r in wc.execute(sql)
            if character_id is None or r["being_id"] == character_id]


# -- the milestone question ------------------------------------------------


def test_ava_discovers_a_lighter_that_was_already_lying_there(tmp_path):
    """The acceptance scenario, end to end, in one place.

    Warren puts the lighter down while Ava is 30 m away. She never perceives
    that. She then walks up to it, and learns it exists.
    """
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t-place").accepted
    history = derive(world, mc)

    # She was not there for it, in the canonical record and in her own history.
    assert world.load_event("evt-000000")["observations"] == {"warren": "CLEAR"}
    assert history.recall("ava") == []

    assert move(world, "ava", AVA_SEES, at="t-arrive").accepted
    history = derive(world, mc)
    ava = history.recall("ava")

    assert [(m["kind"], m["source"], m["grade"]) for m in ava] == [
        ("MOVE", "EVENT", "CLEAR"),        # her own move, by agency
        ("SIGHTING", "STATE", "CLEAR"),    # the thing that was already there
    ]
    assert ava[1]["content"] == {"object": "red lighter", "at": list(LIGHTER)}

    # ...and she STILL has no perception of how it got there.
    assert [m for m in ava if m["kind"] == "PLACE"] == []
    assert "warren" not in json.dumps(ava[1]["content"])


def test_canonical_history_gains_no_event_for_the_looking(tmp_path):
    """"Ava saw a red lighter" is her memory, never world truth."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", AVA_SEES, at="t2").accepted
    derive(world, mc)

    kinds = [r[0] for r in wc.execute(
        "SELECT kind FROM world_event ORDER BY world_seq")]
    assert kinds == ["PLACE", "MOVE"], "looking became an event"
    assert "SIGHTING" not in kinds and "LOOK" not in kinds

    # Nothing anywhere in canonical history says Ava perceived the placement.
    place_observers = {r[0] for r in wc.execute(
        "SELECT being_id FROM world_observation WHERE event_id='evt-000000'")}
    assert place_observers == {"warren"}

    # And no canonical payload asserts what she saw.
    payloads = " ".join(r[0] for r in wc.execute(
        "SELECT payload_json FROM world_event"))
    assert "SIGHTING" not in payloads


def test_a_second_place_is_not_needed_and_never_happens(tmp_path):
    """The object is perceived from its PRESENCE, not from a fresh event."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    before = wc.execute(
        "SELECT COUNT(*) FROM world_event WHERE kind='PLACE'").fetchone()[0]
    assert move(world, "ava", AVA_SEES, at="t2").accepted
    after = wc.execute(
        "SELECT COUNT(*) FROM world_event WHERE kind='PLACE'").fetchone()[0]
    assert before == after == 1
    assert len(sightings(derive(world, mc), "ava")) == 1


# -- the trigger is a successful MOVE, and only that -----------------------


def test_standing_still_never_rescans(tmp_path):
    """No clock, no background sensing: without a MOVE there is no scan."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", AVA_SEES, at="t2").accepted
    history = derive(world, mc)
    assert len(sightings(history, "ava")) == 1

    # Time passes; other things happen; Ava does not move.
    assert pickup(world, "warren", at="t3").accepted
    assert place(world, "warren", *LIGHTER, at="t4").accepted
    for _ in range(3):
        assert PerceptionRouter(world, mc).derive_pending() >= 0
    history = CharacterHistory(mc)
    assert len(sightings(history, "ava")) == 1, "a scan happened without a move"
    assert len(scan_rows(wc, "ava")) == 1


def test_a_rejected_move_produces_no_scan(tmp_path):
    """A move that did not happen cannot have arrived anywhere."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    derive(world, mc)
    before = snapshot(wc)

    x, y, fx, fy = world.current_pose("ava")
    assert not move(world, "ava", (x, y, fx, fy)).accepted          # NO_CHANGE
    assert not move(world, "ava", (10, 10, 0, 0)).accepted           # ZERO_FACING
    assert not move(world, "nobody", AVA_SEES).accepted              # UNKNOWN_ACTOR

    assert snapshot(wc) == before, "a rejected move left canonical state behind"
    assert wc.execute("SELECT COUNT(*) FROM arrival_scan").fetchone()[0] == 0


def test_only_the_mover_scans(tmp_path):
    """Arrival is the mover's; bystanders did not change viewpoint."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", AVA_SEES, at="t2").accepted
    history = derive(world, mc)

    assert {r[1] for r in scan_rows(wc)} == {"ava"}
    assert sightings(history, "ava")
    assert sightings(history, "noah") == []
    assert sightings(history, "warren") == []


def test_a_scan_happens_even_when_nothing_is_visible(tmp_path):
    """Arriving and seeing nothing is a fact, not the absence of one."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    world.add_wall(*BLOCKING_WALL)
    assert move(world, "noah", NOAH_BLOCKED, at="t2").accepted

    assert len(scan_rows(wc, "noah")) == 1, "the scan itself was not recorded"
    assert wc.execute(
        "SELECT COUNT(*) FROM arrival_sighting").fetchone()[0] == 0
    assert sightings(derive(world, mc), "noah") == []


# -- temporal ordering: departure for the event, arrival for the scan ------


def test_the_move_event_still_uses_the_departure_and_the_scan_the_arrival(tmp_path):
    """Both sides of the v0.6/v0.8 seam, asserted together.

    One MOVE, two snapshots, taken from opposite ends of the same transition.
    """
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", AVA_SEES, at="t2").accepted

    event = world.load_event("evt-000001")
    assert event["poses"]["ava"] == START["ava"], "the event snapshot moved"
    assert (event["event_x_cm"], event["event_y_cm"]) == START["ava"][:2]

    scan = world.load_scan("scan-000001")
    assert scan["pose"] == AVA_SEES, "the scan used the departure pose"
    assert scan["event_id"] == "evt-000001"
    assert world.current_pose("ava") == AVA_SEES


def test_the_scan_pose_is_never_the_event_pose(tmp_path):
    """A structural statement of the same thing: the two tables disagree."""
    world, wc, mc = fresh(tmp_path)
    assert move(world, "ava", AVA_SEES, at="t1").accepted
    event_pose = wc.execute(
        "SELECT x_cm, y_cm, facing_x, facing_y FROM world_pose "
        "WHERE event_id='evt-000000' AND being_id='ava'").fetchone()
    scan_pose = wc.execute(
        "SELECT x_cm, y_cm, facing_x, facing_y FROM arrival_scan "
        "WHERE being_id='ava'").fetchone()
    assert tuple(event_pose) == START["ava"]
    assert tuple(scan_pose) == AVA_SEES
    assert tuple(event_pose) != tuple(scan_pose)


def test_arrival_sees_what_only_the_arrival_pose_can_see(tmp_path):
    """The discriminating geometry: invisible from the departure, visible on
    arrival. A scan run from the departure pose would produce nothing."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted

    from one_world.sensing import sense_state
    objects = ((("lighter-1"), LIGHTER[0], LIGHTER[1]),)
    assert sense_state(observer_pose=START["ava"], objects=objects, walls=()) == {}
    assert sense_state(observer_pose=AVA_SEES, objects=objects, walls=()) == {
        "lighter-1": "CLEAR"}

    assert move(world, "ava", AVA_SEES, at="t2").accepted
    assert len(sightings(derive(world, mc), "ava")) == 1


def test_arrival_does_not_see_what_only_the_departure_could_see(tmp_path):
    """The converse geometry, so the control cannot pass by luck in one
    direction. Ava starts where she can see the lighter and walks away."""
    poses = dict(START, ava=(250, 0, -1, 0))
    world, wc, mc = fresh(tmp_path, poses=poses)
    assert place(world, "warren", *LIGHTER, at="t1").accepted

    departed = (250, 0, 1, 0)          # same spot, now facing AWAY from it
    from one_world.sensing import sense_state
    objects = (("lighter-1", LIGHTER[0], LIGHTER[1]),)
    assert sense_state(observer_pose=poses["ava"], objects=objects, walls=())
    assert sense_state(observer_pose=departed, objects=objects, walls=()) == {}

    assert move(world, "ava", departed, at="t2").accepted
    assert sightings(derive(world, mc), "ava") == [], (
        "the scan used the departure pose and saw what she turned away from")


# -- occlusion still governs access ----------------------------------------


def test_ava_sees_it_and_a_wall_keeps_noah_from_the_same_object(tmp_path):
    """Two inhabitants, the same persistent object, different information."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    world.add_wall(*BLOCKING_WALL)

    assert move(world, "ava", AVA_SEES, at="t2").accepted
    assert move(world, "noah", NOAH_BLOCKED, at="t3").accepted
    history = derive(world, mc)

    ava_seen = sightings(history, "ava")
    assert len(ava_seen) == 1 and ava_seen[0]["content"]["object"] == "red lighter"
    assert sightings(history, "noah") == [], "the wall did not block him"

    # The wall is the whole difference: from the very same pose, with nothing
    # in the way, Noah would have resolved it at full detail.
    from one_world.sensing import sense_state
    objects = (("lighter-1", LIGHTER[0], LIGHTER[1]),)
    assert sense_state(observer_pose=NOAH_BLOCKED, objects=objects,
                       walls=()) == {"lighter-1": "CLEAR"}
    assert sense_state(observer_pose=NOAH_BLOCKED, objects=objects,
                       walls=(BLOCKING_WALL[1:],)) == {}


def test_noah_sees_it_after_the_wall_comes_down_and_he_moves_again(tmp_path):
    """A NEW arrival yields a NEW observation; the old blindness stays."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    world.add_wall(*BLOCKING_WALL)
    assert move(world, "noah", NOAH_BLOCKED, at="t2").accepted
    history = derive(world, mc)
    assert sightings(history, "noah") == []
    first_scan = "scan-000001"

    world.remove_wall(BLOCKING_WALL[0])
    assert move(world, "noah", NOAH_CLEAR, at="t3").accepted
    history = derive(world, mc)

    seen = sightings(history, "noah")
    assert len(seen) == 1
    assert seen[0]["content"] == {"object": "red lighter", "at": list(LIGHTER)}

    # The earlier arrival was NOT retroactively filled in.
    assert world.load_scan(first_scan)["sightings"] == []
    assert wc.execute(
        "SELECT COUNT(*) FROM arrival_sighting WHERE scan_id = ?",
        (first_scan,)).fetchone()[0] == 0
    origins = {r[0] for r in mc.execute(
        "SELECT origin_ref FROM perception WHERE character_id='noah' "
        "AND kind='SIGHTING'")}
    assert origins and not any(o.startswith("sig-000001") for o in origins)


def test_removing_the_wall_alone_gives_noah_nothing(tmp_path):
    """Demolition is not perception. Without a new arrival he learns nothing."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    world.add_wall(*BLOCKING_WALL)
    assert move(world, "noah", NOAH_BLOCKED, at="t2").accepted
    derive(world, mc)

    world.remove_wall(BLOCKING_WALL[0])
    PerceptionRouter(world, mc).derive_pending()
    assert sightings(CharacterHistory(mc), "noah") == []


# -- coarse arrival --------------------------------------------------------


def test_a_distant_arrival_learns_only_that_something_is_there(tmp_path):
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", AVA_COARSE, at="t2").accepted
    history = derive(world, mc)

    seen = sightings(history, "ava")
    assert len(seen) == 1
    assert seen[0]["grade"] == "COARSE"
    assert seen[0]["content"] == {"object": "something"}


def test_coarse_arrival_leaks_nothing_through_any_stored_field(tmp_path):
    """Raw minds.db, every column -- not just the content blob.

    origin_ref and perception_id are structural columns that a careless
    identity scheme would use to smuggle the object id out.
    """
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", AVA_COARSE, at="t2").accepted
    derive(world, mc)

    rows = mc.execute(
        "SELECT perception_id, character_id, perception_seq, kind, grade, "
        "perceived_json, origin_ref, source FROM perception "
        "WHERE character_id='ava' AND kind='SIGHTING'").fetchall()
    assert rows, "no coarse sighting to inspect; the check would be vacuous"
    whole = " ".join(str(v) for row in rows for v in row).lower()
    for forbidden in ("lighter-1", "red lighter", "lighter", "red", '"at"',
                      "100"):
        assert forbidden not in whole, f"{forbidden} leaked to a coarse observer"

    contents = [json.loads(r["perceived_json"]) for r in rows]
    assert contents == [{"object": "something"}]


def test_the_canonical_side_did_keep_the_detail(tmp_path):
    """Anti-vacuity for the leak test: the detail exists, and was withheld."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", AVA_COARSE, at="t2").accepted
    derive(world, mc)
    row = wc.execute(
        "SELECT description, x_cm, y_cm, grade FROM arrival_sighting").fetchone()
    assert tuple(row) == ("red lighter", 100, 0, "COARSE")


# -- observation memory is not a live query --------------------------------


def test_what_she_saw_at_p1_stays_p1_after_the_object_moves(tmp_path):
    """The distinction between a memory and a query against present state."""
    world, wc, mc = fresh(tmp_path)
    p1, p2 = LIGHTER, (200, 0)

    assert place(world, "warren", *p1, at="t1").accepted
    assert move(world, "ava", AVA_SEES, at="t2").accepted
    history = derive(world, mc)
    assert [m["content"]["at"] for m in sightings(history, "ava")] == [list(p1)]

    # The lighter is taken away and put down somewhere else entirely.
    assert move(world, "ava", AVA_REACH, at="t3").accepted
    assert pickup(world, "ava", at="t4").accepted
    assert place(world, "ava", *p2, at="t5").accepted
    loc = world.object_location("lighter-1")
    assert (loc["x_cm"], loc["y_cm"]) == p2

    history = derive(world, mc)
    ats = [m["content"]["at"] for m in sightings(history, "ava")]
    assert ats[0] == list(p1), "an old observation was rewritten to today's position"
    assert list(p2) not in ats[:2]


def test_a_later_scan_records_the_new_position_without_touching_the_old(tmp_path):
    world, wc, mc = fresh(tmp_path)
    p1, p2 = LIGHTER, (200, 0)
    assert place(world, "warren", *p1, at="t1").accepted
    assert move(world, "ava", AVA_SEES, at="t2").accepted
    assert move(world, "ava", AVA_REACH, at="t3").accepted   # sees it again
    assert pickup(world, "ava", at="t4").accepted
    assert place(world, "ava", *p2, at="t5").accepted
    assert move(world, "ava", (350, 0, -1, 0), at="t6").accepted

    history = derive(world, mc)
    ats = [m["content"]["at"] for m in sightings(history, "ava")]
    assert ats == [list(p1), list(p1), list(p2)], (
        "observations did not track the object's real history of positions")


def test_a_held_object_is_not_observable_state(tmp_path):
    """v0.8 observes PLACED objects. Pockets are not scanned."""
    world, wc, mc = fresh(tmp_path)
    assert world.object_location("lighter-1")["holder_id"] == "warren"
    assert move(world, "ava", (60, 0, -1, 0), at="t1").accepted   # 20 cm away
    history = derive(world, mc)
    assert sightings(history, "ava") == []
    assert world.placed_objects() == []


# -- repeated observation and replay ---------------------------------------


def test_the_same_object_may_be_observed_again_in_a_later_scan(tmp_path):
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", AVA_SEES, at="t2").accepted
    assert move(world, "ava", AVA_AGAIN, at="t3").accepted
    history = derive(world, mc)

    seen = sightings(history, "ava")
    assert len(seen) == 2, "the second observation was deduplicated away"
    assert seen[0]["content"] == seen[1]["content"]     # same object, same spot
    assert seen[0]["seq"] < seen[1]["seq"]              # explicit ordering

    # Two distinct scans, two distinct origins.
    origins = [r[0] for r in mc.execute(
        "SELECT origin_ref FROM perception WHERE character_id='ava' "
        "AND kind='SIGHTING' ORDER BY perception_seq")]
    assert len(set(origins)) == 2
    assert [o.split("-")[1] for o in origins] == ["000001", "000002"]


def test_replaying_the_same_scan_creates_no_second_memory(tmp_path):
    """The crash-after-write, before-DONE window, for state observations."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", AVA_SEES, at="t2").accepted
    derive(world, mc)
    before = sorted(tuple(r) for r in mc.execute("SELECT * FROM perception"))
    assert before

    for _ in range(3):
        with wc:  # simulate the lost DONE mark, repeatedly
            wc.execute("UPDATE arrival_scan_outbox SET state='PENDING'")
        assert PerceptionRouter(world, mc).derive_pending() == 0
    assert sorted(tuple(r) for r in mc.execute("SELECT * FROM perception")) == before
    assert {r[0] for r in wc.execute(
        "SELECT state FROM arrival_scan_outbox")} == {"DONE"}


def test_a_duplicate_observation_is_structurally_inexpressible(tmp_path):
    """Idempotency is a constraint, not merely a procedure that checks first."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", AVA_SEES, at="t2").accepted
    derive(world, mc)
    row = mc.execute(
        "SELECT * FROM perception WHERE kind='SIGHTING'").fetchone()
    assert row

    with pytest.raises(sqlite3.IntegrityError):
        with mc:
            mc.execute(
                "INSERT INTO perception (perception_id, character_id, "
                "perception_seq, kind, grade, perceived_json, origin_ref, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("forged", row["character_id"], 99, row["kind"], row["grade"],
                 row["perceived_json"], row["origin_ref"], row["source"]),
            )


# -- one order across both epistemic sources -------------------------------


def test_event_and_state_memories_share_one_dense_character_order(tmp_path):
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", AVA_SEES, at="t2").accepted     # move + sighting
    assert pickup(world, "warren", at="t3").accepted          # an event she sees
    assert place(world, "warren", *LIGHTER, at="t4").accepted
    assert move(world, "ava", AVA_AGAIN, at="t5").accepted    # move + sighting
    history = derive(world, mc)

    ava = history.recall("ava")
    assert [(m["kind"], m["source"]) for m in ava] == [
        ("MOVE", "EVENT"),
        ("SIGHTING", "STATE"),
        ("PICKUP", "EVENT"),
        ("PLACE", "EVENT"),
        ("MOVE", "EVENT"),
        ("SIGHTING", "STATE"),
    ]
    assert [m["seq"] for m in ava] == [0, 1, 2, 3, 4, 5]


def test_the_move_event_is_remembered_before_the_arrival_it_caused(tmp_path):
    """The tie-break at one world_seq, stated as a property."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", AVA_SEES, at="t2").accepted
    history = derive(world, mc)
    ava = history.recall("ava")
    assert ava[0]["kind"] == "MOVE" and ava[1]["kind"] == "SIGHTING"

    # Both hang off the same canonical seq: the scan consumed none of its own.
    assert wc.execute(
        "SELECT world_seq FROM arrival_scan").fetchone()[0] == 1
    assert [r[0] for r in wc.execute(
        "SELECT world_seq FROM world_event ORDER BY world_seq")] == [0, 1]


def test_ordering_survives_a_physical_row_reshuffle(tmp_path):
    """Order comes from perception_seq, never from rowid or insertion order."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", AVA_SEES, at="t2").accepted
    before = derive(world, mc).recall("ava")
    assert [m["kind"] for m in before] == ["MOVE", "SIGHTING"]

    rows = [dict(r) for r in mc.execute("SELECT * FROM perception")]
    cols = ("perception_id", "character_id", "perception_seq", "kind", "grade",
            "perceived_json", "origin_ref", "source")
    with mc:
        mc.execute("DELETE FROM perception")
        for r in reversed(rows):
            mc.execute(
                f"INSERT INTO perception ({','.join(cols)}) "
                f"VALUES ({','.join('?' * len(cols))})",
                tuple(r[c] for c in cols))
    seqs = [r[0] for r in mc.execute(
        "SELECT perception_seq FROM perception ORDER BY rowid")]
    assert seqs != sorted(seqs), "the reshuffle did not invert physical order"
    assert CharacterHistory(mc).recall("ava") == before


# -- the arrival record is canonical and immutable -------------------------


@pytest.mark.parametrize(
    "table,statement,message",
    [
        ("arrival_scan", "UPDATE arrival_scan SET x_cm = 9999", "immutable"),
        ("arrival_scan", "DELETE FROM arrival_scan", "append-only"),
        ("arrival_sighting", "UPDATE arrival_sighting SET grade='CLEAR'",
         "immutable"),
        ("arrival_sighting", "DELETE FROM arrival_sighting", "append-only"),
    ],
)
def test_the_arrival_record_cannot_be_rewritten(tmp_path, table, statement,
                                                message):
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", AVA_SEES, at="t2").accepted
    before = sorted(tuple(r) for r in wc.execute(f"SELECT * FROM {table}"))
    assert before, f"{table} is empty; the test would be vacuous"

    with pytest.raises(sqlite3.IntegrityError, match=message):
        with wc:
            wc.execute(statement)
    assert sorted(tuple(r) for r in wc.execute(f"SELECT * FROM {table}")) == before


def test_a_scan_cannot_exist_without_the_move_that_caused_it(tmp_path):
    """An arrival is always anchored to canonical history, structurally.

    This is why the older suites' "leaves no trace" checks still hold without
    naming the arrival tables: a scan with no event cannot be written at all.
    """
    world, wc, mc = fresh(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        with wc:
            wc.execute(
                "INSERT INTO arrival_scan (scan_id, world_seq, event_id, "
                "being_id, x_cm, y_cm, facing_x, facing_y) "
                "VALUES ('scan-forged', 99, 'evt-999999', 'ava', 0, 0, 1, 0)")
    assert wc.execute("SELECT COUNT(*) FROM arrival_scan").fetchone()[0] == 0


def test_one_move_cannot_carry_two_arrival_scans(tmp_path):
    """A MOVE is one arrival, so it anchors exactly one scan."""
    world, wc, mc = fresh(tmp_path)
    assert move(world, "ava", AVA_SEES, at="t1").accepted
    with pytest.raises(sqlite3.IntegrityError):
        with wc:
            wc.execute(
                "INSERT INTO arrival_scan (scan_id, world_seq, event_id, "
                "being_id, x_cm, y_cm, facing_x, facing_y) "
                "VALUES ('scan-second', 99, 'evt-000000', 'ava', 0, 0, 1, 0)")
    assert wc.execute("SELECT COUNT(*) FROM arrival_scan").fetchone()[0] == 1


def test_a_sighting_cannot_be_forged_through_commit_event(tmp_path):
    """SIGHTING is not an event kind and cannot be smuggled in as one."""
    world, wc, mc = fresh(tmp_path)
    assert "SIGHTING" not in STATE_CHANGING_KINDS
    with pytest.raises(ValueError, match="no sensing rule defined"):
        world.commit_event(kind="SIGHTING", location=ROOM, actor_id="ava",
                           payload={"object": "red lighter", "at": [0, 0]},
                           presence=ALL_THREE, event_x_cm=0, event_y_cm=0,
                           occurred_at="t")
    assert wc.execute("SELECT COUNT(*) FROM world_event").fetchone()[0] == 0


def test_arrival_scan_is_atomic_with_the_move(tmp_path, monkeypatch):
    """If the scan fails, the move did not happen either."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    before = snapshot(wc)
    assert world.current_pose("ava") == START["ava"]

    import one_world.world as world_module

    def boom(**kwargs):
        raise RuntimeError("state sensing exploded mid-transaction")

    monkeypatch.setattr(world_module, "sense_state", boom)
    with pytest.raises(RuntimeError, match="exploded"):
        move(world, "ava", AVA_SEES, at="t2")

    assert snapshot(wc) == before, "partial work survived a failed arrival scan"
    assert world.current_pose("ava") == START["ava"], "the pose moved anyway"
    assert wc.execute(
        "SELECT COUNT(*) FROM world_event WHERE kind='MOVE'").fetchone()[0] == 0


def test_the_injection_would_otherwise_have_written(tmp_path):
    """Anti-vacuity for the atomicity test."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    before = snapshot(wc)
    assert move(world, "ava", AVA_SEES, at="t2").accepted
    after = snapshot(wc)
    assert len(after["arrival_scan"]) == len(before["arrival_scan"]) + 1
    assert len(after["arrival_sighting"]) == len(before["arrival_sighting"]) + 1
    assert after["being_pose"] != before["being_pose"]


# -- crash between the arrival and its observations ------------------------


def test_crash_after_move_then_a_changed_world_then_recovery(tmp_path):
    """The hardest v0.8 property, across real processes.

    MOVE commits. The process dies before a single observation is written. The
    lighter is then carried off and a wall goes up across the sight line Ava
    used. Only then does recovery run.

    What Ava perceives must be what she perceived on ARRIVAL -- not what a scan
    of today's world would find, which is nothing at all.
    """
    p = run_phase(tmp_path, "arrival-populate", "--crash-before-derive", "1")
    assert p.returncode == 9, f"expected a hard exit, got {p.returncode}: {p.stderr}"

    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    assert wc.execute(
        "SELECT COUNT(*) FROM arrival_scan").fetchone()[0] == 1
    assert {r[0] for r in wc.execute(
        "SELECT state FROM arrival_scan_outbox")} == {"PENDING"}
    mc = sqlite3.connect(os.path.join(tmp_path, "minds.db"))
    assert mc.execute(
        "SELECT COUNT(*) FROM perception WHERE kind='SIGHTING'").fetchone()[0] == 0

    d = run_phase(tmp_path, "arrival-disturb")
    assert d.returncode == 0, d.stderr
    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    assert wc.execute(
        "SELECT COUNT(*) FROM object_location WHERE x_cm IS NOT NULL"
    ).fetchone()[0] == 0, "the lighter is still lying there; the test is weak"
    assert wc.execute("SELECT COUNT(*) FROM wall").fetchone()[0] == 1

    r = run_phase(tmp_path, "recover")
    assert r.returncode == 0, r.stderr

    data = json.loads(run_phase(tmp_path, "recall").stdout)
    seen = [m for m in data["ava"] if m["kind"] == "SIGHTING"]
    assert len(seen) == 1, "the arrival observation was lost or duplicated"
    assert seen[0]["grade"] == "CLEAR"
    assert seen[0]["content"] == {"object": "red lighter", "at": list(LIGHTER)}
    assert seen[0]["source"] == "STATE"


def test_delayed_recovery_matches_an_uninterrupted_run_exactly(tmp_path):
    """Stated as an equality, not as a spot check on one field."""
    clean = tmp_path / "clean"
    crashed = tmp_path / "crashed"
    os.makedirs(clean, exist_ok=True)
    os.makedirs(crashed, exist_ok=True)

    assert run_phase(clean, "arrival-populate").returncode == 0
    assert run_phase(crashed, "arrival-populate",
                     "--crash-before-derive", "1").returncode == 9
    assert run_phase(crashed, "arrival-disturb").returncode == 0
    assert run_phase(crashed, "recover").returncode == 0

    a = [m for m in json.loads(run_phase(clean, "recall").stdout)["ava"]
         if m["kind"] == "SIGHTING"]
    b = [m for m in json.loads(run_phase(crashed, "recall").stdout)["ava"]
         if m["kind"] == "SIGHTING"]
    assert len(a) == 1, "the uninterrupted run observed nothing; nothing to match"
    assert b == a


def test_recovery_of_an_arrival_scan_is_idempotent(tmp_path):
    assert run_phase(tmp_path, "arrival-populate",
                     "--crash-before-derive", "1").returncode == 9
    assert run_phase(tmp_path, "recover").returncode == 0
    mc = sqlite3.connect(os.path.join(tmp_path, "minds.db"))
    before = mc.execute(
        "SELECT character_id, perception_seq, origin_ref, source FROM perception "
        "ORDER BY character_id, perception_seq").fetchall()
    for _ in range(3):
        rec = json.loads(run_phase(tmp_path, "recover").stdout)
        assert rec["derived"] == 0
    mc = sqlite3.connect(os.path.join(tmp_path, "minds.db"))
    assert mc.execute(
        "SELECT character_id, perception_seq, origin_ref, source FROM perception "
        "ORDER BY character_id, perception_seq").fetchall() == before


def test_the_arrival_observation_survives_a_plain_restart(tmp_path):
    assert run_phase(tmp_path, "arrival-populate").returncode == 0
    first = json.loads(run_phase(tmp_path, "recall").stdout)
    second = json.loads(run_phase(tmp_path, "recall").stdout)
    assert first == second
    seen = [m for m in first["ava"] if m["kind"] == "SIGHTING"]
    assert len(seen) == 1
    assert seen[0]["content"] == {"object": "red lighter", "at": list(LIGHTER)}


# -- source audit: who writes memories, and what do they read --------------


def test_the_scan_replay_path_reads_no_mutable_canonical_table():
    """The structural half of the crash-consistency guarantee.

    Filters on the executed statements, not the docstring -- which names those
    tables precisely to say it does not read them.
    """
    statements = [c for c in WorldStore.load_scan.__code__.co_consts
                  if isinstance(c, str) and "SELECT" in c]
    assert len(statements) == 2, statements
    joined = " ".join(statements)
    for mutable in ("object_location", "being_pose", "wall", "world_pose",
                    "world_event"):
        assert mutable not in joined, f"load_scan consults {mutable}"
    assert "arrival_scan" in joined and "arrival_sighting" in joined


def test_state_sensing_happens_once_at_arrival_and_never_at_projection():
    """Sensing is not re-run when memories are written."""
    import one_world.perception as perception_module
    import one_world.minds as minds_module

    for module in (perception_module, minds_module):
        src = inspect.getsource(module)
        assert "sense_state" not in src, f"{module.__name__} re-senses state"
        assert "sense_event" not in src
    assert "sense_state" in inspect.getsource(WorldStore._record_arrival_scan)


def test_every_production_writer_of_perceptions_is_accounted_for():
    """Mechanical: find the INSERTs, not the names that sound like writers."""
    import one_world.actions as actions_module
    import one_world.minds as minds_module
    import one_world.perception as perception_module
    import one_world.scenario as scenario_module
    import one_world.world as world_module

    # "INSERT INTO perception (" -- the memory table itself, not the
    # similarly-named perception_seq_counter.
    writers = []
    for module in (actions_module, minds_module, perception_module,
                   scenario_module, world_module):
        for line in inspect.getsource(module).splitlines():
            if "INSERT INTO perception (" in line:
                writers.append(module.__name__)
    assert writers == ["one_world.perception"], writers

    router_src = inspect.getsource(PerceptionRouter)
    assert router_src.count("INSERT INTO perception (") == 1, (
        "more than one write path into character memory")

    # Both derivations reach that single writer, and both reduce on the way.
    for name in ("_derive_one", "_derive_scan"):
        src = inspect.getsource(getattr(PerceptionRouter, name))
        assert "self._write(" in src
        assert "project(" in src, f"{name} writes without reducing"


def test_character_facing_code_still_cannot_reach_canonical_state():
    """Including the tables v0.8 introduced."""
    import one_world.minds as minds_module

    src = inspect.getsource(minds_module)
    for token in ("arrival_scan", "arrival_sighting", "object_location",
                  "world_event", "sqlite3.connect", "open_world"):
        assert token not in src, f"character-facing code names {token}"


def test_recall_returns_stored_bytes_and_derives_nothing(tmp_path):
    """A memory is what was written, not a fresh interpretation of it."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", AVA_SEES, at="t2").accepted
    derive(world, mc)

    stored = mc.execute(
        "SELECT perceived_json FROM perception WHERE kind='SIGHTING'"
    ).fetchone()[0]
    recalled = [m for m in CharacterHistory(mc).recall("ava")
                if m["kind"] == "SIGHTING"][0]
    assert recalled["content"] == json.loads(stored)

    # Detach the canonical store entirely; recall is unaffected.
    wc.close()
    assert [m for m in CharacterHistory(mc).recall("ava")
            if m["kind"] == "SIGHTING"][0] == recalled


def test_sighting_projection_fails_closed_on_an_unknown_grade():
    with pytest.raises(ValueError, match="unknown grade"):
        project("SIGHTING", {"object": "red lighter", "at": [0, 0]}, "XRAY")


# -- pre-v0.8 stores -------------------------------------------------------


def test_a_v07_perception_store_migrates_and_keeps_its_rows(tmp_path):
    """Old rows stay valid, and are labelled with the only source they can have."""
    path = os.path.join(tmp_path, "old.db")
    old = sqlite3.connect(path)
    with old:
        old.executescript(
            "CREATE TABLE perception (perception_id TEXT PRIMARY KEY, "
            "character_id TEXT NOT NULL, perception_seq INTEGER NOT NULL, "
            "kind TEXT NOT NULL, grade TEXT NOT NULL, perceived_json TEXT NOT NULL, "
            "origin_ref TEXT NOT NULL, UNIQUE (character_id, perception_seq), "
            "UNIQUE (character_id, origin_ref));"
            "CREATE TABLE perception_seq_counter (character_id TEXT PRIMARY KEY, "
            "next_seq INTEGER NOT NULL);"
        )
        old.execute(
            "INSERT INTO perception VALUES ('evt-000000:ava', 'ava', 0, 'PLACE', "
            "'CLEAR', '{\"actor\":\"warren\"}', 'evt-000000')")
    old.close()

    conn = schema.open_minds(path)
    schema.init_minds(conn)
    recalled = CharacterHistory(conn).recall("ava")
    assert recalled == [{"seq": 0, "kind": "PLACE", "grade": "CLEAR",
                         "source": "EVENT", "content": {"actor": "warren"}}]
