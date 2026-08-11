"""v0.4: events must correspond to valid changes in canonical world state.

Rejection tests deliberately inspect RAW TABLES rather than re-asking the
validator whether it rejected. Asking the component under test to confirm its
own verdict proves nothing; counting rows does.
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
    ALREADY_STOWED, NOT_POSSESSED, SELF_GIVE, UNKNOWN_ACTOR, UNKNOWN_OBJECT,
    UNKNOWN_RECEIVER, attempt_give, propose_stow, respond_to_attempt,
)
from one_world.minds import CharacterHistory
from one_world.perception import PerceptionRouter
from one_world.scenario import ALL_THREE, ROOM, SCENARIO, apply_step, seed_world
from one_world.world import STATE_CHANGING_KINDS, WorldStore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GIVE_POSES = {
    "warren": (0, 0, 1, 0),
    "ava": (100, 0, -1, 0),
    "noah": (50, 800, 0, -1),
}


def run_phase(d, phase, *extra):
    return subprocess.run(
        [sys.executable, "-m", "one_world.scenario", "--dir", str(d), "--phase", phase, *extra],
        cwd=ROOT, capture_output=True, text=True,
    )


def fresh(tmp_path, holder="warren"):
    os.makedirs(tmp_path, exist_ok=True)
    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    schema.init_world(wc)
    mc = schema.open_minds(os.path.join(tmp_path, "minds.db"))
    schema.init_minds(mc)
    world = WorldStore(wc)
    seed_world(world, holder=holder)
    for being_id, pose in GIVE_POSES.items():
        world.set_pose(being_id, *pose)
    return world, wc, mc


def offer(world, **kw):
    """Just the attempt. Possession does not move."""
    base = dict(actor="warren", receiver="ava", object_id="lighter-1",
                presence=ALL_THREE, location=ROOM, occurred_at="0001-01-01T00:00:00Z")
    return attempt_give(world, **{**base, **kw})


def give(world, **kw):
    """A completed transfer: offer, then the named receiver accepts.

    v0.5 removed the direct-transfer API, so this is the only shape a
    successful A->B move can take.
    """
    receiver = kw.get("receiver", "ava")
    made = offer(world, **kw)
    if not made.accepted:
        return made
    return respond_to_attempt(
        world, attempt_id=made.attempt_id, responder=receiver, response="ACCEPT",
        presence=ALL_THREE, location=ROOM, occurred_at="0001-01-01T00:00:01Z")


def stow(world, **kw):
    base = dict(actor="ava", object_id="lighter-1", place="jacket pocket",
                presence=ALL_THREE, location=ROOM, occurred_at="0001-01-01T00:02:00Z")
    return propose_stow(world, **{**base, **kw})


def canonical_snapshot(conn):
    """Everything an action could possibly have touched, read raw."""
    def rows(t):
        return sorted(tuple(r) for r in conn.execute(f"SELECT * FROM {t}"))
    return {t: rows(t) for t in (
        "object_location", "world_event", "world_pose", "world_wall",
        "world_observation", "world_presence", "projection_outbox",
        "world_seq_counter")}


# -- the authority boundary ----------------------------------------------


def test_commit_event_refuses_state_changing_kinds(tmp_path):
    """The action layer is IN SERIES, not a well-behaved caller beside a door."""
    world, wc, _ = fresh(tmp_path)
    for kind in sorted(STATE_CHANGING_KINDS):
        with pytest.raises(ValueError, match="cannot be appended directly"):
            world.commit_event(
                kind=kind, location=ROOM, actor_id="warren",
                payload={"anything": "at all"}, presence=ALL_THREE,
                event_x_cm=0, event_y_cm=0, occurred_at="t")
    assert wc.execute("SELECT COUNT(*) FROM world_event").fetchone()[0] == 0


def test_state_changing_kinds_are_exactly_the_guarded_set():
    """v0.5 added two: GIVE_ATTEMPT creates a pending offer, REFUSAL resolves
    one, so both change canonical state and both must be unforgeable."""
    assert STATE_CHANGING_KINDS == frozenset(
        {"GIVE", "GIVE_ATTEMPT", "STOW", "REFUSAL"})


def test_no_production_module_calls_the_locked_appender_except_actions():
    """Only the validated layer may reach the internal primitive."""
    import one_world.scenario as scenario_module
    import one_world.perception as perception_module

    for mod in (scenario_module, perception_module):
        assert "_append_event_locked" not in inspect.getsource(mod)
    assert "_append_event_locked" in inspect.getsource(actions)


def test_caller_cannot_supply_the_object_description(tmp_path):
    """A proposal names an object_id; the payload comes from canonical state."""
    params = set(inspect.signature(attempt_give).parameters)
    assert "object_id" in params
    assert "payload" not in params and "description" not in params and "object" not in params

    world, wc, _ = fresh(tmp_path)
    assert give(world).accepted
    payloads = [json.loads(r[0]) for r in wc.execute(
        "SELECT payload_json FROM world_event ORDER BY world_seq")]
    assert len(payloads) == 2                       # the offer and the transfer
    for payload in payloads:
        assert payload["object"] == "red lighter"   # canonical description
        assert "lighter-1" not in json.dumps(payload)  # not the internal id


# -- accepted actions ----------------------------------------------------


def test_give_transfers_possession_only_after_the_receiver_accepts(tmp_path):
    world, wc, _ = fresh(tmp_path)
    assert world.object_location("lighter-1")["holder_id"] == "warren"

    made = offer(world)
    assert made.accepted and made.event_id == "evt-000000"
    assert world.object_location("lighter-1")["holder_id"] == "warren", (
        "possession moved on the offer alone")

    result = respond_to_attempt(
        world, attempt_id=made.attempt_id, responder="ava", response="ACCEPT",
        presence=ALL_THREE, location=ROOM, occurred_at="t")
    assert result.accepted and result.event_id == "evt-000001"

    assert world.object_location("lighter-1")["holder_id"] == "ava"
    assert wc.execute("SELECT COUNT(*) FROM world_event").fetchone()[0] == 2
    row = wc.execute(
        "SELECT kind, event_x_cm, event_y_cm FROM world_event WHERE world_seq=1"
    ).fetchone()
    assert row["kind"] == "GIVE"
    # Position DERIVED as the midpoint of (0,0) and (100,0).
    assert (row["event_x_cm"], row["event_y_cm"]) == (50, 0)


def test_stow_sets_the_place_without_changing_the_holder(tmp_path):
    world, _, _ = fresh(tmp_path, holder="ava")
    assert stow(world).accepted
    loc = world.object_location("lighter-1")
    assert loc["holder_id"] == "ava"
    assert loc["stowed_in"] == "jacket pocket"


def test_give_clears_a_previous_stow(tmp_path):
    world, _, _ = fresh(tmp_path, holder="ava")
    assert stow(world).accepted
    assert give(world, actor="ava", receiver="warren").accepted
    loc = world.object_location("lighter-1")
    assert loc["holder_id"] == "warren" and loc["stowed_in"] is None


def test_an_object_cannot_be_held_by_two_beings(tmp_path):
    """Structural: one row per object, so the contradiction is inexpressible."""
    world, wc, _ = fresh(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        with wc:
            wc.execute("INSERT INTO object_location (object_id, holder_id) "
                       "VALUES ('lighter-1', 'ava')")


# -- rejected actions: prove nothing at all happened ---------------------


@pytest.mark.parametrize(
    "describe,call,expected_reason",
    [
        ("noah gives what ava holds",
         lambda w: attempt_give(w, actor="noah", receiver="warren",
                                object_id="lighter-1", presence=ALL_THREE,
                                location=ROOM, occurred_at="t"), NOT_POSSESSED),
        ("warren gives it twice",
         lambda w: attempt_give(w, actor="warren", receiver="noah",
                                object_id="lighter-1", presence=ALL_THREE,
                                location=ROOM, occurred_at="t"), NOT_POSSESSED),
        ("nonexistent object",
         lambda w: attempt_give(w, actor="ava", receiver="noah",
                                object_id="ghost-9", presence=ALL_THREE,
                                location=ROOM, occurred_at="t"), UNKNOWN_OBJECT),
        ("nonexistent receiver",
         lambda w: attempt_give(w, actor="ava", receiver="nobody",
                                object_id="lighter-1", presence=ALL_THREE,
                                location=ROOM, occurred_at="t"), UNKNOWN_RECEIVER),
        ("nonexistent actor",
         lambda w: attempt_give(w, actor="nobody", receiver="ava",
                                object_id="lighter-1", presence=ALL_THREE,
                                location=ROOM, occurred_at="t"), UNKNOWN_ACTOR),
        ("giving to yourself",
         lambda w: attempt_give(w, actor="ava", receiver="ava",
                                object_id="lighter-1", presence=ALL_THREE,
                                location=ROOM, occurred_at="t"), SELF_GIVE),
        ("stowing what you do not hold",
         lambda w: propose_stow(w, actor="noah", object_id="lighter-1",
                                place="pocket", presence=ALL_THREE,
                                location=ROOM, occurred_at="t"), NOT_POSSESSED),
        ("stowing a nonexistent object",
         lambda w: propose_stow(w, actor="ava", object_id="ghost-9",
                                place="pocket", presence=ALL_THREE,
                                location=ROOM, occurred_at="t"), UNKNOWN_OBJECT),
    ],
)
def test_rejected_action_leaves_no_trace(tmp_path, describe, call, expected_reason):
    """After a rejection the world must be byte-identical to before it."""
    world, wc, mc = fresh(tmp_path, holder="ava")   # Ava holds it to start
    before = canonical_snapshot(wc)
    minds_before = mc.execute("SELECT COUNT(*) FROM perception").fetchone()[0]

    result = call(world)
    assert not result.accepted, describe
    assert result.reason == expected_reason
    assert result.event_id is None

    after = canonical_snapshot(wc)
    for table in before:
        assert after[table] == before[table], f"{describe}: {table} changed"
    # Named explicitly, because each is a separate way to leave a trace.
    assert after["world_event"] == []
    assert after["world_pose"] == []
    assert after["world_wall"] == []
    assert after["world_observation"] == []
    assert after["projection_outbox"] == []
    assert wc.execute("SELECT next_seq FROM world_seq_counter").fetchone()[0] == 0
    assert mc.execute("SELECT COUNT(*) FROM perception").fetchone()[0] == minds_before


def test_already_stowed_is_rejected(tmp_path):
    world, wc, _ = fresh(tmp_path, holder="ava")
    assert stow(world).accepted
    before = canonical_snapshot(wc)
    result = stow(world)
    assert not result.accepted and result.reason == ALREADY_STOWED
    assert canonical_snapshot(wc) == before


def test_rejections_do_not_consume_world_seq(tmp_path):
    """A rejected proposal must not leave a gap in canonical history."""
    world, wc, _ = fresh(tmp_path)
    for _ in range(5):
        assert not attempt_give(world, actor="noah", receiver="ava",
                                object_id="lighter-1", presence=ALL_THREE,
                                location=ROOM, occurred_at="t").accepted
    assert give(world).accepted
    assert wc.execute("SELECT world_seq FROM world_event").fetchone()[0] == 0


# -- atomicity -----------------------------------------------------------


def test_failure_inside_the_transaction_rolls_back_state_and_history(tmp_path, monkeypatch):
    """Real injection: make sensing raise AFTER state and event writes.

    sense_event runs inside _append_event_locked, which runs inside the action's
    transaction, after object_location has been updated and after the event,
    pose and wall rows have been inserted. If the transaction is not doing its
    job, some of that survives.
    """
    world, wc, mc = fresh(tmp_path)
    made = offer(world)                      # the offer succeeds normally
    assert made.accepted
    # Snapshot AFTER the offer, so the injection is measured against the
    # transaction that actually moves possession -- the ACCEPT.
    before = canonical_snapshot(wc)
    assert before["object_location"] == [("lighter-1", "warren", None)]

    import one_world.world as world_module

    def boom(**kwargs):
        raise RuntimeError("sensing exploded mid-transaction")

    monkeypatch.setattr(world_module, "sense_event", boom)
    with pytest.raises(RuntimeError, match="exploded"):
        respond_to_attempt(
            world, attempt_id=made.attempt_id, responder="ava", response="ACCEPT",
            presence=ALL_THREE, location=ROOM, occurred_at="t")

    after = canonical_snapshot(wc)
    assert after == before, "partial work survived a failed action"
    assert world.object_location("lighter-1")["holder_id"] == "warren"
    assert world.attempt(made.attempt_id)["outcome"] == "PENDING"
    assert mc.execute("SELECT COUNT(*) FROM perception").fetchone()[0] == 0


def test_the_injection_would_otherwise_have_written(tmp_path):
    """Control: without the injection the same ACCEPT writes everything."""
    world, wc, _ = fresh(tmp_path)
    made = offer(world)
    before = canonical_snapshot(wc)
    assert respond_to_attempt(
        world, attempt_id=made.attempt_id, responder="ava", response="ACCEPT",
        presence=ALL_THREE, location=ROOM, occurred_at="t").accepted
    snap = canonical_snapshot(wc)
    assert len(snap["world_event"]) == len(before["world_event"]) + 1
    assert len(snap["world_pose"]) == len(before["world_pose"]) + 3
    assert len(snap["world_observation"]) == len(before["world_observation"]) + 3
    assert len(snap["projection_outbox"]) == len(before["projection_outbox"]) + 1
    assert snap["object_location"] == [("lighter-1", "ava", None)]


# -- history does not follow current state -------------------------------


def test_earlier_event_meaning_survives_later_transfers(tmp_path):
    """Give it, give it back, give it on. Event 0 still says what it said."""
    world, wc, _ = fresh(tmp_path)
    assert give(world).accepted                                   # warren -> ava
    first = json.loads(
        wc.execute("SELECT payload_json FROM world_event WHERE world_seq=1").fetchone()[0])
    assert first == {"giver": "warren", "object": "red lighter", "receiver": "ava"}

    assert give(world, actor="ava", receiver="warren").accepted
    assert give(world, actor="warren", receiver="noah").accepted
    assert world.object_location("lighter-1")["holder_id"] == "noah"

    again = json.loads(
        wc.execute("SELECT payload_json FROM world_event WHERE world_seq=1").fetchone()[0])
    assert again == first, "current ownership rewrote an old event"


# -- the acceptance scenario, end to end ---------------------------------


def test_full_scenario_state_and_histories(tmp_path):
    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    schema.init_world(wc)
    mc = schema.open_minds(os.path.join(tmp_path, "minds.db"))
    schema.init_minds(mc)
    world = WorldStore(wc)
    seed_world(world)
    assert world.object_location("lighter-1")["holder_id"] == "warren"

    for step in SCENARIO:
        apply_step(world, step)
    PerceptionRouter(world, mc).derive_pending()

    loc = world.object_location("lighter-1")
    assert loc["holder_id"] == "ava" and loc["stowed_in"] == "jacket pocket"

    # v0.5: the transfer now requires an offer Ava accepts, so the GIVE is
    # preceded by a GIVE_ATTEMPT that everyone present can also perceive.
    assert [e["kind"] for e in world.all_events()] == [
        "GIVE_ATTEMPT", "GIVE", "SPEECH", "STOW"]
    history = CharacterHistory(mc)
    assert len(history.recall("ava")) == 4
    assert len(history.recall("warren")) == 3
    assert len(history.recall("noah")) == 2


def test_state_and_histories_survive_restart(tmp_path):
    assert run_phase(tmp_path, "populate").returncode == 0

    conn = schema.open_world(os.path.join(tmp_path, "world.db"))
    loc = conn.execute("SELECT holder_id, stowed_in FROM object_location").fetchone()
    assert (loc["holder_id"], loc["stowed_in"]) == ("ava", "jacket pocket")
    seqs = [r[0] for r in conn.execute(
        "SELECT world_seq FROM world_event ORDER BY world_seq")]
    assert seqs == [0, 1, 2, 3]
    assert conn.execute(
        "SELECT outcome FROM give_attempt").fetchone()[0] == "ACCEPTED"

    data = json.loads(run_phase(tmp_path, "recall").stdout)
    assert len(data["ava"]) == 4
    assert len(data["warren"]) == 3
    assert len(data["noah"]) == 2
    # Noah saw both the offer and the transfer, neither in enough detail.
    assert [m["content"]["object"] for m in data["noah"]] == ["something", "something"]


# -- information boundary ------------------------------------------------


def test_canonical_object_id_never_reaches_any_perception(tmp_path):
    """Stable internal ids are convenient; that is not a reason to leak them."""
    assert run_phase(tmp_path, "populate").returncode == 0
    mc = sqlite3.connect(os.path.join(tmp_path, "minds.db"))
    blob = " ".join(r[0] for r in mc.execute(
        "SELECT perceived_json FROM perception")).lower()
    assert blob
    assert "lighter-1" not in blob
    assert "object_id" not in blob


def test_noahs_stored_bytes_hold_no_canonical_object_detail(tmp_path):
    assert run_phase(tmp_path, "populate").returncode == 0
    mc = sqlite3.connect(os.path.join(tmp_path, "minds.db"))
    blob = " ".join(r[0] for r in mc.execute(
        "SELECT perceived_json FROM perception WHERE character_id='noah'")).lower()
    assert blob
    for forbidden in ("lighter", "red", "lighter-1", "jacket", "pocket",
                      "leaving tomorrow"):
        assert forbidden not in blob, f"{forbidden!r} leaked to Noah"
