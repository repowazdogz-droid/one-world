"""Crash between the canonical commit and the perception write.

The two stores cannot be committed atomically, so the canonical side records
that an event still owes perceptions (projection_outbox, written in the same
transaction as the event). The router re-applies pending work after restart,
and is idempotent because a perception is identified by (character, origin).
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys

import pytest

from one_world import schema
from tests.contract import run_contract
from tests.test_acceptance import StaticHistory

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_phase(d, phase, *extra):
    return subprocess.run(
        [sys.executable, "-m", "one_world.scenario", "--dir", str(d), "--phase", phase, *extra],
        cwd=ROOT, capture_output=True, text=True,
    )


def outbox(d):
    conn = schema.open_world(os.path.join(d, "world.db"))
    return {r["event_id"]: r["state"] for r in conn.execute(
        "SELECT event_id, state FROM projection_outbox ORDER BY world_seq")}


def perception_rows(d):
    conn = sqlite3.connect(os.path.join(d, "minds.db"))
    return conn.execute(
        "SELECT character_id, perception_seq, origin_ref FROM perception "
        "ORDER BY character_id, perception_seq").fetchall()


# -- crash after canonical commit, before perceptions --------------------


@pytest.mark.parametrize("crash_at", [0, 1, 2])
def test_crash_before_derive_then_recover(tmp_path, crash_at):
    p = run_phase(tmp_path, "populate", "--crash-before-derive", str(crash_at))
    assert p.returncode == 9, f"expected hard exit, got {p.returncode}: {p.stderr}"

    # The step's events are committed and marked PENDING; nothing derived yet.
    # A GIVE step now produces TWO events (offer, then transfer), so the
    # pending set is read from the outbox rather than assumed from the index.
    states = outbox(tmp_path)
    pending = {k for k, v in states.items() if v == "PENDING"}
    assert pending, "the crashed step committed no event"
    before = perception_rows(tmp_path)
    assert all(r[2] not in pending for r in before), "crash left perceptions behind"

    r = run_phase(tmp_path, "recover")
    assert r.returncode == 0, r.stderr
    assert all(v == "DONE" for v in outbox(tmp_path).values())

    after = perception_rows(tmp_path)
    assert len(after) > len(before)


def test_full_history_restored_after_crash_on_last_event(tmp_path):
    """Crash on the final event, recover, then run the whole contract."""
    p = run_phase(tmp_path, "populate", "--crash-before-derive", "2")
    assert p.returncode == 9

    partial = json.loads(run_phase(tmp_path, "recall").stdout)
    assert len(partial["ava"]) == 3, "pre-recovery history should be short"

    rec = json.loads(run_phase(tmp_path, "recover").stdout)
    assert rec["derived"] == 1  # Ava alone perceived the STOW

    data = json.loads(run_phase(tmp_path, "recall").stdout)
    failed = sorted(k for k, ok in run_contract(StaticHistory(data)).items() if not ok)
    assert failed == [], f"contract failed after recovery: {failed}"


def test_recovered_perception_keeps_dense_ordering(tmp_path):
    run_phase(tmp_path, "populate", "--crash-before-derive", "2")
    run_phase(tmp_path, "recover")
    data = json.loads(run_phase(tmp_path, "recall").stdout)
    assert [m["seq"] for m in data["ava"]] == [0, 1, 2, 3]
    assert [m["kind"] for m in data["ava"]] == [
        "GIVE_ATTEMPT", "GIVE", "SPEECH", "STOW"]


# -- idempotency: crash AFTER the write, BEFORE the DONE mark ------------


def test_replay_of_already_applied_event_creates_no_duplicates(tmp_path):
    """The second crash window: perceptions committed, DONE mark lost."""
    p = run_phase(tmp_path, "populate")
    assert p.returncode == 0
    before = perception_rows(tmp_path)

    conn = schema.open_world(os.path.join(tmp_path, "world.db"))
    with conn:  # simulate the lost DONE mark
        conn.execute("UPDATE projection_outbox SET state = 'PENDING'")
    assert set(outbox(tmp_path).values()) == {"PENDING"}

    rec = json.loads(run_phase(tmp_path, "recover").stdout)
    assert rec["derived"] == 0, "re-applying wrote new rows"
    assert perception_rows(tmp_path) == before, "rows or ordering changed on replay"
    assert set(outbox(tmp_path).values()) == {"DONE"}


def test_recovery_is_idempotent_across_repeated_runs(tmp_path):
    run_phase(tmp_path, "populate", "--crash-before-derive", "1")
    run_phase(tmp_path, "recover")
    snapshot = perception_rows(tmp_path)
    for _ in range(3):
        rec = json.loads(run_phase(tmp_path, "recover").stdout)
        assert rec["derived"] == 0
    assert perception_rows(tmp_path) == snapshot


def test_each_intended_perception_exists_exactly_once(tmp_path):
    """Crash on the LAST event, so all three are canonically committed."""
    run_phase(tmp_path, "populate", "--crash-before-derive", "2")
    run_phase(tmp_path, "recover")
    run_phase(tmp_path, "recover")
    rows = perception_rows(tmp_path)
    pairs = [(r[0], r[2]) for r in rows]
    assert len(pairs) == len(set(pairs)), "duplicate (character, event) perception"
    # Ava 4 + Warren 3 + Noah 2. The offer is perceived exactly as the
    # transfer is: same poses, same geometry.
    assert len(rows) == 9


def test_crash_at_first_event_loses_uncommitted_later_events(tmp_path):
    """A crash before commit means those events never happened. Not a gap."""
    run_phase(tmp_path, "populate", "--crash-before-derive", "0")
    run_phase(tmp_path, "recover")
    conn = schema.open_world(os.path.join(tmp_path, "world.db"))
    # Step 0 is the offer AND the transfer Ava accepted: two events.
    assert conn.execute("SELECT COUNT(*) FROM world_event").fetchone()[0] == 2
    rows = perception_rows(tmp_path)
    assert len(rows) == 6  # both events, each perceived by all three
    assert {r[2] for r in rows} == {"evt-000000", "evt-000001"}


def test_event_marked_done_only_after_its_perceptions_are_durable(tmp_path):
    """The ordering the whole recovery guarantee rests on.

    If an event were marked DONE before its perceptions were committed, a crash
    in that window would lose them permanently: recovery would never revisit a
    DONE event. No crash injection can reach inside derive_pending, so this
    observes the real production sequence instead -- at each mark_projected
    call, the event's perceptions must ALREADY be visible to a SEPARATE
    connection, i.e. durably committed rather than merely staged.
    """
    from one_world.perception import PerceptionRouter
    from one_world.scenario import BEINGS, SCENARIO, apply_step, seed_world
    from one_world.world import WorldStore

    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    schema.init_world(wc)
    mc = schema.open_minds(os.path.join(tmp_path, "minds.db"))
    schema.init_minds(mc)
    world = WorldStore(wc)
    seed_world(world)
    for step in SCENARIO:
        apply_step(world, step)

    # A separate connection sees only committed rows.
    observer = sqlite3.connect(os.path.join(tmp_path, "minds.db"))
    seen = []
    original = world.mark_projected

    def spy(event_id):
        durable = observer.execute(
            "SELECT COUNT(*) FROM perception WHERE origin_ref = ?", (event_id,)
        ).fetchone()[0]
        expected = len(world.load_event(event_id)["observations"])
        seen.append((event_id, durable, expected))
        return original(event_id)

    world.mark_projected = spy
    PerceptionRouter(world, mc).derive_pending()

    assert len(seen) == world.event_count() == 4, "not every event was marked"
    for event_id, durable, expected in seen:
        assert durable == expected, (
            f"{event_id} marked DONE with {durable}/{expected} perceptions durable"
        )


def test_derivation_order_follows_world_seq_not_outbox_row_order(tmp_path):
    """Discriminatory ordering regression test.

    Commits every event WITHOUT deriving, so several are PENDING at once, then
    physically re-inserts the outbox rows in REVERSE order so that rowid /
    insertion order disagrees with world_seq. Derivation must still allocate
    perception_seq in canonical order.

    Passes only if the drain is ordered by world_seq; would fail under
    ORDER BY rowid or incidental SELECT order.

    The invariant asserted is the exact one: for each character, perceptions
    are a SUBSEQUENCE of canonical order -- gaps allowed, inversions never.
    """
    from one_world.perception import PerceptionRouter
    from one_world.scenario import BEINGS, SCENARIO, apply_step, seed_world
    from one_world.world import WorldStore

    wc = schema.open_world(os.path.join(tmp_path, "world.db"))
    schema.init_world(wc)
    mc = schema.open_minds(os.path.join(tmp_path, "minds.db"))
    schema.init_minds(mc)
    world = WorldStore(wc)
    seed_world(world)

    for step in SCENARIO:                      # all PENDING, none derived
        apply_step(world, step)
    committed = [r["event_id"] for r in world.pending_projections()]
    assert len(committed) == 4                 # offer, transfer, speech, stow

    rows = [dict(r) for r in wc.execute("SELECT * FROM projection_outbox")]
    with wc:
        wc.execute("DELETE FROM projection_outbox")
        for r in reversed(rows):
            wc.execute(
                "INSERT INTO projection_outbox (event_id, world_seq, state) VALUES (?,?,?)",
                (r["event_id"], r["world_seq"], r["state"]),
            )
    physical = [r[0] for r in wc.execute("SELECT event_id FROM projection_outbox ORDER BY rowid")]
    assert physical == list(reversed(committed)), "setup failed to invert physical row order"

    PerceptionRouter(world, mc).derive_pending()

    for character in ("warren", "ava", "noah"):
        got = [
            r[0]
            for r in mc.execute(
                "SELECT origin_ref FROM perception WHERE character_id = ? "
                "ORDER BY perception_seq",
                (character,),
            )
        ]
        assert got, f"{character} perceived nothing"
        assert got == [i for i in committed if i in got], (
            f"{character} perception order inverted vs canonical: {got}"
        )


def test_no_perceptions_leak_forbidden_data_after_recovery(tmp_path):
    run_phase(tmp_path, "populate", "--crash-before-derive", "0")
    run_phase(tmp_path, "recover")
    conn = sqlite3.connect(os.path.join(tmp_path, "minds.db"))
    blob = " ".join(r[0] for r in conn.execute(
        "SELECT perceived_json FROM perception WHERE character_id='noah'")).lower()
    assert blob
    for forbidden in ("lighter", "red", "leaving tomorrow", "jacket", "pocket"):
        assert forbidden not in blob
