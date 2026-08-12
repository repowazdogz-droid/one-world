"""Eight plausible wrong implementations of v0.9, and proof they misbehave.

Same discipline as v0.8: each control mutates production behaviour, re-runs the
scenario the honest suite runs, and asserts the property comes out WRONG -- with
the honest answer pinned in the same test so a mutation that silently did
nothing would itself be caught.

These tests demonstrate the mutants are WRONG. The separate claim -- that the
unmodified honest suite NOTICES -- is established by running the same eight as
source-level mutations against tests/test_v09_look.py, and is reported with the
milestone rather than asserted here.
"""

from __future__ import annotations

import json
import os
import sqlite3

import pytest

from one_world import perception as perception_module
from one_world import world as world_module
from one_world.actions import ActionResult, propose_look
from one_world.minds import CharacterHistory
from one_world.perception import PerceptionRouter
from one_world.scenario import ALL_THREE, ROOM
from one_world.sensing import sense_state
from one_world.world import WorldStore

from tests.test_v09_look import (
    AVA_FAR, AVA_STATION, BEFORE_AVA, BLOCKING_WALL, LIGHTER, NOAH_STATION,
    derive, fresh, look, move, physical_state, pickup, place, seed_ava,
    sightings,
)

ORIGINAL_LOAD_SCAN = WorldStore.load_scan
ORIGINAL_RECORD_SCAN = WorldStore._record_arrival_scan


# -- the mutants -----------------------------------------------------------


def mutant_scan_is_a_noop(self, **kwargs):
    """CONTROL 1 -- LOOK DOES NOTHING.

    The LOOK event commits; no observation scan is created. v0.8 behaviour with
    a new verb bolted on: the action exists and accomplishes nothing.
    """
    return None


def mutant_look_that_moves(world, *, actor, location, occurred_at):
    """CONTROL 2 -- LOOK MUTATES POSE.

    Looking "settles" the actor onto a canonical facing. A plausible slip: the
    author reaches for the pose helper to normalise facing while they are in
    there anyway, and observation quietly becomes movement.
    """
    with world.transaction():
        ax, ay, fx, fy = world.current_pose(actor)
        event_id = world._append_event_locked(
            kind="LOOK", location=location, actor_id=actor,
            payload={"actor": actor}, event_x_cm=ax, event_y_cm=ay, occurred_at=occurred_at)
        world._move_pose(actor, ax, ay, 1, 0)      # <-- the mutation
        world._record_arrival_scan(
            event_id=event_id, world_seq=int(event_id.split("-")[1]),
            being_id=actor, trigger="LOOK")
    return ActionResult(accepted=True, event_id=event_id)


def mutant_load_scan_from_todays_world(self, scan_id):
    """CONTROL 3 -- CURRENT-STATE LOOK RECOVERY.

    Replay recomputes against the world as it is now. Looks like a faithful
    re-derivation; is a time-travel bug.
    """
    row = self._conn.execute(
        "SELECT * FROM arrival_scan WHERE scan_id = ?", (scan_id,)).fetchone()
    placed = self.placed_objects()
    walls = tuple((x1, y1, x2, y2) for _, x1, y1, x2, y2 in self.current_walls())
    grades = sense_state(
        observer_pose=self.current_pose(row["being_id"]),
        objects=tuple((oid, x, y) for oid, _d, x, y in placed),
        walls=walls)
    visible = [p for p in placed if p[0] in grades]
    return {
        "scan_id": row["scan_id"], "world_seq": row["world_seq"],
        "event_id": row["event_id"], "being_id": row["being_id"],
        "trigger": row["trigger"],
        "pose": (row["x_cm"], row["y_cm"], row["facing_x"], row["facing_y"]),
        "sightings": [
            {"sighting_id": f"sig-{row['world_seq']:06d}-{i:03d}",
             "grade": grades[oid],
             "payload": {"object": desc, "at": [x, y]}}
            for i, (oid, desc, x, y) in enumerate(visible)],
    }


