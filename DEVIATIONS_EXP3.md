# Experiment 3 — deviations and instrument defects

Recorded against `PREREGISTRATION_EXP3.md` (commit `9bc2b68`, blob
`334b6534a603438afcf298cc9601beb4dde0fe10`). **Nothing here is folded back into the
registration.** All pinned hashes in §1 were verified unchanged before and after execution.

---

## D1 — Anthropic models absent from the run

**Frozen text.** §1 pins `gpt-5`, `gpt-5-mini`, `gemini-2.5-flash` and records that
`claude-sonnet-5` and `claude-opus-5` failed preflight with HTTP 400,
`"Your credit balance is too low to access the Anthropic API"`.

**Status: not a deviation.** This was known and written into the registration *before* the
freeze, precisely so it could not be discovered afterwards and explained away. It is repeated
here because it is the single most likely thing a reader will want scoped: **no inference about
Claude may be drawn from this experiment.** It is a billing state, not a capability finding.

---

## ID1 — Instrument defect: the executor silently disabled the baseline arm

**Found by:** the `POLICY/OFF` baseline gate, which returned **0/14 successes** where
Experiment 2 recorded 6. This tripped preregistered falsifier #3.

**Cause.** `experiment/exp3.py::execute` validated MOVE parameters with
`isinstance(to, list)`. The pinned Experiment-1 policy returns `to` and `facing` as **tuples**;
a language model returns JSON **lists**. Every policy MOVE was therefore rejected as
`MALFORMED_PARAMS`, while every model MOVE would have passed.

**Why it matters more than an ordinary bug.** The defect was invisible in the condition of
interest and fatal only in the control. Had the baseline gate not been run first, the
experiment would have compared a working model arm against a silently crippled policy arm and
produced a large, clean, entirely artefactual effect in the predicted direction.

**Fix, at the class level.** Accept any 2-sequence for both parameters. Re-exercised in both
directions: tuples and lists now execute; a string, a 1-element sequence and an unknown verb are
still refused (`experiment/test_exp3_controls.py`).

**Scope of what it touched.** One baseline run, discarded. No model call had been made when it
was found, so no result in this report inherits it.

**Verdict after fix:** `POLICY/OFF` reproduces Experiment 2 at **14/14 including success turns**,
and the solvability control reads 14/14 at turn 1.

---

## ID2 — Instrument defect: two negative controls were matching text, not properties

**Found by:** running the control suite before spending model budget. Two controls failed.

**Cause, NC1 (canonical peeking).** The control grepped the agent module's raw source for
canonical tokens. It matched (a) the module docstring, which lists the tokens in order to state
that it does *not* import them, and (b) the `FORBIDDEN` tuple, which is the guard itself. Both
are false positives. A regex hit is a lead, not a fact.

**Cause, NC5 (identity keying).** The control asserted the character name `"ava"` was absent
from the prompt by substring. It matched `"ava"` inside `"available"`.

**Fix, at the class level.** NC1 now parses the module's **AST** for actual import statements
and separately inspects the module namespace for any live database handle or any object
originating in `one_world`. That is strictly stronger than the text grep it replaces, because it
reports what the file *does* rather than what it *mentions*. NC5 now matches on word boundaries.

**Both are positively paired.** `test_nc1_positive_pair_the_import_check_can_go_red` builds a
module that genuinely imports `sqlite3` and `one_world` and asserts the check catches it;
`test_nc5_positive_pair_the_identity_check_can_go_red` asserts a prompt that does name a
character is caught. A control that has only ever been seen to pass is uncharacterised.

**Scope.** Controls only. No subject result was computed under the defective versions.

---

## Note on the publication of this repository

`one-world` was made public on 2026-08-30, before this experiment was run. The repository
history was **deliberately not squashed**, against the usual pre-publication default. Commits
`4cb6493` (the pinned policy) and `34be462` (the Experiment 2 registration) are cited by hash as
evidence that the policy predates the predictions it was tested against; squashing would have
destroyed exactly the provenance that makes Experiment 2 checkable by a stranger. The
Experiment 3 registration was likewise pushed as its own public commit, timestamped
`2026-08-30T08:07:54Z`, before any model call was made.

---

## PE1 — Prediction error: §6 over-generalised from an incomplete floor check

**Not a deviation and not an instrument defect. A wrong prediction, recorded as one.**

**Found by:** preregistered falsifier #1 firing — `0deg/d=301` escaped under `LLM/ON` where §6
predicted zero T-far escapes.

**Cause.** The §6 derivation argued a trapped agent loops because "the memory list is
byte-identical across turns because a rejected action writes no perception." That is true only
for cells where the perception grade at the remembered point is `None`. It is **false** for
cells graded `COARSE`: the arrival scan does write a perception, namely
`{"object": "something"}` — identity and position destroyed, presence retained.

The floor check in §5 probed **rotation in place only**. It therefore could not distinguish
cells that are informationally sealed from cells that deliver a degraded presence signal and are
escapable by translation. Post-hoc diagnostic (`grade` recomputed from
`one_world.geometry`, no results consulted):

| cell | grade at A facing (1,0) | CLEAR reachable by walking forward |
|---|---|---|
| 0deg/d=301 | COARSE | yes, at +50 cm |
| 0deg/d=1000 | COARSE | yes, at +800 cm |
| 45deg/t=213 | COARSE | no (needs diagonal travel) |
| 0deg/d=1600 | **None** | no |
| 90deg/d=1000 | **None** | no |
| 180deg/d=1000 | **None** | no |

**The substructure this reveals is marked POST-HOC and licenses no confirmatory claim.** Only
three T-far cells (d=1600, 90°/d=1000, 180°/d=1000) are informationally sealed. The other three
deliver a presence-without-location signal.

**Why the error is interesting rather than merely embarrassing.** At `0deg/d=301` the world was
not withholding the information that would break the loop. The **pinned policy** was discarding
it: its rule matches `content["object"] == "red lighter"`, and a COARSE sighting says
`"something"`. So Experiment 2's fixed point at that cell is a property of the policy's
matching rule, not of the world's perception model. That distinction is exactly what
Experiment 3 was built to draw, and it was drawn by a falsifier rather than by me.

**No cell was reclassified.** The frozen classes in §5 stand as written, and every result is
reported against them.
