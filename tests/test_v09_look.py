"""v0.9: an inhabitant may observe the world without moving.

The hazard this suite is written against is a LOOK test that passes because the
observer secretly perceived the PLACE, or because they moved at some point and
got an arrival scan for free. Every scenario therefore asserts the negative --
no PLACE perception, and zero MOVE events -- before asserting the positive.

The second hazard is the pose assertion that compares the wrong snapshot. Pose
equality here is read from `being_pose` (canonical present state) before and
after, never from an event-time or scan-time snapshot, which could agree while
the real pose moved underneath.
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
    NOT_PLACED, UNKNOWN_ACTOR, propose_look, propose_move, propose_pickup,
    propose_place,
)
from one_world.minds import CharacterHistory
from one_world.perception import PerceptionRouter, project
from one_world.scenario import ALL_THREE, ROOM, seed_world
from one_world.world import STATE_CHANGING_KINDS, WorldStore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Warren is 60 cm from the drop point so he can reach it. Noah starts 30 m away,
# beyond VIEW_RANGE_CM at any facing. Ava is deliberately NOT seeded here: she
# enters after the PLACE, already stationary, and never moves.
BEFORE_AVA = {
    "warren": (40, 0, 1, 0),
    "noah": (0, -3000, 0, -1),
}
LIGHTER = (100, 0)
PRESENT_WITHOUT_AVA = ["warren", "noah"]

AVA_STATION = (250, 0, -1, 0)     # 150 cm from it: inside DETAIL_RANGE_CM
AVA_FAR = (700, 0, -1, 0)         # 600 cm: seen, not resolved
AVA_AVERTED = (250, 0, 1, 0)      # same spot, facing away
NOAH_STATION = (-150, 0, 1, 0)    # 250 cm, but the wall stands between
BLOCKING_WALL = ("w1", 0, -50, 0, 50)


def run_phase(d, phase, *extra):
    return subprocess.run(
        [sys.executable, "-m", "one_world.scenario", "--dir", str(d),
         "--phase", phase, *extra],
        cwd=ROOT, capture_output=True, text=True,
    )


def fresh(tmp_path, poses=None):
    """A world where the lighter can be placed BEFORE Ava exists in it."""
    os.makedirs(tmp_path, exist_ok=True)
    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    schema.init_world(wc)
    mc = schema.open_minds(os.path.join(tmp_path, "minds.db"))
    schema.init_minds(mc)
    world = WorldStore(wc)
    seed_world(world)
    for being_id, pose in sorted((poses or BEFORE_AVA).items()):
        world.seed_pose(being_id, *pose)
    return world, wc, mc


def place(world, actor, x, y, at="t"):
    return propose_place(world, actor=actor, object_id="lighter-1", x_cm=x,
                         y_cm=y, location=ROOM, occurred_at=at)


def pickup(world, actor, at="t"):
    return propose_pickup(world, actor=actor, object_id="lighter-1",
                          location=ROOM,
                          occurred_at=at)


def look(world, actor, at="t"):
    return propose_look(world, actor=actor, location=ROOM, occurred_at=at)


def move(world, actor, pose, at="t"):
    return propose_move(world, actor=actor, to_x_cm=pose[0], to_y_cm=pose[1],
                        facing_x=pose[2], facing_y=pose[3],
                        location=ROOM, occurred_at=at)


def derive(world, mc):
    PerceptionRouter(world, mc).derive_pending()
    return CharacterHistory(mc)


def physical_state(wc):
    """Everything about the world that LOOK must NOT touch.

    Read from the MUTABLE present-state tables, not from any snapshot: a
    snapshot could agree while canonical reality moved underneath it.
    """
    def rows(t):
        return sorted(tuple(r) for r in wc.execute(f"SELECT * FROM {t}"))
    return {t: rows(t) for t in ("being_pose", "object_location", "wall")}


def sightings(history, character_id):
    return [m for m in history.recall(character_id) if m["kind"] == "SIGHTING"]


def move_count(wc):
    return wc.execute(
        "SELECT COUNT(*) FROM world_event WHERE kind='MOVE'").fetchone()[0]


def seed_ava(world, pose=AVA_STATION):
    world.seed_pose("ava", *pose)


# -- the milestone question ------------------------------------------------


def test_ava_discovers_the_lighter_without_moving(tmp_path):
    """The acceptance scenario: knowledge changes while physical state does not.

    Note WHY the PLACE must precede Ava's existence here. A PLACE event happens
    AT the drop point, so at any single instant no geometry can separate "could
    see the placing" from "can see the object lying there" -- they are the same
    point. Something has to differ between the two moments. The cheapest honest
    difference is that Ava was not yet in the world for the first one.
    """
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t-place").accepted
    derive(world, mc)

    seed_ava(world)
    history = CharacterHistory(mc)
    assert history.recall("ava") == [], "Ava knows something already"
    assert world.load_event("evt-000000")["observations"] == {"warren": "CLEAR"}

    before = physical_state(wc)
    assert look(world, "ava", at="t-look").accepted
    history = derive(world, mc)

    ava = history.recall("ava")
    assert [(m["kind"], m["source"], m["grade"]) for m in ava] == [
        ("LOOK", "EVENT", "CLEAR"),        # she knows she looked, by agency
        ("SIGHTING", "STATE", "CLEAR"),    # and what that got her
    ]
    assert ava[1]["content"] == {"object": "red lighter", "at": list(LIGHTER)}

    # She did NOT acquire the history of how it got there.
    assert [m for m in ava if m["kind"] == "PLACE"] == []
    assert "warren" not in json.dumps(ava[1]["content"])
    # ...and nothing physical moved.
    assert physical_state(wc) == before
    assert move_count(wc) == 0


def test_without_looking_she_stays_ignorant(tmp_path):
    """Anti-vacuity for the acceptance test: LOOK is what changed her."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world)
    for _ in range(3):
        PerceptionRouter(world, mc).derive_pending()
    assert CharacterHistory(mc).recall("ava") == []
    assert world.object_location("lighter-1")["x_cm"] == LIGHTER[0]


