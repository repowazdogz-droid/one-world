"""v0.7: an object can exist in space, and possession must be reached for.

The hazard this suite is written against is a PICKUP test that passes because
the actor happened to be standing near the object anyway. Every reach test
therefore states the distance explicitly and checks the failing side too.
"""

from __future__ import annotations

import inspect
import json
import os
import sqlite3
import subprocess
import sys

import pytest

from one_world import actions, schema
from one_world.actions import (
    INTERACTION_RANGE_CM, NOT_ON_THE_GROUND, NOT_POSSESSED, OUT_OF_REACH,
    UNKNOWN_OBJECT, propose_move, propose_pickup, propose_place,
)
from one_world.geometry import dist_sq
from one_world.minds import CharacterHistory
from one_world.perception import PerceptionRouter
from one_world.scenario import ALL_THREE, BEINGS, ROOM, seed_world
from one_world.world import STATE_CHANGING_KINDS, WorldStore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Warren holds the lighter and puts it down at his feet. Ava watches from 200 cm
# -- close enough to see the detail, far too far to reach it. Noah is 800 cm off.
START = {
    "warren": (0, 0, 1, 0),
    "ava": (200, 0, -1, 0),
    "noah": (0, 800, 0, -1),
}
DROP = (40, 0)                    # 40 cm from Warren: within reach
AVA_REACH = (100, 0, -1, 0)       # 60 cm from the lighter: within reach


def run_phase(d, phase, *extra):
    return subprocess.run(
        [sys.executable, "-m", "one_world.scenario", "--dir", str(d), "--phase", phase, *extra],
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
                         y_cm=y, presence=ALL_THREE, location=ROOM, occurred_at=at)


def pickup(world, actor, at="t"):
    return propose_pickup(world, actor=actor, object_id="lighter-1",
                          presence=ALL_THREE, location=ROOM, occurred_at=at)


def move(world, actor, x, y, fx, fy, at="t"):
    return propose_move(world, actor=actor, to_x_cm=x, to_y_cm=y, facing_x=fx,
                        facing_y=fy, presence=ALL_THREE, location=ROOM,
                        occurred_at=at)


def derive(world, mc):
    PerceptionRouter(world, mc).derive_pending()
    return CharacterHistory(mc)


def snapshot(wc):
    def rows(t):
        return sorted(tuple(r) for r in wc.execute(f"SELECT * FROM {t}"))
    return {t: rows(t) for t in (
        "object_location", "being_pose", "world_event", "world_pose",
        "world_observation", "world_presence", "projection_outbox",
        "world_seq_counter")}


def kinds(wc):
    return [r[0] for r in wc.execute(
        "SELECT kind FROM world_event ORDER BY world_seq")]


# -- the state model is exclusive by construction -------------------------


