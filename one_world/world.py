"""Canonical truth: the append-only record of what actually happened.

Nothing in this module is reachable from character-facing code.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def _dumps(obj: Any) -> str:
    # sort_keys keeps stored bytes deterministic across runs.
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


class WorldStore:
    """Append-only canonical event log with an explicit persistent sequence."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # -- roster ---------------------------------------------------------

    def add_being(self, being_id: str, display_name: str, nature: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO being (being_id, display_name, nature) "
                "VALUES (?, ?, ?)",
                (being_id, display_name, nature),
            )

    # -- ordering -------------------------------------------------------

    def _next_world_seq(self) -> int:
        row = self._conn.execute(
            "SELECT next_seq FROM world_seq_counter WHERE id = 1"
        ).fetchone()
        seq = int(row["next_seq"])
        self._conn.execute(
            "UPDATE world_seq_counter SET next_seq = ? WHERE id = 1", (seq + 1,)
        )
        return seq

    # -- commit ---------------------------------------------------------

    def commit_event(
        self,
        *,
        kind: str,
        location: str,
        actor_id: str,
        payload: dict,
        presence: list[str],
        observations: dict[str, str],
        occurred_at: str,
    ) -> str:
        """Append one immutable event and mark it PENDING projection.

        The outbox row is written in the SAME transaction as the event, so a
        committed event can never exist without a record that it still owes
        perceptions.
        """
        with self._conn:
            seq = self._next_world_seq()
            event_id = f"evt-{seq:06d}"  # deterministic; no UUID anywhere
            self._conn.execute(
                "INSERT INTO world_event "
                "(event_id, world_seq, kind, location, actor_id, payload_json, occurred_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (event_id, seq, kind, location, actor_id, _dumps(payload), occurred_at),
            )
            for being_id in sorted(presence):
                self._conn.execute(
                    "INSERT INTO world_presence (event_id, being_id) VALUES (?, ?)",
                    (event_id, being_id),
                )
            for being_id, grade in sorted(observations.items()):
                self._conn.execute(
                    "INSERT INTO world_observation (event_id, being_id, grade) "
                    "VALUES (?, ?, ?)",
                    (event_id, being_id, grade),
                )
            self._conn.execute(
                "INSERT INTO projection_outbox (event_id, world_seq, state) "
                "VALUES (?, ?, 'PENDING')",
                (event_id, seq),
            )
        return event_id

    # -- projection bookkeeping -----------------------------------------

    def pending_projections(self) -> list[sqlite3.Row]:
        """Events still owing perceptions, in canonical order."""
        return list(
            self._conn.execute(
                "SELECT event_id, world_seq FROM projection_outbox "
                "WHERE state = 'PENDING' ORDER BY world_seq"
            )
        )

    def mark_projected(self, event_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE projection_outbox SET state = 'DONE' WHERE event_id = ?",
                (event_id,),
            )

    # -- reads (world engine / router / audit only) ----------------------

    def load_event(self, event_id: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM world_event WHERE event_id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise KeyError(event_id)
        observations = {
            r["being_id"]: r["grade"]
            for r in self._conn.execute(
                "SELECT being_id, grade FROM world_observation WHERE event_id = ? "
                "ORDER BY being_id",
                (event_id,),
            )
        }
        presence = [
            r["being_id"]
            for r in self._conn.execute(
                "SELECT being_id FROM world_presence WHERE event_id = ? ORDER BY being_id",
                (event_id,),
            )
        ]
        return {
            "event_id": row["event_id"],
            "world_seq": row["world_seq"],
            "kind": row["kind"],
            "location": row["location"],
            "actor_id": row["actor_id"],
            "payload": json.loads(row["payload_json"]),
            "occurred_at": row["occurred_at"],
            "presence": presence,
            "observations": observations,
        }

    def event_count(self) -> int:
        return int(
            self._conn.execute("SELECT COUNT(*) AS n FROM world_event").fetchone()["n"]
        )

    def all_events(self) -> list[dict]:
        ids = [
            r["event_id"]
            for r in self._conn.execute(
                "SELECT event_id FROM world_event ORDER BY world_seq"
            )
        ]
        return [self.load_event(i) for i in ids]
