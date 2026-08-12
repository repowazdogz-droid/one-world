"""Canonical truth: the append-only record of what actually happened.

Nothing in this module is reachable from character-facing code.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any

from one_world.sensing import sense_event, sense_state


#: Kinds that change canonical world state. These may only be created through
#: the validated action layer (one_world.actions), never by a direct call to
#: commit_event -- otherwise the action layer would be a well-behaved caller
#: alongside an open back door, rather than the only way in.
STATE_CHANGING_KINDS = frozenset(
    {"GIVE", "GIVE_ATTEMPT", "MOVE", "PICKUP", "PLACE", "REFUSAL", "STOW"}
)


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

    def seed_pose(self, being_id: str, x_cm: int, y_cm: int,
                  facing_x: int, facing_y: int) -> None:
        """Place a being for the FIRST time. Initialization only.

        A plain INSERT, not an upsert: once a being has a pose this raises, so
        seeding cannot be reused as a teleport API. That is the whole of the
        initialization/runtime boundary -- structural, and narrow enough to
        state precisely rather than a lifecycle state machine.
        """
        with self._conn:
            self._conn.execute(
                "INSERT INTO being_pose (being_id, x_cm, y_cm, facing_x, facing_y) "
                "VALUES (?, ?, ?, ?, ?)",
                (being_id, x_cm, y_cm, facing_x, facing_y),
            )

    def _move_pose(self, being_id: str, x_cm: int, y_cm: int,
                   facing_x: int, facing_y: int) -> None:
        """Change a live inhabitant's pose. Caller MUST hold the transaction.

        UPDATE only: it cannot create a pose, and the MOVE action is its only
        caller, so an inhabitant's position changes only alongside the history
        that explains it.
        """
        self._conn.execute(
            "UPDATE being_pose SET x_cm = ?, y_cm = ?, facing_x = ?, facing_y = ? "
            "WHERE being_id = ?",
            (x_cm, y_cm, facing_x, facing_y, being_id),
        )

    def current_pose(self, being_id: str) -> tuple[int, int, int, int]:
        row = self._conn.execute(
            "SELECT x_cm, y_cm, facing_x, facing_y FROM being_pose WHERE being_id = ?",
            (being_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"{being_id} has no pose")
        return (row["x_cm"], row["y_cm"], row["facing_x"], row["facing_y"])

    def add_wall(self, wall_id: str, x1: int, y1: int, x2: int, y2: int) -> None:
        """Build a wall NOW. Mutable; never consulted for past events."""
        if (x1, y1) == (x2, y2):
            raise ValueError("zero-length wall rejected: no occlusion semantics")
        with self._conn:
            self._conn.execute(
                "INSERT INTO wall (wall_id, x1_cm, y1_cm, x2_cm, y2_cm) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(wall_id) DO UPDATE SET "
                "x1_cm = excluded.x1_cm, y1_cm = excluded.y1_cm, "
                "x2_cm = excluded.x2_cm, y2_cm = excluded.y2_cm",
                (wall_id, x1, y1, x2, y2),
            )

    def remove_wall(self, wall_id: str) -> None:
        """Demolish a wall NOW. Past events keep their own snapshot of it."""
        with self._conn:
            self._conn.execute("DELETE FROM wall WHERE wall_id = ?", (wall_id,))

    def current_walls(self) -> list[tuple[str, int, int, int, int]]:
        return [
            (r["wall_id"], r["x1_cm"], r["y1_cm"], r["x2_cm"], r["y2_cm"])
            for r in self._conn.execute(
                "SELECT wall_id, x1_cm, y1_cm, x2_cm, y2_cm FROM wall ORDER BY wall_id"
            )
        ]

    # -- canonical objects ----------------------------------------------

    def add_object(self, object_id: str, kind: str, description: str,
                   holder_id: str) -> None:
        """Introduce an object and give it an initial holder."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO object (object_id, kind, description) VALUES (?, ?, ?)",
                (object_id, kind, description),
            )
            self._conn.execute(
                "INSERT INTO object_location "
                "(object_id, holder_id, stowed_in, x_cm, y_cm) "
                "VALUES (?, ?, NULL, NULL, NULL)",
                (object_id, holder_id),
            )

    def object_row(self, object_id: str):
        """Canonical identity, or None if no such object exists."""
        return self._conn.execute(
            "SELECT object_id, kind, description FROM object WHERE object_id = ?",
            (object_id,),
        ).fetchone()

    def object_location(self, object_id: str):
        """Current holder and stow label, or None if the object is unknown."""
        return self._conn.execute(
            "SELECT object_id, holder_id, stowed_in, x_cm, y_cm FROM object_location "
            "WHERE object_id = ?",
            (object_id,),
        ).fetchone()

    def placed_objects(self) -> list[tuple[str, str, int, int]]:
        """Objects LYING IN THE WORLD now: (object_id, description, x, y).

        Held and stowed objects are excluded by the WHERE clause, not by a
        caller remembering to filter, so nothing can accidentally sense the
        contents of someone's pockets.
        """
        return [
            (r["object_id"], r["description"], r["x_cm"], r["y_cm"])
            for r in self._conn.execute(
                "SELECT o.object_id, o.description, l.x_cm, l.y_cm "
                "FROM object_location l JOIN object o USING (object_id) "
                "WHERE l.x_cm IS NOT NULL ORDER BY o.object_id"
            )
        ]

    def being_exists(self, being_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM being WHERE being_id = ?", (being_id,)
        ).fetchone() is not None

    def _set_stow(self, object_id: str, stowed_in: str | None) -> None:
        """Change only the stow label. Caller MUST hold the action transaction.

        holder_id is not in this statement at all, so this primitive cannot
        move an object between inhabitants however it is called.
        """
        self._conn.execute(
            "UPDATE object_location SET stowed_in = ? WHERE object_id = ?",
            (stowed_in, object_id),
        )

    def _place_object(self, object_id: str, x_cm: int, y_cm: int) -> None:
        """HELD -> PLACED. Caller MUST hold the transaction.

        Clears the holder and any stow label together with setting the point,
        so the exclusivity CHECK can never be momentarily violated.
        """
        self._conn.execute(
            "UPDATE object_location SET holder_id = NULL, stowed_in = NULL, "
            "x_cm = ?, y_cm = ? WHERE object_id = ?",
            (x_cm, y_cm, object_id),
        )

    def _take_object(self, object_id: str, holder_id: str) -> None:
        """PLACED -> HELD. Caller MUST hold the transaction.

        Clears the point in the same statement that sets the holder, so an
        object can never be both held and lying somewhere.
        """
        self._conn.execute(
            "UPDATE object_location SET holder_id = ?, stowed_in = NULL, "
            "x_cm = NULL, y_cm = NULL WHERE object_id = ?",
            (holder_id, object_id),
        )

    def _transfer_holder(self, object_id: str, to_holder: str,
                         attempt_id: str) -> None:
        """Move an object between inhabitants. Caller MUST hold the transaction.

        The ONLY primitive that can change holder_id, and it structurally
        requires a live attempt naming this object and this receiver. There is
        therefore no way to transfer possession without an offer that the
        receiver is in the act of answering -- recipient agency is not a
        convention the caller may skip.
        """
        live = self._conn.execute(
            "SELECT 1 FROM give_attempt WHERE attempt_id = ? AND outcome = 'PENDING' "
            "AND object_id = ? AND receiver_id = ?",
            (attempt_id, object_id, to_holder),
        ).fetchone()
        if live is None:
            raise ValueError(
                f"possession cannot change: no pending attempt {attempt_id!r} "
                f"offers {object_id!r} to {to_holder!r}"
            )
        self._conn.execute(
            "UPDATE object_location SET holder_id = ?, stowed_in = NULL "
            "WHERE object_id = ?",
            (to_holder, object_id),
        )

    # -- offers awaiting an answer --------------------------------------

    def _create_attempt(self, attempt_id: str, world_seq: int, actor_id: str,
                        receiver_id: str, object_id: str) -> None:
        """Caller MUST hold the action transaction."""
        self._conn.execute(
            "INSERT INTO give_attempt (attempt_id, world_seq, actor_id, "
            "receiver_id, object_id, outcome, resolved_seq) "
            "VALUES (?, ?, ?, ?, ?, 'PENDING', NULL)",
            (attempt_id, world_seq, actor_id, receiver_id, object_id),
        )

    def _resolve_attempt(self, attempt_id: str, outcome: str,
                         resolved_seq: int) -> None:
        """Caller MUST hold the action transaction. Records the OUTCOME FACT."""
        self._conn.execute(
            "UPDATE give_attempt SET outcome = ?, resolved_seq = ? "
            "WHERE attempt_id = ? AND outcome = 'PENDING'",
            (outcome, resolved_seq, attempt_id),
        )

    def attempt(self, attempt_id: str):
        return self._conn.execute(
            "SELECT * FROM give_attempt WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()

    def pending_attempts(self) -> list:
        """Unresolved offers, in canonical order. Survives restart."""
        return list(self._conn.execute(
            "SELECT * FROM give_attempt WHERE outcome = 'PENDING' "
            "ORDER BY world_seq"))

    def attempt_for_event_seq(self, world_seq: int):
        """The attempt an event belongs to -- explicit, never by adjacency."""
        return self._conn.execute(
            "SELECT * FROM give_attempt WHERE world_seq = ? OR resolved_seq = ?",
            (world_seq, world_seq),
        ).fetchone()

    @contextmanager
    def transaction(self):
        """One canonical transaction: state change AND history, or neither."""
        with self._conn:
            yield

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
        the grades stored here are a function of where everyone WAS and which
        walls STOOD at the time, and neither later movement nor later
        demolition can reach back and change them.

        REFUSES state-changing kinds. A GIVE or a STOW asserts that the world
        actually changed, and only the action layer may establish that.
        """
        if kind in STATE_CHANGING_KINDS:
            raise ValueError(
                f"{kind!r} changes canonical world state and cannot be appended "
                f"directly; use one_world.actions"
            )
        with self._conn:
            return self._append_event_locked(
                kind=kind, location=location, actor_id=actor_id, payload=payload,
                presence=presence, event_x_cm=event_x_cm, event_y_cm=event_y_cm,
                occurred_at=occurred_at, audio_mode=audio_mode,
            )

    def _append_event_locked(
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
        """Append the event and everything derived from it.

        The caller MUST already hold the transaction, so that a state change and
        its historical event commit together or not at all. No kind guard here:
        this is the internal primitive the action layer builds on.
        """
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

        walls = []
        for wall_id, x1, y1, x2, y2 in self.current_walls():
            walls.append((x1, y1, x2, y2))
            self._conn.execute(
                "INSERT INTO world_wall "
                "(event_id, wall_id, x1_cm, y1_cm, x2_cm, y2_cm) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, wall_id, x1, y1, x2, y2),
            )

        observations = sense_event(
            kind=kind,
            actor_id=actor_id,
            event_x_cm=event_x_cm,
            event_y_cm=event_y_cm,
            audio_mode=audio_mode,
            poses=poses,
            walls=tuple(walls),
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

    # -- v0.8: arrival-state sensing -------------------------------------

    def _record_arrival_scan(self, *, event_id: str, world_seq: int,
                             being_id: str) -> str:
        """Sense what is PRESENT from the pose a MOVE just arrived at.

        The caller MUST already hold the action transaction, and MUST already
        have applied the pose transition. Both halves matter:

          * Same transaction, so a committed MOVE always leaves behind the
            durable, authoritative inputs its arrival scan was computed from.
            There is no window in which the world says Ava arrived but has
            forgotten what she arrived to.

          * AFTER the transition, because the pose this reads is the ARRIVAL
            pose. It comes from current_pose -- the canonical present, which the
            caller has just updated -- and NOT from the MOVE's world_pose
            snapshot, which by design records the departure. Reusing world_pose
            here would look tidy and be temporally wrong.

        Object positions, descriptions and grades are SNAPSHOTTED into
        arrival_sighting rather than left to be looked up when the perceptions
        are eventually projected. That is what makes a delayed or retried
        projection reproduce the observation an uninterrupted MOVE would have
        produced, however much the world has moved on in the meantime.

        A scan row is written even when nothing was visible: arriving and seeing
        nothing is a fact, and a later scan must not be able to fill it in.

        ORDERING: the scan takes the MOVE's OWN world_seq rather than consuming
        a new one. A scan is not an event -- appending "Ava looked" to canonical
        history would make an inhabitant's perception into world truth, which is
        precisely the distinction this project exists to keep -- and burning
        event sequence numbers on non-events would leave holes in a log whose
        density is a v0.1 invariant. The MOVE is the canonical fact; the scan
        hangs off it, and the drain breaks the tie by putting the event first.
        """
        seq = world_seq
        scan_id = f"scan-{seq:06d}"  # deterministic; no UUID anywhere
        pose = self.current_pose(being_id)     # ARRIVAL pose, post-transition
        self._conn.execute(
            "INSERT INTO arrival_scan "
            "(scan_id, world_seq, event_id, being_id, x_cm, y_cm, facing_x, facing_y) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (scan_id, seq, event_id, being_id, *pose),
        )

        placed = self.placed_objects()
        walls = tuple((x1, y1, x2, y2) for _, x1, y1, x2, y2 in self.current_walls())
        grades = sense_state(
            observer_pose=pose,
            objects=tuple((oid, x, y) for oid, _desc, x, y in placed),
            walls=walls,
        )
        for index, (object_id, description, x_cm, y_cm) in enumerate(
            [p for p in placed if p[0] in grades]
        ):
            self._conn.execute(
                "INSERT INTO arrival_sighting (sighting_id, scan_id, object_id, "
                "description, grade, x_cm, y_cm) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"sig-{seq:06d}-{index:03d}", scan_id, object_id, description,
                 grades[object_id], x_cm, y_cm),
            )

        self._conn.execute(
            "INSERT INTO arrival_scan_outbox (scan_id, world_seq, state) "
            "VALUES (?, ?, 'PENDING')",
            (scan_id, seq),
        )
        return scan_id

    def pending_scans(self) -> list[sqlite3.Row]:
        """Arrival scans still owing observations, in canonical order."""
        return list(
            self._conn.execute(
                "SELECT scan_id, world_seq FROM arrival_scan_outbox "
                "WHERE state = 'PENDING' ORDER BY world_seq"
            )
        )

    def mark_scan_projected(self, scan_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE arrival_scan_outbox SET state = 'DONE' WHERE scan_id = ?",
                (scan_id,),
            )

    def load_scan(self, scan_id: str) -> dict:
        """Replay one arrival scan, from the arrival-time record ALONE.

        Every value returned here comes from arrival_scan or arrival_sighting,
        both of which are immutable and were written inside the MOVE's own
        transaction. This function reads NO mutable table -- not object_location,
        not wall, not being_pose -- so it cannot substitute today's world for the
        world the inhabitant actually arrived to. That property is the whole
        point of snapshotting, and it is asserted structurally as well as
        behaviourally in the v0.8 tests.
        """
        row = self._conn.execute(
            "SELECT * FROM arrival_scan WHERE scan_id = ?", (scan_id,)
        ).fetchone()
        if row is None:
            raise KeyError(scan_id)
        sightings = [
            {
                "sighting_id": r["sighting_id"],
                "grade": r["grade"],
                # The canonical payload of a sighting, assembled from the
                # snapshot. The router reduces this before it reaches anyone.
                "payload": {"object": r["description"], "at": [r["x_cm"], r["y_cm"]]},
            }
            for r in self._conn.execute(
                "SELECT sighting_id, description, grade, x_cm, y_cm "
                "FROM arrival_sighting WHERE scan_id = ? ORDER BY sighting_id",
                (scan_id,),
            )
        ]
        return {
            "scan_id": row["scan_id"],
            "world_seq": row["world_seq"],
            "event_id": row["event_id"],
            "being_id": row["being_id"],
            "pose": (row["x_cm"], row["y_cm"], row["facing_x"], row["facing_y"]),
            "sightings": sightings,
        }

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
        walls = {
            r["wall_id"]: (r["x1_cm"], r["y1_cm"], r["x2_cm"], r["y2_cm"])
            for r in self._conn.execute(
                "SELECT wall_id, x1_cm, y1_cm, x2_cm, y2_cm FROM world_wall "
                "WHERE event_id = ? ORDER BY wall_id",
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
            "walls": walls,          # event-time geometry, NOT today's layout
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
