"""Eight plausible wrong implementations of v0.8, and proof the tests kill them.

A suite that only ever passes tells you nothing about its own detection power.
Each control here MUTATES production code, re-runs the scenario the honest
suite runs, and asserts the specific property the honest suite asserts now
comes out WRONG.

Every control also pins the honest answer in the same test, so that a mutation
which silently did nothing at all would itself be caught. A control that
produced no output would otherwise "kill" the mutant vacuously.

The mutations are not strawmen. Each is a shape a competent engineer actually
reaches for: reuse the pose snapshot you already have, join to current state to
get the details, key idempotency on the subject rather than the observation.
"""

from __future__ import annotations

import json
import os
import sqlite3

import pytest

from one_world import perception as perception_module
from one_world import schema
from one_world import world as world_module
from one_world.actions import propose_move, propose_pickup, propose_place
from one_world.minds import CharacterHistory
from one_world.perception import PerceptionRouter
from one_world.scenario import ALL_THREE, ROOM, seed_world
from one_world.sensing import sense_state
from one_world.world import WorldStore

from tests.test_v08_arrival_state import (
    AVA_AGAIN, AVA_COARSE, AVA_REACH, AVA_SEES, BLOCKING_WALL, LIGHTER,
    NOAH_BLOCKED, START, fresh, place, pickup, move, derive, sightings,
)

#: Captured before any monkeypatching, so mutants can wrap the real thing.
ORIGINAL_LOAD_SCAN = WorldStore.load_scan
ORIGINAL_RECORD_SCAN = WorldStore._record_arrival_scan


# -- the mutants -----------------------------------------------------------


def mutant_no_arrival_scan(self, **kwargs):
    """CONTROL 1 -- EVENT-ONLY PERCEPTION.

    v0.7 behaviour: a MOVE changes the pose and nothing else. Perception stays
    purely event-derived.
    """
    return None


def mutant_omniscient_sense_state(*, observer_pose, objects, walls):
    """CONTROL 2 -- OMNISCIENT STATE SCAN.

    Every placed object is written CLEAR regardless of range, facing or walls.
    The shape of a scan that forgot it was supposed to be physical.
    """
    return {object_id: "CLEAR" for object_id, _x, _y in objects}


def mutant_load_scan_from_todays_world(self, scan_id):
    """CONTROL 3 -- CURRENT-STATE RECOVERY.

    Replay recomputes the scan against the world as it is NOW: today's object
    positions, today's walls, today's pose. Looks like a faithful re-derivation
    and is a time-travel bug.
    """
    row = self._conn.execute(
        "SELECT * FROM arrival_scan WHERE scan_id = ?", (scan_id,)).fetchone()
    placed = self.placed_objects()
    walls = tuple((x1, y1, x2, y2) for _, x1, y1, x2, y2 in self.current_walls())
    grades = sense_state(
        observer_pose=self.current_pose(row["being_id"]),
        objects=tuple((oid, x, y) for oid, _d, x, y in placed),
        walls=walls,
    )
    visible = [p for p in placed if p[0] in grades]
    return {
        "scan_id": row["scan_id"],
        "world_seq": row["world_seq"],
        "event_id": row["event_id"],
        "being_id": row["being_id"],
        "pose": (row["x_cm"], row["y_cm"], row["facing_x"], row["facing_y"]),
        "sightings": [
            {
                "sighting_id": f"sig-{row['world_seq']:06d}-{index:03d}",
                "grade": grades[oid],
                "payload": {"object": desc, "at": [x, y]},
            }
            for index, (oid, desc, x, y) in enumerate(visible)
        ],
    }


def mutant_load_scan_with_live_positions(self, scan_id):
    """CONTROL 4 -- LIVE-MEMORY OBJECT STATE.

    Grades come from the snapshot, but the object's position is fetched by
    joining to current state -- "the snapshot says she saw lighter-1, so look up
    where lighter-1 is". Memory becomes a live query.
    """
    scan = ORIGINAL_LOAD_SCAN(self, scan_id)
    live = {oid: (desc, x, y) for oid, desc, x, y in self.placed_objects()}
    object_ids = [r[0] for r in self._conn.execute(
        "SELECT object_id FROM arrival_sighting WHERE scan_id = ? "
        "ORDER BY sighting_id", (scan_id,))]
    for sighting, object_id in zip(scan["sightings"], object_ids):
        if object_id in live:
            desc, x, y = live[object_id]
            sighting["payload"] = {"object": desc, "at": [x, y]}
    return scan


