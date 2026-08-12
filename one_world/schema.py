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

-- Canonical object identity. `description` is the world's own detail, e.g.
-- "red lighter"; it is NOT what any character necessarily perceives.
CREATE TABLE IF NOT EXISTS object (
    object_id    TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    description  TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS object_no_update
BEFORE UPDATE ON object
BEGIN SELECT RAISE(ABORT, 'object identity is immutable'); END;

CREATE TRIGGER IF NOT EXISTS object_no_delete
BEFORE DELETE ON object
BEGIN SELECT RAISE(ABORT, 'object identity is append-only'); END;

-- MUTABLE present-day object state. An object is EITHER held by an inhabitant
-- OR lying at a point in the world -- never both, never neither.
--
-- The exclusivity is STRUCTURAL, not checked in Python:
--   * one row per object (PRIMARY KEY)  -> no two holders, no two positions
--   * exactly one of holder_id / x_cm   -> no "held and on the floor", and no
--                                          object with no state at all
--   * x_cm and y_cm both-or-neither     -> no half a position
--   * stowed_in only while held         -> you cannot pocket the floor
--
-- `stowed_in` keeps its narrow v0.4 meaning: a label for having put the object
-- away on your person. It applies only to a HELD object, and PLACE clears it,
-- because an object lying on the ground is not in anyone's pocket.
CREATE TABLE IF NOT EXISTS object_location (
    object_id  TEXT PRIMARY KEY REFERENCES object(object_id),
    holder_id  TEXT REFERENCES being(being_id),
    stowed_in  TEXT,
    x_cm       INTEGER,
    y_cm       INTEGER,
    CHECK ((holder_id IS NOT NULL) + (x_cm IS NOT NULL) = 1),
    CHECK ((x_cm IS NULL) = (y_cm IS NULL)),
    CHECK (stowed_in IS NULL OR holder_id IS NOT NULL)
);

-- An offer that has reached its recipient and is awaiting their answer.
--
-- This is MUTABLE canonical state, deliberately: `outcome` moves PENDING ->
-- ACCEPTED/REFUSED exactly once, like projection_outbox rather than like the
-- append-only history. A PENDING row IS the unresolved interaction, so an
-- attempt survives a restart as world state rather than as in-memory workflow.
--
-- `outcome` and `resolved_seq` are the persisted HISTORICAL FACT of what
-- happened. Nothing anywhere re-derives whether an attempt succeeded by looking
-- at who holds the object today.
CREATE TABLE IF NOT EXISTS give_attempt (
    attempt_id    TEXT PRIMARY KEY,
    world_seq     INTEGER NOT NULL UNIQUE,   -- seq of its GIVE_ATTEMPT event
    actor_id      TEXT NOT NULL REFERENCES being(being_id),
    receiver_id   TEXT NOT NULL REFERENCES being(being_id),
    object_id     TEXT NOT NULL REFERENCES object(object_id),
    outcome       TEXT NOT NULL
                  CHECK (outcome IN ('PENDING', 'ACCEPTED', 'REFUSED')),
    resolved_seq  INTEGER,                   -- seq of the GIVE or REFUSAL event
    CHECK ((outcome = 'PENDING') = (resolved_seq IS NULL))
);

-- MUTABLE present-day world structure. Walls are visual information barriers,
-- not realistic physical objects: no thickness, material, doors or windows.
-- Zero-length walls are rejected rather than given invented semantics.
CREATE TABLE IF NOT EXISTS wall (
    wall_id  TEXT PRIMARY KEY,
    x1_cm    INTEGER NOT NULL,
    y1_cm    INTEGER NOT NULL,
    x2_cm    INTEGER NOT NULL,
    y2_cm    INTEGER NOT NULL,
    CHECK (x1_cm != x2_cm OR y1_cm != y2_cm)
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

-- IMMUTABLE event-time geometry snapshot: which walls existed, and where, when
-- the event happened. Written in the same transaction as the event.
--
-- wall_id deliberately has NO foreign key to `wall`: the wall may later be
-- demolished, and the historical record of it must survive that. This is the
-- same reasoning that keeps minds.db free of cross-database keys.
CREATE TABLE IF NOT EXISTS world_wall (
    event_id  TEXT NOT NULL REFERENCES world_event(event_id),
    wall_id   TEXT NOT NULL,
    x1_cm     INTEGER NOT NULL,
    y1_cm     INTEGER NOT NULL,
    x2_cm     INTEGER NOT NULL,
    y2_cm     INTEGER NOT NULL,
    PRIMARY KEY (event_id, wall_id)
);

CREATE TRIGGER IF NOT EXISTS world_wall_no_update
BEFORE UPDATE ON world_wall
BEGIN SELECT RAISE(ABORT, 'world_wall is immutable'); END;

CREATE TRIGGER IF NOT EXISTS world_wall_no_delete
BEFORE DELETE ON world_wall
BEGIN SELECT RAISE(ABORT, 'world_wall is append-only'); END;

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

-- IMMUTABLE arrival snapshot: WHERE an inhabitant ended up after a MOVE.
--
-- This is NOT world_pose. world_pose is the event-time snapshot and, for a
-- MOVE, deliberately records the DEPARTURE (see propose_move). Arrival sensing
-- needs the pose AFTER the transition, which no existing table holds, so it
-- gets its own row rather than a reinterpretation of an existing one.
--
-- One scan per successful MOVE: world_seq and event_id are the MOVE's own, so
-- an arrival is anchored to the canonical history that caused it and needs no
-- clock of its own. A scan row exists even when nothing was visible -- "Noah
-- arrived and saw nothing" is a historical fact, not an absence of one.
CREATE TABLE IF NOT EXISTS arrival_scan (
    scan_id    TEXT PRIMARY KEY,
    world_seq  INTEGER NOT NULL UNIQUE,
    event_id   TEXT NOT NULL UNIQUE REFERENCES world_event(event_id),
    being_id   TEXT NOT NULL REFERENCES being(being_id),
    x_cm       INTEGER NOT NULL,          -- ARRIVAL pose, not departure
    y_cm       INTEGER NOT NULL,
    facing_x   INTEGER NOT NULL,
    facing_y   INTEGER NOT NULL,
    CHECK (facing_x != 0 OR facing_y != 0)
);

CREATE TRIGGER IF NOT EXISTS arrival_scan_no_update
BEFORE UPDATE ON arrival_scan
BEGIN SELECT RAISE(ABORT, 'arrival_scan is immutable'); END;

CREATE TRIGGER IF NOT EXISTS arrival_scan_no_delete
BEFORE DELETE ON arrival_scan
BEGIN SELECT RAISE(ABORT, 'arrival_scan is append-only'); END;

-- IMMUTABLE record of one object seen during one arrival scan, at the fidelity
-- the geometry allowed. Absent row == that object was not visible from there.
--
-- `description` and `x_cm/y_cm` are SNAPSHOTTED, not looked up later. The
-- object may be picked up, moved, or carried away long before these rows are
-- projected into anyone's memory; what Ava saw is what was there when she
-- arrived. This is the same reasoning as world_pose and world_wall, applied to
-- present-state perception instead of event perception.
--
-- `sighting_id` is the perception's origin identity and is deliberately OPAQUE:
-- it embeds the scan and an index, never the object_id. A COARSE observer's
-- perception row carries this string, so an id built from object_id would leak
-- canonical identity through a structural column while the content stayed
-- clean.
CREATE TABLE IF NOT EXISTS arrival_sighting (
    sighting_id  TEXT PRIMARY KEY,
    scan_id      TEXT NOT NULL REFERENCES arrival_scan(scan_id),
    object_id    TEXT NOT NULL REFERENCES object(object_id),
    description  TEXT NOT NULL,           -- arrival-time canonical detail
    grade        TEXT NOT NULL CHECK (grade IN ('CLEAR', 'COARSE')),
    x_cm         INTEGER NOT NULL,        -- arrival-time position
    y_cm         INTEGER NOT NULL,
    UNIQUE (scan_id, object_id)
);

CREATE TRIGGER IF NOT EXISTS arrival_sighting_no_update
BEFORE UPDATE ON arrival_sighting
BEGIN SELECT RAISE(ABORT, 'arrival_sighting is immutable'); END;

CREATE TRIGGER IF NOT EXISTS arrival_sighting_no_delete
BEFORE DELETE ON arrival_sighting
BEGIN SELECT RAISE(ABORT, 'arrival_sighting is append-only'); END;

-- Mutable projection bookkeeping for arrival scans, kept OUT of arrival_scan
-- for exactly the reason projection_outbox is kept out of world_event: the
-- fact is immutable, the bookkeeping is not.
CREATE TABLE IF NOT EXISTS arrival_scan_outbox (
    scan_id    TEXT PRIMARY KEY REFERENCES arrival_scan(scan_id),
    world_seq  INTEGER NOT NULL UNIQUE,
    state      TEXT NOT NULL CHECK (state IN ('PENDING', 'DONE'))
);

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
-- One row per thing a character perceived. perceived_json holds the
-- ALREADY-REDUCED payload: information the character did not perceive is never
-- written here, rather than written and filtered at read time.
--
-- v0.8 -- TWO EPISTEMIC SOURCES, ONE HISTORY.
--
--   source='EVENT'  something HAPPENED while the character had physical access
--                   to it. origin_ref is the canonical event_id.
--   source='STATE'  something WAS ALREADY THERE when the character arrived and
--                   looked. origin_ref is an opaque arrival_sighting id.
--
-- They share one table and one perception_seq deliberately: a character has a
-- single remembered order, and "I saw Warren put something down" and "I can see
-- a red lighter lying there" are both memories in it. They are NOT collapsed
-- into each other -- `source` is what keeps them distinguishable, and neither
-- is ever derived from the other.
--
-- UNIQUE (character_id, origin_ref) is what makes retry idempotent, and it is
-- deliberately keyed on ORIGIN rather than on subject: two scans of the same
-- lighter are two different origins and therefore two different memories, while
-- a replay of one scan is the same origin and therefore the same memory.
CREATE TABLE IF NOT EXISTS perception (
    perception_id   TEXT PRIMARY KEY,
    character_id    TEXT NOT NULL,
    perception_seq  INTEGER NOT NULL,   -- per-character memory order
    kind            TEXT NOT NULL,
    grade           TEXT NOT NULL,
    perceived_json  TEXT NOT NULL,
    origin_ref      TEXT NOT NULL,      -- opaque canonical id; audit only
    source          TEXT NOT NULL DEFAULT 'EVENT'
                    CHECK (source IN ('EVENT', 'STATE')),
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
        _migrate_perception_source(conn)


def _migrate_perception_source(conn: sqlite3.Connection) -> None:
    """Give a pre-v0.8 perception store the `source` column it now needs.

    Every row such a store holds is event-derived BY CONSTRUCTION -- state
    observation did not exist before v0.8 and there was no code path that could
    have written one -- so 'EVENT' is a true statement about them, not a
    default chosen for convenience.

    HONEST LIMIT: ALTER TABLE ADD COLUMN cannot add the CHECK constraint, so a
    migrated store enforces the domain by the column default and the writing
    code only, where a store created fresh under v0.8 enforces it in the
    schema. Both reject the value at the point that matters -- the write -- but
    they are not equally strong, and a raw INSERT into a migrated store could
    write a third source value.
    """
    columns = {r[1] for r in conn.execute("PRAGMA table_info(perception)")}
    if "source" not in columns:
        conn.execute(
            "ALTER TABLE perception ADD COLUMN source TEXT NOT NULL "
            "DEFAULT 'EVENT'"
        )
