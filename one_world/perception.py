"""The router: the only component that holds both stores.

It reads canonical events, REDUCES each payload to what a given character
actually perceived, and writes only that reduced payload into minds.db.

Reduce-at-write, not filter-at-read. Information a character did not perceive
is never stored against them, so it cannot leak through a future bug or a
differently-shaped query.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Callable

from one_world.world import WorldStore, _dumps

GRADES = ("CLEAR", "COARSE")


# -- projection functions ------------------------------------------------
# Pure: output depends only on (kind, payload, grade). No clock, no randomness.


def _give_clear(p: dict) -> dict:
    return {"giver": p["giver"], "receiver": p["receiver"], "object": p["object"]}


def _give_coarse(p: dict) -> dict:
    # The object's identity is destroyed here, not hidden.
    return {"giver": p["giver"], "receiver": p["receiver"], "object": "something"}


def _speech_clear(p: dict) -> dict:
    return {
        "speaker": p["speaker"],
        "addressee": p["addressee"],
        "utterance": p["utterance"],
    }


def _attempt_clear(p: dict) -> dict:
    return {"giver": p["giver"], "receiver": p["receiver"], "object": p["object"]}


def _attempt_coarse(p: dict) -> dict:
    # Seen from too far to tell what is being offered. The identity is
    # destroyed here, not hidden: "Warren tried to give Ava something".
    return {"giver": p["giver"], "receiver": p["receiver"], "object": "something"}


def _refusal_clear(p: dict) -> dict:
    return {"refuser": p["refuser"], "utterance": p["utterance"]}


def _move_clear(p: dict) -> dict:
    return {"actor": p["actor"], "from": p["from"], "to": p["to"],
            "facing": p["facing"]}


def _move_coarse(p: dict) -> dict:
    # Seen from too far to tell where they went. Exact coordinates are canonical
    # detail the observer did not receive, so they are destroyed here rather
    # than stored and filtered.
    return {"actor": p["actor"], "moved": True}


def _place_clear(p: dict) -> dict:
    return {"actor": p["actor"], "object": p["object"], "at": p["at"]}


def _place_coarse(p: dict) -> dict:
    # "Warren put something down." Neither what it was nor exactly where.
    return {"actor": p["actor"], "put_down": True}


def _pickup_clear(p: dict) -> dict:
    return {"actor": p["actor"], "object": p["object"], "at": p["at"]}


def _pickup_coarse(p: dict) -> dict:
    return {"actor": p["actor"], "picked_up": True}


def _stow_clear(p: dict) -> dict:
    return {"actor": p["actor"], "object": p["object"], "place": p["place"]}


_PROJECTIONS: dict[tuple[str, str], Callable[[dict], dict]] = {
    ("GIVE", "CLEAR"): _give_clear,
    ("GIVE", "COARSE"): _give_coarse,
    ("SPEECH", "CLEAR"): _speech_clear,
    ("STOW", "CLEAR"): _stow_clear,
    ("GIVE_ATTEMPT", "CLEAR"): _attempt_clear,
    ("GIVE_ATTEMPT", "COARSE"): _attempt_coarse,
    ("REFUSAL", "CLEAR"): _refusal_clear,
    ("MOVE", "CLEAR"): _move_clear,
    ("MOVE", "COARSE"): _move_coarse,
    ("PLACE", "CLEAR"): _place_clear,
    ("PLACE", "COARSE"): _place_coarse,
    ("PICKUP", "CLEAR"): _pickup_clear,
    ("PICKUP", "COARSE"): _pickup_coarse,
}


def project(kind: str, payload: dict, grade: str) -> dict:
    """Reduce a canonical payload to what `grade` perception yields.

    Fails closed: an unhandled (kind, grade) raises rather than passing the
    full payload through.
    """
    if grade not in GRADES:
        raise ValueError(f"unknown grade: {grade!r}")
    fn = _PROJECTIONS.get((kind, grade))
    if fn is None:
        raise ValueError(f"no projection defined for kind={kind!r} grade={grade!r}")
    return fn(payload)


class PerceptionRouter:
    """Derives perceptions for events the outbox still marks PENDING.

    Idempotent by construction: a perception is identified by
    (character_id, origin_ref), so replaying a partially-applied event neither
    duplicates rows nor burns a sequence number.
    """

    def __init__(self, world: WorldStore, minds_conn: sqlite3.Connection) -> None:
        self._world = world
        self._minds = minds_conn

    def _already_perceived(self, character_id: str, origin_ref: str) -> bool:
        row = self._minds.execute(
            "SELECT 1 FROM perception WHERE character_id = ? AND origin_ref = ?",
            (character_id, origin_ref),
        ).fetchone()
        return row is not None

    def _next_perception_seq(self, character_id: str) -> int:
        row = self._minds.execute(
            "SELECT next_seq FROM perception_seq_counter WHERE character_id = ?",
            (character_id,),
        ).fetchone()
        if row is None:
            self._minds.execute(
                "INSERT INTO perception_seq_counter (character_id, next_seq) VALUES (?, 1)",
                (character_id,),
            )
            return 0
        seq = int(row["next_seq"])
        self._minds.execute(
            "UPDATE perception_seq_counter SET next_seq = ? WHERE character_id = ?",
            (seq + 1, character_id),
        )
        return seq

    def derive_pending(self) -> int:
        """Apply every PENDING event in canonical order. Returns rows written."""
        written = 0
        for row in self._world.pending_projections():
            event = self._world.load_event(row["event_id"])
            written += self._derive_one(event)
            # Marked DONE only after its perceptions are durably committed.
            self._world.mark_projected(event["event_id"])
        return written

    def _derive_one(self, event: dict) -> int:
        origin_ref = event["event_id"]
        written = 0
        with self._minds:
            for character_id, grade in sorted(event["observations"].items()):
                if self._already_perceived(character_id, origin_ref):
                    continue  # crash-after-write, before-DONE: skip, do not duplicate
                perceived = project(event["kind"], event["payload"], grade)
                seq = self._next_perception_seq(character_id)
                self._minds.execute(
                    "INSERT INTO perception (perception_id, character_id, perception_seq, "
                    "kind, grade, perceived_json, origin_ref) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"{origin_ref}:{character_id}",  # deterministic identity
                        character_id,
                        seq,
                        event["kind"],
                        grade,
                        _dumps(perceived),
                        origin_ref,
                    ),
                )
                written += 1
        return written
