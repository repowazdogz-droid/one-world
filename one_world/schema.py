"""DDL for the two ONE WORLD databases, and how to open them.

Two files, not one. This is an *architectural / capability* boundary, not an OS
security boundary: code running as this user can open world.db if it is given or
discovers the path. What the split buys is that canonical access becomes a
visible, greppable, testable act rather than an ordinary SELECT away.

The enforced invariant is stated and tested in tests/test_structural.py.
"""

from __future__ import annotations

import sqlite3

WORLD_DDL = """
CREATE TABLE IF NOT EXISTS being (
    being_id      TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    nature        TEXT NOT NULL CHECK (nature IN ('human', 'ai'))
);

-- MUTABLE present-day world state: where each being is NOW. Positions are
-- integer centimetres; facing is an integer direction vector, not both zero.
-- Historical perception must NEVER be derived from this table -- see world_pose.
CREATE TABLE IF NOT EXISTS being_pose (
    being_id   TEXT PRIMARY KEY REFERENCES being(being_id),
    x_cm       INTEGER NOT NULL,
    y_cm       INTEGER NOT NULL,
    facing_x   INTEGER NOT NULL,
    facing_y   INTEGER NOT NULL,
    CHECK (facing_x != 0 OR facing_y != 0)
);

-- The immutable record of what actually happened, in full.
CREATE TABLE IF NOT EXISTS world_event (
    event_id      TEXT PRIMARY KEY,
    world_seq     INTEGER NOT NULL UNIQUE,
    kind          TEXT NOT NULL,
    location      TEXT NOT NULL,
    actor_id      TEXT NOT NULL REFERENCES being(being_id),
    payload_json  TEXT NOT NULL,
    event_x_cm    INTEGER NOT NULL,      -- where the observable action happened
    event_y_cm    INTEGER NOT NULL,
    audio_mode    TEXT
                  CHECK (audio_mode IS NULL OR audio_mode IN ('PUBLIC', 'DIRECTED')),
    occurred_at   TEXT NOT NULL          -- descriptive only; NEVER used to order
);

CREATE TRIGGER IF NOT EXISTS world_event_no_update
BEFORE UPDATE ON world_event
BEGIN SELECT RAISE(ABORT, 'world_event is immutable'); END;

CREATE TRIGGER IF NOT EXISTS world_event_no_delete
BEFORE DELETE ON world_event
BEGIN SELECT RAISE(ABORT, 'world_event is append-only'); END;

-- Who was physically there. Deliberately distinct from what they perceived.
CREATE TABLE IF NOT EXISTS world_presence (
    event_id  TEXT NOT NULL REFERENCES world_event(event_id),
    being_id  TEXT NOT NULL REFERENCES being(being_id),
    PRIMARY KEY (event_id, being_id)
);

CREATE TRIGGER IF NOT EXISTS world_presence_no_update
BEFORE UPDATE ON world_presence
BEGIN SELECT RAISE(ABORT, 'world_presence is immutable'); END;

CREATE TRIGGER IF NOT EXISTS world_presence_no_delete
BEFORE DELETE ON world_presence
BEGIN SELECT RAISE(ABORT, 'world_presence is append-only'); END;

-- IMMUTABLE event-time pose snapshot: where everyone present WAS when the event
-- happened. Written in the same transaction as the event and never revisited.
-- This is the authoritative sensing input; being_pose is not.
CREATE TABLE IF NOT EXISTS world_pose (
    event_id   TEXT NOT NULL REFERENCES world_event(event_id),
    being_id   TEXT NOT NULL REFERENCES being(being_id),
    x_cm       INTEGER NOT NULL,
    y_cm       INTEGER NOT NULL,
    facing_x   INTEGER NOT NULL,
    facing_y   INTEGER NOT NULL,
    PRIMARY KEY (event_id, being_id)
);

CREATE TRIGGER IF NOT EXISTS world_pose_no_update
BEFORE UPDATE ON world_pose
BEGIN SELECT RAISE(ABORT, 'world_pose is immutable'); END;

CREATE TRIGGER IF NOT EXISTS world_pose_no_delete
BEFORE DELETE ON world_pose
BEGIN SELECT RAISE(ABORT, 'world_pose is append-only'); END;

-- Who perceived the event, and at what fidelity. Absent row == did not perceive.
-- DERIVED at commit time by sensing.sense_event from world_pose; in v0.1 this
-- was author-supplied. Persisted canonically so that projection is replayable
-- after a restart WITHOUT re-consulting present-day positions.
CREATE TABLE IF NOT EXISTS world_observation (
    event_id  TEXT NOT NULL REFERENCES world_event(event_id),
    being_id  TEXT NOT NULL REFERENCES being(being_id),
    grade     TEXT NOT NULL CHECK (grade IN ('CLEAR', 'COARSE')),
    PRIMARY KEY (event_id, being_id)
);

CREATE TRIGGER IF NOT EXISTS world_observation_no_update
BEFORE UPDATE ON world_observation
BEGIN SELECT RAISE(ABORT, 'world_observation is immutable'); END;

CREATE TRIGGER IF NOT EXISTS world_observation_no_delete
BEFORE DELETE ON world_observation
BEGIN SELECT RAISE(ABORT, 'world_observation is append-only'); END;

-- Mutable projection bookkeeping, kept OUT of world_event so the fact itself
-- stays immutable. Written in the same transaction as the event.
CREATE TABLE IF NOT EXISTS projection_outbox (
    event_id   TEXT PRIMARY KEY REFERENCES world_event(event_id),
    world_seq  INTEGER NOT NULL UNIQUE,
    state      TEXT NOT NULL CHECK (state IN ('PENDING', 'DONE'))
);

CREATE TABLE IF NOT EXISTS world_seq_counter (
    id        INTEGER PRIMARY KEY CHECK (id = 1),
    next_seq  INTEGER NOT NULL
);
"""

MINDS_DDL = """
-- One row per (character, event they perceived). perceived_json holds the
-- ALREADY-REDUCED payload: information the character did not perceive is never
-- written here, rather than written and filtered at read time.
CREATE TABLE IF NOT EXISTS perception (
    perception_id   TEXT PRIMARY KEY,
    character_id    TEXT NOT NULL,
    perception_seq  INTEGER NOT NULL,   -- per-character memory order
    kind            TEXT NOT NULL,
    grade           TEXT NOT NULL,
    perceived_json  TEXT NOT NULL,
    origin_ref      TEXT NOT NULL,      -- opaque canonical id; audit only
    UNIQUE (character_id, perception_seq),
    UNIQUE (character_id, origin_ref)   -- makes retry idempotent
);

CREATE TABLE IF NOT EXISTS perception_seq_counter (
    character_id  TEXT PRIMARY KEY,
    next_seq      INTEGER NOT NULL
);
"""


def _open(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def open_world(path: str) -> sqlite3.Connection:
    """Open the canonical store. Only the world engine and router call this."""
    return _open(path)


def open_minds(path: str) -> sqlite3.Connection:
    """Open the perception store. This is what character code is handed."""
    return _open(path)


def init_world(conn: sqlite3.Connection) -> None:
    with conn:
        conn.executescript(WORLD_DDL)
        conn.execute(
            "INSERT OR IGNORE INTO world_seq_counter (id, next_seq) VALUES (1, 0)"
        )


def init_minds(conn: sqlite3.Connection) -> None:
    with conn:
        conn.executescript(MINDS_DDL)