@pytest.mark.parametrize(
    "describe,sql",
    [
        ("held AND placed", "UPDATE object_location SET x_cm=10, y_cm=10"),
        ("neither held nor placed", "UPDATE object_location SET holder_id=NULL"),
        ("half a position", "UPDATE object_location SET holder_id=NULL, x_cm=10"),
        ("a second holder", "INSERT INTO object_location (object_id, holder_id) "
                            "VALUES ('lighter-1','ava')"),
        ("a second position", "INSERT INTO object_location (object_id, x_cm, y_cm) "
                              "VALUES ('lighter-1',1,1)"),
        ("stowed while on the ground",
         "UPDATE object_location SET holder_id=NULL, x_cm=1, y_cm=1, stowed_in='pocket'"),
    ],
)
def test_contradictory_object_states_are_inexpressible(tmp_path, describe, sql):
    """Enforced by the schema, not by Python -- raw SQL cannot express these."""
    world, wc, _ = fresh(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        with wc:
            wc.execute(sql)


def test_an_object_is_always_in_exactly_one_state(tmp_path):
    world, wc, _ = fresh(tmp_path)
    loc = world.object_location("lighter-1")
    assert loc["holder_id"] == "warren" and loc["x_cm"] is None

    assert place(world, "warren", *DROP).accepted
    loc = world.object_location("lighter-1")
    assert loc["holder_id"] is None
    assert (loc["x_cm"], loc["y_cm"]) == DROP
    assert loc["stowed_in"] is None


# -- the physical interaction rule ----------------------------------------


def test_place_range_boundary_is_inclusive(tmp_path):
    """Exactly at the radius is within reach; one cm further is not."""
    at_limit = (INTERACTION_RANGE_CM, 0)
    one_past = (INTERACTION_RANGE_CM + 1, 0)
    assert dist_sq(0, 0, *at_limit) == INTERACTION_RANGE_CM ** 2

    world, _, _ = fresh(tmp_path / "at")
    assert place(world, "warren", *at_limit).accepted

    world2, wc2, _ = fresh(tmp_path / "past")
    before = snapshot(wc2)
    result = place(world2, "warren", *one_past)
    assert not result.accepted and result.reason == OUT_OF_REACH
    assert snapshot(wc2) == before


def test_pickup_range_boundary_is_inclusive(tmp_path):
    """Ava at exactly the radius may take it; one cm further away may not."""
    world, wc, _ = fresh(tmp_path)
    assert place(world, "warren", *DROP).accepted
    ox, oy = DROP

    far = (ox + INTERACTION_RANGE_CM + 1, oy, -1, 0)
    assert move(world, "ava", *far, at="t-far").accepted
    before = snapshot(wc)
    result = pickup(world, "ava")
    assert not result.accepted and result.reason == OUT_OF_REACH
    assert snapshot(wc) == before

    exact = (ox + INTERACTION_RANGE_CM, oy, -1, 0)
    assert dist_sq(exact[0], exact[1], ox, oy) == INTERACTION_RANGE_CM ** 2
    assert move(world, "ava", *exact, at="t-exact").accepted
    assert pickup(world, "ava").accepted
    assert world.object_location("lighter-1")["holder_id"] == "ava"


# -- the acceptance sequence ----------------------------------------------


def test_acceptance_place_fail_move_pickup(tmp_path):
    """Held -> placed -> pickup refused at distance -> move -> pickup works."""
    world, wc, mc = fresh(tmp_path)

    assert place(world, "warren", *DROP).accepted
    loc = world.object_location("lighter-1")
    assert loc["holder_id"] is None and (loc["x_cm"], loc["y_cm"]) == DROP

    # Ava is 160 cm from the lighter: too far by a wide margin.
    ax, ay, _, _ = world.current_pose("ava")
    assert dist_sq(ax, ay, *DROP) > INTERACTION_RANGE_CM ** 2
    before = snapshot(wc)
    failed = pickup(world, "ava", at="t-fail")
    assert not failed.accepted and failed.reason == OUT_OF_REACH
    assert snapshot(wc) == before, "a refused pickup left a trace"
    assert mc.execute("SELECT COUNT(*) FROM perception").fetchone()[0] == 0
    assert "PICKUP" not in kinds(wc)

    assert move(world, "ava", *AVA_REACH, at="t-move").accepted
    ax, ay, _, _ = world.current_pose("ava")
    assert dist_sq(ax, ay, *DROP) <= INTERACTION_RANGE_CM ** 2

    assert pickup(world, "ava", at="t-take").accepted
    loc = world.object_location("lighter-1")
    assert loc["holder_id"] == "ava" and loc["x_cm"] is None
    assert kinds(wc) == ["PLACE", "MOVE", "PICKUP"]


def test_acceptance_survives_restart(tmp_path):
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *DROP).accepted
    assert not pickup(world, "ava", at="t-fail").accepted
    assert move(world, "ava", *AVA_REACH, at="t-move").accepted
    assert pickup(world, "ava", at="t-take").accepted
    derive(world, mc)
    before = {b: CharacterHistory(mc).recall(b) for b in ("warren", "ava", "noah")}

    # Reopen from disk only.
    wc2 = schema.open_world(os.path.join(tmp_path, "world.db"))
    mc2 = schema.open_minds(os.path.join(tmp_path, "minds.db"))
    world2 = WorldStore(wc2)
    loc = world2.object_location("lighter-1")
    assert loc["holder_id"] == "ava" and loc["x_cm"] is None
    assert json.loads(wc2.execute(
        "SELECT payload_json FROM world_event WHERE kind='PLACE'").fetchone()[0]
    )["at"] == list(DROP)
    assert json.loads(wc2.execute(
        "SELECT payload_json FROM world_event WHERE kind='PICKUP'").fetchone()[0]
    )["actor"] == "ava"
    assert {b: CharacterHistory(mc2).recall(b)
            for b in ("warren", "ava", "noah")} == before