def test_the_lighter_may_also_appear_after_she_is_already_standing_there(tmp_path):
    """The stronger version: Ava exists throughout, a wall hides the placing.

    She is present for the PLACE and perceives nothing, because the wall stands
    between her and the drop point. The wall is later demolished -- which is not
    an event and gives her nothing -- and only her LOOK informs her.
    """
    world, wc, mc = fresh(tmp_path)
    seed_ava(world)
    world.add_wall("w-hide", 175, -50, 175, 50)   # between Ava and the drop

    assert place(world, "warren", *LIGHTER, at="t1").accepted
    history = derive(world, mc)
    assert history.recall("ava") == [], "the wall did not hide the placing"

    world.remove_wall("w-hide")
    history = derive(world, mc)
    assert history.recall("ava") == [], "demolition alone taught her something"

    before = physical_state(wc)
    assert look(world, "ava", at="t2").accepted
    history = derive(world, mc)
    seen = sightings(history, "ava")
    assert len(seen) == 1
    assert seen[0]["content"] == {"object": "red lighter", "at": list(LIGHTER)}
    assert [m for m in history.recall("ava") if m["kind"] == "PLACE"] == []
    assert physical_state(wc) == before
    assert move_count(wc) == 0


# -- the non-movement invariant --------------------------------------------


def test_look_changes_no_physical_state_at_all(tmp_path):
    """Raw before/after over every mutable present-state table."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world)
    world.add_wall("w-x", 900, -50, 900, 50)

    before = physical_state(wc)
    assert before["being_pose"] and before["object_location"] and before["wall"]

    for i in range(3):
        assert look(world, "ava", at=f"t-look-{i}").accepted
    after = physical_state(wc)

    assert after == before, "LOOK moved the world"
    assert world.current_pose("ava") == AVA_STATION
    assert move_count(wc) == 0


def test_look_does_not_change_facing(tmp_path):
    """Facing is taken as it already is; rotation remains a MOVE."""
    world, wc, mc = fresh(tmp_path)
    seed_ava(world, AVA_AVERTED)
    assert look(world, "ava", at="t1").accepted
    assert world.current_pose("ava") == AVA_AVERTED

    # Facing away, she learns nothing even with the lighter in range.
    assert place(world, "warren", *LIGHTER, at="t2").accepted
    assert look(world, "ava", at="t3").accepted
    assert sightings(derive(world, mc), "ava") == []
    assert world.current_pose("ava") == AVA_AVERTED


def test_look_holds_no_primitive_that_could_move_anything():
    """Capability, not naming: the source cannot reach the mutating helpers."""
    src = inspect.getsource(propose_look)
    for primitive in ("_move_pose", "_place_object", "_take_object",
                      "_transfer_holder", "_set_stow", "add_wall",
                      "remove_wall", "seed_pose"):
        assert primitive not in src, f"propose_look can call {primitive}"


def test_rotating_then_looking_is_the_documented_route(tmp_path):
    """v0.9 does not fuse turn+look; the two-step route works."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world, AVA_AVERTED)

    assert look(world, "ava", at="t2").accepted
    assert sightings(derive(world, mc), "ava") == []

    assert move(world, "ava", AVA_STATION, at="t3").accepted   # pure rotation
    assert look(world, "ava", at="t4").accepted
    assert len(sightings(derive(world, mc), "ava")) == 2, (
        "expected the MOVE arrival scan AND the LOOK scan")


