"""Experiment 2 harness. EXECUTION SIDE.

Implements exactly the design frozen in PREREGISTRATION_EXP2.md (commit 34be462,
blob f071c8f2f84e67344fa6eee153820a3ee7403d42). Selection remains the pinned
Experiment-1 policy, unmodified; this module only builds worlds and runs turns.
"""

from __future__ import annotations

import json
import os
import sys

from one_world import schema
from one_world.actions import propose_move, propose_pickup, propose_place
from one_world.perception import PerceptionRouter
from one_world.scenario import ROOM, seed_world
from one_world.world import WorldStore

from experiment.driver import Inhabitant
from experiment.runner import DESCRIPTIONS

A = (0, 0)
D = (0, 3000, 1, 0)          # decision pose, >= 3000 cm from A and every B
OBS_A = (-100, 0, 1, 0)      # 100 cm from A, in cone, inside detail range
TURN_BUDGET = 5

#: bearing label -> list of (offset, cell label)
MATRIX = [
    ("0deg", [((80, 0), "d=80"), ((81, 0), "d=81"), ((300, 0), "d=300"),
              ((301, 0), "d=301"), ((1000, 0), "d=1000"), ((1600, 0), "d=1600")]),
    ("45deg", [((56, 56), "t=56"), ((57, 57), "t=57"),
               ((212, 212), "t=212"), ((213, 213), "t=213")]),
    ("90deg", [((0, 100), "d=100"), ((0, 1000), "d=1000")]),
    ("180deg", [((-100, 0), "d=100"), ((-1000, 0), "d=1000")]),
]


def cells():
    for bearing, offs in MATRIX:
        for offset, label in offs:
            yield bearing, offset, label


def _open(d):
    os.makedirs(d, exist_ok=True)
    wc = schema.open_world(os.path.join(d, "world.db"))
    schema.init_world(wc)
    mc = schema.open_minds(os.path.join(d, "minds.db"))
    schema.init_minds(mc)
    return WorldStore(wc), wc, mc


def _mv(world, actor, pose, at):
    r = propose_move(world, actor=actor, to_x_cm=pose[0], to_y_cm=pose[1],
                     facing_x=pose[2], facing_y=pose[3], location=ROOM,
                     occurred_at=at)
    assert r.accepted, f"setup MOVE rejected: {r.reason}"


def _place(world, x, y, at):
    r = propose_place(world, actor="warren", object_id="lighter-1", x_cm=x,
                      y_cm=y, location=ROOM, occurred_at=at)
    assert r.accepted, f"setup PLACE rejected: {r.reason}"


def _relocate(world, B, tag):
    """warren takes it from A and puts it at B. Ava is at D throughout."""
    r = propose_pickup(world, actor="warren", object_id="lighter-1",
                       location=ROOM, occurred_at=f"{tag}-pick")
    assert r.accepted, f"setup PICKUP rejected: {r.reason}"
    _mv(world, "warren", (B[0] - 50, B[1], 1, 0), f"{tag}-walk")
    _place(world, B[0], B[1], f"{tag}-place")


def build(d, B, arm):
    """Identical scripts; the ONLY difference is when Ava's trip happens."""
    world, wc, mc = _open(d)
    seed_world(world)
    world.seed_pose("warren", *A, 1, 0)
    world.seed_pose("ava", *D)                 # noah is NOT placed
    router = PerceptionRouter(world, mc)

    _place(world, A[0], A[1], "s1")
    if arm == "stale":
        _mv(world, "ava", OBS_A, "s2")         # CLEAR sighting of A
        _mv(world, "ava", D, "s3")
        _relocate(world, B, "s4")              # unperceived: Ava >= 3000 away
    else:
        _relocate(world, B, "s2")              # unperceived: Ava at D
        _mv(world, "ava", (B[0] - 100, B[1], 1, 0), "s3")   # CLEAR sighting of B
        _mv(world, "ava", D, "s4")
    router.derive_pending()
    return world, wc, mc


def run_turns(world, wc, mc, who="ava"):
    driver = Inhabitant(mc)
    hist = driver.evidence(who)
    turns = []
    success_turn = None
    fixed_turn = None

    for t in range(1, TURN_BUDGET + 1):
        before = list(hist)
        events_before = wc.execute(
            "SELECT COUNT(*) FROM world_event").fetchone()[0]
        proposal = driver.propose(who)

        results = []
        for i, (verb, params) in enumerate(proposal):
            stamp = f"turn{t}-{i}"
            if verb == "MOVE":
                to, f = params["to"], params["facing"]
                r = propose_move(world, actor=who, to_x_cm=to[0], to_y_cm=to[1],
                                 facing_x=f[0], facing_y=f[1], location=ROOM,
                                 occurred_at=stamp)
            elif verb == "TAKE":
                r = propose_pickup(world, actor=who,
                                   object_id=DESCRIPTIONS[params["description"]],
                                   location=ROOM, occurred_at=stamp)
            else:
                raise ValueError(verb)
            results.append({"verb": verb, "params": _plain(params),
                            "accepted": r.accepted, "reason": r.reason})
            if verb == "TAKE" and r.accepted and success_turn is None:
                success_turn = t

        PerceptionRouter(world, mc).derive_pending()
        hist = driver.evidence(who)
        events_after = wc.execute(
            "SELECT COUNT(*) FROM world_event").fetchone()[0]

        new = hist[len(before):]
        unchanged = (hist == before)
        appended = events_after - events_before
        is_fixed = (unchanged and appended == 0 and success_turn is None)
        if is_fixed and fixed_turn is None:
            fixed_turn = t

        turns.append({
            "turn": t,
            "history_in": [_mem(m) for m in before],
            "proposal": [[v, _plain(p)] for v, p in proposal],
            "results": results,
            "new_event_perceptions": [_mem(m) for m in new if m["source"] == "EVENT"],
            "new_state_perceptions": [_mem(m) for m in new if m["source"] == "STATE"],
            "history_unchanged": unchanged,
            "events_appended": appended,
            "fixed_point": is_fixed,
            "history_out": [_mem(m) for m in hist],
        })
        if success_turn is not None:
            break

    return {"turns": turns, "success": success_turn is not None,
            "success_turn": success_turn, "fixed_point": fixed_turn is not None,
            "first_fixed_turn": fixed_turn}


def _plain(p):
    return {k: (list(v) if isinstance(v, tuple) else v) for k, v in p.items()}


def _mem(m):
    return {"seq": m["seq"], "kind": m["kind"], "grade": m["grade"],
            "source": m["source"], "content": m["content"]}


def main():
    root = sys.argv[1]
    out = {}
    for bearing, offset, label in cells():
        key = f"{bearing}/{label}"
        out[key] = {"bearing": bearing, "offset": list(offset), "label": label}
        for arm in ("stale", "fresh"):
            d = os.path.join(root, bearing, label.replace("=", ""), arm)
            world, wc, mc = build(d, offset, arm)
            out[key][arm] = run_turns(world, wc, mc)
            out[key][arm]["db"] = d
    with open(os.path.join(root, "exp2.json"), "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"wrote {os.path.join(root, 'exp2.json')}  cells={len(out)}")


if __name__ == "__main__":
    main()
