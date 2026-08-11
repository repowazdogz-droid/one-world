# ONE WORLD — v0.1

A persistent world inhabited by humans and AI characters.

> There is one reality, but nobody automatically sees all of it.

The system keeps three things apart:

```
what actually happened   →   what each inhabitant perceived   →   what they can later recall
```

Headless, no dependencies beyond the Python standard library.

## The rule

Character memory derives **only** from persisted perceptions assigned to that
character. Characters never obtain memories by querying canonical events. The
canonical event may contain more than any single perception ever did.

```
  world engine
       │  commit_event(...)
       ▼
  world.db  ── canonical truth, append-only, immutable, explicit world_seq
       │      (+ projection_outbox: this event still owes perceptions)
       │
       │  read at derivation time only
       ▼
  PerceptionRouter ── the only component holding both stores
       │              project(kind, payload, grade) reduces the payload; fails closed
       ▼
  minds.db  ── per-character perceptions, already reduced, explicit perception_seq
       │
       ▼
  CharacterHistory.recall(character_id)
```

## What the two-database split is, and is not

It is an **architectural / capability boundary**, not OS confinement. Code
running as this user can open `world.db` if given or discovering the path.
What the split buys is that canonical access becomes a visible, greppable,
testable act rather than an ordinary `SELECT` away.

The invariant that is actually enforced and tested (`tests/test_structural.py`):
character-facing code receives only a perception-store connection; receives no
canonical connection or path; imports no canonical-storage module; and has no
helper that opens canonical storage.

## Reduce at write, not filter at read

The router constructs a **new, smaller payload** and stores only that. Noah's
row literally contains `{"giver":"warren","object":"something","receiver":"ava"}`.
The string `red lighter` is never written against Noah, so the acceptance test
can assert on raw stored bytes rather than on API output — a filtering API can
be bypassed by a future query; bytes that were never written cannot leak.

## Ordering

Explicit persistent sequences only, allocated from counter tables inside the
writing transaction: `world_event.world_seq` (global) and
`perception.perception_seq` (**per character**). Nothing relies on UUIDs,
rowid, timestamps, or insertion order. `occurred_at` is descriptive and never
used to sort. Character recall orders by `perception_seq`, never by a canonical
column — ordering by `world_seq` would mean reading canonical truth to order
character memory.

## Crash between the two stores

The stores cannot be committed atomically. `projection_outbox` is written in
the same transaction as the event, so a committed event can never exist without
a record that it still owes perceptions. After restart the router re-applies
pending work in `world_seq` order. Perceptions are keyed
`UNIQUE(character_id, origin_ref)`, so replaying a partially-applied event
neither duplicates rows nor burns a sequence number. Canonical events stay
immutable; only the outbox row mutates.

## v0.2: physical perception

v0.1 had an author hand `CLEAR` / `COARSE` to `commit_event`. That parameter is
gone. `commit_event` now snapshots everyone's pose into `world_pose` and derives
the grades with `sensing.sense_event`, in the same transaction.

**The model.** Positions are integer centimetres; facing is an integer direction
vector. Every predicate is exact integer arithmetic — no `sqrt`, `cos`, or
`atan2`, and no floating point anywhere. The 45° cone test works because
cos²(45°) = ½, so `dot > 0 and 2·dot² ≥ |v|²·|f|²`.

```
VISUAL   actor of the event            -> CLEAR   (self/agency, see below)
         observer standing on it       -> CLEAR   (no direction to test)
         beyond VIEW_RANGE_CM   1500   -> nothing
         outside the +-45 deg cone     -> nothing
         within DETAIL_RANGE_CM  300   -> CLEAR
         otherwise                     -> COARSE

AUDIO    speaker                       -> CLEAR
         within radius(mode)           -> CLEAR   PUBLIC 1000 / DIRECTED 150
         otherwise                     -> nothing
         binary: hearing never yields COARSE
```

Boundaries are explicit: range and cone edges are **inclusive**; exactly abeam
(90° off facing) is **exclusive**. Unknown event kinds and audio modes raise.

Two rules are worth stating plainly, because their names flatter them:

