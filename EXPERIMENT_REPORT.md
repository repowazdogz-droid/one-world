# ONE WORLD — experiment 1: history-to-action

Preregistered at commit `b6ce6b1`, blob `4f5c4719ce7fd55ce44120c0d070601b2df1f099`,
which contains `PREREGISTRATION.md` and nothing else. The implementation did not
exist in the working tree at that point. The ordering is verifiable from git
history alone.

World under test: `098c4a4` (the presence-seam repair). No canonical ONE WORLD
code was modified by this experiment.

**Research question.** Can two inhabitants facing the same current objective
situation choose different actions solely because their physically acquired
histories differ?

---

## OBSERVED

### Setup

`A = (-2000,0)`, `B = (2000,0)`, decision point `(0,0)`. Both A and B lie 2000 cm
from the decision point, beyond `VIEW_RANGE_CM` (1500), so nothing is
perceptible from there. Each observation post is 100 cm from its target, inside
`DETAIL_RANGE_CM` (300) and inside the 45° cone. No wall is used anywhere: the
asymmetry is produced by range alone.

At selection time both inhabitants stood at the **identical canonical pose**
`(0, 0, 1, 0)` — beings have no collision, so co-location is expressible and
removes position as a confound.

### Exact histories

Complete, not excerpted:

```
ava   seq=0 MOVE     EVENT CLEAR  {actor: ava,  from: [0, 3000],   to: [-2100, 0]}
      seq=1 SIGHTING STATE CLEAR  {object: red lighter, at: [-2000, 0]}
      seq=2 MOVE     EVENT CLEAR  {actor: ava,  from: [-2100, 0],  to: [0, 0]}

noah  seq=0 MOVE     EVENT CLEAR  {actor: noah, from: [0, -3000],  to: [2100, 0]}
      seq=1 SIGHTING STATE CLEAR  {object: red lighter, at: [2000, 0]}
      seq=2 MOVE     EVENT CLEAR  {actor: noah, from: [2100, 0],   to: [0, 0]}
```

The two histories are identical in length, kind, grade, source and order. They
differ in exactly one integer pair. Neither contains any memory of the lighter
being relocated.

Canonical `world_observation` for the relocation events:

```
evt-000003 PICKUP at A   observed by: warren
evt-000004 MOVE          observed by: warren
evt-000005 PLACE at B    observed by: warren
```

Derived from range by the sensing model. Since the presence repair there is no
`presence` parameter in the production path, so this gap cannot be an artifact
of an authored eligibility list.

### Exact selected actions

Selection ran on stored history only, through one policy object.

| Condition | Ava selected | Noah selected | Identical? |
|---|---|---|---|
| ASYMMETRIC | `MOVE to (-2000,0)`, `TAKE "red lighter"` | `MOVE to (2000,0)`, `TAKE "red lighter"` | **No** |
| SYMMETRIC (control) | `MOVE to (2000,0)`, `TAKE "red lighter"` | `MOVE to (2000,0)`, `TAKE "red lighter"` | **Yes** |

### Exact canonical outcomes — recorded separately from selection

| Condition | Ava | Noah |
|---|---|---|
| ASYMMETRIC | MOVE accepted; TAKE **rejected `OUT_OF_REACH`** | MOVE accepted; TAKE accepted |
| SYMMETRIC | MOVE accepted; TAKE accepted | MOVE accepted; TAKE **rejected `NOT_ON_THE_GROUND`** |

The symmetric rejection is an **execution-order artifact**: both selected the
same action, and the two were executed sequentially in one shared world, so Ava
took the lighter first and it was no longer on the ground for Noah. It has no
bearing on the selection result. A canonical rejection is recorded here strictly
as a physical consequence and is not evidence about any inhabitant's internal
state.

### Raw results

```
$ python3 -m experiment.trial <fresh-dir>
  asymmetric evidence -> proposals differ : True
  symmetric  evidence -> proposals same   : True

$ python3 -m pytest experiment/ -q
16 passed in 0.33s

$ python3 -m pytest tests/ -q
369 passed in 14.09s
```

