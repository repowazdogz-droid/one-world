"""Run the preregistered trial and print the three records SEPARATELY.

  1. subjective evidence available to each inhabitant
  2. action selected from that evidence
  3. canonical validity/outcome of the attempted action

They are printed apart, and deliberately not merged, so that a rejected action
is never silently reinterpreted as proof of what the inhabitant believed.
"""

from __future__ import annotations

import json
import sys

from experiment.driver import Inhabitant
from experiment.runner import (
    A, B, DECISION, build_asymmetric, build_symmetric, execute,
)


def lighter_evidence(memories):
    """Every memory that carries a lighter coordinate, in order."""
    return [
        {"seq": m["seq"], "kind": m["kind"], "grade": m["grade"],
         "source": m["source"], "at": m["content"]["at"]}
        for m in memories
        if "at" in m.get("content", {})
        and m["content"].get("object") == "red lighter"
    ]


def run(d, build, label):
    world, wc, mc = build(d)
    driver = Inhabitant(mc)          # selection stage: minds connection only

    print(f"\n{'='*70}\n{label}\n{'='*70}")

    print("\n-- 0. objective situation at decision time (identical for both) --")
    loc = world.object_location("lighter-1")
    print(f"   lighter canonically at : ({loc['x_cm']}, {loc['y_cm']})")
    for who in ("ava", "noah"):
        print(f"   {who:5} pose             : {world.current_pose(who)}")
    print(f"   poses identical        : "
          f"{world.current_pose('ava') == world.current_pose('noah')}")

    print("\n-- 1. subjective evidence (each inhabitant's own history) --")
    evidence = {}
    for who in ("ava", "noah"):
        mem = driver.evidence(who)
        evidence[who] = mem
        print(f"   {who}: {len(mem)} memories; lighter coordinates held:")
        for e in lighter_evidence(mem):
            print(f"        seq={e['seq']} {e['kind']}/{e['source']}/{e['grade']}"
                  f" at={e['at']}")
        if not lighter_evidence(mem):
            print("        (none)")

    print("\n-- 2. action SELECTED from that evidence (same policy object) --")
    proposals = {}
    for who in ("ava", "noah"):
        p = driver.propose(who)
        proposals[who] = p
        print(f"   {who:5} -> {[(v, dict(q)) for v, q in p]}")
    same = proposals["ava"] == proposals["noah"]
    print(f"   proposals identical    : {same}")

    print("\n-- 3. canonical outcome of executing those choices --")
    outcomes = {}
    for who in ("ava", "noah"):
        outcomes[who] = execute(world, mc, who, proposals[who])
        for o in outcomes[who]:
            verdict = "ACCEPTED" if o["accepted"] else f"REJECTED ({o['reason']})"
            print(f"   {who:5} {o['verb']:5} -> {verdict}")
    print(f"   final pose ava={world.current_pose('ava')} "
          f"noah={world.current_pose('noah')}")
    holder = world.object_location("lighter-1")["holder_id"]
    print(f"   lighter holder now     : {holder}")

    return {"evidence": {k: lighter_evidence(v) for k, v in evidence.items()},
            "proposals": {k: [[v, dict(q)] for v, q in p]
                          for k, p in proposals.items()},
            "outcomes": outcomes, "identical": same}


def main():
    root = sys.argv[1]
    asym = run(f"{root}/asym", build_asymmetric,
               "CONDITION 1 -- ASYMMETRIC (Ava holds A, Noah holds B)")
    sym = run(f"{root}/sym", build_symmetric,
              "CONDITION 2 -- CONTROL, SYMMETRIC (both hold B)")

    print(f"\n{'='*70}\nSUMMARY\n{'='*70}")
    print(f"  asymmetric evidence -> proposals differ : {not asym['identical']}")
    print(f"  symmetric  evidence -> proposals same   : {sym['identical']}")
    print(f"  A = {A}   B = {B}   decision pose = {DECISION}")
    with open(f"{root}/result.json", "w") as f:
        json.dump({"asymmetric": asym, "symmetric": sym}, f, indent=2, default=str)


main()
