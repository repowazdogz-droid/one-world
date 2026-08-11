"""v0.5: an inhabitant can refuse, and the refusal is part of reality.

"Warren tried to give Ava the lighter" and "Warren gave Ava the lighter" are
different truths. The suite's job is to prove the system never collapses one
into the other.

Invalid-response tests count raw rows rather than re-asking the API whether it
rejected: a component confirming its own verdict is not evidence.
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
    ALREADY_RESOLVED, NOT_POSSESSED, UNKNOWN_ATTEMPT, UNKNOWN_RESPONSE,
    WRONG_RESPONDER, attempt_give, respond_to_attempt,
)
from one_world.minds import CharacterHistory
from one_world.perception import PerceptionRouter
from one_world.scenario import (
    ALL_THREE, ROOM, seed_world, setup_social_scene, social_answer, social_offer,
)
from one_world.world import STATE_CHANGING_KINDS, WorldStore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def transfer(world, *, giver, receiver, object_id="lighter-1", at="t"):
    """A successful A->B transfer, the only way one is now possible.

    Offer, then the named receiver accepts. Returns the ActionResult of the
    resolving response so callers can assert on the outcome.
    """
    offer = attempt_give(world, actor=giver, receiver=receiver,
                         object_id=object_id, presence=ALL_THREE,
                         location=ROOM, occurred_at=at)
    if not offer.accepted:
        return offer
    return respond_to_attempt(world, attempt_id=offer.attempt_id,
                              responder=receiver, response="ACCEPT",
                              presence=ALL_THREE, location=ROOM, occurred_at=at)



def run_phase(d, phase, *extra):
    return subprocess.run(
        [sys.executable, "-m", "one_world.scenario", "--dir", str(d), "--phase", phase, *extra],
        cwd=ROOT, capture_output=True, text=True,
    )


def fresh(tmp_path):
    os.makedirs(tmp_path, exist_ok=True)
    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    schema.init_world(wc)
    mc = schema.open_minds(os.path.join(tmp_path, "minds.db"))
    schema.init_minds(mc)
    world = WorldStore(wc)
    seed_world(world)
    setup_social_scene(world)
    return world, wc, mc


def derive(world, mc):
    PerceptionRouter(world, mc).derive_pending()
    return CharacterHistory(mc)


def kinds(wc):
    return [r[0] for r in wc.execute(
        "SELECT kind FROM world_event ORDER BY world_seq")]


def canonical_snapshot(wc):
    def rows(t):
        return sorted(tuple(r) for r in wc.execute(f"SELECT * FROM {t}"))
    return {t: rows(t) for t in (
        "object_location", "give_attempt", "world_event", "world_pose",
        "world_observation", "world_presence", "projection_outbox",
        "world_seq_counter")}


# -- SCENE A: refusal ----------------------------------------------------


def test_refusal_leaves_the_object_where_it_was(tmp_path):
    world, wc, mc = fresh(tmp_path)
    offer = social_offer(world)
    assert offer.accepted and offer.outcome == "PENDING"
    assert world.object_location("lighter-1")["holder_id"] == "warren"

    answer = social_answer(world, offer.attempt_id, "REFUSE")
    assert answer.accepted and answer.outcome == "REFUSED"

    assert world.object_location("lighter-1")["holder_id"] == "warren"
    assert kinds(wc) == ["GIVE_ATTEMPT", "REFUSAL"]


def test_refusal_creates_no_successful_give_event(tmp_path):
    """The load-bearing non-truth: history must not claim the transfer."""
    world, wc, mc = fresh(tmp_path)
    offer = social_offer(world)
    social_answer(world, offer.attempt_id, "REFUSE")
    assert "GIVE" not in kinds(wc)
    assert wc.execute(
        "SELECT COUNT(*) FROM world_event WHERE kind='GIVE'").fetchone()[0] == 0


def test_refusal_records_both_the_attempt_and_the_refusal(tmp_path):
    world, wc, mc = fresh(tmp_path)
    offer = social_offer(world)
    social_answer(world, offer.attempt_id, "REFUSE")

    events = {r["kind"]: json.loads(r["payload_json"]) for r in wc.execute(
        "SELECT kind, payload_json FROM world_event")}
    assert events["GIVE_ATTEMPT"] == {
        "giver": "warren", "receiver": "ava", "object": "red lighter"}
    assert events["REFUSAL"] == {"refuser": "ava", "utterance": "No."}

    att = world.attempt(offer.attempt_id)
    assert att["outcome"] == "REFUSED"
    assert att["resolved_seq"] == 1 and att["world_seq"] == 0


def test_refusal_survives_restart(tmp_path):
    assert run_phase(tmp_path, "offer").returncode == 0
    assert run_phase(tmp_path, "answer", "--response", "REFUSE").returncode == 0

    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    assert wc.execute(
        "SELECT holder_id FROM object_location").fetchone()[0] == "warren"
    assert kinds(wc) == ["GIVE_ATTEMPT", "REFUSAL"]
    assert wc.execute("SELECT outcome FROM give_attempt").fetchone()[0] == "REFUSED"

    data = json.loads(run_phase(tmp_path, "recall").stdout)
    assert [m["kind"] for m in data["ava"]] == ["GIVE_ATTEMPT", "REFUSAL"]
    assert [m["kind"] for m in data["warren"]] == ["GIVE_ATTEMPT", "REFUSAL"]
    assert [m["kind"] for m in data["noah"]] == ["GIVE_ATTEMPT"]


# -- SCENE B: acceptance, the same offer with one variable changed -------


def test_acceptance_transfers_and_records_a_give(tmp_path):
    world, wc, mc = fresh(tmp_path)
    offer = social_offer(world)
    answer = social_answer(world, offer.attempt_id, "ACCEPT")
    assert answer.outcome == "ACCEPTED"

    assert world.object_location("lighter-1")["holder_id"] == "ava"
    assert kinds(wc) == ["GIVE_ATTEMPT", "GIVE"]
    assert "REFUSAL" not in kinds(wc)
    assert world.attempt(offer.attempt_id)["outcome"] == "ACCEPTED"


def test_response_alone_changes_the_outcome(tmp_path):
    """Identical offer; only the answer differs."""
    refused_world, refused_wc, _ = fresh(tmp_path / "refused")
    r = social_offer(refused_world)
    social_answer(refused_world, r.attempt_id, "REFUSE")

    accepted_world, accepted_wc, _ = fresh(tmp_path / "accepted")
    a = social_offer(accepted_world)
    social_answer(accepted_world, a.attempt_id, "ACCEPT")

    assert r.attempt_id == a.attempt_id  # same deterministic offer
    assert refused_world.object_location("lighter-1")["holder_id"] == "warren"
    assert accepted_world.object_location("lighter-1")["holder_id"] == "ava"
    assert kinds(refused_wc) == ["GIVE_ATTEMPT", "REFUSAL"]
    assert kinds(accepted_wc) == ["GIVE_ATTEMPT", "GIVE"]


# -- unresolved attempt is persistent world state ------------------------


def test_unresolved_attempt_survives_a_full_restart(tmp_path):
    """Offer in one process, answer in another. Nothing is in-memory workflow."""
    made = json.loads(run_phase(tmp_path, "offer").stdout)
    assert made["accepted"] and made["outcome"] == "PENDING"

    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    pending = WorldStore(wc).pending_attempts()
    assert len(pending) == 1 and pending[0]["outcome"] == "PENDING"
    assert wc.execute(
        "SELECT holder_id FROM object_location").fetchone()[0] == "warren"

    # A separate process finds the offer on disk and refuses it.
    answered = json.loads(run_phase(tmp_path, "answer", "--response", "REFUSE").stdout)
    assert answered["accepted"] and answered["outcome"] == "REFUSED"
    assert answered["attempt_id"] == made["attempt_id"]

    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    assert WorldStore(wc).pending_attempts() == []
    assert wc.execute(
        "SELECT holder_id FROM object_location").fetchone()[0] == "warren"


# -- historical stability ------------------------------------------------


def test_old_outcomes_survive_later_transfers(tmp_path):
    """Refuse, then accept, then hand it back. Both old outcomes stand."""
    world, wc, mc = fresh(tmp_path)

    first = social_offer(world, "t1")
    social_answer(world, first.attempt_id, "REFUSE", "t2")
    second = social_offer(world, "t3")
    social_answer(world, second.attempt_id, "ACCEPT", "t4")
    assert world.object_location("lighter-1")["holder_id"] == "ava"

    # Ava hands it back -- which is itself an offer Warren must accept.
    third = transfer(world, giver="ava", receiver="warren", at="t5")
    assert third.accepted and third.outcome == "ACCEPTED"
    assert world.object_location("lighter-1")["holder_id"] == "warren"

    # Current ownership now matches the state AFTER the refusal, which is
    # exactly the trap: a system deriving outcome from ownership would now
    # call the accepted attempts refused.
    assert world.attempt(first.attempt_id)["outcome"] == "REFUSED"
    assert world.attempt(second.attempt_id)["outcome"] == "ACCEPTED"
    assert world.attempt(third.attempt_id)["outcome"] == "ACCEPTED"
    assert kinds(wc) == ["GIVE_ATTEMPT", "REFUSAL",
                         "GIVE_ATTEMPT", "GIVE",
                         "GIVE_ATTEMPT", "GIVE"]


def test_attempt_linkage_is_explicit_not_adjacency(tmp_path):
    world, wc, _ = fresh(tmp_path)
    first = social_offer(world, "t1")
    social_answer(world, first.attempt_id, "REFUSE", "t2")
    second = social_offer(world, "t3")
    social_answer(world, second.attempt_id, "ACCEPT", "t4")

    for seq, expected in [(0, first), (1, first), (2, second), (3, second)]:
        assert world.attempt_for_event_seq(seq)["attempt_id"] == expected.attempt_id


# -- perception ----------------------------------------------------------


def test_noah_sees_only_that_something_was_offered(tmp_path):
    world, wc, mc = fresh(tmp_path)
    offer = social_offer(world)
    social_answer(world, offer.attempt_id, "REFUSE")
    history = derive(world, mc)

    noah = history.recall("noah")
    assert len(noah) == 1                       # the attempt; not the refusal
    assert noah[0]["kind"] == "GIVE_ATTEMPT"
    assert noah[0]["grade"] == "COARSE"
    assert noah[0]["content"] == {
        "giver": "warren", "receiver": "ava", "object": "something"}


def test_noah_does_not_hear_the_refusal(tmp_path):
    """He is 802 cm away; a DIRECTED refusal carries 150 cm."""
    world, wc, mc = fresh(tmp_path)
    offer = social_offer(world)
    social_answer(world, offer.attempt_id, "REFUSE")
    refusal_seq = world.attempt(offer.attempt_id)["resolved_seq"]
    obs = {r["being_id"] for r in wc.execute(
        "SELECT being_id FROM world_observation WHERE event_id = ?",
        (f"evt-{refusal_seq:06d}",))}
    assert obs == {"warren", "ava"}


def test_ava_and_warren_perceive_the_whole_interaction(tmp_path):
    world, _, mc = fresh(tmp_path)
    offer = social_offer(world)
    social_answer(world, offer.attempt_id, "REFUSE")
    history = derive(world, mc)
    for who in ("ava", "warren"):
        got = [(m["kind"], m["grade"]) for m in history.recall(who)]
        assert got == [("GIVE_ATTEMPT", "CLEAR"), ("REFUSAL", "CLEAR")]


# -- information boundary ------------------------------------------------


def test_noahs_stored_bytes_carry_no_object_detail_or_correlation_id(tmp_path):
    assert run_phase(tmp_path, "offer").returncode == 0
    assert run_phase(tmp_path, "answer", "--response", "REFUSE").returncode == 0
    mc = sqlite3.connect(os.path.join(tmp_path, "minds.db"))
    blob = " ".join(r[0] for r in mc.execute(
        "SELECT perceived_json FROM perception WHERE character_id='noah'")).lower()
    assert blob
    for forbidden in ("lighter", "red", "lighter-1", "att-", "attempt_id",
                      "no.", "refus"):
        assert forbidden not in blob, f"{forbidden!r} leaked to Noah"


def test_no_correlation_id_reaches_any_perception(tmp_path):
    assert run_phase(tmp_path, "offer").returncode == 0
    assert run_phase(tmp_path, "answer", "--response", "ACCEPT").returncode == 0
    mc = sqlite3.connect(os.path.join(tmp_path, "minds.db"))
    rows = mc.execute("SELECT perceived_json FROM perception").fetchall()
    assert len(rows) >= 5, "no perceptions to inspect; the check would be vacuous"
    blob = " ".join(r[0] for r in rows).lower()
    assert "att-" not in blob and "attempt" not in blob and "lighter-1" not in blob


# -- impossible is not the same as refused -------------------------------


def test_impossible_attempt_creates_no_attempt_and_no_event(tmp_path):
    """Noah cannot offer what Warren holds. Nothing reached anyone to refuse."""
    world, wc, mc = fresh(tmp_path)
    before = canonical_snapshot(wc)
    result = attempt_give(world, actor="noah", receiver="warren",
                          object_id="lighter-1", presence=ALL_THREE,
                          location=ROOM, occurred_at="t")
    assert not result.accepted and result.reason == NOT_POSSESSED
    assert result.attempt_id is None
    assert canonical_snapshot(wc) == before
    assert wc.execute("SELECT COUNT(*) FROM give_attempt").fetchone()[0] == 0
    assert wc.execute("SELECT next_seq FROM world_seq_counter").fetchone()[0] == 0


def test_refused_and_impossible_are_distinguishable(tmp_path):
    impossible_world, impossible_wc, _ = fresh(tmp_path / "impossible")
    attempt_give(impossible_world, actor="noah", receiver="warren",
                 object_id="lighter-1", presence=ALL_THREE, location=ROOM,
                 occurred_at="t")

    refused_world, refused_wc, _ = fresh(tmp_path / "refused")
    offer = social_offer(refused_world)
    social_answer(refused_world, offer.attempt_id, "REFUSE")

    assert kinds(impossible_wc) == []
    assert kinds(refused_wc) == ["GIVE_ATTEMPT", "REFUSAL"]
    # Both leave the object with Warren -- state alone cannot tell them apart.
    for w in (impossible_world, refused_world):
        assert w.object_location("lighter-1")["holder_id"] == "warren"


# -- invalid responses fail closed with no side effects ------------------


@pytest.mark.parametrize(
    "describe,mutate,expected",
    [
        ("unknown response verb",
         lambda w, a: dict(attempt_id=a, responder="ava", response="MAYBE"),
         UNKNOWN_RESPONSE),
        ("nonexistent attempt",
         lambda w, a: dict(attempt_id="att-999999", responder="ava", response="REFUSE"),
         UNKNOWN_ATTEMPT),
        ("wrong responder",
         lambda w, a: dict(attempt_id=a, responder="noah", response="REFUSE"),
         WRONG_RESPONDER),
        ("the offerer answering for the recipient",
         lambda w, a: dict(attempt_id=a, responder="warren", response="ACCEPT"),
         WRONG_RESPONDER),
    ],
)
def test_invalid_response_leaves_no_trace(tmp_path, describe, mutate, expected):
    world, wc, mc = fresh(tmp_path)
    offer = social_offer(world)
    before = canonical_snapshot(wc)
    minds_before = mc.execute("SELECT COUNT(*) FROM perception").fetchone()[0]

    result = respond_to_attempt(
        world, presence=ALL_THREE, location=ROOM, occurred_at="t",
        **mutate(world, offer.attempt_id))
    assert not result.accepted, describe
    assert result.reason == expected

    assert canonical_snapshot(wc) == before, f"{describe}: canonical state moved"
    assert world.attempt(offer.attempt_id)["outcome"] == "PENDING"
    assert mc.execute("SELECT COUNT(*) FROM perception").fetchone()[0] == minds_before


def test_an_attempt_cannot_be_answered_twice(tmp_path):
    world, wc, _ = fresh(tmp_path)
    offer = social_offer(world)
    assert social_answer(world, offer.attempt_id, "REFUSE").accepted
    before = canonical_snapshot(wc)

    second = social_answer(world, offer.attempt_id, "ACCEPT")
    assert not second.accepted and second.reason == ALREADY_RESOLVED
    assert canonical_snapshot(wc) == before
    assert world.object_location("lighter-1")["holder_id"] == "warren"
    assert world.attempt(offer.attempt_id)["outcome"] == "REFUSED"


def test_a_response_cannot_resolve_a_different_attempt(tmp_path):
    """Two live offers; answering one must not touch the other."""
    world, wc, _ = fresh(tmp_path)
    first = social_offer(world, "t1")
    # Warren still holds it, so a second distinct offer is possible.
    second = attempt_give(world, actor="warren", receiver="noah",
                          object_id="lighter-1", presence=ALL_THREE,
                          location=ROOM, occurred_at="t2")
    assert second.accepted and second.attempt_id != first.attempt_id

    social_answer(world, first.attempt_id, "REFUSE", "t3")
    assert world.attempt(first.attempt_id)["outcome"] == "REFUSED"
    assert world.attempt(second.attempt_id)["outcome"] == "PENDING"
    assert world.attempt(second.attempt_id)["resolved_seq"] is None


def test_accepting_an_offer_the_giver_can_no_longer_honour_is_rejected(tmp_path):
    """Warren offers, then hands the lighter elsewhere before Ava answers."""
    world, wc, _ = fresh(tmp_path)
    offer = social_offer(world)
    assert transfer(world, giver="warren", receiver="noah", at="t2").accepted

    result = social_answer(world, offer.attempt_id, "ACCEPT")
    assert not result.accepted and result.reason == NOT_POSSESSED
    assert world.object_location("lighter-1")["holder_id"] == "noah"
    assert world.attempt(offer.attempt_id)["outcome"] == "PENDING"


# -- bypass audit --------------------------------------------------------


@pytest.mark.parametrize("kind", ["GIVE_ATTEMPT", "REFUSAL"])
def test_social_events_cannot_be_forged_through_commit_event(tmp_path, kind):
    world, wc, _ = fresh(tmp_path)
    assert kind in STATE_CHANGING_KINDS
    with pytest.raises(ValueError, match="cannot be appended directly"):
        world.commit_event(
            kind=kind, location=ROOM, actor_id="ava",
            payload={"refuser": "ava", "utterance": "forged"},
            presence=ALL_THREE, event_x_cm=0, event_y_cm=0, occurred_at="t",
            audio_mode="DIRECTED" if kind == "REFUSAL" else None)
    assert wc.execute("SELECT COUNT(*) FROM world_event").fetchone()[0] == 0


def test_only_the_action_layer_touches_attempt_state():
    """No other production module may create or resolve an attempt."""
    import one_world.perception as perception_module
    import one_world.scenario as scenario_module

    for mod in (perception_module, scenario_module):
        src = inspect.getsource(mod)
        assert "_create_attempt" not in src
        assert "_resolve_attempt" not in src
    assert "_create_attempt" in inspect.getsource(actions)
    assert "_resolve_attempt" in inspect.getsource(actions)


def test_caller_cannot_author_the_outcome():
    """respond_to_attempt takes a response, never an outcome or a payload."""
    params = set(inspect.signature(respond_to_attempt).parameters)
    assert "response" in params
    for forbidden in ("outcome", "payload", "accepted", "transfer"):
        assert forbidden not in params


def test_unknown_response_is_not_guessed():
    """Fail closed rather than interpreting an unrecognised answer."""
    from one_world.actions import RESPONSES
    assert RESPONSES == frozenset({"ACCEPT", "REFUSE"})


# -- the closed bypass: no direct transfer exists ------------------------


def test_no_production_path_transfers_possession_without_an_accept(tmp_path):
    """The v0.5 guarantee, tested as capability rather than as API shape.

    Every public entry point in the action layer is invoked against a world
    where Warren holds the lighter. None of them may end with Ava holding it.
    Only the offer/ACCEPT pair may.
    """
    world, wc, _ = fresh(tmp_path)
    assert world.object_location("lighter-1")["holder_id"] == "warren"
    assert wc.execute("SELECT COUNT(*) FROM give_attempt").fetchone()[0] == 0
    assert wc.execute(
        "SELECT COUNT(*) FROM world_event WHERE kind='GIVE'").fetchone()[0] == 0

    public = [n for n in dir(actions)
              if not n.startswith("_") and callable(getattr(actions, n))
              and getattr(actions, n).__module__ == "one_world.actions"]
    assert set(public) >= {"attempt_give", "propose_stow", "respond_to_attempt"}
    assert "propose_give" not in public, "the direct-transfer API is back"

    # Try every public action from a FRESH initial world -- one call each, so
    # nothing this loop does can set up the precondition for the next call.
    # No single production call may end with Ava holding the lighter.
    for i, name in enumerate(sorted(public)):
        fn = getattr(actions, name)
        for j, kwargs in enumerate((
            dict(actor="warren", receiver="ava", object_id="lighter-1"),
            dict(actor="warren", object_id="lighter-1", place="ava"),
            dict(attempt_id="att-000000", responder="ava", response="ACCEPT"),
        )):
            solo, _, _ = fresh(tmp_path / f"solo-{i}-{j}")
            try:
                fn(solo, **kwargs, presence=ALL_THREE, location=ROOM,
                   occurred_at="t")
            except TypeError:
                continue          # wrong shape for this verb; not a transfer
            assert solo.object_location("lighter-1")["holder_id"] == "warren", (
                f"{name}{tuple(kwargs)} moved possession without an ACCEPT")

    # And the internal primitive refuses too, without a live attempt.
    with pytest.raises(ValueError, match="possession cannot change"):
        with world.transaction():
            world._transfer_holder("lighter-1", "ava", "att-000000")
    assert world.object_location("lighter-1")["holder_id"] == "warren"

    # The only route that works: offer, then Ava accepts.
    made = social_offer(world)
    assert made.accepted
    assert world.object_location("lighter-1")["holder_id"] == "warren"

    done = social_answer(world, made.attempt_id, "ACCEPT")
    assert done.accepted and done.outcome == "ACCEPTED"
    assert world.object_location("lighter-1")["holder_id"] == "ava"
    assert kinds(wc) == ["GIVE_ATTEMPT", "GIVE"]
    assert wc.execute(
        "SELECT COUNT(*) FROM world_event WHERE kind='GIVE'").fetchone()[0] == 1
    assert world.attempt(made.attempt_id)["outcome"] == "ACCEPTED"


def test_refusal_cannot_be_routed_around(tmp_path):
    """After Ava refuses, no production path may complete the transfer."""
    world, wc, _ = fresh(tmp_path)
    made = social_offer(world)
    social_answer(world, made.attempt_id, "REFUSE")
    assert world.object_location("lighter-1")["holder_id"] == "warren"

    # The resolved attempt can no longer authorise a transfer.
    with pytest.raises(ValueError, match="possession cannot change"):
        with world.transaction():
            world._transfer_holder("lighter-1", "ava", made.attempt_id)
    assert social_answer(world, made.attempt_id, "ACCEPT").reason == ALREADY_RESOLVED

    assert world.object_location("lighter-1")["holder_id"] == "warren"
    assert "GIVE" not in kinds(wc)


def test_stow_can_never_change_the_holder(tmp_path):
    """The stow primitive does not mention holder_id at all."""
    import one_world.world as world_module

    # Inspect the SQL the method actually executes, not its prose.
    sql = [c for c in world_module.WorldStore._set_stow.__code__.co_consts
           if isinstance(c, str) and "UPDATE" in c]
    assert len(sql) == 1
    assert "holder_id" not in sql[0], f"stow can change the holder: {sql[0]}"
    assert "stowed_in" in sql[0]

    world, _, _ = fresh(tmp_path)
    from one_world.actions import propose_stow
    assert propose_stow(world, actor="warren", object_id="lighter-1",
                        place="pocket", presence=ALL_THREE, location=ROOM,
                        occurred_at="t").accepted
    loc = world.object_location("lighter-1")
    assert loc["holder_id"] == "warren" and loc["stowed_in"] == "pocket"