# -- occlusion, without anybody moving -------------------------------------


def test_a_wall_divides_two_stationary_lookers(tmp_path):
    world, wc, mc = fresh(tmp_path, poses={
        "warren": (40, 0, 1, 0), "noah": NOAH_STATION})
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world)
    world.add_wall(*BLOCKING_WALL)

    assert look(world, "ava", at="t2").accepted
    assert look(world, "noah", at="t3").accepted
    history = derive(world, mc)

    assert len(sightings(history, "ava")) == 1
    assert sightings(history, "noah") == [], "the wall did not block him"
    assert move_count(wc) == 0

    # The wall is the whole difference: unobstructed, from that very pose, he
    # would have resolved it at full detail.
    from one_world.sensing import sense_state
    objects = (("lighter-1", LIGHTER[0], LIGHTER[1]),)
    assert sense_state(observer_pose=NOAH_STATION, objects=objects,
                       walls=()) == {"lighter-1": "CLEAR"}


def test_noah_learns_it_by_looking_again_with_no_move_at_all(tmp_path):
    """The v0.8 limitation lifted: v0.8 needed another MOVE for a new scan."""
    world, wc, mc = fresh(tmp_path, poses={
        "warren": (40, 0, 1, 0), "noah": NOAH_STATION})
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    world.add_wall(*BLOCKING_WALL)

    assert look(world, "noah", at="t2").accepted
    history = derive(world, mc)
    assert sightings(history, "noah") == []
    first_scan = "scan-000001"

    world.remove_wall(BLOCKING_WALL[0])
    pose_before = world.current_pose("noah")
    assert look(world, "noah", at="t3").accepted
    history = derive(world, mc)

    seen = sightings(history, "noah")
    assert len(seen) == 1
    assert seen[0]["content"] == {"object": "red lighter", "at": list(LIGHTER)}
    assert world.current_pose("noah") == pose_before == NOAH_STATION
    assert move_count(wc) == 0, "he moved; the milestone claim is not proven"

    # The earlier LOOK stays a non-observation, not retroactively filled in.
    assert world.load_scan(first_scan)["sightings"] == []
    assert wc.execute(
        "SELECT COUNT(*) FROM arrival_sighting WHERE scan_id = ?",
        (first_scan,)).fetchone()[0] == 0


def test_removing_the_wall_alone_still_gives_nothing(tmp_path):
    """Demolition is not perception, and v0.9 does not make it one."""
    world, wc, mc = fresh(tmp_path, poses={
        "warren": (40, 0, 1, 0), "noah": NOAH_STATION})
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    world.add_wall(*BLOCKING_WALL)
    assert look(world, "noah", at="t2").accepted
    derive(world, mc)

    world.remove_wall(BLOCKING_WALL[0])
    PerceptionRouter(world, mc).derive_pending()
    assert sightings(CharacterHistory(mc), "noah") == []


# -- LOOK and arrival must agree -------------------------------------------


def test_look_and_arrival_at_the_same_pose_see_exactly_the_same_thing(tmp_path):
    """If these disagreed, one of them would be using the wrong geometry."""
    # A: Ava arrives at the pose by moving.
    a, awc, amc = fresh(tmp_path / "arrival")
    assert place(a, "warren", *LIGHTER, at="t1").accepted
    a.seed_pose("ava", 0, 3000, 0, 1)
    assert move(a, "ava", AVA_STATION, at="t2").accepted
    arrival = sightings(derive(a, amc), "ava")

    # B: Ava is already standing at that pose and looks.
    b, bwc, bmc = fresh(tmp_path / "look")
    assert place(b, "warren", *LIGHTER, at="t1").accepted
    b.seed_pose("ava", *AVA_STATION)
    assert look(b, "ava", at="t2").accepted
    looked = sightings(derive(b, bmc), "ava")

    assert arrival and looked, "one side observed nothing; comparison is vacuous"
    assert [(m["grade"], m["content"]) for m in arrival] == [
        (m["grade"], m["content"]) for m in looked]

    # ...and the canonical record still says which trigger produced each.
    assert awc.execute(
        "SELECT trigger FROM arrival_scan").fetchone()[0] == "MOVE"
    assert bwc.execute(
        "SELECT trigger FROM arrival_scan").fetchone()[0] == "LOOK"