**Actor → CLEAR is self/agency knowledge, not vision.** An actor is taken to
know what they themselves just did. No geometry is consulted. It is not evidence
that the actor visually perceived their own action; it exists so the degenerate
case — an actor at zero distance from their own event, where facing means
nothing — has an explicit answer rather than an arithmetic accident.

**DIRECTED speech is just a shorter hearing radius.** It is not addressee-aware:
the model never consults who was being spoken to, and anyone inside the radius
hears the sentence exactly as the addressee does. It is not an acoustic model
either — no attenuation, volume, directivity, masking, or walls. Ava hears the
private line and Noah does not because of 100 cm versus 802 cm, and nothing
else.

**Historical perception.** `being_pose` is mutable present-day state.
`world_pose` is the immutable event-time snapshot, and it — never `being_pose` —
is what perception was derived from. Grades are computed once, at commit, and
stored in `world_observation`, so crash recovery replays a decision rather than
re-taking it. Walking closer after the fact cannot retroactively sharpen what
you remember.

**Occlusion is deferred, deliberately.** A wall would need its own event-time
snapshot discipline to stay consistent with everything else here, and the
acceptance scenario is fully determined by distance and orientation without it.
Adding it now would buy realism the milestone does not need at the cost of the
machinery the milestone is actually about.

## v0.3: occlusion — the world can block access to information

v0.2 let sight pass through solid matter. v0.3 adds walls: two inhabitants at
identical distance and orientation can now acquire different histories because
structure stood between one of them and the event.

**A wall** is a line segment in the same integer-centimetre plane. It is a
visual information barrier, nothing more — no thickness, material, doors,
windows, transparency, or sound occlusion.

**Occlusion semantics**, chosen rather than inherited:

> A wall occludes iff some point of the **closed** wall segment lies on the
> sight segment **excluding the sight segment's own two endpoints**.

Each half is deliberate. The *closed wall* means sight grazing a wall's endpoint
is blocked — a barrier should err toward withholding, never toward leaking,
which is the same instinct as fail-closed projection. The *open sight line*
means an observer standing on a wall is not blinded by it, and an event
happening on a wall is still visible: you are at the barrier, not behind it.
Blocking there would mean standing against a wall blinds you to everything.

Zero-length walls are rejected at `add_wall` and by a CHECK constraint, rather
than being given invented semantics. All predicates are exact integer
cross-products — still no floating point anywhere.

**Historical geometry.** `wall` is mutable present-day structure; `world_wall`
is the immutable per-event snapshot, written in the same transaction as the
event, exactly mirroring `being_pose` / `world_pose`. `world_wall.wall_id`
deliberately has no foreign key to `wall`, because a wall may be demolished and
the historical record of it must survive that. Demolishing a wall cannot
retroactively grant information about an earlier event, and building one cannot
retroactively remove it.

**Accepted v0.3 limitation.** `set_pose`, `add_wall` and `remove_wall` change
canonical present-day state *without themselves being events*. Nobody perceives
movement or construction; there is no history of who built what or who saw them
build it. v0.3 tests historical perception, not yet perception of change.

## Accepted v0.1 limitation: an unprojectable event wedges the queue

Projection fails closed. If `project()` raises for a committed event — an
unknown `(kind, grade)` pair, say — that event stays `PENDING` and every later
event stays queued behind it. Derivation stops rather than stepping over it.

This is deliberate, and it is the safe failure. The system will not silently
skip a piece of canonical history, will not invert perception order, and will
not guess at a reduction it has no rule for. The cost is that recovery does not
self-heal: a human has to add the missing projection rule or amend the
observation before the queue drains.

v0.1 has no dead-letter queue, no skip, no backoff, and no alerting. Nothing
notices the wedge automatically. That is out of scope here, not overlooked.

## Run it

```bash
python3 -m pytest tests/ -q

python3 -m one_world.scenario --dir /tmp/w --phase populate
python3 -m one_world.scenario --dir /tmp/w --phase recall     # separate process
python3 -m one_world.scenario --dir /tmp/w --phase recover
```

## Not in v0.1

No LLMs, Unreal, VR, mocap, voice, autonomous agents, vector databases, or
formal methods. An LLM may eventually interpret perceptions and propose
actions; it must never become the authority on what historically happened.
