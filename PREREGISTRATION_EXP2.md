# ONE WORLD — preregistration: Experiment 2

**Frozen before any Experiment 2 implementation or trial exists.** Written
against HEAD `4cb6493` (Experiment 1 closed). No ONE WORLD mechanics are
modified by this experiment.

---

## 0. Standing of this experiment, stated before running it

**A confirming result is EXPECTED and has limited evidential value.** The
transition at ~300 cm is readable from `DETAIL_RANGE_CM` in the source. This
experiment is not framed as a discovery of that constant, and a confirming
outcome must not later be presented as one.

What is actually under test is **composition**: whether five mechanisms
(rejection semantics, grade boundary, arrival scans, a pure history-only policy,
and the turn loop) behave together as inspection of each separately predicts.

The value is therefore **asymmetric**:

- **Confirmation** validates that the composition holds no surprises. Low value.
- **Disagreement** with any preregistered cell is potentially informative and
  **must be investigated before anything is changed**.

**If every cell matches prediction, the default next action is to CLOSE this
experimental line, not to elaborate it.**

---

## 1. Research question

Can stale physically acquired information produce a **stable behavioural fixed
point**, and under what existing sensing conditions can the inhabitant escape it?

---

## 2. The policy — pinned, not written for this experiment

Experiment 2 reuses the Experiment 1 policy **verbatim and unmodified**:

```
file    experiment/policy.py
sha256  3e4484df67b652a1a4703e0df68c489e7b203c717e7c25f0d2c2ab4ad1115a00
blob    967c4087a2d9a62a693eec989cd64aa761d66049   (committed at 4cb6493)
FACING  (1, 0)          TARGET_DESCRIPTION  "red lighter"
```

It predates these predictions and is committed, so it **cannot be tuned to the
result**. Any change to that hash invalidates this preregistration.

The policy selects the most recent memory satisfying **both** `"at" in content`
**and** `content["object"] == "red lighter"`, and proposes
`MOVE(to=that, facing=(1,0))` then `TAKE("red lighter")`. Otherwise it abstains.

### 2.1 Which channels the policy can and cannot act upon

Derived from source, and load-bearing for every prediction below:

| Channel | Content delivered | Policy can act? | Why |
|---|---|---|---|
| **CLEAR state observation** | `{object: "red lighter", at: [x,y]}` | **YES** | satisfies both predicates |
| **COARSE state observation** | `{object: "something"}` | **NO** | no `at`; identity destroyed, so the object predicate also fails |
| **LOOK** | would deliver as above | **UNREACHABLE** | the pinned policy never proposes LOOK |
| **MOVE-triggered arrival scan** | as CLEAR/COARSE above | **YES** | fires on every *accepted* MOVE; this is the only route by which a CLEAR observation can arrive |
| **Event perception** (PLACE/PICKUP CLEAR) | carries `at` + `object` | in principle YES | **inert by construction**: no canonical events occur during the turn phase, because Warren is idle after setup |

**Consequence:** the pinned policy has exactly **one** escape channel — a CLEAR
state observation delivered by the arrival scan of its own accepted MOVE. This
bounds the finding to (this world × this policy); it is not a claim about the
world alone.

---

## 3. World construction

One object (`lighter-1`, "red lighter"). Two beings placed: `warren` (who
relocates it) and `ava` (the experimental inhabitant). `noah` is not placed and
is therefore not in the world. Presence is derived from `placed_beings()`; no
authored presence list exists anywhere.

```
A = (0, 0)                      first position of the lighter
B = A + offset                  current position, varies by cell
D = (0, 3000)                   decision pose, facing (1,0)
obs_A = (-100, 0) facing (1,0)  100 cm from A, inside cone and detail range
obs_B = B + (-100, 0) facing (1,0)
```

`D` is ≥ 3000 cm from A and from every B in the matrix, i.e. **beyond
`VIEW_RANGE_CM` (1500)**, so nothing is perceptible from the decision pose.

**Both arms run the identical script with exactly two setup MOVEs for Ava,
ending at the identical decision pose.** The sole manipulation is *when* her
observation trip occurs relative to the relocation.

| | STALE arm | FRESH arm |
|---|---|---|
| 1 | warren PLACE lighter at A | warren PLACE lighter at A |
| 2 | ava MOVE → obs_A (**CLEAR sighting at A**) | warren PICKUP; MOVE; PLACE at B |
| 3 | ava MOVE → D | ava MOVE → obs_B (**CLEAR sighting at B**) |
| 4 | warren PICKUP; MOVE; PLACE at B (Ava ≥3000 away: perceives nothing) | ava MOVE → D |
| 5 | turns begin | turns begin |