def test_a_look_uses_where_she_is_now_not_where_she_last_arrived(tmp_path):
    """The LOOK pose is the CURRENT pose, not any earlier scan's.

    Ava arrives first at 600 cm -- inside visual range, outside detail range, so
    that arrival resolves nothing -- and then at 150 cm. A LOOK computed from
    either earlier arrival snapshot would come back COARSE.

    This is the only shape of stale-pose bug LOOK can have. Reusing the LOOK
    event's own world_pose would be undetectable and harmless, because LOOK
    changes no pose and that snapshot therefore equals the current one; the
    staleness has to come from an EARLIER scan.
    """
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    world.seed_pose("ava", 0, 3000, 0, 1)
    assert move(world, "ava", AVA_FAR, at="t2").accepted        # arrival: far
    assert move(world, "ava", AVA_STATION, at="t3").accepted    # arrival: near
    assert look(world, "ava", at="t4").accepted

    grades = [m["grade"] for m in sightings(derive(world, mc), "ava")]
    assert grades == ["COARSE", "CLEAR", "CLEAR"], grades

    look_pose = wc.execute(
        "SELECT x_cm, y_cm, facing_x, facing_y FROM arrival_scan "
        "WHERE trigger='LOOK'").fetchone()
    assert tuple(look_pose) == AVA_STATION == world.current_pose("ava")
    # ...and the earlier arrival really did record a different pose.
    poses = [tuple(r) for r in wc.execute(
        "SELECT x_cm, y_cm, facing_x, facing_y FROM arrival_scan "
        "WHERE trigger='MOVE' ORDER BY world_seq")]
    assert poses == [AVA_FAR, AVA_STATION]


# -- repeated looks --------------------------------------------------------


