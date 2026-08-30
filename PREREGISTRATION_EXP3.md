# ONE WORLD — Experiment 3 preregistration

**Frozen 2026-08-30, before any model call.** Written against the world engine as it stands at
the parent commit of this file. Any change to a hash in §1 invalidates this preregistration.

---

## 1. Pinned artifact identity

| artifact | identity |
|---|---|
| world engine HEAD (parent of this commit) | `eb134f9` |
| `experiment/policy.py` (baseline agent) | blob `967c4087a2d9a62a693eec989cd64aa761d66049`, sha256 `3e4484df67b652a1a4703e0df68c489e7b203c717e7c25f0d2c2ab4ad1115a00`, committed at `4cb6493` (Experiment 1) |
| `PREREGISTRATION_EXP2.md` | blob `f071c8f2f84e67344fa6eee153820a3ee7403d42`, committed at `34be462` |
| `EXPERIMENT_2_REPORT.md` | the result this experiment takes as its baseline |
| cell matrix | `experiment/exp2.py::MATRIX`, unmodified |
| geometry constants | `one_world/sensing.py`: `VIEW_RANGE_CM = 1500`, `DETAIL_RANGE_CM = 300`, cone ±45°; `one_world/actions.py`: `INTERACTION_RANGE_CM = 80` |

The baseline policy was committed in Experiment 1, before the Experiment 2 predictions existed
and before this document existed. It is reused verbatim. It could not have been tuned to any
result here.

**Models, pinned by preflight on 2026-08-30:** `gpt-5`, `gpt-5-mini` (OpenAI), `gemini-2.5-flash`
(Google). Each returned a correct response to a one-word smoke call before this document was
frozen.

**Anthropic models are ABSENT from this run and the reason is recorded here rather than
discovered later:** `claude-sonnet-5` and `claude-opus-5` both returned HTTP 400,
`"Your credit balance is too low to access the Anthropic API"`, on the same preflight. This is
a billing state, not a capability finding, and **no inference about Claude may be drawn from
this experiment.**

## 2. Research question

Does a language model escape the stale-information fixed point that the pinned scripted policy
cannot — and is the answer determined by whether the environment returns the outcome of a
rejected action?

## 3. Why this is worth running

Experiment 2 established that in 8 of 14 cells an agent acting on a stale memory enters a fixed
point: it proposes an action, the action is rejected, and nothing it can perceive updates the
belief that produced the failure. The agent there was a scripted policy that reads only its
memory list. It is not entitled to conclude anything about agents that can reason.

Two things separate a language model from that policy. It can choose to turn or search rather
than re-propose. And it can, if the environment tells it, notice that its action failed. The
second is an **environment property, not a model property**: the same model is run against two
environments that differ only in whether the per-action outcome is returned.

**Asymmetry of value, stated before the run.** A finding that models escape where the policy
loops is modest on its own — it says a richer agent beats a trivial one, which is expected. The
informative result is the *interaction*: whether the escape depends on the feedback channel. If
the same model loops without feedback and escapes with it, the environment's observation
contract, not the model, decided the measured capability. If models escape in both conditions,
the feedback channel is not load-bearing here and the Experiment 2 fixed point is a fact about
the policy rather than about the world.

## 4. Design

**Frozen:** world engine, the 14 cells and their geometry, the two arms (`stale`, `fresh`), the
5-turn budget, the perception model, the setup scripts, the pinned baseline policy.

**Manipulated, two factors:**

| factor | levels |
|---|---|
| agent | `POLICY` (pinned Experiment-1 policy) · `LLM` |
| feedback | `OFF` (agent receives only its memory list, exactly as the policy does) · `ON` (agent additionally receives, for each action it proposed last turn, whether it was accepted and the rejection reason) |

`POLICY × ON` is run and is a **control**, not a condition of interest: the policy is a pure
function of the memory list and structurally cannot consume feedback, so it must loop
identically. If it does not, the harness is leaking.

**Action surface offered to the LLM.** `MOVE` (position and facing; a pure rotation is a legal
move), `LOOK` (changes no physical state), `TAKE` (by description). Identical vocabulary in both
feedback conditions. The LLM returns proposals in the same `(verb, params)` form the policy
returns; execution is unchanged and remains on the canonical side.

**Capability boundary, inherited unchanged.** The prompt is built only from
`CharacterHistory.recall(character_id)`. The agent module imports no canonical storage module,
receives no world handle, and is not told which character it is deciding for.

## 5. Cell classes, derived from a floor check run before this document was frozen

A "turn in place through the four cardinal facings" probe was scripted against each cell's
trap geometry to establish that an escape route exists at all. Result: **8 of 14 cells escapable
by rotation alone.** Six of those eight are cells the pinned policy already solves. That leaves:

| class | n | cells | pinned policy | escape route |
|---|---|---|---|---|
| **S** solvable | 6 | 0°/d=80, d=81, d=300; 45°/t=56, t=57, t=212 | SUCCESS | not needed |
| **T-near** trap, rotation suffices | 2 | 90°/d=100, 180°/d=100 | FIXED POINT | rotate in place; CLEAR at probe turn 2 and 3 |
| **T-far** trap, translation required | 6 | 0°/d=301, d=1000, d=1600; 45°/t=213; 90°/d=1000; 180°/d=1000 | FIXED POINT | must move to a new vantage; for the far cells this is blind search |

**T-near is the confirmatory cell class.** It is the only class where escape is both unavailable
to the policy and reachable within budget without blind search.

**T-far is exploratory and is marked as such.** No channel available to the agent carries the
object's new location, and blind 2D search within four remaining turns is not expected to
succeed. The measure of interest there is secondary and behavioural: does the agent recognise an
inescapable situation and abstain, or does it re-propose?

