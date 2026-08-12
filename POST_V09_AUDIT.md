# ONE WORLD — post-v0.9 milestone audit

Frozen at `41e00c058b24a6e3319c7427b0fffb21741a84dc`. 358 tests passing.

Reconstructed from committed code, tests, and decision rows D255–D268. Capability
claims below were established by running the code or reading the executed SQL,
not by matching names: where this audit says something cannot happen, it means a
probe was written and the thing did not happen.

> **CORRECTION — the [X1] finding has since been repaired.**
>
> This document is preserved as the record of the discovery and describes the
> tree at `41e00c0`. The authored-`presence` seam reported in §2 as **[X1]** was
> treated as a potential violation of the central information-boundary claim and
> closed immediately afterwards, in the commit this note ships with. `presence`
> was deleted from every production signature; eligibility for sensing is now
> derived from `being_pose` via `placed_beings()`.
>
> Two conclusions below are superseded by that repair, and both move in the same
> direction:
>
> - §5 called presence derivation "not a blocker … hardening, not a
>   prerequisite". It was done first anyway, because the audit's own §7 was
>   right that it could confound the experiment.
> - §7's caveat *"`presence` could contaminate the result"* no longer applies.
>   The recommendation in §6 is unchanged and now rests on firmer ground.
>
> Everything else in this document — the milestone reconstruction, the three
> experiments, the [C6] structural absence, and the recommendation — stands as
> written.

---

## 1. What v0.1–v0.9 collectively establish

| v | New capability | Invariant established | Strongest evidence | Accepted limitation | Depended on by |
|---|---|---|---|---|---|
| 0.1 | Two stores; character memory separate from world truth | Memory is written already-reduced; canonical history is append-only and explicitly ordered | `UnsafeCharacterHistory` negative control: 14 named checks flip when recall is served from canonical truth filtered by presence | Unprojectable event wedges the queue, by design | everything |
| 0.2 | Physical sensing derives grades | Event-time pose is snapshotted; perception is a function of that snapshot, never of present state | Grades are nowhere authored; `commit_event` has no `observations` parameter | Crude thresholds; audio is binary | 0.3–0.9 |
| 0.3 | Occlusion | Event-time geometry snapshotted and participates in sensing; later demolition cannot alter past perception | Two observers with identical distance/facing diverge on a wall alone | Walls block sight only, never movement or sound | 0.7–0.9 |
| 0.4 | Validated actions | State-changing events exist only via the action layer; state change and its history commit atomically | `commit_event` refuses all 8 guarded kinds; rejection leaves no row, no sequence number | `stow` is a label, not containment | 0.5–0.9 |
| 0.5 | Refusal | Possession changes only through an offer the receiver answers | `_transfer_holder` structurally requires a live PENDING attempt naming that receiver | Consent covers GIVE only | 0.7 |
| 0.6 | Movement | Pose changes only through MOVE; the event is sensed from the **departure** | Snapshot shows origin while `being_pose` shows destination | Discrete; no path, speed, or collision | 0.8, 0.9 |
| 0.7 | Objects in space | Exactly one location state, held **or** placed, enforced by schema | Six contradictory states are inexpressible in raw SQL | Bare points; no surfaces, gravity, or collision | 0.8, 0.9 |
| 0.8 | STATE perception on arrival | Present state generates observations independently of event perception; arrival-time snapshot governs delayed recovery | Crash → object removed and wall built → recovery still reproduces the arrival observation | Arrival-only; placed objects only | 0.9 |
| 0.9 | LOOK | Intentional observation is independent of movement; observing present state never implies witnessing the event that produced it | Stationary Noah blocked, wall removed, informed by LOOK alone with **zero MOVE events** | Discrete; facing-bound; no gaze perception | — |

**The collective achievement is one property, held under nine kinds of pressure:**
information reaches an inhabitant only through a physical mechanism that the
world derives, and never through the author, the payload, the recall API, or
present-day state. Sixteen source-level mutants (eight in v0.8, eight in v0.9)
were run against the unmodified suites; none survived.

---

## 2. Current architecture, and every information crossing

```
        author/harness
             │  presence, location, occurred_at, SPEECH payload   ← [X1][X2]
             ▼
   ┌──────── actions ────────┐   propose_{look,move,place,pickup,stow},
   │  validate against       │   attempt_give, respond_to_attempt
   │  canonical state        │
   └────────────┬────────────┘
                │ [C1] guarded: STATE_CHANGING_KINDS  (world.py:324)
                ▼
        canonical world state ────────────────────┐
        being_pose, object_location, wall         │
                │                                 │
    [C2] snapshot at event time                [C3] read at scan time
    world_pose, world_wall (world.py:367)      current_pose/placed_objects
                │                              (world.py:464,473)
                ▼                                 ▼
        sense_event (world.py:391)          sense_state (world.py:475)
                │        both via _visual_grade — one geometry
                ▼                                 ▼
        world_observation                   arrival_sighting (immutable)
                └──────────────┬──────────────────┘
                               │ [C4] project() reduces, THEN one INSERT
                               ▼        (perception.py:238)
                        minds.db perception
                               │ [C5] recall, stored bytes only
                               ▼        (minds.py:25)
                      individual histories
                               │
                              [C6]  ✗ NOTHING HERE
```