def mutant_scan_from_a_stale_arrival_pose(self, *, event_id, world_seq,
                                          being_id, trigger="MOVE"):
    """CONTROL 4 -- A PRIOR ARRIVAL SNAPSHOT USED AS THE LOOK POSE.

    "Where is this being? Look them up in arrival_scan." The query has no
    ORDER BY and no LIMIT, so it takes whichever row comes back first -- the
    OLDEST arrival, not where the actor stands now.

    Note this is the only shape of stale-pose bug that LOOK can actually have.
    Reusing the LOOK event's own world_pose would be undetectable, because LOOK
    changes no pose and that snapshot therefore equals the current one. The
    staleness has to come from an EARLIER scan.
    """
    pose = None
    if trigger == "LOOK":
        prior = self._conn.execute(
            "SELECT x_cm, y_cm, facing_x, facing_y FROM arrival_scan "
            "WHERE being_id = ?", (being_id,)).fetchone()
        if prior is not None:
            pose = tuple(prior)
    if pose is None:
        pose = self.current_pose(being_id)

    seq = world_seq
    scan_id = f"scan-{seq:06d}"
    self._conn.execute(
        "INSERT INTO arrival_scan (scan_id, world_seq, event_id, being_id, "
        "trigger, x_cm, y_cm, facing_x, facing_y) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (scan_id, seq, event_id, being_id, trigger, *pose))
    placed = self.placed_objects()
    walls = tuple((x1, y1, x2, y2) for _, x1, y1, x2, y2 in self.current_walls())
    grades = sense_state(
        observer_pose=pose,
        objects=tuple((oid, x, y) for oid, _d, x, y in placed), walls=walls)
    for i, (oid, desc, x, y) in enumerate(
            [p for p in placed if p[0] in grades]):
        self._conn.execute(
            "INSERT INTO arrival_sighting (sighting_id, scan_id, object_id, "
            "description, grade, x_cm, y_cm) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"sig-{seq:06d}-{i:03d}", scan_id, oid, desc, grades[oid], x, y))
    self._conn.execute(
        "INSERT INTO arrival_scan_outbox (scan_id, world_seq, state) "
        "VALUES (?, ?, 'PENDING')", (scan_id, seq))
    return scan_id


def mutant_load_scan_keyed_on_the_object(self, scan_id):
    """CONTROL 5 -- GLOBAL OBJECT DEDUP.

    Observation identity collapses to the object, so having once seen the
    lighter -- by arrival OR by an earlier LOOK -- permanently prevents seeing
    it again.
    """
    scan = ORIGINAL_LOAD_SCAN(self, scan_id)
    object_ids = [r[0] for r in self._conn.execute(
        "SELECT object_id FROM arrival_sighting WHERE scan_id = ? "
        "ORDER BY sighting_id", (scan_id,))]
    for sighting, object_id in zip(scan["sightings"], object_ids):
        sighting["sighting_id"] = f"sight:{object_id}"
    return scan


def mutant_never_already_perceived(self, character_id, origin_ref):
    """CONTROL 6 -- SAME-LOOK UNDER-DEDUP."""
    return False


def mutant_sighting_as_a_place_memory(p: dict) -> dict:
    """CONTROL 8 -- LOOK CREATES A FALSE PLACE MEMORY.

    The sighting is reduced into the shape of a witnessed PLACE, complete with
    an actor. Ava now "remembers" Warren putting it down, which she never saw.
    """
    return {"actor": "warren", "object": p["object"], "at": p["at"]}


# -- CONTROL 1: LOOK does nothing ------------------------------------------


def test_control_look_without_a_scan_leaves_her_ignorant(tmp_path, monkeypatch):
    honest, _, honest_mc = fresh(tmp_path / "honest")
    assert place(honest, "warren", *LIGHTER, at="t1").accepted
    seed_ava(honest)
    assert look(honest, "ava", at="t2").accepted
    assert len(sightings(derive(honest, honest_mc), "ava")) == 1

    monkeypatch.setattr(WorldStore, "_record_arrival_scan", mutant_scan_is_a_noop)
    world, wc, mc = fresh(tmp_path / "mutant")
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world)
    assert look(world, "ava", at="t2").accepted
    history = derive(world, mc)

    assert sightings(history, "ava") == [], "the mutation did nothing"
    assert [m["kind"] for m in history.recall("ava")] == ["LOOK"], (
        "she looked, and learned nothing")
    assert wc.execute("SELECT COUNT(*) FROM arrival_scan").fetchone()[0] == 0
    assert world.object_location("lighter-1")["x_cm"] == LIGHTER[0]


# -- CONTROL 2: LOOK mutates pose ------------------------------------------


def test_control_a_look_that_moves_breaks_the_non_movement_invariant(tmp_path):
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world)
    before = physical_state(wc)
    pose_before = world.current_pose("ava")

    assert mutant_look_that_moves(world, actor="ava", location=ROOM, occurred_at="t2").accepted

    after = physical_state(wc)
    assert after != before, "the mutation did nothing"
    assert after["object_location"] == before["object_location"]
    assert after["wall"] == before["wall"]
    assert world.current_pose("ava") != pose_before, (
        "the pose-equality assertion would still have passed")
    assert world.current_pose("ava") == (250, 0, 1, 0)


