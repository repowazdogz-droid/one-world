"""Canonical truth: the append-only record of what actually happened.

Nothing in this module is reachable from character-facing code.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from one_world.sensing import sense_event


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

    # -- present-day physical state -------------------------------------

    def set_pose(self, being_id: str, x_cm: int, y_cm: int, facing_x: int, facing_y: int) -> None:
        """Move/turn a being NOW. Mutable; never consulted for past events."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO being_pose (being_id, x_cm, y_cm, facing_x, facing_y) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(being_id) DO UPDATE SET "
                "x_cm = excluded.x_cm, y_cm = excluded.y_cm, "
                "facing_x = excluded.facing_x, facing_y = excluded.facing_y",
                (being_id, x_cm, y_cm, facing_x, facing_y),
            )

    def current_pose(self, being_id: str) -> tuple[int, int, int, int]:
        row = self._conn.execute(
            "SELECT x_cm, y_cm, facing_x, facing_y FROM being_pose WHERE being_id = ?",
            (being_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"{being_id} has no pose")
        return (row["x_cm"], row["y_cm"], row["facing_x"], row["facing_y"])

    # -- commit ---------------------------------------------------------

    def commit_event(
        self,
        *,
        kind: str,
        location: str,
        actor_id: str,
        payload: dict,
        presence: list[str],
        event_x_cm: int,
        event_y_cm: int,
        occurred_at: str,
        audio_mode: str | None = None,
    ) -> str:
        """Append one immutable event, SNAPSHOT the scene, DERIVE who perceived
        what, and mark it PENDING projection -- all in one transaction.

        There is no `observations` parameter. Grades are derived by
        sensing.sense_event from the event-time pose snapshot, so nobody hands
        the system the answer it is supposed to work out.

        Snapshotting before sensing is what makes historical perception stable:
        the grades stored here are a function of where everyone WAS, and later
        movement cannot reach back and change them.
        """
        with self._conn:
            seq = self._next_world_seq()
            event_id = f"evt-{seq:06d}"  # deterministic; no UUID anywhere
            self._conn.execute(
                "INSERT INTO world_event "
                "(event_id, world_seq, kind, location, actor_id, payload_json, "
                "event_x_cm, event_y_cm, audio_mode, occurred_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, seq, kind, location, actor_id, _dumps(payload),
                 event_x_cm, event_y_cm, audio_mode, occurred_at),
            )

            poses: dict[str, tuple[int, int, int, int]] = {}
            for being_id in sorted(presence):
                self._conn.execute(
                    "INSERT INTO world_presence (event_id, being_id) VALUES (?, ?)",
                    (event_id, being_id),
                )
                pose = self.current_pose(being_id)  # fails closed if absent
                poses[being_id] = pose
                self._conn.execute(
                    "INSERT INTO world_pose "
                    "(event_id, being_id, x_cm, y_cm, facing_x, facing_y) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (event_id, being_id, *pose),
                )

            observations = sense_event(
                kind=kind,
                actor_id=actor_id,
                event_x_cm=event_x_cm,
                event_y_cm=event_y_cm,
                audio_mode=audio_mode,
                poses=poses,
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
        poses = {
            r["being_id"]: (r["x_cm"], r["y_cm"], r["facing_x"], r["facing_y"])
            for r in self._conn.execute(
                "SELECT being_id, x_cm, y_cm, facing_x, facing_y FROM world_pose "
                "WHERE event_id = ? ORDER BY being_id",
                (event_id,),
            )
        }
        return {
            "event_id": row["event_id"],
            "world_seq": row["world_seq"],
            "kind": row["kind"],
            "location": row["location"],
            "actor_id": row["actor_id"],
            "payload": json.loads(row["payload_json"]),
            "event_x_cm": row["event_x_cm"],
            "event_y_cm": row["event_y_cm"],
            "audio_mode": row["audio_mode"],
            "occurred_at": row["occurred_at"],
            "presence": presence,
            "poses": poses,          # event-time snapshot, NOT current positions
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