# -- perception ------------------------------------------------------------


def test_place_is_perceived_by_physical_access(tmp_path):
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *DROP).accepted
    history = derive(world, mc)

    warren = history.recall("warren")
    assert len(warren) == 1 and warren[0]["grade"] == "CLEAR"   # agency
    assert warren[0]["content"]["object"] == "red lighter"

    ava = history.recall("ava")                                  # 160 cm: detail
    assert len(ava) == 1 and ava[0]["grade"] == "CLEAR"
    assert ava[0]["content"] == {"actor": "warren", "object": "red lighter",
                                 "at": list(DROP)}

    noah = history.recall("noah")                                # 800 cm: coarse
    assert len(noah) == 1 and noah[0]["grade"] == "COARSE"
    assert noah[0]["content"] == {"actor": "warren", "put_down": True}


def test_coarse_observer_learns_neither_object_nor_place(tmp_path):
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *DROP).accepted
    assert move(world, "ava", *AVA_REACH, at="t-move").accepted
    assert pickup(world, "ava", at="t-take").accepted
    derive(world, mc)

    rows = mc.execute(
        "SELECT perception_id, character_id, perception_seq, kind, grade, "
        "perceived_json, origin_ref FROM perception WHERE character_id='noah'"
    ).fetchall()
    assert rows, "no perceptions to inspect; the check would be vacuous"
    whole = " ".join(str(v) for row in rows for v in row).lower()
    for forbidden in ("lighter-1", "red lighter", '"at"', '"object"', "40"):
        assert forbidden not in whole, f"{forbidden} leaked to a coarse observer"
    contents = [json.loads(r["perceived_json"]) for r in rows]
    assert {"put_down": True, "actor": "warren"} in contents


# -- historical stability --------------------------------------------------


def test_p1_pickup_p2_leaves_the_first_place_untouched(tmp_path):
    world, wc, mc = fresh(tmp_path)
    p1, p2 = DROP, (140, 0)

    assert place(world, "warren", *p1, at="t1").accepted
    assert move(world, "ava", *AVA_REACH, at="t2").accepted
    assert pickup(world, "ava", at="t3").accepted
    assert place(world, "ava", *p2, at="t4").accepted

    loc = world.object_location("lighter-1")
    assert (loc["x_cm"], loc["y_cm"]) == p2

    places = [json.loads(r["payload_json"]) for r in wc.execute(
        "SELECT payload_json FROM world_event WHERE kind='PLACE' ORDER BY world_seq")]
    assert [p["at"] for p in places] == [list(p1), list(p2)]
    assert [p["actor"] for p in places] == ["warren", "ava"]

    took = json.loads(wc.execute(
        "SELECT payload_json FROM world_event WHERE kind='PICKUP'").fetchone()[0])
    assert took["at"] == list(p1), "the pickup drifted to the later position"


def test_load_event_does_not_reinterpret_an_old_place(tmp_path):
    """The production read path, not just raw payload_json.

    load_event is what the perception router consumes, so a mutant that
    re-derived positions there would be invisible to a raw-SQL test.
    """
    world, wc, _ = fresh(tmp_path)
    p1, p2 = DROP, (140, 0)
    assert place(world, "warren", *p1, at="t1").accepted
    assert move(world, "ava", *AVA_REACH, at="t2").accepted
    assert pickup(world, "ava", at="t3").accepted
    assert place(world, "ava", *p2, at="t4").accepted

    assert world.load_event("evt-000000")["payload"]["at"] == list(p1)
    assert world.load_event("evt-000002")["payload"]["at"] == list(p1)   # pickup
    assert world.load_event("evt-000003")["payload"]["at"] == list(p2)