def test_control_the_moving_look_also_changes_what_she_sees(tmp_path):
    """Not merely a bookkeeping difference: it changes her knowledge."""
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world)
    assert mutant_look_that_moves(world, actor="ava", location=ROOM, occurred_at="t2").accepted
    # Facing forced to +x, away from the lighter at -x: she sees nothing.
    assert sightings(derive(world, mc), "ava") == []


# -- CONTROL 3: current-state LOOK recovery --------------------------------


def test_control_recovery_from_todays_world_loses_the_look(tmp_path, monkeypatch):
    def scenario(root):
        world, wc, mc = fresh(root)
        assert place(world, "warren", *LIGHTER, at="t1").accepted
        seed_ava(world)
        assert look(world, "ava", at="t2").accepted
        assert mc.execute("SELECT COUNT(*) FROM perception").fetchone()[0] == 0
        assert pickup(world, "warren", at="t3").accepted   # world moves on
        return world, wc, mc

    honest, _, honest_mc = scenario(tmp_path / "honest")
    assert [m["content"] for m in sightings(derive(honest, honest_mc), "ava")] == [
        {"object": "red lighter", "at": list(LIGHTER)}]

    monkeypatch.setattr(WorldStore, "load_scan", mutant_load_scan_from_todays_world)
    world, wc, mc = scenario(tmp_path / "mutant")
    assert sightings(derive(world, mc), "ava") == [], (
        "the mutation did nothing; recovery still used the snapshot")


def test_control_a_later_wall_changes_a_recovered_look(tmp_path, monkeypatch):
    """The object never moves; only the geometry does."""
    monkeypatch.setattr(WorldStore, "load_scan", mutant_load_scan_from_todays_world)
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world)
    assert look(world, "ava", at="t2").accepted
    world.add_wall("w-late", 175, -50, 175, 50)

    assert sightings(derive(world, mc), "ava") == [], "the mutation did nothing"
    assert world.object_location("lighter-1")["x_cm"] == LIGHTER[0], (
        "the lighter moved; this control isolates the geometry")


# -- CONTROL 4: a stale arrival pose used for LOOK -------------------------


def scenario_moved_since_the_last_arrival(root, tmp_path):
    """Ava arrives somewhere blind, then moves somewhere she can see, then LOOKs.

    Her FIRST arrival is at 700 cm -- inside visual range, outside detail range,
    so it yields only a coarse sighting. Her second puts her at 150 cm. A LOOK
    computed from the stale first arrival resolves nothing.
    """
    world, wc, mc = fresh(root)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    world.seed_pose("ava", 0, 3000, 0, 1)
    assert move(world, "ava", AVA_FAR, at="t2").accepted        # arrival 1: far
    assert move(world, "ava", AVA_STATION, at="t3").accepted    # arrival 2: near
    assert look(world, "ava", at="t4").accepted
    return world, wc, mc


def test_control_a_stale_arrival_pose_degrades_the_look(tmp_path, monkeypatch):
    honest, _, honest_mc = scenario_moved_since_the_last_arrival(
        tmp_path / "honest", tmp_path)
    honest_grades = [m["grade"] for m in sightings(derive(honest, honest_mc), "ava")]
    assert honest_grades == ["COARSE", "CLEAR", "CLEAR"], honest_grades

    monkeypatch.setattr(WorldStore, "_record_arrival_scan",
                        mutant_scan_from_a_stale_arrival_pose)
    world, wc, mc = scenario_moved_since_the_last_arrival(
        tmp_path / "mutant", tmp_path)
    grades = [m["grade"] for m in sightings(derive(world, mc), "ava")]

    assert grades == ["COARSE", "CLEAR", "COARSE"], grades
    assert grades != honest_grades, "the mutation did nothing"
    # The LOOK scan recorded a pose the actor had already left.
    look_pose = wc.execute(
        "SELECT x_cm, y_cm, facing_x, facing_y FROM arrival_scan "
        "WHERE trigger='LOOK'").fetchone()
    assert tuple(look_pose) == AVA_FAR
    assert world.current_pose("ava") == AVA_STATION


# -- CONTROL 5: global object dedup ----------------------------------------


