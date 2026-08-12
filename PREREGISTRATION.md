# ONE WORLD — preregistration: first inhabitant experiment

**Frozen before the evidential trial was run.** Written against the world at
`098c4a4` (the presence-seam repair). Nothing in this document was edited after
observing the trial output.

---

## 1. Research question

Can two inhabitants facing the same current objective situation choose different
actions solely because their physically acquired histories differ?

## 2. Hypothesis

**H1.** Under one shared deterministic policy that reads only an inhabitant's own
stored `minds.db` history, Ava and Noah — standing at an identical canonical pose
with an identical action API and an identical objective world — will propose
*different* actions, and the difference will be attributable to the coordinate
each of them physically acquired through ONE WORLD's established sensing
boundary.

**H0 (what would refute it).** They propose the same action, or the difference
traces to something other than their histories.

## 3. Exact world setup

Distances in integer centimetres. Thresholds are the existing ones:
`VIEW_RANGE_CM = 1500`, `DETAIL_RANGE_CM = 300`, `INTERACTION_RANGE_CM = 80`.

```
        A = (-2000, 0)                (0,0)                B = (2000, 0)
        lighter first here          DECISION POINT        lighter ends here
                                   Ava and Noah both
                                   stand here, pose
                                   identical (0,0,1,0)

        ava start  (0,  3000) facing (0,-1)
        noah start (0, -3000) facing (0, 1)
        warren start (-2000, 0) facing (1,0)
```

Verified by arithmetic before freezing: A→decision 2000 and B→decision 2000 are
both **beyond** view range, so nothing is perceptible from the decision point;
Ava's observation post (-2100,0) is 100 from A and Noah's (2100,0) is 100 from B,
both **inside** detail range and inside the 45° cone; every other pairing in the
script exceeds 1500.

**Trial sequence** (ASYMMETRIC condition):

| # | Action | Intended perception |
|---|---|---|
| 1 | warren PLACE lighter at A | ava 3605 away, noah 3605 away: neither perceives |
| 2 | ava MOVE to (-2100,0) | arrival scan → **CLEAR sighting, lighter at A** |
| 3 | ava MOVE to (0,0) | arrival scan → nothing (2000 > 1500) |
| 4 | warren PICKUP at A | ava 2000 away: nothing |
| 5 | warren MOVE to (2050,0) | event at departure A; ava 2000: nothing |
| 6 | warren PLACE lighter at B | ava 2000, noah 3605: neither perceives |
| 7 | noah MOVE to (2100,0) | arrival scan → **CLEAR sighting, lighter at B** |
| 8 | noah MOVE to (0,0) | arrival scan → nothing |

At the decision point the lighter is canonically at **B**, and Ava's most recent
lighter coordinate is **A**. Her belief is stale; the world never told her.

**CONTROL condition (SYMMETRIC).** Identical policy, identical structure, but the
lighter is placed at B and *both* Ava and Noah make an observation trip to
(2100,0) / (2100,50) before returning to (0,0), so both hold **B**. Prediction:
identical proposals. This is the condition that distinguishes "history caused the
divergence" from "the policy behaves differently per character".

**No wall is used anywhere.** The asymmetry is produced by range alone, so the
unhistoried `add_wall` capability noted in D270 is not part of the causal chain.

## 4. Which histories are intended to differ, and why

| | Ava | Noah |
|---|---|---|
| Lighter coordinate held | A = (-2000, 0) | B = (2000, 0) |
| How acquired | v0.8 arrival scan on MOVE | v0.8 arrival scan on MOVE |
| Grade | CLEAR (100 cm ≤ 300) | CLEAR (100 cm ≤ 300) |
| Source | STATE | STATE |

The two histories differ in **content only**, not in kind, grade, source or
acquisition mechanism. The single cause is **range**: each inhabitant was within
detail range of the lighter at a different time, and beyond view range of every
event that would have corrected them.

Per **D270**, sensing eligibility is derived from `placed_beings()`. No authored
presence list exists anywhere in the production path, so the divergence cannot
arise from an author naming who was there. All three inhabitants are canonically
placed for every event in the script.

## 5. Policy — specified before its output was observed

One implementation, used for every inhabitant. It is deliberately trivial: the
experiment tests the causal chain, not the sophistication of the decision.