**Independent worlds.** Every (cell × arm) is constructed in its own directory
with its own `world.db` and `minds.db`. Nothing is shared, so sequential
execution cannot contaminate the comparison — the flaw that produced the
order artifact in Experiment 1's control.

---

## 4. Turn protocol

Fixed budget: **5 turns**. Each turn:

1. policy reads the inhabitant's history and returns a proposal list;
2. the driver executes that list in order against canonical state;
3. perceptions are derived.

Recorded **every turn**: complete input history; selected proposal; canonical
execution result per action (accepted / rejection reason); any new EVENT
perception; any new STATE perception; resulting history.

Selection remains history-only. The driver never reports outcomes back to the
policy — it cannot, since a rejected action leaves no perception.

---

## 5. Operational definition of a behavioural fixed point

Defined **before execution**:

> A fixed point occurs at turn *t* iff, during turn *t*: the inhabitant's history
> at end-of-turn is byte-identical to its history at end-of-turn *t−1*; **and**
> no canonical `world_event` was appended; **and** the task has not succeeded.

Because the policy is a pure function of history, an unchanged history
necessarily yields an identical proposal on the following turn, so this state
**provably persists** for the remainder of the budget. The report will record the
first turn at which it holds, and verify persistence to turn 5 rather than
assuming it.

**Task success** = a `TAKE` proposal accepted by canonical state.

---

## 6. The matrix: distance × bearing

Bearing is explicit because facing/cone geometry is potentially causal: the
policy's fixed `FACING = (1,0)` means an arrival at A looks only into the +x
cone, so B's *bearing*, not merely its distance, can decide reacquisition.

All offsets are exact integers; boundary cells are chosen so the squared-distance
comparisons land exactly on `INTERACTION_RANGE_CM² = 6400` and
`DETAIL_RANGE_CM² = 90000`.

| Bearing | Offsets from A |
|---|---|
| 0° | `(80,0) (81,0) (300,0) (301,0) (1000,0) (1600,0)` |
| 45° | `(56,56) (57,57) (212,212) (213,213)` |
| 90° | `(0,100) (0,1000)` |
| 180° | `(-100,0) (-1000,0)` |

14 cells × 2 arms = 28 independent worlds.

---

## 7. Cell-by-cell predictions

Derived from `_visual_grade` and `INTERACTION_RANGE_CM` at observer = A, facing
(1,0), before any trial was run.

### STALE arm

| Bearing | Offset | dsq | grade at A | in reach | PREDICTION |
|---|---|---|---|---|---|
| 0° | (80,0) | 6400 | CLEAR | yes | **SUCCESS turn 1** (reach; staleness masked) |
| 0° | (81,0) | 6561 | CLEAR | no | **ESCAPE → SUCCESS turn 2** |
| 0° | (300,0) | 90000 | CLEAR | no | **ESCAPE → SUCCESS turn 2** |
| 0° | (301,0) | 90601 | COARSE | no | **FIXED POINT, no success** |
| 0° | (1000,0) | 1000000 | COARSE | no | **FIXED POINT, no success** |
| 0° | (1600,0) | 2560000 | none | no | **FIXED POINT, no success** |
| 45° | (56,56) | 6272 | CLEAR | yes | **SUCCESS turn 1** (reach) |
| 45° | (57,57) | 6498 | CLEAR | no | **ESCAPE → SUCCESS turn 2** |
| 45° | (212,212) | 89888 | CLEAR | no | **ESCAPE → SUCCESS turn 2** |
| 45° | (213,213) | 90738 | COARSE | no | **FIXED POINT, no success** |
| 90° | (0,100) | 10000 | none | no | **FIXED POINT, no success** |
| 90° | (0,1000) | 1000000 | none | no | **FIXED POINT, no success** |
| 180° | (-100,0) | 10000 | none | no | **FIXED POINT, no success** |
| 180° | (-1000,0) | 1000000 | none | no | **FIXED POINT, no success** |

Predicted fixed point, where it occurs, is first satisfied at **turn 2** in every
trap cell — including the COARSE cells, because the COARSE sighting arrives
during turn 1 and turn 2 then changes nothing.

### FRESH arm

**SUCCESS at turn 1 in all 14 cells.** This arm is a **baseline, not a finding**:
its success is guaranteed by construction and is reported only to demonstrate
that the task, policy, budget and world are jointly satisfiable.

### Summary predictions

- The escape boundary at 0° and 45° lies at `DETAIL_RANGE_CM` (300), **not** at
  `VIEW_RANGE_CM` (1500).
- At 90° and 180° no escape occurs at **any** distance, because the cone test
  precedes the range test.
- Below `INTERACTION_RANGE_CM` (80) staleness is masked: the inhabitant succeeds
  by accident, having gone to the wrong place closely enough.