def test_control_object_keyed_identity_forbids_looking_twice(tmp_path, monkeypatch):
    def scenario(root):
        world, wc, mc = fresh(root)
        assert place(world, "warren", *LIGHTER, at="t1").accepted
        seed_ava(world)
        assert look(world, "ava", at="t2").accepted
        assert look(world, "ava", at="t3").accepted
        return world, wc, mc

    honest, _, honest_mc = scenario(tmp_path / "honest")
    assert len(sightings(derive(honest, honest_mc), "ava")) == 2

    monkeypatch.setattr(WorldStore, "load_scan", mutant_load_scan_keyed_on_the_object)
    world, wc, mc = scenario(tmp_path / "mutant")
    assert len(sightings(derive(world, mc), "ava")) == 1, "the mutation did nothing"
    assert wc.execute("SELECT COUNT(*) FROM arrival_scan").fetchone()[0] == 2
    assert wc.execute("SELECT COUNT(*) FROM arrival_sighting").fetchone()[0] == 2


def test_control_object_dedup_also_blocks_a_look_after_an_arrival(tmp_path,
                                                                  monkeypatch):
    """Across trigger kinds too: an arrival sighting swallows the later LOOK."""
    monkeypatch.setattr(WorldStore, "load_scan", mutant_load_scan_keyed_on_the_object)
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    world.seed_pose("ava", 0, 3000, 0, 1)
    assert move(world, "ava", AVA_STATION, at="t2").accepted
    assert look(world, "ava", at="t3").accepted
    assert len(sightings(derive(world, mc), "ava")) == 1


# -- CONTROL 6: same-LOOK under-dedup --------------------------------------


def test_control_skipping_the_dedup_check_cannot_duplicate_a_look(
        tmp_path, monkeypatch):
    """Rejected by UNIQUE (character_id, origin_ref), not by the procedure.

    Same result as the v0.8 control and worth restating: idempotency for LOOK
    observations is a database constraint. With the procedural check removed the
    second write is refused, not silently accepted.
    """
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world)
    assert look(world, "ava", at="t2").accepted
    derive(world, mc)
    before = sorted(tuple(r) for r in mc.execute("SELECT * FROM perception"))
    assert before

    monkeypatch.setattr(PerceptionRouter, "_already_perceived",
                        mutant_never_already_perceived)
    with wc:
        wc.execute("UPDATE arrival_scan_outbox SET state='PENDING'")

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        PerceptionRouter(world, mc).derive_pending()
    assert sorted(tuple(r) for r in mc.execute("SELECT * FROM perception")) == before


# -- CONTROL 7: coarse LOOK leak -------------------------------------------


def test_control_a_coarse_look_that_reduces_nothing_leaks_everything(
        tmp_path, monkeypatch):
    monkeypatch.setitem(perception_module._PROJECTIONS, ("SIGHTING", "COARSE"),
                        perception_module._sighting_clear)
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world, AVA_FAR)
    assert look(world, "ava", at="t2").accepted
    derive(world, mc)

    rows = mc.execute(
        "SELECT perception_id, character_id, perception_seq, kind, grade, "
        "perceived_json, origin_ref, source FROM perception "
        "WHERE kind='SIGHTING'").fetchall()
    assert rows, "no coarse sighting; the control would be vacuous"
    assert rows[0]["grade"] == "COARSE", "the grade was mutated instead"
    whole = " ".join(str(v) for row in rows for v in row).lower()
    leaked = [s for s in ("red lighter", '"at"', "100") if s in whole]
    assert leaked == ["red lighter", '"at"', "100"], (
        f"the mutation did not leak; only {leaked} present")


# -- CONTROL 8: LOOK creates a false PLACE memory --------------------------


def test_control_a_sighting_dressed_as_a_witnessed_place(tmp_path, monkeypatch):
    """The conceptually important one: IS there vs how it GOT there."""
    honest, _, honest_mc = fresh(tmp_path / "honest")
    assert place(honest, "warren", *LIGHTER, at="t1").accepted
    seed_ava(honest)
    assert look(honest, "ava", at="t2").accepted
    honest_seen = sightings(derive(honest, honest_mc), "ava")
    assert "actor" not in honest_seen[0]["content"]

    monkeypatch.setitem(perception_module._PROJECTIONS, ("SIGHTING", "CLEAR"),
                        mutant_sighting_as_a_place_memory)
    world, wc, mc = fresh(tmp_path / "mutant")
    assert place(world, "warren", *LIGHTER, at="t1").accepted
    seed_ava(world)
    assert look(world, "ava", at="t2").accepted
    seen = sightings(derive(world, mc), "ava")

    assert seen, "no sighting to inspect; the control would be vacuous"
    assert seen[0]["content"].get("actor") == "warren", "the mutation did nothing"
    assert seen[0]["content"] != honest_seen[0]["content"]
    # She now "remembers" a man she never saw putting it down.
    assert "warren" in json.dumps(seen[0]["content"])
    assert world.load_event("evt-000000")["observations"] == {"warren": "CLEAR"}, (
        "she genuinely did not perceive the PLACE; the memory is fabricated")
