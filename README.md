# ONE WORLD

A persistent world inhabited by humans and AI characters.

> There is one reality, but nobody automatically sees all of it.

## Where to start

The world engine is documented below, milestone by milestone (v0.1 through v0.4). Three
experiments have been run in it. Each was preregistered in its own commit, before the run.

| | |
|---|---|
| **Experiment 1** | [`PREREGISTRATION.md`](PREREGISTRATION.md), [`EXPERIMENT_REPORT.md`](EXPERIMENT_REPORT.md). First inhabitant, history to action. Pins `experiment/policy.py`, which every later experiment reuses verbatim. |
| **Experiment 2** | [`PREREGISTRATION_EXP2.md`](PREREGISTRATION_EXP2.md), [`EXPERIMENT_2_REPORT.md`](EXPERIMENT_2_REPORT.md). The stale-information fixed point. 28 worlds, 14 cells by 2 arms. **14 of 14 cells matched prediction, all 8 controls passed.** Agent is the pinned scripted policy. |
| **Experiment 3** | [`PREREGISTRATION_EXP3.md`](PREREGISTRATION_EXP3.md), [`EXPERIMENT_3_REPORT.md`](EXPERIMENT_3_REPORT.md), [`DEVIATIONS_EXP3.md`](DEVIATIONS_EXP3.md). Language models in the same world. **Verdict: DISAGREEMENT.** |

**Experiment 3 in one paragraph.** The one manipulated variable is whether the environment returns
the outcome of a rejected action. Across three models and eighteen runs, no agent escaped the fixed
point when that outcome was withheld; with it returned, 6 of 18 escaped (Fisher p = 0.019). The
preregistered criterion required the effect to hold across two model families and **it did not**:
one model carries almost all of it and the second vendor's model never escaped. The supported claim
is that the observation contract was necessary and not sufficient. One preregistered falsifier
fired. Read [`DEVIATIONS_EXP3.md`](DEVIATIONS_EXP3.md) before the result: it records four apparatus
faults and one confound, two of which would independently have manufactured the predicted result.

**Chronology is checkable from git.** Each preregistration is a commit containing that file and
nothing else, made before the corresponding run. `experiment/policy.py` was committed at `4cb6493`
on 2026-08-13 and is byte-identical at HEAD, so it could not have been tuned to any later result.

**How results are checked.** Outcomes are read from canonical world state, never from an agent's
own account. Experiment 3's scorer reads `object_location`; the per-cell `world.db` and `minds.db`
are retained so any trace can be reconstructed independently.

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

## v0.7: objects exist in space

Until now every object was always in someone's hand — `object_location.holder_id`
was `NOT NULL`, so the world could not represent a lighter lying on a table.
v0.7 separates *existing* from *being possessed*.

An object is **either** held **or** lying at a point, never both and never
neither, and that is enforced by the schema rather than by Python:

```sql
CHECK ((holder_id IS NOT NULL) + (x_cm IS NOT NULL) = 1)   -- exactly one state
CHECK ((x_cm IS NULL) = (y_cm IS NULL))                    -- no half a position
CHECK (stowed_in IS NULL OR holder_id IS NOT NULL)         -- no pocketing the floor
```

Together with `PRIMARY KEY (object_id)` — one row, so no two holders and no two
positions — every contradictory state is rejected by SQLite itself.

**Two actions.** `propose_place(actor, object_id, x_cm, y_cm)` puts down
something you hold, at a point you can reach. `propose_pickup(actor, object_id)`
takes something lying in the world, if you are close enough to it. Reach is
derived from canonical poses and the object's own position — no caller asserts
that something is reachable.

```
INTERACTION_RANGE_CM = 80    inclusive at the radius, rejected one cm past it
```

Deliberately crude: one radius, no arm length, no reaching direction, no hand
pose, no height. Exact integer squared-distance, like every other threshold.

**Perception.** PLACE and PICKUP are visual events like any other. CLEAR gives
`{actor, object, at}`; COARSE gives `{actor, put_down}` or `{actor, picked_up}`
— neither what it was nor where. A wall between you and the table means you
never learn it happened at all.

