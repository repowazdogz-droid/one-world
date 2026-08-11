"""The v0.1 behavioural contract, across a real process restart."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys

import pytest

from one_world import schema
from one_world.minds import CharacterHistory
from one_world.perception import project
from one_world.world import WorldStore
from tests.contract import run_contract

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_phase(d, phase, *extra):
    return subprocess.run(
        [sys.executable, "-m", "one_world.scenario", "--dir", str(d), "--phase", phase, *extra],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


class StaticHistory:
    """Adapts the recall JSON emitted by the restarted process."""

    def __init__(self, data):
        self._data = data

    def recall(self, character_id):
        return self._data[character_id]


@pytest.fixture
def restarted(tmp_path):
    """Populate in one process; recall in a genuinely separate one."""
    p = run_phase(tmp_path, "populate")
    assert p.returncode == 0, p.stderr
    r = run_phase(tmp_path, "recall")
    assert r.returncode == 0, r.stderr
    return tmp_path, json.loads(r.stdout)


# -- the contract --------------------------------------------------------


def test_contract_passes_after_restart(restarted):
    _, data = restarted
    results = run_contract(StaticHistory(data))
    failed = sorted(k for k, ok in results.items() if not ok)
    assert failed == [], f"failed checks: {failed}"


def test_no_in_memory_state_survives(restarted):
    """Recall came from a separate process, so it can only be from disk."""
    tmp, data = restarted
    assert os.path.exists(os.path.join(tmp, "minds.db"))
    assert len(data["ava"]) == 3 and len(data["noah"]) == 1


# -- raw persisted bytes -------------------------------------------------


def test_noah_forbidden_strings_never_written_to_disk(restarted):
    """The strongest check: assert on stored bytes, not on API output.

    A filtering API can be bypassed by a future query. Bytes that were never
    written cannot leak.
    """
    tmp, _ = restarted
    conn = sqlite3.connect(os.path.join(tmp, "minds.db"))
    blob = " ".join(
        row[0]
        for row in conn.execute(
            "SELECT perceived_json FROM perception WHERE character_id = 'noah'"
        )
    ).lower()
    assert blob  # Noah does have a memory
    for forbidden in ("lighter", "red", "leaving tomorrow", "jacket", "pocket"):
        assert forbidden not in blob, f"{forbidden!r} present in Noah's stored bytes"


def test_warren_stow_detail_never_written_to_disk(restarted):
    tmp, _ = restarted
    conn = sqlite3.connect(os.path.join(tmp, "minds.db"))
    blob = " ".join(
        row[0]
        for row in conn.execute(
            "SELECT perceived_json FROM perception WHERE character_id = 'warren'"
        )
    ).lower()
    assert "jacket" not in blob and "pocket" not in blob


def test_minds_db_has_no_canonical_tables(restarted):
    tmp, _ = restarted
    conn = sqlite3.connect(os.path.join(tmp, "minds.db"))
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == {"perception", "perception_seq_counter"}


# -- explicit ordering ---------------------------------------------------


def test_order_survives_physical_row_reshuffle(restarted, tmp_path):
    """Prove order comes from perception_seq, not rowid or insertion order."""
    tmp, data = restarted
    shuffled = os.path.join(tmp_path, "shuffled.db")
    shutil.copy(os.path.join(tmp, "minds.db"), shuffled)

    conn = sqlite3.connect(shuffled)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM perception")]
    with conn:
        conn.execute("DELETE FROM perception")
        for row in reversed(rows):  # invert physical order, preserve seq
            conn.execute(
                "INSERT INTO perception (perception_id, character_id, perception_seq, "
                "kind, grade, perceived_json, origin_ref) VALUES (?,?,?,?,?,?,?)",
                tuple(row[k] for k in
                      ("perception_id", "character_id", "perception_seq",
                       "kind", "grade", "perceived_json", "origin_ref")),
            )
    rowids = [r[0] for r in conn.execute("SELECT rowid FROM perception ORDER BY rowid")]
    seqs = [r[0] for r in conn.execute("SELECT perception_seq FROM perception ORDER BY rowid")]
    assert rowids == sorted(rowids)
    assert seqs != sorted(seqs), "reshuffle did not actually invert physical order"

    conn.row_factory = sqlite3.Row
    assert CharacterHistory(conn).recall("ava") == data["ava"]


def test_seq_is_per_character_and_dense(restarted):
    tmp, data = restarted
    assert [m["seq"] for m in data["ava"]] == [0, 1, 2]
    assert [m["seq"] for m in data["warren"]] == [0, 1]
    assert [m["seq"] for m in data["noah"]] == [0]


# -- canonical immutability ----------------------------------------------


def test_canonical_events_cannot_be_updated(restarted):
    tmp, _ = restarted
    conn = schema.open_world(os.path.join(tmp, "world.db"))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with conn:
            conn.execute("UPDATE world_event SET kind = 'TAMPERED'")


def test_canonical_events_cannot_be_deleted(restarted):
    tmp, _ = restarted
    conn = schema.open_world(os.path.join(tmp, "world.db"))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with conn:
            conn.execute("DELETE FROM world_event")


def _snapshot(conn, table):
    return sorted(tuple(r) for r in conn.execute(f"SELECT * FROM {table}"))


@pytest.mark.parametrize(
    "table,statement,message",
    [
        ("world_presence", "UPDATE world_presence SET being_id = being_id", "immutable"),
        ("world_presence", "DELETE FROM world_presence", "append-only"),
        ("world_observation", "UPDATE world_observation SET grade = 'CLEAR'", "immutable"),
        ("world_observation", "DELETE FROM world_observation", "append-only"),
    ],
)
def test_canonical_presence_and_observation_are_append_only(
    restarted, table, statement, message
):
    """Presence and observation are canonical truth and get the same protection.

    Who was there, and who perceived what, are facts about the world -- not
    bookkeeping. Rewriting an observation grade after the fact would silently
    change what a character was entitled to perceive.
    """
    tmp, _ = restarted
    conn = schema.open_world(os.path.join(tmp, "world.db"))
    before = _snapshot(conn, table)
    assert before, f"{table} is empty; the test would be vacuous"

    with pytest.raises(sqlite3.IntegrityError, match=message):
        with conn:
            conn.execute(statement)

    assert _snapshot(conn, table) == before, f"{table} changed despite the abort"


def test_canonical_holds_more_than_anyone_perceived(restarted):
    tmp, data = restarted
    conn = schema.open_world(os.path.join(tmp, "world.db"))
    world = WorldStore(conn)
    assert world.event_count() == 3
    assert max(len(v) for v in data.values()) <= 3
    assert len(data["warren"]) < world.event_count()


def test_world_seq_is_dense_and_ordered(restarted):
    tmp, _ = restarted
    conn = schema.open_world(os.path.join(tmp, "world.db"))
    seqs = [r["world_seq"] for r in conn.execute(
        "SELECT world_seq FROM world_event ORDER BY world_seq")]
    assert seqs == [0, 1, 2]


# -- projection fails closed ---------------------------------------------


def test_projection_rejects_unknown_kind_grade_pair():
    with pytest.raises(ValueError, match="no projection defined"):
        project("SPEECH", {"speaker": "warren"}, "COARSE")


def test_projection_rejects_unknown_grade():
    with pytest.raises(ValueError, match="unknown grade"):
        project("GIVE", {}, "TELEPATHIC")
