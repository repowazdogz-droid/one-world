# ONE WORLD — Experiment 2: stale-information fixed point

Executed exactly as frozen. **All 14 cells matched prediction; all eight
controls passed.** No ONE WORLD mechanics were modified.

---

## OBSERVED

### Frozen preregistration identifiers

| | |
|---|---|
| Preregistration | `PREREGISTRATION_EXP2.md` |
| Commit | `34be462` (contains that file and nothing else, 308 insertions) |
| Blob | `f071c8f2f84e67344fa6eee153820a3ee7403d42` |
| HEAD at execution | `34be46292d6503ca8fd0896a110aec608f4bdf6c` |
| Pinned policy | `experiment/policy.py`, sha256 `3e4484df67b652a1a4703e0df68c489e7b203c717e7c25f0d2c2ab4ad1115a00`, blob `967c4087a2d9a62a693eec989cd64aa761d66049` (committed at `4cb6493`, Experiment 1) |

The policy predates the predictions and was verified unchanged before and after
execution, so it could not have been tuned to the result.

### The 14-cell prediction/result table

28 independently constructed worlds (14 cells × 2 arms), each with its own
`world.db` and `minds.db`.

| Cell | grade@A | Pred. stale | Obs. stale | Pred. fresh | Obs. fresh | Verdict |
|---|---|---|---|---|---|---|
| 0°/d=80 | CLEAR | SUCCESS t1 | SUCCESS t1 | SUCCESS t1 | SUCCESS t1 | MATCH |
| 0°/d=81 | CLEAR | SUCCESS t2 | SUCCESS t2 | SUCCESS t1 | SUCCESS t1 | MATCH |
| 0°/d=300 | CLEAR | SUCCESS t2 | SUCCESS t2 | SUCCESS t1 | SUCCESS t1 | MATCH |
| 0°/d=301 | COARSE | FIXED POINT | FIXED POINT (t2) | SUCCESS t1 | SUCCESS t1 | MATCH |
| 0°/d=1000 | COARSE | FIXED POINT | FIXED POINT (t2) | SUCCESS t1 | SUCCESS t1 | MATCH |
| 0°/d=1600 | none | FIXED POINT | FIXED POINT (t2) | SUCCESS t1 | SUCCESS t1 | MATCH |
| 45°/t=56 | CLEAR | SUCCESS t1 | SUCCESS t1 | SUCCESS t1 | SUCCESS t1 | MATCH |
| 45°/t=57 | CLEAR | SUCCESS t2 | SUCCESS t2 | SUCCESS t1 | SUCCESS t1 | MATCH |
| 45°/t=212 | CLEAR | SUCCESS t2 | SUCCESS t2 | SUCCESS t1 | SUCCESS t1 | MATCH |
| 45°/t=213 | COARSE | FIXED POINT | FIXED POINT (t2) | SUCCESS t1 | SUCCESS t1 | MATCH |
| 90°/d=100 | none | FIXED POINT | FIXED POINT (t2) | SUCCESS t1 | SUCCESS t1 | MATCH |
| 90°/d=1000 | none | FIXED POINT | FIXED POINT (t2) | SUCCESS t1 | SUCCESS t1 | MATCH |
| 180°/d=100 | none | FIXED POINT | FIXED POINT (t2) | SUCCESS t1 | SUCCESS t1 | MATCH |
| 180°/d=1000 | none | FIXED POINT | FIXED POINT (t2) | SUCCESS t1 | SUCCESS t1 | MATCH |

**14/14 matched. Zero disagreements.** In every trap cell the fixed point first
held at turn 2 and persisted to the turn-5 budget — verified turn by turn, not
assumed from the purity argument.

### Complete traces, one per distinct outcome class

Setup history is identical in shape across all stale cells: two of Ava's own
MOVE agency records and one CLEAR sighting of the lighter at A = (0,0).

#### Class 1 — SUCCESS turn 1, staleness masked by reach (`0°/d=80`)

```
TURN 1
  history_in (3): [0]MOVE/EVENT/CLEAR{actor:ava, from:[0,3000], to:[-100,0]}
                  [1]SIGHTING/STATE/CLEAR{at:[0,0], object:red lighter}
                  [2]MOVE/EVENT/CLEAR{actor:ava, from:[-100,0], to:[0,3000]}
  proposal      : MOVE to [0,0] facing [1,0] ; TAKE "red lighter"
  exec          : MOVE  -> ACCEPTED
                  TAKE  -> ACCEPTED
  new EVENT     : own MOVE; own PICKUP {at:[80,0], object:red lighter}
  new STATE     : CLEAR {at:[80,0], object:red lighter}
  history unchanged=False  events_appended=2  FIXED_POINT=False
RESULT: success=True turn=1
```

