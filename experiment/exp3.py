"""Experiment 3 harness. EXECUTION SIDE.

Implements exactly the design frozen in PREREGISTRATION_EXP3.md (commit 9bc2b68,
blob 334b6534a603438afcf298cc9601beb4dde0fe10).

Selection is either the pinned Experiment-1 policy or a language model; neither
can reach canonical state. This module builds worlds, executes proposals that
have already been chosen, and scores from `object_location` -- never from the
transcript and never from the model's own account of what it did.
"""

from __future__ import annotations

import json
import os
import sys

from one_world.actions import (
    propose_look, propose_move, propose_pickup,
)
from one_world.perception import PerceptionRouter
from one_world.scenario import ROOM
from experiment import agent_llm
from experiment.driver import Inhabitant
from experiment.exp2 import A, TURN_BUDGET, build, cells
from experiment.runner import DESCRIPTIONS

WHO = "ava"
TARGET_OBJECT = DESCRIPTIONS["red lighter"]

#: Cell classes, derived by the floor check and frozen in the preregistration.
S_CELLS = {"0deg/d=80", "0deg/d=81", "0deg/d=300",
           "45deg/t=56", "45deg/t=57", "45deg/t=212"}
T_NEAR = {"90deg/d=100", "180deg/d=100"}
T_FAR = {"0deg/d=301", "0deg/d=1000", "0deg/d=1600",
         "45deg/t=213", "90deg/d=1000", "180deg/d=1000"}


def holder(wc):
    """Canonical possession. THE SCORER. Reads world state, nothing else."""
    row = wc.execute(
        "SELECT holder_id FROM object_location WHERE object_id = ?",
        (TARGET_OBJECT,)).fetchone()
    return row[0] if row else None


def execute(world, verb, params, stamp):
    if verb == "MOVE":
        to, f = params.get("to"), params.get("facing")
        # Accept any 2-sequence. The pinned policy emits tuples and the model
        # emits JSON lists; requiring one of them silently disabled the other
        # (instrument defect found by the POLICY baseline, 2026-08-30).
        if not (isinstance(to, (list, tuple)) and len(to) == 2
                and isinstance(f, (list, tuple)) and len(f) == 2):
            return {"accepted": False, "reason": "MALFORMED_PARAMS"}
        r = propose_move(world, actor=WHO, to_x_cm=int(to[0]), to_y_cm=int(to[1]),
                         facing_x=int(f[0]), facing_y=int(f[1]),
                         location=ROOM, occurred_at=stamp)
    elif verb == "LOOK":
        r = propose_look(world, actor=WHO, location=ROOM, occurred_at=stamp)
    elif verb == "TAKE":
        r = propose_pickup(world, actor=WHO, object_id=TARGET_OBJECT,
                           location=ROOM, occurred_at=stamp)
    else:
        return {"accepted": False, "reason": "UNKNOWN_VERB"}
    return {"accepted": r.accepted, "reason": r.reason}


def run_cell(world, wc, mc, agent, model, feedback):
    """One cell, one condition. Returns the full trace."""
    drv = Inhabitant(mc)
    hist = drv.evidence(WHO)
    outcomes = [] if feedback else None
    turns, success_turn, fixed_turn, malformed = [], None, None, 0

    for t in range(1, TURN_BUDGET + 1):
        before = list(hist)
        ev_before = wc.execute("SELECT COUNT(*) FROM world_event").fetchone()[0]

        if agent == "POLICY":
            proposal, raw, status = drv.propose(WHO), "", "ok"
        else:
            proposal, _prompt, raw, status = agent_llm.propose(
                model, before, outcomes)
            if proposal is None:
                malformed += 1
                proposal = []

        results = []
        for i, (verb, params) in enumerate(proposal):
            r = execute(world, verb, dict(params), f"t{t}-{i}")
            results.append({"verb": verb, "params": params, **r})

        PerceptionRouter(world, mc).derive_pending()
        hist = drv.evidence(WHO)
        ev_after = wc.execute("SELECT COUNT(*) FROM world_event").fetchone()[0]

        # THE SCORER: canonical possession, not any claim in `raw`.
        if holder(wc) == WHO and success_turn is None:
            success_turn = t

        unchanged = (hist == before)
        appended = ev_after - ev_before
        is_fixed = unchanged and appended == 0 and success_turn is None
        if is_fixed and fixed_turn is None:
            fixed_turn = t

        turns.append({
            "turn": t, "status": status,
            "proposal": [[v, p] for v, p in proposal],
            "results": results,
            "raw": raw[:600],
            "history_unchanged": unchanged, "events_appended": appended,
            "fixed_point": is_fixed, "holder": holder(wc),
        })
        if feedback:
            outcomes = results
        if success_turn is not None:
            break

    return {"turns": turns, "success": success_turn is not None,
            "success_turn": success_turn,
            "fixed_point": fixed_turn is not None,
            "first_fixed_turn": fixed_turn, "malformed": malformed,
            "final_holder": holder(wc)}


def main():
    root, spec = sys.argv[1], sys.argv[2]
    agent, model, fb, reps = spec.split(":")
    feedback, reps = (fb == "ON"), int(reps)
    out = {}
    for bearing, offset, label in cells():
        key = f"{bearing}/{label}"
        out[key] = {"offset": list(offset),
                    "klass": ("S" if key in S_CELLS else
                              "T-near" if key in T_NEAR else "T-far")}
        for arm in ("stale", "fresh"):
            out[key][arm] = []
            for rep in range(reps):
                d = os.path.join(root, agent, model, fb, bearing,
                                 label.replace("=", ""), arm, f"r{rep}")
                assert not os.path.exists(d), f"cell path reused: {d}"  # NC6
                world, wc, mc = build(d, offset, arm)
                out[key][arm].append(run_cell(world, wc, mc, agent, model,
                                              feedback))
        done = sum(1 for r in out[key]["stale"] if r["success"])
        print(f"  {key:<16} {out[key]['klass']:<7} "
              f"stale success {done}/{reps}", flush=True)

    os.makedirs(root, exist_ok=True)
    p = os.path.join(root, f"exp3_{agent}_{model}_{fb}.json")
    with open(p, "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