def test_perception_derived_late_records_the_original_positions(tmp_path):
    """All four actions commit, THEN memories form. The lighter has moved on."""
    world, wc, mc = fresh(tmp_path)
    p1, p2 = DROP, (140, 0)
    assert place(world, "warren", *p1, at="t1").accepted
    assert move(world, "ava", *AVA_REACH, at="t2").accepted
    assert pickup(world, "ava", at="t3").accepted
    assert place(world, "ava", *p2, at="t4").accepted
    assert mc.execute("SELECT COUNT(*) FROM perception").fetchone()[0] == 0

    history = derive(world, mc)
    ava = [m for m in history.recall("ava") if m["kind"] in ("PLACE", "PICKUP")]
    assert [m["content"]["at"] for m in ava] == [list(p1), list(p1), list(p2)]


# -- occlusion still governs access ---------------------------------------


def test_a_wall_decides_who_sees_the_lighter_put_down(tmp_path):
    """Same physical action; different subjective access, from geometry alone."""
    poses = {
        "warren": (0, 0, 1, 0),
        "ava": (-200, 0, 1, 0),      # 200 cm west, looking east: clear line
        "noah": (200, 0, -1, 0),     # 200 cm east, looking west: wall between
    }
    world, wc, mc = fresh(tmp_path, poses=poses)
    world.add_wall("w1", 100, -50, 100, 50)

    assert place(world, "warren", 0, 0, at="t1").accepted
    history = derive(world, mc)
    assert len(history.recall("ava")) == 1
    assert history.recall("noah") == [], "the wall did not block him"
    before_noah = history.recall("noah")

    # Take the wall down; an equivalent later action IS perceived.
    world.remove_wall("w1")
    assert move(world, "ava", -60, 0, 1, 0, at="t2").accepted  # 60 cm: in reach
    assert pickup(world, "ava", at="t3").accepted
    history = derive(world, mc)
    noah = history.recall("noah")
    assert any(m["kind"] == "PICKUP" for m in noah)
    # ...and his blindness to the original PLACE is unchanged.
    assert [m for m in noah if m["kind"] == "PLACE"] == before_noah


# -- rejections leave nothing ---------------------------------------------


@pytest.mark.parametrize(
    "describe,call,expected",
    [
        ("placing what you do not hold",
         lambda w: place(w, "ava", 200, 0), NOT_POSSESSED),
        ("placing a nonexistent object",
         lambda w: propose_place(w, actor="warren", object_id="ghost-9", x_cm=0,
                                 y_cm=0, presence=ALL_THREE, location=ROOM,
                                 occurred_at="t"), UNKNOWN_OBJECT),
        ("placing out of reach",
         lambda w: place(w, "warren", 5000, 5000), OUT_OF_REACH),
        ("picking up something held",
         lambda w: pickup(w, "ava"), NOT_ON_THE_GROUND),
        ("picking up a nonexistent object",
         lambda w: propose_pickup(w, actor="ava", object_id="ghost-9",
                                  presence=ALL_THREE, location=ROOM,
                                  occurred_at="t"), UNKNOWN_OBJECT),
    ],
)
def test_rejected_interaction_leaves_no_trace(tmp_path, describe, call, expected):
    world, wc, mc = fresh(tmp_path)
    before = snapshot(wc)
    result = call(world)
    assert not result.accepted, describe
    assert result.reason == expected
    assert snapshot(wc) == before, f"{describe}: canonical state moved"
    assert wc.execute("SELECT next_seq FROM world_seq_counter").fetchone()[0] == 0
    assert mc.execute("SELECT COUNT(*) FROM perception").fetchone()[0] == 0


# -- atomicity -------------------------------------------------------------


def test_failure_during_pickup_rolls_the_object_back(tmp_path, monkeypatch):
    world, wc, mc = fresh(tmp_path)
    assert place(world, "warren", *DROP).accepted
    assert move(world, "ava", *AVA_REACH, at="t-move").accepted
    before = snapshot(wc)
    assert world.object_location("lighter-1")["holder_id"] is None

    import one_world.world as world_module

    def boom(**kwargs):
        raise RuntimeError("sensing exploded mid-transaction")

    monkeypatch.setattr(world_module, "sense_event", boom)
    with pytest.raises(RuntimeError, match="exploded"):
        pickup(world, "ava")

    assert snapshot(wc) == before, "partial work survived a failed pickup"
    loc = world.object_location("lighter-1")
    assert loc["holder_id"] is None and (loc["x_cm"], loc["y_cm"]) == DROP