def test_two_looks_at_an_unchanged_world_are_two_observations(tmp_path):
    """Looking twice is two experiences; the world does not judge one wasteful."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world)
    assert look(world, "ava", at="t2").accepted
    assert look(world, "ava", at="t3").accepted
    history = derive(world, mc)

    seen = sightings(history, "ava")
    assert len(seen) == 2, "the second look was deduplicated away"
    assert seen[0]["content"] == seen[1]["content"]
    assert seen[0]["seq"] < seen[1]["seq"]
    origins = [r[0] for r in mc.execute(
        "SELECT origin_ref FROM perception WHERE character_id='ava' "
        "AND kind='SIGHTING' ORDER BY perception_seq")]
    assert len(set(origins)) == 2


def test_the_second_look_records_the_new_position_and_leaves_the_first(tmp_path):
    world, wc, mc = fresh(tmp_path)
    p1, p2 = LIGHTER, (200, 0)
    assert place(world, "warren", *p1, at="t1").accepted
    seed_ava(world)
    assert look(world, "ava", at="t2").accepted
    history = derive(world, mc)
    assert [m["content"]["at"] for m in sightings(history, "ava")] == [list(p1)]

    # Warren takes it and puts it down elsewhere. Ava still has not moved.
    assert pickup(world, "warren", at="t3").accepted
    assert move(world, "warren", (160, 0, 1, 0), at="t4").accepted
    assert place(world, "warren", *p2, at="t5").accepted
    assert world.current_pose("ava") == AVA_STATION

    assert look(world, "ava", at="t6").accepted
    history = derive(world, mc)
    ats = [m["content"]["at"] for m in sightings(history, "ava")]
    assert ats == [list(p1), list(p2)], "a look rewrote an earlier one"


def test_replaying_the_same_look_creates_no_second_memory(tmp_path):
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world)
    assert look(world, "ava", at="t2").accepted
    derive(world, mc)
    before = sorted(tuple(r) for r in mc.execute("SELECT * FROM perception"))
    assert before
    looks_before = wc.execute(
        "SELECT COUNT(*) FROM world_event WHERE kind='LOOK'").fetchone()[0]

    for _ in range(3):
        with wc:  # the lost DONE mark, repeatedly
            wc.execute("UPDATE arrival_scan_outbox SET state='PENDING'")
            wc.execute("UPDATE projection_outbox SET state='PENDING'")
        assert PerceptionRouter(world, mc).derive_pending() == 0
    assert sorted(tuple(r) for r in mc.execute("SELECT * FROM perception")) == before
    assert wc.execute(
        "SELECT COUNT(*) FROM world_event WHERE kind='LOOK'"
    ).fetchone()[0] == looks_before, "the replay produced a SECOND look"


# -- ordering --------------------------------------------------------------


def test_the_look_event_is_remembered_before_what_it_revealed(tmp_path):
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world)
    assert look(world, "ava", at="t2").accepted
    ava = derive(world, mc).recall("ava")
    assert [(m["kind"], m["source"]) for m in ava] == [
        ("LOOK", "EVENT"), ("SIGHTING", "STATE")]
    assert wc.execute(
        "SELECT world_seq FROM arrival_scan").fetchone()[0] == 1
    assert [r[0] for r in wc.execute(
        "SELECT world_seq FROM world_event ORDER BY world_seq")] == [0, 1]


def test_mixed_event_state_history_keeps_one_dense_order(tmp_path):
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    world.seed_pose("ava", 0, 3000, 0, 1)
    assert move(world, "ava", AVA_STATION, at="t2").accepted   # MOVE + arrival
    assert look(world, "ava", at="t3").accepted                # LOOK + sighting
    assert pickup(world, "warren", at="t4").accepted           # an event she sees
    assert look(world, "ava", at="t5").accepted                # LOOK, nothing left
    ava = derive(world, mc).recall("ava")

    assert [(m["kind"], m["source"]) for m in ava] == [
        ("MOVE", "EVENT"),
        ("SIGHTING", "STATE"),
        ("LOOK", "EVENT"),
        ("SIGHTING", "STATE"),
        ("PICKUP", "EVENT"),
        ("LOOK", "EVENT"),        # looked, and the lighter was gone
    ]
    assert [m["seq"] for m in ava] == [0, 1, 2, 3, 4, 5]


def test_look_ordering_survives_a_physical_row_reshuffle(tmp_path):
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world)
    assert look(world, "ava", at="t2").accepted
    before = derive(world, mc).recall("ava")
    assert [m["kind"] for m in before] == ["LOOK", "SIGHTING"]

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


# -- information boundary --------------------------------------------------


def test_a_distant_look_learns_only_that_something_is_there(tmp_path):
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world, AVA_FAR)
    assert look(world, "ava", at="t2").accepted
    seen = sightings(derive(world, mc), "ava")
    assert len(seen) == 1
    assert seen[0]["grade"] == "COARSE"
    assert seen[0]["content"] == {"object": "something"}


def test_a_coarse_look_leaks_nothing_through_any_stored_field(tmp_path):
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world, AVA_FAR)
    assert look(world, "ava", at="t2").accepted
    derive(world, mc)

    rows = mc.execute(
        "SELECT perception_id, character_id, perception_seq, kind, grade, "
        "perceived_json, origin_ref, source FROM perception "
        "WHERE character_id='ava' AND kind='SIGHTING'").fetchall()
    assert rows, "no coarse sighting to inspect; the check would be vacuous"
    whole = " ".join(str(v) for row in rows for v in row).lower()
    for forbidden in ("lighter-1", "red lighter", "lighter", "red", '"at"',
                      "100", "scan-"):
        assert forbidden not in whole, f"{forbidden} leaked to a coarse looker"
    assert [json.loads(r["perceived_json"]) for r in rows] == [
        {"object": "something"}]

    # Anti-vacuity: the canonical side kept the detail and withheld it.
    assert tuple(wc.execute(
        "SELECT description, x_cm, y_cm, grade FROM arrival_sighting"
    ).fetchone()) == ("red lighter", 100, 0, "COARSE")


def test_a_sighting_is_never_recalled_as_having_witnessed_the_placing(tmp_path):
    """Seeing that something IS there is not seeing how it GOT there."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world)
    assert look(world, "ava", at="t2").accepted
    history = derive(world, mc)

    seen = sightings(history, "ava")
    assert len(seen) == 1
    assert seen[0]["kind"] == "SIGHTING" and seen[0]["source"] == "STATE"
    # A PLACE memory carries an actor; a sighting must not.
    assert "actor" not in seen[0]["content"]
    assert set(seen[0]["content"]) == {"object", "at"}
    assert [m for m in history.recall("ava")
            if m["kind"] == "PLACE" or m["source"] == "EVENT"
            and "put_down" in m["content"]] == []
    # And her origin refs point at a sighting, never at the PLACE event.
    origins = [r[0] for r in mc.execute(
        "SELECT origin_ref FROM perception WHERE character_id='ava' "
        "AND kind='SIGHTING'")]
    assert all(o.startswith("sig-") for o in origins)
    assert "evt-000000" not in origins


