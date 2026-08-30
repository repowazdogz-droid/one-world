# ONE WORLD — Experiment 3: does a language model escape the stale-information fixed point?

Executed 2026-08-30 against the design frozen in `PREREGISTRATION_EXP3.md`
(commit `9bc2b68`, blob `334b6534a603438afcf298cc9601beb4dde0fe10`, pushed public at
`2026-08-30T08:07:54Z`, **before any model call was made**).

**Verdict: DISAGREEMENT.** One preregistered falsifier fired, the confirmatory prediction was met
in one model family and not the other, and the frozen stopping condition's two-family bar was
**not** met. Every deviation, instrument defect and confound is in `DEVIATIONS_EXP3.md`.

---

## OBSERVED

### Frozen identifiers, verified unchanged before and after

| | |
|---|---|
| Preregistration | commit `9bc2b68`, blob `334b6534a603438afcf298cc9601beb4dde0fe10`, 1 file, 198 insertions |
| Pinned baseline policy | `experiment/policy.py`, sha256 `3e4484df67b652a1a4703e0df68c489e7b203c717e7c25f0d2c2ab4ad1115a00`, committed at `4cb6493` (Experiment 1) |
| Models | `gpt-5`, `gpt-5-mini` (OpenAI), `gemini-2.5-flash` (Google) |
| Absent | Anthropic models — API credit exhausted at preflight, recorded in §1 of the registration before the freeze. **No inference about Claude may be drawn from this run.** |
| Scale | 6 conditions × 14 cells × 2 arms × 3 repeats = **504 cell-runs** |

### Baseline gate

`POLICY/OFF` reproduces Experiment 2 at **14/14 cells including exact success turns** (6 SUCCESS,
8 FIXED POINT). `POLICY/ON` differs in **0 of 14** cells, as required — the pinned policy is a
pure function of its memory list and structurally cannot consume feedback (NC7).

### The confirmatory class: T-near, pooled over 3 models × 2 cells × 3 repeats

| measure | feedback OFF | feedback ON | Fisher p |
|---|---|---|---|
| **escaped** (canonical possession moved) | **0/18 = 0.000** [0.000, 0.176] | **6/18 = 0.333** [0.163, 0.563] | **0.019** |
| **ever oriented toward the object** | **0/18 = 0.000** [0.000, 0.176] | **8/18 = 0.444** [0.246, 0.663] | **0.0029** |

Per model, out of 6 runs each:

| model | OFF escaped | ON escaped | OFF oriented | ON oriented | Fisher p (escape) |
|---|---|---|---|---|---|
| `gpt-5` | 0/6 | **5/6** | 0/6 | 5/6 | **0.015** |
| `gpt-5-mini` | 0/6 | 1/6 | 0/6 | 1/6 | 1 |
| `gemini-2.5-flash` | 0/6 | 0/6 | 0/6 | **2/6** | 1 |

**Not one agent, of three models over eighteen runs, escaped when the environment withheld the
outcome of its rejected action.** With the outcome returned, one model escaped 5 of 6 times, one
escaped once, and one never escaped but began orienting toward the target where it previously
never had.

### All cell classes (stale arm)

| condition | S | T-near | T-far |
|---|---|---|---|
| `gemini-2.5-flash/OFF` | 6/18 = 0.333 | 0/6 | 0/18 |
| `gemini-2.5-flash/ON` | 12/18 = 0.667 | 0/6 | 0/18 |
| `gpt-5/OFF` | 17/18 = 0.944 | 0/6 | 0/18 |
| `gpt-5/ON` | 17/18 = 0.944 | **5/6 = 0.833** | 2/18 = 0.111 |
| `gpt-5-mini/OFF` | 13/18 = 0.722 | 0/6 | 0/18 |
| `gpt-5-mini/ON` | 18/18 = 1.000 | 1/6 = 0.167 | 1/18 = 0.056 |

Within-model feedback effect on S cells: `gpt-5-mini` 0.722 → 1.000 (p = 0.045),
`gemini` 0.333 → 0.667 (p = 0.094), `gpt-5` 0.944 → 0.944 (at ceiling, p = 1).

### The complete escape trace, verified from world state

`gpt-5-mini / ON / 180deg/d=100 / rep0`. Object truly at `(-100,0)`; agent remembers `(0,0)`;
reach is 80 cm.

```
t1  MOVE (0,0) facing (1,0) ACCEPTED ; TAKE REJECTED OUT_OF_REACH
t2  LOOK ACCEPTED                      (facing away; nothing acquired)
t3  TAKE REJECTED OUT_OF_REACH         history unchanged, 0 events -> FIXED POINT
t4  MOVE (10,0) facing (-1,0) ACCEPTED ; TAKE REJECTED OUT_OF_REACH
t5  MOVE (-100,0) ACCEPTED ; TAKE ACCEPTED        holder = ava
```

Verified in the perception store rather than inferred: `perception_seq 1` holds the stale
`SIGHTING/CLEAR {"at":[0,0]}`; the turn-4 reorientation emits `evt-000008`; `perception_seq 6`
holds `SIGHTING/CLEAR {"at":[-100,0]}` with `origin_ref sig-000008-000`; turn 5 consumes it;
`object_location.holder_id = 'ava'`. The corrective information existed only because the agent
turned, and the agent turned only because it was told its action had failed.

