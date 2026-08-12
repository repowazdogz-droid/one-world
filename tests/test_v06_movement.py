"""v0.6: an inhabitant cannot silently teleport.

Position decides what someone can see, hear and be occluded from, so a pose
change with no cause is a silent change to everyone's future perception.
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
    NO_CHANGE, NOT_PLACED, UNKNOWN_ACTOR, ZERO_FACING, propose_move,
)
from one_world.minds import CharacterHistory
from one_world.perception import PerceptionRouter
from one_world.scenario import ALL_THREE, BEINGS, ROOM, seed_world
from one_world.world import STATE_CHANGING_KINDS, WorldStore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Noah starts behind Ava's shoulder, far from the table, facing the wrong way.
# Ava stands close and looking at him; Warren faces away from him entirely.
START = {
    "warren": (0, 0, -1, 0),      # facing -x, away from Noah at +x
    "ava": (300, 0, 1, 0),        # 500 cm from Noah, looking at him
    "noah": (800, 0, -1, 0),
}
DEST = (800, 400, 0, -1)          # Noah steps aside and turns


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
        "being_pose", "world_event", "world_pose", "world_observation",
        "world_presence", "projection_outbox", "world_seq_counter",
        # v0.8 canonical state. DEFENCE IN DEPTH, not a new detection: probed
        # with a mutant where a rejected move records a scan anyway, these
        # columns changed no verdict, because arrival_scan.event_id references
        # world_event and a scan with no event is already inexpressible. They
        # are listed so the helper stays honest about covering ALL canonical
        # state, and would start discriminating if that FK ever loosened.
        "arrival_scan", "arrival_sighting", "arrival_scan_outbox")}


# -- the pose bypass is closed -------------------------------------------


def test_no_production_path_moves_a_placed_inhabitant_without_a_move_event(tmp_path):
    """Capability, not naming: try every public entry point and every pose
    primitive, and prove none silently relocates a placed inhabitant."""
    world, wc, _ = fresh(tmp_path)
    assert world.current_pose("noah") == START["noah"]

    # Seeding is initialization-only: it cannot be reused as a teleport.
    with pytest.raises(sqlite3.IntegrityError):
        world.seed_pose("noah", *DEST)
    assert world.current_pose("noah") == START["noah"]

    assert not hasattr(WorldStore, "set_pose"), "the old upsert teleport is back"

    public = sorted(n for n in dir(actions)
                    if not n.startswith("_") and callable(getattr(actions, n))
                    and getattr(actions, n).__module__ == "one_world.actions")
    for name in public:
        if name == "propose_move":
            continue
        fn = getattr(actions, name)
        for kwargs in (
            dict(actor="noah", receiver="ava", object_id="lighter-1"),
            dict(actor="noah", object_id="lighter-1", place="pocket"),
            dict(attempt_id="att-000000", responder="noah", response="ACCEPT"),
        ):
            try:
                fn(world, **kwargs, presence=ALL_THREE, location=ROOM,
                   occurred_at="t")
            except TypeError:
                continue
        assert world.current_pose("noah") == START["noah"], (
            f"{name} moved a placed inhabitant")

    assert wc.execute(
        "SELECT COUNT(*) FROM world_event WHERE kind='MOVE'").fetchone()[0] == 0

    # The one route that works.
    assert move(world, "noah", *DEST).accepted
    assert world.current_pose("noah") == DEST
    assert wc.execute(
        "SELECT COUNT(*) FROM world_event WHERE kind='MOVE'").fetchone()[0] == 1


def test_move_is_a_guarded_event_kind():
    assert "MOVE" in STATE_CHANGING_KINDS


def test_move_cannot_be_forged_through_commit_event(tmp_path):
    world, wc, _ = fresh(tmp_path)
    with pytest.raises(ValueError, match="cannot be appended directly"):
        world.commit_event(kind="MOVE", location=ROOM, actor_id="noah",
                           payload={"actor": "noah", "from": [0, 0],
                                    "to": [9, 9], "facing": [1, 0]},
                           presence=ALL_THREE, event_x_cm=0, event_y_cm=0,
                           occurred_at="t")
    assert wc.execute("SELECT COUNT(*) FROM world_event").fetchone()[0] == 0
    assert world.current_pose("noah") == START["noah"]


def test_the_move_primitive_cannot_create_a_pose():
    """_move_pose is an UPDATE, so it can only change someone already placed."""
    # Filter on the executed statement, not the docstring (which says UPDATE).
    sql = [c for c in WorldStore._move_pose.__code__.co_consts
           if isinstance(c, str) and "being_pose" in c and "?" in c]
    assert len(sql) == 1, sql
    assert sql[0].startswith("UPDATE")
    assert "INSERT" not in sql[0]


def test_only_the_action_layer_moves_poses():
    import one_world.perception as perception_module
    import one_world.scenario as scenario_module

    assert "_move_pose" not in inspect.getsource(perception_module)
    assert "_move_pose" not in inspect.getsource(scenario_module)
    assert "_move_pose" in inspect.getsource(actions)


# -- validation ----------------------------------------------------------


@pytest.mark.parametrize(
    "describe,kwargs,expected",
    [
        ("unknown actor", dict(actor="nobody", x=1, y=1, fx=1, fy=0), UNKNOWN_ACTOR),
        ("zero facing", dict(actor="noah", x=1, y=1, fx=0, fy=0), ZERO_FACING),
        ("no change at all", dict(actor="noah", x=800, y=0, fx=-1, fy=0), NO_CHANGE),
    ],
)
def test_invalid_move_leaves_no_trace(tmp_path, describe, kwargs, expected):
    world, wc, mc = fresh(tmp_path)
    before = snapshot(wc)
    result = move(world, kwargs["actor"], kwargs["x"], kwargs["y"],
                  kwargs["fx"], kwargs["fy"])
    assert not result.accepted and result.reason == expected, describe
    assert snapshot(wc) == before, f"{describe}: canonical state moved"
    assert wc.execute("SELECT next_seq FROM world_seq_counter").fetchone()[0] == 0
    assert mc.execute("SELECT COUNT(*) FROM perception").fetchone()[0] == 0


def test_moving_an_unplaced_being_is_rejected(tmp_path):
    os.makedirs(tmp_path, exist_ok=True)
    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    schema.init_world(wc)
    world = WorldStore(wc)
    for being_id, name, nature in BEINGS:
        world.add_being(being_id, name, nature)
    result = move(world, "noah", 1, 1, 1, 0)
    assert not result.accepted and result.reason == NOT_PLACED
    assert wc.execute("SELECT COUNT(*) FROM world_event").fetchone()[0] == 0


def test_rotation_alone_is_a_real_move(tmp_path):
    """Orientation already changes future perception, so turning is a move."""
    world, wc, _ = fresh(tmp_path)
    x, y, _, _ = world.current_pose("noah")
    assert move(world, "noah", x, y, 0, 1).accepted
    assert world.current_pose("noah") == (x, y, 0, 1)
    row = wc.execute("SELECT kind, payload_json FROM world_event").fetchone()
    payload = json.loads(row["payload_json"])
    assert row["kind"] == "MOVE"
    assert payload["from"] == payload["to"] == [x, y]
    assert payload["facing"] == [0, 1]


# -- temporal semantics: the event happens at the departure --------------


def test_observers_see_the_mover_where_they_set_off_from(tmp_path):
    """The snapshot must show the world BEFORE the transition.

    Updating being_pose first would make the mover appear already arrived to
    everyone perceiving the movement.
    """
    world, wc, _ = fresh(tmp_path)
    assert move(world, "noah", *DEST).accepted

    event = world.load_event("evt-000000")
    assert event["poses"]["noah"] == START["noah"], "snapshot shows the destination"
    assert (event["event_x_cm"], event["event_y_cm"]) == START["noah"][:2]
    assert world.current_pose("noah") == DEST      # ...but the world did move


# -- the acceptance scenario ---------------------------------------------


def test_acceptance_move_state_history_and_perception(tmp_path):
    world, wc, mc = fresh(tmp_path)
    assert move(world, "noah", *DEST).accepted
    history = derive(world, mc)

    assert world.current_pose("noah") == DEST
    assert [e["kind"] for e in world.all_events()] == ["MOVE"]
    payload = world.load_event("evt-000000")["payload"]
    assert payload == {"actor": "noah", "from": [800, 0], "to": [800, 400],
                       "facing": [0, -1]}

    noah = history.recall("noah")
    assert len(noah) == 1 and noah[0]["grade"] == "CLEAR"
    assert noah[0]["content"]["to"] == [800, 400]      # agency, not vision

    ava = history.recall("ava")
    assert len(ava) == 1 and ava[0]["grade"] == "COARSE"   # 500 cm away
    assert ava[0]["content"] == {"actor": "noah", "moved": True}

    assert history.recall("warren") == []               # facing the other way


def test_acceptance_survives_restart(tmp_path):
    assert run_phase(tmp_path, "populate").returncode == 0
    before = json.loads(run_phase(tmp_path, "recall").stdout)
    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    pose_before = wc.execute(
        "SELECT x_cm, y_cm, facing_x, facing_y FROM being_pose "
        "WHERE being_id='noah'").fetchone()

    m = run_phase(tmp_path, "move", "--being", "noah",
                  "--x", "800", "--y", "400", "--fx", "0", "--fy", "-1")
    assert m.returncode == 0, m.stderr

    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    assert tuple(wc.execute(
        "SELECT x_cm, y_cm, facing_x, facing_y FROM being_pose "
        "WHERE being_id='noah'").fetchone()) == (800, 400, 0, -1)
    assert tuple(pose_before) != (800, 400, 0, -1)
    assert wc.execute(
        "SELECT COUNT(*) FROM world_event WHERE kind='MOVE'").fetchone()[0] == 3

    after = json.loads(run_phase(tmp_path, "recall").stdout)
    for being in ("warren", "ava", "noah"):
        assert after[being][: len(before[being])] == before[being], being


# -- movement changes future perception, never past -----------------------


def test_moving_closer_improves_the_next_event_but_not_the_last(tmp_path):
    """The counterfactual that ties movement to the perception model."""
    world, wc, mc = fresh(tmp_path, poses={
        "warren": (0, 0, 1, 0),
        "ava": (100, 0, -1, 0),
        "noah": (50, 800, 0, -1),      # 800 cm: sees, cannot resolve detail
    })
    from one_world.actions import ACCEPT, attempt_give, respond_to_attempt

    def exchange(giver, receiver, at):
        made = attempt_give(world, actor=giver, receiver=receiver,
                            object_id="lighter-1", presence=ALL_THREE,
                            location=ROOM, occurred_at=at)
        assert made.accepted
        assert respond_to_attempt(
            world, attempt_id=made.attempt_id, responder=receiver,
            response=ACCEPT, presence=ALL_THREE, location=ROOM,
            occurred_at=at).accepted

    exchange("warren", "ava", "t1")                    # events 0,1 -- far away
    history = derive(world, mc)
    before = [dict(m) for m in history.recall("noah")]
    assert all(m["content"]["object"] == "something" for m in before)

    assert move(world, "noah", 50, 200, 0, -1, at="t2").accepted   # event 2

    exchange("ava", "warren", "t3")                    # events 3,4 -- close now
    history = derive(world, mc)
    after = history.recall("noah")

    # The old memories are byte-identical: no retroactive improvement.
    assert [m for m in after if m["seq"] < len(before)] == before
    # The new ones resolve the object, because he is 200 cm away.
    fresh_ones = [m for m in after if m["kind"] in ("GIVE", "GIVE_ATTEMPT")
                  and m["seq"] > 2]
    assert fresh_ones
    assert all(m["content"]["object"] == "red lighter" for m in fresh_ones)


# -- historical stability -------------------------------------------------


def test_a_to_b_to_c_keeps_both_legs(tmp_path):
    world, wc, _ = fresh(tmp_path)
    a = START["noah"]
    b = (800, 400, 0, -1)
    c = (200, 400, -1, 0)
    assert move(world, "noah", *b, at="t1").accepted
    assert move(world, "noah", *c, at="t2").accepted
    assert world.current_pose("noah") == c

    legs = [json.loads(r["payload_json"]) for r in wc.execute(
        "SELECT payload_json FROM world_event WHERE kind='MOVE' ORDER BY world_seq")]
    assert legs[0]["from"] == list(a[:2]) and legs[0]["to"] == list(b[:2])
    assert legs[1]["from"] == list(b[:2]) and legs[1]["to"] == list(c[:2])


def test_legs_survive_restart(tmp_path):
    assert run_phase(tmp_path, "populate").returncode == 0
    for x, y in ((50, 400), (50, 100)):
        assert run_phase(tmp_path, "move", "--being", "noah", "--x", str(x),
                         "--y", str(y), "--fx", "0", "--fy", "-1").returncode == 0
    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    legs = [json.loads(r[0]) for r in wc.execute(
        "SELECT payload_json FROM world_event WHERE kind='MOVE' ORDER BY world_seq")]
    hops = [(tuple(l["from"]), tuple(l["to"])) for l in legs
            if l["actor"] == "noah" and l["from"] != l["to"]]
    assert hops == [((50, 800), (50, 400)), ((50, 400), (50, 100))]


# -- atomicity ------------------------------------------------------------


def test_failure_during_a_move_rolls_the_pose_back(tmp_path, monkeypatch):
    world, wc, mc = fresh(tmp_path)
    before = snapshot(wc)
    assert world.current_pose("noah") == START["noah"]

    import one_world.world as world_module

    def boom(**kwargs):
        raise RuntimeError("sensing exploded mid-transaction")

    monkeypatch.setattr(world_module, "sense_event", boom)
    with pytest.raises(RuntimeError, match="exploded"):
        move(world, "noah", *DEST)

    assert snapshot(wc) == before, "partial work survived a failed move"
    assert world.current_pose("noah") == START["noah"]
    assert mc.execute("SELECT COUNT(*) FROM perception").fetchone()[0] == 0


def test_the_injection_would_otherwise_have_written(tmp_path):
    world, wc, _ = fresh(tmp_path)
    before = snapshot(wc)
    assert move(world, "noah", *DEST).accepted
    after = snapshot(wc)
    assert len(after["world_event"]) == len(before["world_event"]) + 1
    assert len(after["world_pose"]) == len(before["world_pose"]) + 3
    assert after["being_pose"] != before["being_pose"]


# -- information boundary -------------------------------------------------


def test_coarse_observer_receives_no_coordinates(tmp_path):
    """Ava is 500 cm away: she sees him move, not where to."""
    world, wc, mc = fresh(tmp_path)
    assert move(world, "noah", *DEST).accepted
    derive(world, mc)

    rows = mc.execute(
        "SELECT perceived_json FROM perception WHERE character_id='ava'").fetchall()
    assert len(rows) == 1, "no perception to inspect; the check would be vacuous"
    blob = rows[0][0]
    assert blob == '{"actor":"noah","moved":true}'
    # Exact JSON keys and the coordinate values -- not bare substrings, which
    # would false-positive on "to" inside "actor".
    for forbidden in ('"from"', '"to"', '"facing"', "800", "400"):
        assert forbidden not in blob, f"{forbidden} leaked to a coarse observer"


def test_no_structural_field_leaks_the_destination(tmp_path):
    """Coordinates must not arrive through kind, grade or origin_ref either."""
    world, wc, mc = fresh(tmp_path)
    assert move(world, "noah", *DEST).accepted
    derive(world, mc)
    row = mc.execute(
        "SELECT perception_id, character_id, perception_seq, kind, grade, "
        "perceived_json, origin_ref FROM perception WHERE character_id='ava'"
    ).fetchone()
    assert row
    whole = " ".join(str(v) for v in row)
    assert "400" not in whole and "800" not in whole


def test_load_event_does_not_reinterpret_an_old_move(tmp_path):
    """The read path must not re-derive a past destination from today's pose.

    The stability tests above read payload_json straight from SQL, which is
    good for independence but never exercises load_event -- and load_event is
    what the perception router consumes. This closes that gap.
    """
    world, _, _ = fresh(tmp_path)
    b = (800, 400, 0, -1)
    c = (200, 400, -1, 0)
    assert move(world, "noah", *b, at="t1").accepted
    assert move(world, "noah", *c, at="t2").accepted
    assert world.current_pose("noah") == c

    first = world.load_event("evt-000000")["payload"]
    assert first["from"] == [800, 0] and first["to"] == [800, 400], (
        "load_event rewrote an old move from the current pose")
    second = world.load_event("evt-000001")["payload"]
    assert second["from"] == [800, 400] and second["to"] == [200, 400]


def test_perception_derived_late_still_records_the_original_destination(tmp_path):
    """Two moves commit, THEN perceptions derive. The mover has already gone on.

    If anything read the destination from being_pose at derivation time, Noah's
    memory of his first move would name where he ended up, not where he went.
    """
    world, wc, mc = fresh(tmp_path)
    b = (800, 400, 0, -1)
    c = (200, 400, -1, 0)
    assert move(world, "noah", *b, at="t1").accepted
    assert move(world, "noah", *c, at="t2").accepted
    assert mc.execute("SELECT COUNT(*) FROM perception").fetchone()[0] == 0
    assert world.current_pose("noah") == c          # already elsewhere

    history = derive(world, mc)                     # only now do memories form
    legs = [m["content"] for m in history.recall("noah") if m["kind"] == "MOVE"]
    assert len(legs) == 2
    assert legs[0]["from"] == [800, 0] and legs[0]["to"] == [800, 400]
    assert legs[1]["from"] == [800, 400] and legs[1]["to"] == [200, 400]