# -- LOOK is not perceptible to bystanders ---------------------------------


def test_nobody_else_perceives_a_look(tmp_path):
    """AGENCY: the actor knows; the room does not."""
    world, wc, mc = fresh(tmp_path)
    seed_ava(world, (60, 0, -1, 0))    # 20 cm from Warren, in his face
    assert look(world, "ava", at="t1").accepted
    history = derive(world, mc)

    assert [m["kind"] for m in history.recall("ava")] == ["LOOK"]
    assert history.recall("warren") == [], "Warren perceived her looking"
    assert history.recall("noah") == []
    observers = {r[0] for r in wc.execute(
        "SELECT being_id FROM world_observation WHERE event_id='evt-000000'")}
    assert observers == {"ava"}


def test_the_look_event_is_still_canonical_history(tmp_path):
    """Unperceived by others, but real, ordered, and permanent."""
    world, wc, mc = fresh(tmp_path)
    seed_ava(world)
    assert look(world, "ava", at="t1").accepted
    row = wc.execute(
        "SELECT world_seq, kind, actor_id, payload_json, event_x_cm, event_y_cm "
        "FROM world_event").fetchone()
    assert (row["kind"], row["actor_id"]) == ("LOOK", "ava")
    assert json.loads(row["payload_json"]) == {"actor": "ava"}
    assert (row["event_x_cm"], row["event_y_cm"]) == AVA_STATION[:2]
    # Its pose snapshot exists and is her real pose.
    assert tuple(wc.execute(
        "SELECT x_cm, y_cm, facing_x, facing_y FROM world_pose "
        "WHERE event_id='evt-000000' AND being_id='ava'").fetchone()
    ) == AVA_STATION


def test_canonical_history_never_says_what_she_saw(tmp_path):
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world)
    assert look(world, "ava", at="t2").accepted
    derive(world, mc)

    kinds = [r[0] for r in wc.execute(
        "SELECT kind FROM world_event ORDER BY world_seq")]
    assert kinds == ["PLACE", "LOOK"]
    assert "SIGHTING" not in kinds
    payloads = " ".join(r[0] for r in wc.execute(
        "SELECT payload_json FROM world_event"))
    assert "SIGHTING" not in payloads and "saw" not in payloads


# -- validation and forgery ------------------------------------------------


@pytest.mark.parametrize("describe,actor,expected", [
    ("an actor who does not exist", "nobody", UNKNOWN_ACTOR),
    ("an actor with no pose", "ava", NOT_PLACED),
])
def test_a_rejected_look_leaves_nothing(tmp_path, describe, actor, expected):
    world, wc, mc = fresh(tmp_path)          # Ava deliberately not seeded
    before = physical_state(wc)
    result = propose_look(world, actor=actor, location=ROOM, occurred_at="t")
    assert not result.accepted and result.reason == expected, describe
    assert physical_state(wc) == before
    assert wc.execute("SELECT COUNT(*) FROM world_event").fetchone()[0] == 0
    assert wc.execute("SELECT COUNT(*) FROM arrival_scan").fetchone()[0] == 0
    assert wc.execute("SELECT next_seq FROM world_seq_counter").fetchone()[0] == 0
    assert mc.execute("SELECT COUNT(*) FROM perception").fetchone()[0] == 0


def test_look_cannot_be_forged_through_commit_event(tmp_path):
    """A forged LOOK would be a canonical claim with no observation behind it."""
    world, wc, mc = fresh(tmp_path)
    seed_ava(world)
    assert "LOOK" in STATE_CHANGING_KINDS
    with pytest.raises(ValueError, match="cannot be appended directly"):
        world.commit_event(kind="LOOK", location=ROOM, actor_id="ava",
                           payload={"actor": "ava"}, event_x_cm=0, event_y_cm=0, occurred_at="t")
    assert wc.execute("SELECT COUNT(*) FROM world_event").fetchone()[0] == 0
    assert wc.execute("SELECT COUNT(*) FROM arrival_scan").fetchone()[0] == 0