### Controls

| control | expected | observed |
|---|---|---|
| NC1 canonical peeking | 0 violations | 0 — AST import check plus namespace check, positively paired |
| NC2 solvability (fresh arm) | 100% at turn 1 | **42/42 = 1.000 in all six conditions** |
| NC3 impossible cell | 0 successes | 0 |
| NC4 scorer reads self-report | outcome = failure | failure; positively paired against a real TAKE |
| NC5 identity keying | no character id in prompt | 0, word-boundary matched, positively paired |
| NC6 cross-cell contamination | 0 shared paths | 0, asserted per cell |
| NC7 policy cannot consume feedback | identical in 14 cells | 0 cells differ |
| NC8 malformed never imputed | counted separately | 3 malformed turns, all `gemini/ON`, none scored as intent |

**Instrument health: 504 cell-runs, 0 transport errors, 3 malformed turns (0.6%).**

### Falsifier results

| # | falsifier | fired? |
|---|---|---|
| 1 | escape in any T-far cell | **YES — 3 escapes**, all at `0deg/d=301`, all under ON |
| 2 | proposal names a coordinate never told | no |
| 3 | baseline fails to reproduce 14/14 | no (after ID1 fixed) |
| 4 | `POLICY/ON` differs from `POLICY/OFF` | no |
| 5 | success where object never within reach | no |
| 6 | history changes after a rejected action | no |
| 7 | escape under OFF above ON | no (0/18 vs 6/18) |

All three T-far escapes are in the single cell my post-hoc diagnostic identified as reachable by
walking forward after a COARSE sighting (`DEVIATIONS_EXP3.md` PE1). That agreement is
**post-hoc and licenses no confirmatory claim.**

---

## EXPECTED / NOT DISCOVERED

Stated prominently, because a result this directional is easy to inflate afterwards.

- **The `OFF` fixed point is close to guaranteed by construction, not discovered.** A rejected
  action writes no perception, so in a sealed cell the agent's entire input is byte-identical
  turn to turn. An agent whose input does not change has no basis for changing its output. The
  0/18 confirms the mechanism operates as designed; it is not evidence that models are poor
  reasoners.
- **The T-far predictions were mostly readable from the geometry**, which is why falsifier 1
  firing in exactly one cell is informative and the other five reading zero is not.
- **`gpt-5` on S cells was at ceiling in both conditions** (0.944), so that row measures nothing
  about feedback.
- **The three cell classes were authored by me**, from a floor check that turned out to measure
  the wrong endpoint (ID3). The classes are not natural kinds.
- Turn budget, cell geometry, repeat count and the four cardinal facings are **authored values**.
  Escape turns are budget-relative and are not behavioural costs.

---

## NOT ESTABLISHED

- **The frozen stopping condition was NOT met.** It required the T-near effect to hold "across at
  least two model families". `gpt-5` and `gpt-5-mini` are one family; the second family,
  `gemini-2.5-flash`, escaped **0/6 even with feedback**. The pooled p = 0.019 is carried almost
  entirely by one model.
- **None of the three claims pre-written in §10 fits this result.** The outcome space I wrote did
  not contain what happened, which is itself a finding about the design and is recorded rather
  than resolved by picking the nearest one.
- **The comparison against the scripted policy is CONFOUNDED and licenses nothing** (CF1). The
  policy hardcodes `FACING = (1,0)`, which lies inside the perception cone for all six S cells
  and outside it for exactly the cells it fails. It is pre-aimed. Every number above is a
  **within-LLM** OFF-versus-ON contrast for this reason.
- **The T-near budget was too tight for the route the class was defined around** (ID3). The floor
  check scored CLEAR *perception*, but the task requires *possession*, and `DETAIL_RANGE_CM` is
  300 while `INTERACTION_RANGE_CM` is 80. Escape needs rotate → perceive → approach → take. Five
  of the six `gpt-5` escapes landed at turns 2–5 and the only `gpt-5-mini` escape at turn 5. The
  6/18 is therefore a **lower bound** under a budget with no margin, not a capability estimate.
- **"Feedback is necessary" is not established.** 0/18 is a null with a 95% interval of
  [0.000, 0.176]; the honest statement is that no escape was observed in 18 runs without
  feedback, not that none can occur.
- **Nothing about Claude.** No Anthropic model was run.
- **Scope is this world × these three models × this harness × a 5-turn budget.** It does not
  transfer to other perception models, other action vocabularies, or longer horizons. "Coarse
  information was not actionable under this policy" must not become "coarse information is not
  actionable".

---

## The claim this run supports, at the strength the evidence reaches

> In this world, the environment's observation contract was **necessary but not sufficient** for
> escaping a stale-belief fixed point. Across three models and eighteen runs, no agent escaped
> when the environment withheld the outcome of its rejected action. When the environment returned
> that outcome, escapes appeared (6/18, p = 0.019) and orientation toward the target appeared more
> often still (8/18, p = 0.0029) — but only one of the three models converted the channel into
> task success, and the second model family converted it into no successes at all.

The half that is about the environment is the stronger half: the same model, same prompt, same
budget, same world, differing only in whether one line of outcome text was returned, goes from
never escaping to escaping. The half that is about the models is where the effect stops being
uniform, and that is where this run stops.