She went to the **wrong** place and succeeded anyway: the object lay within
`INTERACTION_RANGE_CM` of the remembered point, so staleness had no behavioural
expression at all.

#### Class 2 — escape via CLEAR arrival scan → SUCCESS turn 2 (`0°/d=300`)

```
TURN 1
  proposal   : MOVE to [0,0] ; TAKE
  exec       : MOVE -> ACCEPTED ; TAKE -> REJECTED OUT_OF_REACH
  new STATE  : CLEAR {at:[300,0], object:red lighter}     <- the escape channel
  history unchanged=False  events_appended=1
TURN 2
  history_in (5): ... [4]SIGHTING/STATE/CLEAR{at:[300,0], object:red lighter}
  proposal   : MOVE to [300,0] ; TAKE          <- proposal CHANGED
  exec       : MOVE -> ACCEPTED ; TAKE -> ACCEPTED
RESULT: success=True turn=2
```

#### Class 3 — FIXED POINT, COARSE received and inert (`0°/d=301`)

```
TURN 1
  proposal   : MOVE to [0,0] ; TAKE
  exec       : MOVE -> ACCEPTED ; TAKE -> REJECTED OUT_OF_REACH
  new STATE  : COARSE {object: "something"}    <- information DID arrive
  history unchanged=False  events_appended=1
TURN 2
  history_in (5): ... [4]SIGHTING/STATE/COARSE{object: something}
  proposal   : MOVE to [0,0] ; TAKE            <- IDENTICAL to turn 1
  exec       : MOVE -> REJECTED NO_CHANGE ; TAKE -> REJECTED OUT_OF_REACH
  new EVENT  : (none)     new STATE : (none)
  history unchanged=True  events_appended=0  FIXED_POINT=True
TURNS 3, 4, 5: byte-identical to turn 2. FIXED_POINT=True throughout.
RESULT: success=False  fixed_point=True  first_fixed_turn=2
```

#### Class 4 — FIXED POINT, nothing received, out of cone (`90°/d=100`)

```
TURN 1
  proposal   : MOVE to [0,0] ; TAKE
  exec       : MOVE -> ACCEPTED ; TAKE -> REJECTED OUT_OF_REACH
  new STATE  : (none)      <- inside detail range, but outside the cone
  history unchanged=False  events_appended=1
TURN 2..5: proposal identical; MOVE -> NO_CHANGE; TAKE -> OUT_OF_REACH;
           no new perceptions; history unchanged; FIXED_POINT=True
RESULT: success=False  fixed_point=True  first_fixed_turn=2
```

#### Class 5 — fresh baseline (`0°/d=300`, fresh arm)

```
TURN 1
  history_in (3): ... [1]SIGHTING/STATE/CLEAR{at:[300,0], object:red lighter}
  proposal   : MOVE to [300,0] ; TAKE
  exec       : MOVE -> ACCEPTED ; TAKE -> ACCEPTED
RESULT: success=True turn=1
```

### The three COARSE cells, in detail

| Cell | Turn-1 STATE perception | Class |
|---|---|---|
| 0°/d=301 | `COARSE {object: "something"}` | **B — received and retained; action unchanged** |
| 0°/d=1000 | `COARSE {object: "something"}` | **B** |
| 45°/t=213 | `COARSE {object: "something"}` | **B** |
| 0°/d=1600, 90°/d=100, 90°/d=1000, 180°/d=100, 180°/d=1000 | none | A — no new information |

**No cell fell into class C.** Class B is evidenced rather than assumed: in those
three cells the COARSE sighting is present in the turn-2 `history_in` (length 5,
containing `{object: "something"}`), and the turn-2 proposal is nevertheless
byte-identical to turn 1's.

### The eight controls

| # | Control | Result |
|---|---|---|
| 1 | canonical-state peeking | Selection holds no world handle; `TypeError` on a second connection; policy source names no canonical token |
| 2 | current-state substitution | Every trap cell proposed the **remembered** point `(0,0)`, never the object's current position |
| 3 | accidental policy differences | sha256 matches the pinned value; one policy object throughout, asserted by identity |
| 4 | identity-keyed behaviour | Histories drive the choice; policy has no `who` parameter |
| 5 | sequential-world contamination | 28 distinct world directories, all present; turn-0 canonical state equivalent across arms |
| 6 | unintended arrival-scan reacquisition | No CLEAR sighting appeared in any trap cell at any turn |
| 7 | bearing/facing confounding | 90°/d=100 and 180°/d=100 lie **inside** detail range and yield nothing, while 0°/d=81 escapes — distance cannot explain it, bearing can |
| 8 | rejected actions producing evidence | Every all-rejected turn left history byte-identical, 0 events appended, 0 new perceptions |