def test_look_is_atomic_with_its_scan(tmp_path, monkeypatch):
    """If the sensing fails, the LOOK did not happen either."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world)
    before = physical_state(wc)
    events_before = wc.execute(
        "SELECT COUNT(*) FROM world_event").fetchone()[0]

    import one_world.world as world_module

    def boom(**kwargs):
        raise RuntimeError("state sensing exploded mid-transaction")

    monkeypatch.setattr(world_module, "sense_state", boom)
    with pytest.raises(RuntimeError, match="exploded"):
        look(world, "ava", at="t2")

    assert physical_state(wc) == before
    assert wc.execute(
        "SELECT COUNT(*) FROM world_event").fetchone()[0] == events_before
    assert wc.execute(
        "SELECT COUNT(*) FROM world_event WHERE kind='LOOK'").fetchone()[0] == 0
    assert wc.execute("SELECT COUNT(*) FROM arrival_scan").fetchone()[0] == 0


def test_the_injection_would_otherwise_have_written(tmp_path):
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world)
    before = wc.execute("SELECT COUNT(*) FROM arrival_scan").fetchone()[0]
    assert look(world, "ava", at="t2").accepted
    assert wc.execute(
        "SELECT COUNT(*) FROM arrival_scan").fetchone()[0] == before + 1
    assert wc.execute(
        "SELECT COUNT(*) FROM arrival_sighting").fetchone()[0] == 1


def test_a_look_scan_is_recorded_even_when_nothing_is_visible(tmp_path):
    world, wc, mc = fresh(tmp_path)
    seed_ava(world)                       # nothing placed anywhere
    assert look(world, "ava", at="t1").accepted
    assert wc.execute(
        "SELECT COUNT(*) FROM arrival_scan WHERE trigger='LOOK'"
    ).fetchone()[0] == 1
    assert wc.execute("SELECT COUNT(*) FROM arrival_sighting").fetchone()[0] == 0
    assert sightings(derive(world, mc), "ava") == []


# -- crash between the LOOK and its observations ---------------------------


def test_crash_after_look_then_a_changed_world_then_recovery(tmp_path):
    """LOOK commits, the process dies, the world moves on, recovery runs."""
    p = run_phase(tmp_path, "look-populate", "--crash-before-derive", "1")
    assert p.returncode == 9, f"expected a hard exit, got {p.returncode}: {p.stderr}"

    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    assert wc.execute(
        "SELECT COUNT(*) FROM arrival_scan WHERE trigger='LOOK'"
    ).fetchone()[0] == 1
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
    ).fetchone()[0] == 0, "the lighter is still there; the test is weak"
    assert wc.execute("SELECT COUNT(*) FROM wall").fetchone()[0] == 1

    assert run_phase(tmp_path, "recover").returncode == 0
    data = json.loads(run_phase(tmp_path, "recall").stdout)
    seen = [m for m in data["ava"] if m["kind"] == "SIGHTING"]
    assert len(seen) == 1
    assert seen[0]["grade"] == "CLEAR"
    assert seen[0]["source"] == "STATE"
    assert seen[0]["content"] == {"object": "red lighter", "at": list(LIGHTER)}


def test_delayed_look_recovery_matches_an_uninterrupted_run(tmp_path):
    clean, crashed = tmp_path / "clean", tmp_path / "crashed"
    os.makedirs(clean, exist_ok=True)
    os.makedirs(crashed, exist_ok=True)

    assert run_phase(clean, "look-populate").returncode == 0
    assert run_phase(crashed, "look-populate",
                     "--crash-before-derive", "1").returncode == 9
    assert run_phase(crashed, "arrival-disturb").returncode == 0
    assert run_phase(crashed, "recover").returncode == 0

    a = [m for m in json.loads(run_phase(clean, "recall").stdout)["ava"]
         if m["kind"] == "SIGHTING"]
    b = [m for m in json.loads(run_phase(crashed, "recall").stdout)["ava"]
         if m["kind"] == "SIGHTING"]
    assert len(a) == 1, "the uninterrupted run observed nothing to match"
    assert b == a


def test_look_recovery_is_idempotent(tmp_path):
    assert run_phase(tmp_path, "look-populate",
                     "--crash-before-derive", "1").returncode == 9
    assert run_phase(tmp_path, "recover").returncode == 0
    mc = sqlite3.connect(os.path.join(tmp_path, "minds.db"))
    before = mc.execute(
        "SELECT character_id, perception_seq, origin_ref, source FROM perception "
        "ORDER BY character_id, perception_seq").fetchall()
    for _ in range(3):
        assert json.loads(run_phase(tmp_path, "recover").stdout)["derived"] == 0
    mc = sqlite3.connect(os.path.join(tmp_path, "minds.db"))
    assert mc.execute(
        "SELECT character_id, perception_seq, origin_ref, source FROM perception "
        "ORDER BY character_id, perception_seq").fetchall() == before


def test_a_second_look_across_a_restart_is_a_second_observation(tmp_path):
    assert run_phase(tmp_path, "look-populate").returncode == 0
    first = json.loads(run_phase(tmp_path, "recall").stdout)["ava"]
    assert len([m for m in first if m["kind"] == "SIGHTING"]) == 1

    assert run_phase(tmp_path, "look-again").returncode == 0
    second = json.loads(run_phase(tmp_path, "recall").stdout)["ava"]
    assert second[: len(first)] == first, "the restart rewrote her history"
    assert len([m for m in second if m["kind"] == "SIGHTING"]) == 2
    assert len([m for m in second if m["kind"] == "LOOK"]) == 2


# -- bypass / source audit -------------------------------------------------


def test_exactly_two_production_triggers_create_a_state_scan():
    """Mechanical: find the calls, not the names that sound like triggers."""
    import one_world.actions as actions_module
    import one_world.minds as minds_module
    import one_world.perception as perception_module
    import one_world.scenario as scenario_module
    import one_world.world as world_module

    callers = []
    for module in (actions_module, minds_module, perception_module,
                   scenario_module, world_module):
        src = inspect.getsource(module)
        for line in src.splitlines():
            if "_record_arrival_scan(" in line and "def " not in line:
                callers.append(module.__name__)
    assert callers == ["one_world.actions", "one_world.actions"], callers

    # ...and they are exactly propose_move and propose_look.
    triggering = sorted(
        name for name in dir(actions_module)
        if not name.startswith("_")
        and callable(getattr(actions_module, name))
        and getattr(getattr(actions_module, name), "__module__", None)
        == "one_world.actions"
        and "_record_arrival_scan(" in inspect.getsource(
            getattr(actions_module, name)))
    assert triggering == ["propose_look", "propose_move"]


def test_each_trigger_passes_its_own_trigger_label():
    src_move = inspect.getsource(propose_move)
    src_look = inspect.getsource(propose_look)
    assert 'trigger="MOVE"' in src_move and 'trigger="LOOK"' not in src_move
    assert 'trigger="LOOK"' in src_look and 'trigger="MOVE"' not in src_look


def test_the_scan_replay_path_still_reads_no_mutable_table():
    statements = [c for c in WorldStore.load_scan.__code__.co_consts
                  if isinstance(c, str) and "SELECT" in c]
    assert len(statements) == 2, statements
    joined = " ".join(statements)
    for mutable in ("object_location", "being_pose", "wall", "world_pose",
                    "world_event"):
        assert mutable not in joined, f"load_scan consults {mutable}"


def test_look_projection_and_sensing_stay_out_of_the_router():
    import one_world.minds as minds_module
    import one_world.perception as perception_module

    for module in (perception_module, minds_module):
        src = inspect.getsource(module)
        assert "sense_state" not in src
        assert "sense_event" not in src
    assert "arrival_scan" not in inspect.getsource(minds_module)


def test_look_projection_fails_closed_for_a_grade_it_does_not_define():
    """LOOK is AGENCY-sensed, so COARSE is undefined rather than permissive."""
    with pytest.raises(ValueError, match="no projection defined"):
        project("LOOK", {"actor": "ava"}, "COARSE")


def test_an_unknown_kind_still_fails_closed():
    from one_world.sensing import sense_event
    with pytest.raises(ValueError, match="no sensing rule defined"):
        sense_event(kind="PEEK", actor_id="ava", event_x_cm=0, event_y_cm=0,
                    audio_mode=None, poses={"ava": (0, 0, 1, 0)}, walls=())