def mutant_load_scan_keyed_on_the_object(self, scan_id):
    """CONTROL 5 -- SCAN DEDUP TOO BROAD.

    Observation identity collapses to the object, which is what
    UNIQUE(character, object_id) would amount to: an inhabitant can never
    observe the same thing twice.
    """
    scan = ORIGINAL_LOAD_SCAN(self, scan_id)
    object_ids = [r[0] for r in self._conn.execute(
        "SELECT object_id FROM arrival_sighting WHERE scan_id = ? "
        "ORDER BY sighting_id", (scan_id,))]
    for sighting, object_id in zip(scan["sightings"], object_ids):
        sighting["sighting_id"] = f"sight:{object_id}"
    return scan


def mutant_never_already_perceived(self, character_id, origin_ref):
    """CONTROL 6 -- SCAN DEDUP TOO WEAK. Replay writes the memory again."""
    return False


def mutant_record_scan_from_the_departure(self, *, event_id, world_seq,
                                          being_id):
    """CONTROL 8 -- PRE-MOVE POSE USED FOR ARRIVAL.

    Reuses the MOVE's existing world_pose snapshot instead of reading the pose
    the transition produced. Architecturally tidy -- one pose table, already
    written, already immutable -- and temporally wrong, because that snapshot
    is the DEPARTURE by design.
    """
    seq = world_seq
    scan_id = f"scan-{seq:06d}"
    pose = tuple(self._conn.execute(
        "SELECT x_cm, y_cm, facing_x, facing_y FROM world_pose "
        "WHERE event_id = ? AND being_id = ?", (event_id, being_id)).fetchone())
    self._conn.execute(
        "INSERT INTO arrival_scan (scan_id, world_seq, event_id, being_id, "
        "x_cm, y_cm, facing_x, facing_y) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (scan_id, seq, event_id, being_id, *pose),
    )
    placed = self.placed_objects()
    walls = tuple((x1, y1, x2, y2) for _, x1, y1, x2, y2 in self.current_walls())
    grades = sense_state(
        observer_pose=pose,
        objects=tuple((oid, x, y) for oid, _d, x, y in placed),
        walls=walls,
    )
    for index, (object_id, description, x_cm, y_cm) in enumerate(
            [p for p in placed if p[0] in grades]):
        self._conn.execute(
            "INSERT INTO arrival_sighting (sighting_id, scan_id, object_id, "
            "description, grade, x_cm, y_cm) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"sig-{seq:06d}-{index:03d}", scan_id, object_id, description,
             grades[object_id], x_cm, y_cm),
        )
    self._conn.execute(
        "INSERT INTO arrival_scan_outbox (scan_id, world_seq, state) "
        "VALUES (?, ?, 'PENDING')", (scan_id, seq))
    return scan_id


# -- shared scenarios ------------------------------------------------------