**Crossings, and what guards each:**

- **[C1] action → canonical.** Guarded. Eight kinds refuse direct append. Verified: `commit_event` raises for every one.
- **[C2] canonical → event sensing.** Snapshot-then-sense, same transaction. Past perception cannot be altered by later movement or demolition.
- **[C3] canonical → state sensing.** Reads present state at scan time, snapshots it immutably. `load_scan` reads *no* mutable table (2 statements, verified).
- **[C4] canonical → minds.** One `INSERT INTO perception (`, in one method, always downstream of `project()`. No unreduced write path exists.
- **[C5] minds → character.** Stored bytes only. `minds.py` names no canonical token and holds no canonical handle.
- **[C6] minds → action.** **Does not exist.** `recall_all` output goes to stdout and nowhere else. `actions.py` does not import `minds`. Nothing a character remembers can influence anything a character does.

### Two author-supplied inputs remain, and one of them is load-bearing

**[X1] `presence` is an authored gate upstream of all geometry.** Every action
takes `presence` as a parameter; it is never derived. `world.py:367` iterates
that list to write the `world_pose` rows that are the *sole* sensing input.

Probed directly:

```
Noah at (50,0) facing the event, 10 cm away, no walls, omitted from presence
  Ava  perceived: [('PLACE','CLEAR')]
  Noah perceived: []
  world_pose rows: ['ava','warren']
```

Noah is blinded by a list, not by physics. Every exact-integer threshold,
facing cone and occlusion test in the project sits *downstream* of this.

The suite does not probe it: 57 call sites pass `ALL_THREE`, the handful of
subsets exist only to exclude beings that have no pose yet, and **no test
asserts that presence must correspond to physical reality**. This is the
clearest instance in the codebase of a check that is comfortable because it is
never pointed at itself.

**[X2] SPEECH is the one authorable event kind** (not in `STATE_CHANGING_KINDS`),
and `utterance` is an opaque author-written string. What anyone says is asserted,
not derived from anything they know.

---

## 3. Three experiments the world can already run, that v0.1 could not

Each involves inhabitants holding genuinely different information. None is a
demonstration of a mechanic.

### E1 — Does the world punish acting on stale belief?

Ava observes the lighter at P1 and is then blinded (wall, or facing away). The
lighter moves to P2. Ava acts on P1: moves there, attempts PICKUP, and is
refused `OUT_OF_REACH`. **Question:** does the epistemic model have *consequences*,
or only contents? A world where wrong beliefs cost nothing has not modelled
knowledge, only bookkeeping.

Available because: v0.7 gives the object a real location, v0.8/0.9 give Ava a
belief with a timestamp, v0.4 gives a rejection that is causally derived.

### E2 — Does information asymmetry alone produce behavioural divergence?

Same policy, two inhabitants, different histories. Ava saw CLEAR; Noah saw
COARSE (`{"object": "something"}`) or nothing. Both run the *identical* decision
rule. Any difference in what they do is attributable to information alone,
because the policy is the same object.

Available because: v0.2/0.3 make the grade split physical, v0.8/0.9 make it
persistent and re-acquirable.

### E3 — Is testimony already distinguishable from observation?

Ava sees the lighter and tells Noah. Noah's history gains a SPEECH memory. The
audit finding here is that ONE WORLD **already** separates three epistemic
sources structurally, without new work:

| | kind | source |
|---|---|---|
| I watched it happen | `PLACE` | `EVENT` |
| I can see it there | `SIGHTING` | `STATE` |
| I was told | `SPEECH` | `EVENT` |

**Question:** can an inhabitant act differently on hearsay than on sight? The
machinery to *distinguish* them exists today. What is missing is only that
`utterance` is an opaque string.

---

## 4. Actual blockers

**Exactly one, and it is not a world mechanic.**

> **[C6] Nothing reads a character's history to decide what that character does.**

All three experiments need the same thing: an action chosen using *only*
information the character actually has. Today the only way to drive an
inhabitant is a script written by an author who can see everything. A
hand-written script that makes Ava walk to P1 does not establish that she acted
on her own stale belief — it establishes that the author knew about P1. The
finding would be staged, not measured.

This is the same argument the project already makes about `minds.py`: the value
is not that recall happens to return the right bytes, it is that recall *holds
no handle* through which it could return anything else. A decision procedure
constructed with only a minds connection is structurally incapable of cheating.

Per-experiment:

| | Blocking | Realism | Convenience | Cosmetic |
|---|---|---|---|---|
| E1 stale belief | history→action driver | — | presence helper | — |
| E2 divergence | history→action driver | — | presence helper | — |
| E3 testimony | history→action driver; structured utterance | speech partial-audibility | — | — |

E3's structured-utterance need is real but small, and it is the *only* item in
this audit that would touch the world schema. E1 and E2 need no world change at
all.

---

## 5. Non-blocking temptations