### Test commands and results

```
$ python3 -m pytest experiment/ -q
27 passed

$ python3 -m pytest tests/ -q
369 passed
```

Nothing failed.

---

## INFERRED

Only the accepted narrow claim:

> Under the pinned Experiment-1 policy, stale physically acquired information
> produces a stable behavioural fixed point in this world whenever the object's
> current position is not both within the facing cone and within CLEAR range of
> the remembered position. Where escape occurs, it occurs through a CLEAR state
> observation delivered by the arrival scan of the inhabitant's own move, and the
> escape boundary coincides with `DETAIL_RANGE_CM`. The composition behaved as
> inspection of the constituent mechanisms predicted.

### The three COARSE cells

The inhabitant **received and retained new information**, and that information
was **not actionable under the pinned policy**, because the reduced
representation contained neither the identity nor the coordinate the policy
requires.

**This must not be generalised into "coarse information is not actionable."** It
was not actionable *under this policy*. A different policy — one that treated
`{object: "something"}` as a cue to approach, or to look again — could in
principle act on exactly the same perception. What was demonstrated is a property
of the pairing, not of coarse information.

---

## EXPECTED / NOT DISCOVERED

Stated prominently, because a confirming result is easy to inflate after the
fact:

- **14/14 confirmation was predicted**, cell by cell, before execution.
- **The ~300 cm transition was known from the source beforehand.** It is
  `DETAIL_RANGE_CM`, read directly, and was written into the preregistration. It
  was **not discovered here**.
- **The fresh baseline was guaranteed by construction.** Its success carries no
  evidential weight; it exists only to show the task, policy, budget and world
  are jointly satisfiable.
- **No unexpected behaviour occurred.** No disagreement, no anomalous
  reacquisition, no control failure, no unexplained intermediate observation.
- **Turn counts and path lengths are authored, not measured behavioural costs.**
  The turn budget (5), the geometry, the observation posts and the decision pose
  were all chosen by the experimenter. No behavioural cost is claimed or implied.

The value of this experiment was always asymmetric: confirmation validates that
the composition holds no surprises, and that is a modest result.

---

## NOT ESTABLISHED

- **World × policy, not world alone.** Every finding is bounded to the pairing of
  this world with the pinned policy.
- **LOOK was unavailable to the policy by construction.** The pinned policy never
  proposes it, so the inhabitant had exactly one escape channel — the arrival
  scan of its own accepted move. A LOOK-capable policy has a channel this
  experiment did not test.
- **Persistence assumes decision-relevant external conditions remain fixed.** An
  unchanged history under a pure policy implies repeated behaviour *only while
  nothing else in the world changes*. Warren was idle by construction throughout
  the turn phase. Nothing here shows an inhabitant would remain stuck in a world
  where something else moved, spoke, or came into range.
- **No generalisation.** 14 cells, one policy, one hand-built geometry, one
  object. No rate, proportion or trend may be computed from this.
- **No intelligence, rationality or belief claim.** The policy is a hand-written
  lookup. A retained memory and a rejected action are records; they license no
  attribution of an internal state.
- **No autonomous belief revision.** Nothing here revises anything; the escape,
  where it occurred, was a new perception outranking an old one by sequence
  number.
- **No population result.** One inhabitant acts per world; no interaction,
  transmission or coordination was observed.

---

## CLOSURE

The preregistered stopping condition fired.

`PREREGISTRATION_EXP2.md` §0 stated in advance: *"If every cell matches
prediction, the default next action is to CLOSE this experimental line, not to
elaborate it."* All 14 cells matched and all eight controls passed.

> **This deterministic experimental line is CLOSED rather than elaborated.**

Adding cells, bearings, distances or policy variants to this design would
rearrange a deterministic system whose constants are readable from source, and
would produce further predicted confirmations at increasing cost.

**This does not mean ONE WORLD is finished, or that no further useful experiment
exists.** What is closed is this specific line — increasingly rearranged
deterministic single-inhabitant retrieval tests over known constants. Directions
this closure says nothing about include multi-inhabitant information transfer,
policies with channels the pinned one lacked, and the architectural questions
already recorded elsewhere.

---

*Nothing in this report claims more than the accepted narrow claim. The
preregistration and the pinned policy were verified unchanged before and after
execution.*