**Accepted v0.7 limitations.** A placed object is a bare point: no tables,
surfaces, containers, rooms, or nesting; no dimensions, mass, gravity, or
collision, so two objects may occupy the same point and nothing ever falls.
Objects are perceived only through the PLACE and PICKUP *events* — there is no
continuous observation, so walking into a room does not tell you what is lying
in it. Nobody may refuse or contest a pickup; v0.5's consent covers GIVE only.

## v0.8: perceiving state that was already there

Through v0.7 perception was **event-only**. A character learned that a lighter
existed by witnessing the PLACE that put it down. If Warren dropped it yesterday
and Ava walked in today, Ava learned nothing — the lighter was canonically real
and epistemically invisible to her.

v0.8 adds the second source. There are now two ways to come to know something,
and neither is derived from the other:

```
source='EVENT'   "I saw Warren put something down."
source='STATE'   "I can see a red lighter lying there."
```

Both may be true; either may be true alone. Seeing the lighter now does **not**
retroactively mean Ava saw it being placed, and witnessing a PLACE does not
require the object to still be there.

**The trigger is a successful MOVE, and nothing else.** No clock, no tick, no
background sensing, no LOOK action. Standing still never rescans.

**The two halves of a move are perceived from opposite ends of it.** This is the
part that looks tidy to get wrong:

```
BEFORE state
   MOVE event ......... perceived by everyone, from the DEPARTURE snapshot
canonical pose transition
   arrival scan ....... perceived by the mover alone, from the ARRIVAL pose
```

v0.6's rule is untouched: observers still see the mover where they set off from.
The arrival scan needs the pose *after* the transition, which `world_pose` does
not hold and must not be asked to — so an arrival gets its own snapshot.

**What is sensed.** Placed objects only. Not held or stowed objects, not other
beings, not walls-as-memories, not rooms. Range, facing cone and occlusion are
the *same* `_visual_grade` used for events — one implementation, so the two
cannot drift into two different physics. CLEAR gives `{object, at}`; COARSE
gives `{object: "something"}`, with identity and position destroyed at write.

**Looking is not an event.** No LOOK is appended, and canonical history never
records "Ava saw a red lighter". That is her memory, not world truth. A scan
takes the MOVE's own `world_seq` rather than consuming one, so the canonical
event log stays dense.

**Crash consistency.** The MOVE transaction persists the arrival pose *and* each
sighting's grade, description and position. `load_scan` reads only those
immutable tables — never `object_location`, `wall`, or `being_pose` — so a scan
projected after a crash, after the lighter has been carried off and a wall built
across the sight line, still yields what Ava saw when she arrived.

**Identity and repetition.** A memory is keyed on the *observation*, never the
subject. Two arrivals are two sightings and become two memories; one arrival
replayed is one sighting and stays one memory. `UNIQUE (character_id,
origin_ref)` makes the duplicate inexpressible rather than merely avoided.
Sighting ids are opaque (`sig-000001-000`) precisely so a coarse observer's
`origin_ref` column cannot leak an object id that the content withheld.

**Accepted v0.8 limitations.** Observation is discrete and arrival-only: an
object placed in front of a standing character is not noticed until they next
move. Only placed objects are observable — no perceiving people, containers or
structure as persistent state. There is no object permanence, no belief
revision, no forgetting, no confidence, and no reconciliation between an old
sighting and a new one: if Ava saw the lighter at P1 and later at P2, she holds
two memories and the world never tells her they are the same lighter. A coarse
sighting yields no fuzzy position at all. Nothing models memory of where you
yourself left something — state sensing has no agency shortcut, so your own
pocket is as invisible as anyone else's.