Tested one by one against the three experiments. **None is required next.**

| Candidate | Verdict | Why not |
|---|---|---|
| Perceive inhabitants as persistent state | Not required | E1–E3 need object information, not people-tracking. Wanted only if an experiment turns on "where is Noah", which none does. Genuine realism gap. |
| Memory reconciliation / belief state | **Actively harmful now** | E1's whole finding is that an *unreconciled* stale belief has a cost. Add reconciliation and you delete the experiment before running it. |
| Autonomous action selection | Required **as a harness, not a world capability** | This is [C6]. It belongs outside the authority boundary, exactly where the code has always said a model would sit. |
| Communication from private histories | Only for E3 | SPEECH exists with PUBLIC/DIRECTED radii. Needs structure in `utterance`, nothing else. |
| Attention / selective LOOK | Not required | v0.9 LOOK is already the discrete, chosen observation. Directional choice is a refinement of a thing that works. |
| Object permanence | Not required | E1 depends on its *absence*. |
| Authorization / ownership | Not required | v0.5 consent covers the only transfer path. |
| Continuous time | Not required | Every experiment is a finite ordered sequence. Ordering is explicit and already sufficient. |
| Richer physics | Not required | Bare points and exact integers are what make replay machine-independent. Adding mass or collision buys nothing here and costs determinism. |

**`presence` derivation ([X1]) deserves its own line.** It is not a blocker,
because a harness can adopt the convention "presence = every placed being" and
let geometry decide everything, which is what 57 of the existing call sites
already do in effect. It *is* a genuine soundness gap and a latent bypass: it is
the one remaining way to make someone ignorant without a physical reason. It
should be closed, but as hardening, not as a prerequisite.

---

## 6. Recommended next move

> ## B — Run the first inhabitant experiment on the existing world.
>
> **No v0.10 world capability. No refactor. No new mechanic.**

Concretely, the smallest thing that yields the most information:

1. An **inhabitant driver** constructed with a minds connection and the action
   API only — never a `WorldStore`, never a world path. Structurally tested the
   way `minds.py` is: no canonical import, no canonical handle, no parameter
   through which one could arrive.
2. One **deterministic policy** (no LLM), shared by both inhabitants, reading
   only `recall()`.
3. Run **E1 and E2**. Same policy, different histories, and see whether the
   world produces divergence and whether stale belief actually costs anything.

Why this rather than a mechanic: after nine milestones the world has never once
been asked to *do* anything. Every property established is a property of the
plumbing. The single largest unknown is not whether another mechanic can be
built correctly — the evidence says it can — but whether the machinery already
built produces anything worth watching. That is one experiment away, and no
amount of v0.10 makes it more answerable.

It is also the cheapest possible falsification of the whole project. If two
inhabitants running the same policy on genuinely different histories behave
identically, or diverge in ways nobody finds interesting, that is decisive
information — and it arrives before another mechanic is paid for.

**Deliberately excluded:** `presence` derivation (hardening, do it when a being
must credibly leave scope), structured utterances (only E3 needs them), the
`arrival_scan` naming debt (D268, accepted), the migrated-store CHECK asymmetry
(D267, accepted).

---

## 7. Strongest argument against this recommendation

**The falsification I could not fully dismiss:** E1's headline result is
available *today*, with no driver, in about twenty lines.

```
place at P1 → Ava LOOKs → move object to P2 → Ava moves to P1 → PICKUP → OUT_OF_REACH
```

That test would pass, and it demonstrates that a stale belief leads to a refused
action. If that is the finding, the driver is ceremony and the recommendation
collapses into "write one more test", which needs no milestone at all.

**The rebuttal, and its limit.** The hand-written version proves the *world*
rejects a badly-aimed pickup. It cannot prove Ava *believed* anything, because
the author chose P1 while knowing about P2. The finding "an inhabitant acted on
their own outdated knowledge and paid for it" requires that the choice
provably came from her history — which is a capability claim about the decision
procedure, not a behavioural claim about the world. Only the boundary
establishes it.

That rebuttal is sound but it is narrower than it first appears: it justifies
the *driver*, not any particular richness of policy. So the recommendation
should be read strictly — build the smallest possible driver that cannot cheat,
and resist the pull toward an interesting policy, because policy sophistication
is the one thing this experiment does not measure.

**Two further honest challenges:**

- *Same-policy divergence may be trivially guaranteed.* If the policy branches
  on a field that only CLEAR observations carry, divergence is arithmetic, not
  discovery. The experiment must state in advance what result would count as
  uninteresting.
- *`presence` could contaminate the result.* Until [X1] is closed, any observed
  asymmetry has a second possible cause: the harness's presence lists. The
  experiment must fix `presence = every placed being` and say so, or its
  divergence finding is confounded.

**What would change the recommendation.** If the intended research question is
about *populations* rather than individuals — reputation, coordination, or
whether misinformation spreads — then E3 is the real target, structured
utterances become blocking, and A is correct instead. That depends on a
statement of the research question this audit cannot derive from the code.

---

*No production code, tests, decisions, or commits were changed in producing this
audit.*
