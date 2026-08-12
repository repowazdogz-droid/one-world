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

## v0.4: actions — events must correspond to real state changes

Through v0.3 an event could assert almost anything. Nothing required that a red
lighter existed, that Warren held it, or that possession actually moved. History
was persistent and perceptually bounded, but not causally grounded.

**The action layer.** A caller proposes; the world engine decides.

```
propose_give(world, actor="warren", receiver="ava", object_id="lighter-1", ...)
  -> ActionResult(accepted=True, event_id="evt-000000")
  -> ActionResult(accepted=False, reason="NOT_POSSESSED")
```

`commit_event` now **refuses** `GIVE` and `STOW`. Those kinds assert that the
world changed, and only a validated action may establish that. The action layer
is the only way in, not a well-behaved caller beside an open door. `SPEECH`
changes no state and still goes through `commit_event`.

The payload is **generated from canonical state**, not supplied. A proposal
names `object_id`; the engine writes the object's own `description`. A caller
cannot describe an outcome into existence, which is the authority boundary a
language model would eventually sit outside of.

**Object model.** One row per object in `object_location`, so "held by two
beings at once" is not a state the schema can express. Possession moves on
GIVE; STOW sets a `stowed_in` label without changing the holder.

**Atomicity.** Validation, the state change, the event, the pose and wall
snapshots, sensing, the observations and the outbox row all commit in one
`world.db` transaction. A rejected proposal leaves nothing: no state change, no
event, no consumed sequence number, no snapshot, no observation, no outbox row,
and therefore no perception. A rejected proposal did not happen.

**History does not follow current state.** The payload is materialised at commit
into the immutable event. Giving the lighter onwards afterwards never rewrites
what the earlier event says.

**Accepted v0.4 limitations.** Every object is always held by someone — there is
no free-standing "on the floor" state, and no containers as first-class objects.
Retrieving something you stowed is not an event. There is no authorization model:
validation asks whether an action is *possible*, never whether it is *permitted*.

## v0.5: refusal — an inhabitant can say no

Through v0.4 the world asked only whether an action was *possible*. If Warren
held the lighter, `propose_give` moved it; Ava had no say. v0.5 puts a decision
in that gap.

```
attempt_give(world, actor="warren", receiver="ava", object_id="lighter-1")
  -> ActionResult(accepted=True, attempt_id="att-000000", outcome="PENDING")

respond_to_attempt(world, attempt_id="att-000000", responder="ava",
                   response="REFUSE")
  -> ActionResult(accepted=True, outcome="REFUSED")
```

**Refusal is part of reality.** On REFUSE the object does not move and no GIVE
event exists, but the GIVE_ATTEMPT and REFUSAL events do. "Warren tried to give
Ava the lighter" and "Warren gave Ava the lighter" are different truths and the
system never collapses one into the other.

**An unresolved offer is world state, not workflow.** A PENDING `give_attempt`
row survives a hard restart; a separate process can read the offer off disk and
answer it.

**The outcome is persisted, never re-derived.** `give_attempt.outcome` records
what happened at resolution. Nothing works out whether an offer succeeded by
looking at who holds the object today — which matters, because after a refusal,
an acceptance and a hand-back, current ownership matches the *refused* state.

**Impossible is not refused.** A causally invalid offer produces no event and no
attempt: it never reached anyone to be refused. Refusal exists only downstream
of a valid attempt.

**The response is supplied by the caller, and that is deliberate.** A perception
grade is a physical fact the world should derive; a decision is an inhabitant's
own act. The canonical fact recorded is only "Ava refused this attempt" — never
a reason. Unknown response verbs fail closed rather than being interpreted.

**Refusal is not optional.** There is no direct-transfer API. `_transfer_holder`
is the only primitive that writes `holder_id`, and it refuses to run without a
live attempt naming that object and that receiver, so possession cannot move
without an ACCEPT however the caller comes at it. `_set_stow` does not mention
`holder_id` at all. Initial seeding via `add_object` establishes a first holder
and is not a transfer.

**Accepted v0.5 limitations.** This is recipient agency for GIVE, not a general
authorization system: it establishes no rights, no ownership law, no coercion
resistance, and no consent for any other action class. There is no counter-offer,
no negotiation, no timeout or expiry for a PENDING offer, and no way to withdraw
one. Invalid responses leave no trace at all, so nobody can perceive a failed
attempt to answer. Refusal carries no reason and no model infers one. Raw SQL
remains outside the API boundary.

## v0.6: movement is world history

Objects could not change hands without a cause, but inhabitants could still
cross the room silently. Position decides what someone can see, hear and be
occluded from, so a pose change with no cause is a silent change to everyone's
future perception.

`set_pose` is gone. Two narrower primitives replace it:

```
seed_pose(...)   INSERT only -- initialization. Raises if already placed, so
                 seeding cannot be reused as a teleport API.
_move_pose(...)  UPDATE only -- cannot create a pose; the MOVE action is its
                 sole caller.
```

`propose_move(actor, to_x_cm, to_y_cm, facing_x, facing_y)` validates that the
actor exists and is placed, the facing vector is non-zero, and the destination
differs from the current pose. **A pure rotation is a real move**: orientation
already changes what someone will perceive next.

**Temporal semantics, chosen rather than left to statement order.** The MOVE
event happens **at the departure**. Its position is the FROM position, and the
event-time snapshot records the world immediately *before* the transition, so
observers perceive the mover where they set off. The pose updates only after
the event and its snapshots are written. This is the reverse of GIVE, and
deliberately: an object's location is not a sensing input, so a transfer may
move state first — but an actor's **pose is the sensing input**, and changing
it first would make the mover appear already arrived to everyone watching.

**Perception.** CLEAR gives `{actor, from, to, facing}`; COARSE gives only
`{actor, moved}`. Exact coordinates are canonical detail a distant observer did
not receive, so they are destroyed at write rather than stored and filtered.
The mover knows their own movement by agency, not vision.

**Accepted v0.6 limitations.** A move is discrete: no path, duration, speed,
collision, or reachability, so nothing prevents crossing a wall or covering a
kilometre in one action. Walls block sight, never movement. Coarse observers
learn *that* someone moved, with no direction or distance — there is no fuzzy
position estimate. Initialization is enforced by `seed_pose` being insert-only,
which is an API-level boundary, not a lifecycle state machine.

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