Re-run in a fresh directory after acceptance produced byte-identical output.

### Control results

| Control | Outcome |
|---|---|
| Driver secretly reads canonical state | Peeking driver proposes B for Ava (honest: A); rejected structurally by the constructor boundary whatever answer it gives |
| Different policies for Ava and Noah | Detected — `Inhabitant.POLICY is last_known_position` asserted by object identity |
| Histories injected rather than sensed | Provenance audit resolves all 10 memory origins to real `world_event` / `arrival_sighting` rows; a forged row is caught as `[("ava","made-up")]` |
| Policy hard-coded by character identity | History-swap test: swapping the evidence swaps the choices; the policy has no `who` parameter |
| Current canonical state substituted for stale evidence | Divergence collapses — both would select B |

Boundary audit: `policy.py` imports nothing at all; `driver.py` imports only
`one_world.minds` and `experiment.policy`; `Inhabitant.__init__` takes
`minds_conn` only and raises `TypeError` if handed a second connection; public
surface is `POLICY`, `evidence`, `propose`. Canonical state is reachable only
from `runner.py`, the execution stage, which acts on already-chosen proposals.

---

## INFERRED

Under the frozen identical policy, the divergence in selected actions was caused
by the differing coordinate each inhabitant acquired through the world's
range-based sensing, after these competing explanations were controlled:
per-character policy (single object, asserted by identity), identity-keying (no
id reaches the policy; swap test), decision position (identical pose), differing
objective world (one world, one lighter), canonical peeking (structural
boundary), injected memories (provenance audit), and authored sensing
eligibility (no `presence` parameter exists).

**Strongest warranted claim, and no stronger:**

> Under one deterministic policy holding no canonical handle, two inhabitants
> standing at an identical canonical pose in an identical objective world
> selected different actions, and the sole difference between their inputs was a
> coordinate each acquired through the world's own range-based sensing.

The history-to-action mapping is deliberately trivial: a policy that returns the
last remembered coordinate will differ when the remembered coordinates differ.
This was stated in the preregistration before the run. What the trial tests is
that the end-to-end chain — geometry → sensing → stored history → action — is
connected and unbroken, and that no stage short-circuits to canonical state. It
is a validation of that chain, not a discovery of surprising behaviour.

---

## NOT ESTABLISHED

- **Intelligence.** The policy is a hand-written lookup.
- **Rationality.** No standard of good reasoning was defined or tested.
- **Belief.** Nothing here licenses attributing an internal state to an
  inhabitant. A stored memory and a rejected action are records, not evidence of
  what anyone held to be true.
- **Generalisation.** N = 2 inhabitants, one policy, one constructed world. No
  rate, frequency or proportion may be computed from this, and none is claimed.
- **Emergent behaviour.** Every step was scripted or deterministic.
- **Population effects.** Two inhabitants who never interact are not a
  population, and nothing about spread, coordination or influence was observed.

Also not established: theory of mind, autonomous agency, general
decision-making, or anything about language-model behaviour.

---

## Accepted limitations

- N = 2.
- One deterministic hand-written policy.
- One constructed world.
- No rate or generalisation claim.
- No intelligence, rationality, belief or theory-of-mind claim.
- The history-to-action mapping is deliberately trivial.
- The experiment validates an end-to-end causal chain rather than discovering
  surprising behaviour.
- Canonical execution outcomes are recorded separately from action selection and
  must not be read back into it.
- Sequential execution in the symmetric control causes an order artifact that
  does not bear on the selection result.
- Both inhabitants' location evidence came from v0.8 arrival scans (STATE
  source), so event-derived perception is not exercised as a decision input.
- Resolving a remembered description to a canonical `object_id` happens in the
  execution stage; it is identical for both inhabitants and therefore cannot
  contribute to divergence.