---

## 8. Observations that would contradict the current model

Any of these is a **disagreement** and must be investigated before anything is
changed:

1. **Actionable recovery from information believed insufficient** — escape in any
   COARSE cell (`(301,0)`, `(1000,0)`, `(213,213)`). Would mean COARSE content is
   reaching the policy, or another channel is supplying a coordinate.
2. **Recovery through an unexpected channel** — escape in any 90°/180° cell.
   Would mean the cone is not governing the arrival scan, or the scan pose/facing
   is not what the source implies.
3. **Failure to recover where CLEAR should be available** — no escape in
   `(81,0)`, `(300,0)`, `(57,57)`, `(212,212)`. Would mean the arrival scan did
   not fire, the sighting did not reach history, or the policy predicate failed.
4. **History changing after a rejected action** — any turn in which every action
   was rejected yet the history differs. Would contradict the invariant that
   rejection is epistemically silent, which is load-bearing for the whole design.
5. **Transition at a distance other than 300** on the in-cone bearings.
6. **No fixed point in a trap cell** — proposals varying across turns 2–5.
   Would mean the policy is not a pure function of history, or something is
   changing history that this preregistration has not accounted for.
7. **Success in a trap cell within budget** by any route.

---

## 9. Negative controls, predefined

| # | Detects | Method |
|---|---|---|
| 1 | canonical-state peeking | structural: policy imports nothing; driver takes only a minds connection and holds no `WorldStore` (Experiment 1 boundary tests, re-run) |
| 2 | current-state substitution for stale history | a variant fed the lighter's current position must produce success everywhere and therefore differ from the observed stale arm |
| 3 | accidental policy differences | one policy object asserted by **identity** across all cells and both arms, plus the pinned sha256 |
| 4 | identity-keyed behaviour | history-swap: exchanging the two arms' histories must exchange the proposals |
| 5 | sequential-world contamination | each cell×arm has its own database files; assert distinct paths and equivalent turn-0 canonical state across arms |
| 6 | unintended arrival-scan reacquisition | every STATE perception is logged per turn; any CLEAR sighting appearing in a predicted-trap cell is a flagged anomaly, not a silent pass |
| 7 | bearing/facing confounding | the 90°/180° rows hold distance fixed against the 0° row and vary only bearing |
| 8 | rejected actions producing decision-relevant evidence | for every all-rejected turn, assert history is byte-identical before and after |

---

## 10. Authored values — must never be reported as discovered costs

The turn budget (5), the geometry (A, B offsets, D, observation posts), the path
lengths implied by those coordinates, and the number of setup actions are all
**chosen by me**. Turn counts and distances travelled are therefore **not**
measured behavioural costs and will not be reported as such. The only quantities
treated as outcomes are: success/failure within budget, the proposal sequence,
the occurrence and turn-index of a fixed point, and the escape mechanism.

---

## 11. Separate modelling finding — not an Experiment 2 result

Recorded here so it is not smuggled in later as an experimental outcome:

> ONE WORLD currently permits **verbatim SPEECH information over a range in which
> visual state information is degraded.** `SPEECH` has no COARSE projection and
> preserves `utterance` intact to `AUDIO_RANGE_CM["PUBLIC"] = 1000`, whereas a
> visual observation loses the coordinate and the object's identity beyond
> `DETAIL_RANGE_CM = 300`. Hearsay at 900 cm therefore carries strictly more
> actionable information than direct sight at 400 cm.

This is an **architectural/model finding derived from existing semantics**, not
an experimental result. It is established by inspection, is not tested by this
experiment, and no part of Experiment 2's outcome bears on it.

---

## 12. Strongest claim available under each outcome

**Under confirmation (expected):**

> Under the pinned Experiment-1 policy, stale physically acquired information
> produces a stable behavioural fixed point in this world whenever the object's
> current position is not both within the cone and within CLEAR range of the
> remembered position; where escape occurs, it occurs through a CLEAR state
> observation delivered by the arrival scan of the inhabitant's own move, and the
> escape boundary coincides with `DETAIL_RANGE_CM`. The composition of the five
> mechanisms behaves as inspection of each separately predicts.

Explicitly **not** claimed: that this measures a behavioural cost; that the
threshold was discovered; that the trap is a property of the world independent of
this policy; anything about intelligence, rationality, belief or generalisation.

**Under disagreement:**

> A specific, named composition of ONE WORLD's mechanisms behaves differently from
> what inspection of the individual mechanisms predicts, in cell X.

That is the informative outcome, and it would be investigated — and the cause
identified — **before any code is changed**.

---

*Frozen prior to implementation. Any deviation forced by the code will be
reported as a deviation, not folded back into this design.*