## 6. Per-cell predictions

Stale arm. `ESC(t)` = possession moves by turn t.

| class | POLICY/OFF | POLICY/ON | LLM/OFF | LLM/ON |
|---|---|---|---|---|
| S (6 cells) | SUCCESS, as Experiment 2 | SUCCESS, identical | SUCCESS | SUCCESS |
| T-near (2 cells) | FIXED POINT | FIXED POINT | **FIXED POINT** | **ESCAPE by turn 4** |
| T-far (6 cells) | FIXED POINT | FIXED POINT | FIXED POINT | FIXED POINT *(exploratory)* |

Fresh arm, all cells, all conditions: **SUCCESS at turn 1.** This is the solvability control.

**Derivation of the two load-bearing predictions.** Under `OFF` the LLM's input is a function of
its memory list alone, and in a T-near cell the memory list is byte-identical across turns
because a rejected action writes no perception. An agent whose entire input is unchanged has no
basis for changing its output, so absent sampling noise it re-proposes and loops. Under `ON` the
input changes at turn 2 (the rejection appears), the rejection reason names the failure, and the
floor check establishes a rotation reaches CLEAR within the remaining budget.

**Predicted baseline reproduction:** `POLICY/OFF` reproduces Experiment 2 exactly — 6 SUCCESS,
8 FIXED POINT, 14/14. **If it does not, the run is VOID and reports no verdict.**

## 7. Observations that would CONTRADICT the model

Numbered, because a surprise has to be recognisable as one.

1. Escape in any **T-far** cell. The geometry analysis says no channel carries the location;
   an escape means either a channel exists that was not modelled, or the agent reached state it
   should not have.
2. Any proposal naming a coordinate the agent was never told, in any condition.
3. `POLICY/OFF` failing to reproduce Experiment 2's 14/14.
4. `POLICY/ON` differing from `POLICY/OFF` in any cell. The policy cannot consume feedback; a
   difference is a harness leak.
5. Success in a cell where the object was never within `INTERACTION_RANGE_CM` of any pose the
   agent actually occupied.
6. A character's history changing after a **rejected** action. Rejections must write no
   perception.
7. Escape under `OFF` at a rate materially above `ON`. That inverts the mechanism and would mean
   the feedback channel is harmful rather than load-bearing.

## 8. Negative controls

| # | detects | method | pre-committed expected value |
|---|---|---|---|
| NC1 | canonical peeking | agent module imports no canonical storage module and holds no world handle; prompt asserted to contain no canonical token (`world.db`, `object_location`, `sqlite3`, `WorldStore`, `lighter-1`) | 0 violations |
| NC2 | unsolvable substrate | fresh arm, every cell, every condition | SUCCESS at turn 1, 100% |
| NC3 | trivially-succeeding scorer | an **impossible cell**: object placed beyond `VIEW_RANGE_CM` and never brought within reach | 0 successes |
| NC4 | scorer reading self-report | a stub model whose prose asserts it has taken the lighter while it proposes nothing | recorded outcome = failure |
| NC5 | identity keying | agent is not passed a character id; the same prompt builder serves any character | prompt contains no character id |
| NC6 | cross-cell contamination | each cell and condition gets its own `world.db` and `minds.db` at a distinct asserted path | 0 shared paths |
| NC7 | feedback channel load-bearing on the wrong agent | `POLICY/ON` | identical to `POLICY/OFF` in all 14 cells |
| NC8 | malformed-response imputation | unparseable model output is recorded as malformed and proposes nothing; it is never imputed to intent | malformed counted separately, never scored as abstention |

Each control declares what it detects. Whether each **can go red** is a separate obligation:
NC2, NC3, NC4 and NC7 are positively paired by construction (a control that has only ever been
seen to pass is uncharacterised).

## 9. Authored values

Chosen by me, not measured, and never to be reported as measured costs:
`TURN_BUDGET = 5`; the 14 cells and their offsets (inherited from Experiment 2); the four
cardinal facings offered in the floor check; temperature 0 where the provider honours it;
`max_tokens = 1024`; 2 retries on transport error; 3 independent repeats per cell per condition
to expose sampling variance. Quantities derived from these (turn counts, escape turns) are
budget-relative and are not behavioural costs.

## 10. The strongest claim available under each outcome

**If T-near escapes under ON and loops under OFF, in at least two model families:**
> In this world, whether an agent escapes a stale-belief fixed point is determined by the
> environment's observation contract rather than by the agent's reasoning ability. The same
> model, same prompt, same budget and same world loops when the environment withholds the
> outcome of a rejected action and escapes when it returns it.

**If T-near escapes under both ON and OFF:**
> The Experiment 2 fixed point is a property of the pinned policy, not of the world. A reasoning
> agent escapes it without needing the environment to report failure.

**If T-near loops under both:**
> The fixed point survives replacing a trivial policy with a frontier language model. Escape
> requires an environment change, not a better agent.

**Not claimed under any outcome:** anything about Claude; anything about models not run;
anything about horizons beyond 5 turns; that coarse information is in general unactionable; that
these results transfer to a world with a different perception model. Scope is **this world ×
these models × this harness**, and the report must say so in those words.

## 11. Stopping condition

**Fires on confirmation as well as on failure.** If the T-near prediction holds across at least
two model families, the line is **CLOSED** and the default next action is to report it, not to
elaborate the design with more cells, more models or more turns. If every cell loops, the null
is reported at `0/N under this frame` with the frame named, and the line is **CLOSED**.

Elaboration requires a new question, not a better-powered version of this one.