def arrival_scenario(tmp_path):
    """Warren puts the lighter down; Ava, 30 m away, later walks up to it."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", AVA_SEES, at="t2").accepted
    return world, wc, mc


def deferred_scenario(tmp_path):
    """Ava arrives, and NOTHING is derived. The projection is still owed.

    This is the in-process form of the crash window: the arrival is durably
    committed, no observation has been written, and the world is then free to
    move on before anyone projects it.
    """
    world, wc, mc = arrival_scenario(tmp_path)
    assert mc.execute("SELECT COUNT(*) FROM perception").fetchone()[0] == 0
    return world, wc, mc


# -- CONTROL 1: event-only perception --------------------------------------


def test_control_event_only_perception_never_learns_of_the_lighter(
        tmp_path, monkeypatch):
    honest, _, honest_mc = arrival_scenario(tmp_path / "honest")
    assert len(sightings(derive(honest, honest_mc), "ava")) == 1

    monkeypatch.setattr(WorldStore, "_record_arrival_scan", mutant_no_arrival_scan)
    world, wc, mc = arrival_scenario(tmp_path / "mutant")
    history = derive(world, mc)

    assert sightings(history, "ava") == [], "the mutation did nothing"
    assert history.recall("ava") == [
        m for m in history.recall("ava") if m["kind"] == "MOVE"]
    assert wc.execute("SELECT COUNT(*) FROM arrival_scan").fetchone()[0] == 0
    # Ava stands 150 cm from a red lighter and does not know it exists.
    assert world.object_location("lighter-1")["x_cm"] == LIGHTER[0]


# -- CONTROL 2: omniscient state scan --------------------------------------


def test_control_omniscient_scan_sees_through_the_wall(tmp_path, monkeypatch):
    monkeypatch.setattr(world_module, "sense_state", mutant_omniscient_sense_state)
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    world.add_wall(*BLOCKING_WALL)
    assert move(world, "noah", NOAH_BLOCKED, at="t2").accepted
    history = derive(world, mc)

    seen = sightings(history, "noah")
    assert seen, "the mutation did nothing"
    assert seen[0]["content"] == {"object": "red lighter", "at": list(LIGHTER)}, (
        "the honest suite's occlusion assertion would still have passed")


def test_control_omniscient_scan_hands_detail_to_a_distant_observer(
        tmp_path, monkeypatch):
    monkeypatch.setattr(world_module, "sense_state", mutant_omniscient_sense_state)
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", AVA_COARSE, at="t2").accepted   # 600 cm away
    derive(world, mc)

    rows = mc.execute(
        "SELECT perceived_json, grade FROM perception WHERE kind='SIGHTING'"
    ).fetchall()
    assert rows
    assert rows[0]["grade"] == "CLEAR", "the mutation did nothing"
    blob = rows[0]["perceived_json"].lower()
    assert "red lighter" in blob and "100" in blob, (
        "the coarse-leak assertion would still have passed")


def test_control_omniscient_scan_also_sees_what_is_behind_you(
        tmp_path, monkeypatch):
    """Range and occlusion are not the only rules it discards."""
    monkeypatch.setattr(world_module, "sense_state", mutant_omniscient_sense_state)
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", (250, 0, 1, 0), at="t2").accepted   # facing away
    assert sightings(derive(world, mc), "ava"), "the mutation did nothing"


# -- CONTROL 3: current-state recovery -------------------------------------


def test_control_recovery_from_todays_world_loses_the_observation(
        tmp_path, monkeypatch):
    """MOVE commits, the lighter is carried off, and only then is it projected."""
    honest, _, honest_mc = deferred_scenario(tmp_path / "honest")
    assert pickup(honest, "warren", at="t3").accepted
    assert [m["content"] for m in sightings(derive(honest, honest_mc), "ava")] == [
        {"object": "red lighter", "at": list(LIGHTER)}]

    monkeypatch.setattr(WorldStore, "load_scan", mutant_load_scan_from_todays_world)
    world, wc, mc = deferred_scenario(tmp_path / "mutant")
    assert pickup(world, "warren", at="t3").accepted    # no longer lying there
    history = derive(world, mc)

    assert sightings(history, "ava") == [], (
        "the mutation did nothing; recovery still used the snapshot")


def test_control_recovery_from_todays_world_is_changed_by_a_later_wall(
        tmp_path, monkeypatch):
    """The object never moves; only the geometry does. That is enough."""
    monkeypatch.setattr(WorldStore, "load_scan", mutant_load_scan_from_todays_world)
    world, wc, mc = deferred_scenario(tmp_path)
    world.add_wall("w-late", 175, -50, 175, 50)    # across Ava's line of sight
    assert sightings(derive(world, mc), "ava") == [], "the mutation did nothing"
    assert world.object_location("lighter-1")["x_cm"] == LIGHTER[0], (
        "the lighter moved; this control is meant to isolate the geometry")


# -- CONTROL 4: live-memory object state -----------------------------------


def test_control_live_positions_rewrite_an_old_observation(
        tmp_path, monkeypatch):
    """P1 becomes P2 in a memory that was formed before the object moved."""
    p2 = (200, 0)

    def move_it(world):
        assert move(world, "ava", AVA_REACH, at="t3").accepted
        assert pickup(world, "ava", at="t4").accepted
        assert place(world, "ava", *p2, at="t5").accepted

    honest, _, honest_mc = deferred_scenario(tmp_path / "honest")
    move_it(honest)
    assert [m["content"]["at"] for m in sightings(derive(honest, honest_mc), "ava")][0] \
        == list(LIGHTER)

    monkeypatch.setattr(WorldStore, "load_scan", mutant_load_scan_with_live_positions)
    world, wc, mc = deferred_scenario(tmp_path / "mutant")
    move_it(world)
    ats = [m["content"]["at"] for m in sightings(derive(world, mc), "ava")]

    assert ats, "no observation to inspect; the control would be vacuous"
    assert ats[0] == list(p2), "the mutation did nothing"
    assert ats[0] != list(LIGHTER), (
        "the historical-stability assertion would still have passed")


# -- CONTROL 5: dedup too broad --------------------------------------------


def test_control_object_keyed_identity_forbids_a_second_observation(
        tmp_path, monkeypatch):
    honest, _, honest_mc = fresh(tmp_path / "honest")
    assert place(honest, "warren", *LIGHTER, at="t1").accepted
    assert move(honest, "ava", AVA_SEES, at="t2").accepted
    assert move(honest, "ava", AVA_AGAIN, at="t3").accepted
    assert len(sightings(derive(honest, honest_mc), "ava")) == 2

    monkeypatch.setattr(WorldStore, "load_scan", mutant_load_scan_keyed_on_the_object)
    world, wc, mc = fresh(tmp_path / "mutant")
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", AVA_SEES, at="t2").accepted
    assert move(world, "ava", AVA_AGAIN, at="t3").accepted
    history = derive(world, mc)

    assert len(sightings(history, "ava")) == 1, "the mutation did nothing"
    # Two scans really did happen; the second observation was swallowed.
    assert wc.execute("SELECT COUNT(*) FROM arrival_scan").fetchone()[0] == 2
    assert wc.execute("SELECT COUNT(*) FROM arrival_sighting").fetchone()[0] == 2


# -- CONTROL 6: dedup too weak ---------------------------------------------


def test_control_skipping_the_dedup_check_cannot_write_a_duplicate(
        tmp_path, monkeypatch):
    """The under-dedup mutant does not produce a duplicate memory -- it CRASHES.

    That is a stronger result than the brief asks for, and worth stating
    precisely: idempotency here is not a procedure that remembers to check
    first, it is UNIQUE (character_id, origin_ref) in the schema. With the
    procedural check removed the second write is not silently accepted; it is
    refused by the store. A duplicate memory is inexpressible, not merely
    avoided.
    """
    world, wc, mc = arrival_scenario(tmp_path)
    derive(world, mc)
    before = sorted(tuple(r) for r in mc.execute("SELECT * FROM perception"))
    assert before

    monkeypatch.setattr(PerceptionRouter, "_already_perceived",
                        mutant_never_already_perceived)
    with wc:  # the lost-DONE-mark window
        wc.execute("UPDATE arrival_scan_outbox SET state='PENDING'")

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        PerceptionRouter(world, mc).derive_pending()

    assert sorted(tuple(r) for r in mc.execute("SELECT * FROM perception")) == before


def test_control_a_store_without_the_constraint_does_duplicate(tmp_path):
    """Anti-vacuity for the control above: the constraint is load-bearing.

    Without UNIQUE (character_id, origin_ref) the very same replay writes the
    memory a second time. The exception in the previous test is therefore
    caused by the constraint, not by something incidental.
    """
    world, wc, mc = arrival_scenario(tmp_path)
    derive(world, mc)
    row = mc.execute("SELECT * FROM perception WHERE kind='SIGHTING'").fetchone()
    assert row

    loose = sqlite3.connect(os.path.join(tmp_path, "loose.db"))
    loose.row_factory = sqlite3.Row
    with loose:
        loose.execute(
            "CREATE TABLE perception (perception_id TEXT, character_id TEXT, "
            "perception_seq INTEGER, kind TEXT, grade TEXT, perceived_json TEXT, "
            "origin_ref TEXT, source TEXT)")   # no UNIQUE anywhere
        for _ in range(2):
            loose.execute(
                "INSERT INTO perception VALUES (?,?,?,?,?,?,?,?)",
                tuple(row[k] for k in ("perception_id", "character_id",
                                       "perception_seq", "kind", "grade",
                                       "perceived_json", "origin_ref", "source")))
    assert loose.execute(
        "SELECT COUNT(*) FROM perception").fetchone()[0] == 2
    assert len(CharacterHistory(loose).recall("ava")) == 2


# -- CONTROL 7: coarse state leak ------------------------------------------


def test_control_coarse_sighting_that_reduces_nothing_leaks_everything(
        tmp_path, monkeypatch):
    monkeypatch.setitem(perception_module._PROJECTIONS, ("SIGHTING", "COARSE"),
                        perception_module._sighting_clear)
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", AVA_COARSE, at="t2").accepted
    derive(world, mc)

    rows = mc.execute(
        "SELECT perception_id, character_id, perception_seq, kind, grade, "
        "perceived_json, origin_ref, source FROM perception "
        "WHERE kind='SIGHTING'").fetchall()
    assert rows, "no coarse sighting; the control would be vacuous"
    assert rows[0]["grade"] == "COARSE", "the grade itself was mutated instead"
    whole = " ".join(str(v) for row in rows for v in row).lower()

    leaked = [s for s in ("red lighter", '"at"', "100") if s in whole]
    assert leaked == ["red lighter", '"at"', "100"], (
        f"the mutation did not leak; only {leaked} present")


# -- CONTROL 8: departure pose used for arrival ----------------------------


def test_control_departure_pose_misses_what_the_arrival_can_see(
        tmp_path, monkeypatch):
    honest, _, honest_mc = arrival_scenario(tmp_path / "honest")
    assert len(sightings(derive(honest, honest_mc), "ava")) == 1

    monkeypatch.setattr(WorldStore, "_record_arrival_scan",
                        mutant_record_scan_from_the_departure)
    world, wc, mc = arrival_scenario(tmp_path / "mutant")
    history = derive(world, mc)

    assert sightings(history, "ava") == [], "the mutation did nothing"
    # The scan happened; it was simply taken from 30 m away.
    scan = wc.execute(
        "SELECT x_cm, y_cm, facing_x, facing_y FROM arrival_scan").fetchone()
    assert tuple(scan) == START["ava"]
    assert tuple(scan) != AVA_SEES


def test_control_departure_pose_sees_what_the_arrival_turned_away_from(
        tmp_path, monkeypatch):
    """The converse direction, so the control cannot pass by luck."""
    poses = dict(START, ava=(250, 0, -1, 0))    # starts looking AT the lighter
    turned_away = (250, 0, 1, 0)

    honest, _, honest_mc = fresh(tmp_path / "honest", poses=poses)
    assert place(honest, "warren", *LIGHTER, at="t1").accepted
    assert move(honest, "ava", turned_away, at="t2").accepted
    assert sightings(derive(honest, honest_mc), "ava") == []

    monkeypatch.setattr(WorldStore, "_record_arrival_scan",
                        mutant_record_scan_from_the_departure)
    world, wc, mc = fresh(tmp_path / "mutant", poses=poses)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", turned_away, at="t2").accepted
    history = derive(world, mc)

    seen = sightings(history, "ava")
    assert len(seen) == 1, "the mutation did nothing"
    assert seen[0]["content"] == {"object": "red lighter", "at": list(LIGHTER)}


def test_control_departure_pose_is_not_caught_by_a_test_that_never_moves(
        tmp_path, monkeypatch):
    """Why the acceptance geometry has to be chosen, not stumbled into.

    A pure ROTATION in place leaves position unchanged, so a departure-pose
    mutant and the honest implementation can agree. A suite whose only arrival
    test rotated on the spot would call this control dead. It is not; the
    geometry is.
    """
    poses = dict(START, ava=(250, 0, -1, 0))
    rotate = (250, 0, -1, 0)                 # same pose entirely -> NO_CHANGE
    world, _, _ = fresh(tmp_path / "reject", poses=poses)
    assert not move(world, "ava", rotate).accepted

    # A rotation that keeps the lighter in view: both agree, and prove nothing.
    small_turn = (250, 0, -2, 1)
    honest, _, honest_mc = fresh(tmp_path / "honest", poses=poses)
    assert place(honest, "warren", *LIGHTER, at="t1").accepted
    assert move(honest, "ava", small_turn, at="t2").accepted
    honest_seen = sightings(derive(honest, honest_mc), "ava")

    monkeypatch.setattr(WorldStore, "_record_arrival_scan",
                        mutant_record_scan_from_the_departure)
    world, wc, mc = fresh(tmp_path / "mutant", poses=poses)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    assert move(world, "ava", small_turn, at="t2").accepted
    mutant_seen = sightings(derive(world, mc), "ava")

    assert [m["content"] for m in honest_seen] == [m["content"] for m in mutant_seen]
    assert honest_seen, "both produced nothing; the demonstration is vacuous"