*Migration asymmetry (technical debt).* A `minds.db` created fresh under v0.8
enforces `source IN ('EVENT','STATE')` with a SQLite CHECK. A pre-v0.8 store
migrated by `init_minds` gets the column and its `DEFAULT 'EVENT'`, but SQLite
cannot attach the equivalent CHECK through a simple `ALTER TABLE ADD COLUMN`,
so a migrated store has **weaker schema-level enforcement** than a fresh one. In
both cases every production write goes through the single perception writer,
which emits only `EVENT` or `STATE` — but that is code-level, not schema-level,
and a raw INSERT into a migrated store could write a third value. Rebuilding the
table to attach the constraint is deliberately deferred, not overlooked.

## v0.9: LOOK — observing without moving

v0.8's only trigger for state perception was a successful MOVE, so movement and
observation were the same act. Ava could stand still while Warren put a lighter
down in front of her and remain ignorant of it forever, unless she walked
somewhere. That was the largest artificial feature left in the epistemic model.

**LOOK** is the smallest intentional observation action:

```python
propose_look(world, actor="ava", presence=..., location=..., occurred_at=...)
```

Preconditions are only that the actor exists and is placed. There is no
NO_CHANGE rule — looking twice at an unchanged world is two real experiences,
and the world does not rule that the second was pointless.

**LOOK changes no physical state.** Not by convention: `propose_look` holds no
pose primitive and no object primitive, so there is nothing in it that could
move anything. Facing is taken as it already is. An inhabitant who wants to
inspect another direction rotates with a MOVE first — rotation is already
movement, and v0.9 does not fuse the two.

**Three things, kept apart.**

```
canonical LOOK event ..... "Ava looked."              world truth
observation scan ......... snapshotted from her pose  world truth
STATE sightings .......... "Ava saw a red lighter."   HER truth, never the world's
```

Canonical history records that she looked. It never records what she saw.

**LOOK is AGENCY-sensed.** The actor knows they looked; no bystander perceives
it. This world models no physical manifestation of looking beyond facing, and
facing changes are already MOVE — so rather than invent eye or head motion that
nothing else models, bystanders receive nothing. Conservative, and a real
limitation rather than a claim that looking is undetectable in principle.

**One scan mechanism, two triggers.** v0.9 did not build a parallel LOOK scan.
The v0.8 machinery was already trigger-agnostic — it reads `current_pose`,
meaning "wherever the observer is when the scan is taken" — so LOOK needed no
second copy of the sensing, snapshotting or recovery code. A `trigger` column
keeps the semantics distinct:

```
trigger='MOVE'   ARRIVAL observation, from the POST-MOVE pose
trigger='LOOK'   INTENTIONAL observation, from the CURRENT pose
```

Both record the pose at scan time. Neither may come from `world_pose`: for a
MOVE that snapshot is the departure by design, and for a LOOK it is whatever
pose the actor held at some earlier event. The table is still called
`arrival_scan` — a historical name, kept deliberately rather than renamed across
the suite for tidiness.

Everything else is inherited unchanged: the same `_visual_grade`, so a LOOK and
an arrival from the same pose in the same world see exactly the same thing;
LOOK-time positions, descriptions and grades snapshotted so delayed recovery
cannot substitute today's world; identity keyed on the observation so repeated
looks are distinct memories while a replay is not; and one explicit
per-character order, with a LOOK event always remembered before what it
revealed.

**Accepted v0.9 limitations.** Observation is still discrete and deliberate:
there is no continuous sensing, no tick, no autonomous looking, and an object
placed in front of a standing character goes unnoticed until they choose to
look. LOOK sees only currently placed objects — no people, held objects,
containers or structure. Direction cannot be chosen independently of facing.
Nobody can perceive that someone else is looking, so there is no gaze, no
attention, and no being watched. There is still no object permanence, belief
revision or forgetting: two looks at one lighter are two unreconciled memories.

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

*(Scope note as written at the v0.1 milestone. Experiment 3 later added a language-model agent
under the same boundary: it receives only persisted perceptions and proposes actions, and it is
never the authority on what historically happened. See `experiment/agent_llm.py`.)*

No LLMs, Unreal, VR, mocap, voice, autonomous agents, vector databases, or
formal methods. An LLM may eventually interpret perceptions and propose
actions; it must never become the authority on what historically happened.