def test_failure_during_place_rolls_the_object_back(tmp_path, monkeypatch):
    world, wc, _ = fresh(tmp_path)
    before = snapshot(wc)

    import one_world.world as world_module

    def boom(**kwargs):
        raise RuntimeError("sensing exploded mid-transaction")

    monkeypatch.setattr(world_module, "sense_event", boom)
    with pytest.raises(RuntimeError, match="exploded"):
        place(world, "warren", *DROP)

    assert snapshot(wc) == before
    assert world.object_location("lighter-1")["holder_id"] == "warren"


def test_the_injection_would_otherwise_have_written(tmp_path):
    world, wc, _ = fresh(tmp_path)
    before = snapshot(wc)
    assert place(world, "warren", *DROP).accepted
    after = snapshot(wc)
    assert len(after["world_event"]) == len(before["world_event"]) + 1
    assert after["object_location"] != before["object_location"]


# -- bypass audit ----------------------------------------------------------


@pytest.mark.parametrize("kind", ["PLACE", "PICKUP"])
def test_place_and_pickup_cannot_be_forged(tmp_path, kind):
    world, wc, _ = fresh(tmp_path)
    assert kind in STATE_CHANGING_KINDS
    with pytest.raises(ValueError, match="cannot be appended directly"):
        world.commit_event(kind=kind, location=ROOM, actor_id="ava",
                           payload={"actor": "ava", "object": "forged",
                                    "at": [0, 0]},
                           presence=ALL_THREE, event_x_cm=0, event_y_cm=0,
                           occurred_at="t")
    assert wc.execute("SELECT COUNT(*) FROM world_event").fetchone()[0] == 0
    assert world.object_location("lighter-1")["holder_id"] == "warren"


def test_only_the_action_layer_writes_object_state():
    import one_world.perception as perception_module
    import one_world.scenario as scenario_module

    a_src = inspect.getsource(actions)
    for prim in ("_place_object", "_take_object", "_transfer_holder"):
        assert prim in a_src
        assert prim not in inspect.getsource(perception_module)
        assert prim not in inspect.getsource(scenario_module)


def test_no_public_action_can_relocate_an_object_arbitrarily(tmp_path):
    """One call each, from a fresh world: none may reposition the lighter."""
    public = sorted(n for n in dir(actions)
                    if not n.startswith("_") and callable(getattr(actions, n))
                    and getattr(actions, n).__module__ == "one_world.actions")
    assert {"propose_place", "propose_pickup"} <= set(public)

    for i, name in enumerate(public):
        if name in ("propose_place", "propose_pickup"):
            continue
        fn = getattr(actions, name)
        for j, kwargs in enumerate((
            dict(actor="noah", object_id="lighter-1", x_cm=5000, y_cm=5000),
            dict(actor="noah", object_id="lighter-1"),
            dict(actor="noah", receiver="ava", object_id="lighter-1"),
        )):
            solo, _, _ = fresh(tmp_path / f"solo-{i}-{j}")
            try:
                fn(solo, **kwargs, presence=ALL_THREE, location=ROOM,
                   occurred_at="t")
            except TypeError:
                continue
            loc = solo.object_location("lighter-1")
            assert loc["holder_id"] == "warren" and loc["x_cm"] is None, (
                f"{name} relocated the object")


def test_object_state_writers_are_exactly_the_five_expected():
    """Each primitive's SQL, classified by what it can actually do."""
    writers = {}
    for name in dir(WorldStore):
        fn = getattr(WorldStore, name, None)
        if not callable(fn) or not hasattr(fn, "__code__"):
            continue
        sql = [c for c in fn.__code__.co_consts
               if isinstance(c, str) and "object_location" in c
               and ("UPDATE" in c or "INSERT" in c)]
        if sql:
            writers[name] = sql[0].split()[0]
    assert writers == {
        "add_object": "INSERT",        # initial seed
        "_set_stow": "UPDATE",         # STOW: stow label only
        "_transfer_holder": "UPDATE",  # GIVE acceptance
        "_place_object": "UPDATE",     # PLACE
        "_take_object": "UPDATE",      # PICKUP
    }
    # And the narrow ones really are narrow.
    stow_sql = [c for c in WorldStore._set_stow.__code__.co_consts
                if isinstance(c, str) and "object_location" in c][0]
    assert "holder_id" not in stow_sql and "x_cm" not in stow_sql