```
POLICY last_known_position(history) -> list of proposals

INPUT   history: the list returned by CharacterHistory.recall for ONE
        inhabitant. Each memory is {seq, kind, grade, source, content}.
        The policy receives NOTHING else. In particular it does not receive
        the character's id, its pose, or any canonical handle.

1. Scan memories in DESCENDING seq order.
2. Take the first memory M where BOTH:
       'at' in M.content
       M.content.get('object') == 'red lighter'
3. If there is no such M -> return []  (ABSTAIN)
4. Otherwise let P = M.content['at'] and return, in order:
       ("MOVE", {"to": P, "facing": (1, 0)})
       ("TAKE", {"description": "red lighter"})
```

The facing `(1,0)` is a fixed constant, identical for both, chosen before the
run. `TAKE` names a **description**, because that is all a history contains;
resolving a description to a canonical `object_id` happens in the execution
stage and is identical for both inhabitants (both remember "red lighter"), so it
cannot be a source of divergence.

## 6. Variables

- **Independent:** the content of the inhabitant's own stored history — the
  lighter coordinate they physically acquired. Manipulated only by where each
  inhabitant stood relative to the lighter.
- **Dependent (primary):** the proposal list returned by the policy, specifically
  `MOVE.to`.
- **Dependent (secondary, recorded separately):** the canonical accept/reject
  outcome of executing those proposals. This is *not* evidence of what the
  inhabitant believed.
- **Held fixed:** the policy implementation (one function object, asserted
  identical by identity); the action API; the decision pose (both at exactly
  `(0,0,1,0)` — beings have no collision, so this is expressible and removes
  position as a confound); the objective world at decision time (lighter at B for
  both); the `facing` constant; the world thresholds; the derived-presence rule.

## 7. Success criterion

All of the following, or the experiment does not support H1:

1. Ava's history contains a CLEAR lighter coordinate equal to A, and Noah's
   equal to B.
2. Both stand at the identical canonical pose at decision time.
3. The same policy object produces `MOVE.to == A` for Ava and `MOVE.to == B` for
   Noah.
4. The CONTROL condition, run with the same policy, produces **identical**
   proposals for both.
5. Swapping the two histories swaps the proposals (the policy is not keyed to
   identity).

## 8. Failure criterion

Any of: the histories do not differ as intended; the proposals do not differ; the
CONTROL condition also diverges (implying identity-dependence, not
history-dependence); the divergence survives replacing history with current
canonical state (implying the policy was not reading history at all); or the
selection stage is found to hold any canonical handle.

## 9. Competing explanations to be ruled out or admitted

| Explanation | How it is addressed |
|---|---|
| The policy differs per character | Single function object; policy never receives character id; history-swap test |
| An authored presence list caused the perception gap | Impossible since D270; no `presence` parameter exists |
| Their positions at decision time differ | Both placed at the identical pose `(0,0,1,0)` |
| The world was different for each at decision time | One world, one lighter, one canonical state; both act in the same world |
| The driver peeked at canonical state | Structural test: selection stage holds no `WorldStore`, imports nothing canonical |
| Histories were hand-injected rather than sensed | Provenance audit: every memory's `origin_ref` must resolve to a real `world_event` or `arrival_sighting` row |
| The divergence is arithmetic, not a finding | Admitted openly — see §10 |

## 10. What this experiment does NOT establish

It does **not** establish intelligence, rationality, realistic belief, theory of
mind, autonomous agency, general decision-making, LLM behaviour, or emergent
social behaviour.

It does not establish that the policy is a good one. The policy is deliberately
trivial, and the mapping from "remembered coordinate" to "action" is a
deterministic lookup. **The step from history to action is arithmetic; the claim
under test is about the whole chain — geometry → sensing → stored history →
action — and specifically that the world, not the author, populated the link that
differs.**

It is a paired observation with N = 2 inhabitants under one policy in one
hand-built world. It is a demonstration that the chain is connected and causal,
not a measurement of anything, and no rate, frequency or generalisation may be
computed from it.

It does not establish that a rejected action means the inhabitant "believed"
anything. Canonical outcomes are recorded strictly as physical consequences.

---

*Frozen prior to the trial. Any deviation forced by the code will be reported as
a deviation, not silently folded into the design.*
