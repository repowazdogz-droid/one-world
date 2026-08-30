"""Experiment 3 report. Recomputes every number from committed run artefacts
with no model access. Wilson 95% intervals on rates.
"""
from __future__ import annotations

import glob
import json
import math
import os
import sys

from experiment.exp3 import S_CELLS, T_FAR, T_NEAR

ORDER = ["S", "T-near", "T-far"]


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def _logfact(n, _c={0: 0.0}):
    if n not in _c:
        v = _c[max(_c)]
        for i in range(max(_c) + 1, n + 1):
            v += math.log(i)
            _c[i] = v
    return _c[n]


def fisher(a, b, c, d):
    """Two-sided Fisher exact on [[a,b],[c,d]]."""
    n = a + b + c + d
    if n == 0:
        return 1.0

    def p_tab(a_):
        b_, c_, d_ = a + b - a_, a + c - a_, d - a + a_
        if min(b_, c_, d_) < 0:
            return 0.0
        return math.exp(_logfact(a + b) + _logfact(c + d) + _logfact(a + c)
                        + _logfact(b + d) - _logfact(n) - _logfact(a_)
                        - _logfact(b_) - _logfact(c_) - _logfact(d_))

    obs = p_tab(a)
    tot = 0.0
    for a_ in range(0, min(a + b, a + c) + 1):
        pt = p_tab(a_)
        if pt <= obs * (1 + 1e-9):
            tot += pt
    return min(1.0, tot)


def fmt(k, n):
    p, lo, hi = wilson(k, n)
    return f"{k}/{n} = {p:.3f} [{lo:.3f}, {hi:.3f}]"


def load(root):
    runs = {}
    for p in sorted(glob.glob(os.path.join(root, "exp3_*.json"))):
        base = os.path.basename(p)[len("exp3_"):-len(".json")]
        agent, model, fb = base.rsplit("_", 2)
        runs[(agent, model, fb)] = json.load(open(p))
    return runs


def klass(key):
    return "S" if key in S_CELLS else "T-near" if key in T_NEAR else "T-far"


def main():
    root = sys.argv[1]
    runs = load(root)
    print("# Experiment 3 — results\n")
    print(f"Conditions loaded: {len(runs)}\n")

    print("## 1. Escape rate by cell class (stale arm)\n")
    print("| condition | S | T-near | T-far |")
    print("|---|---|---|---|")
    table = {}
    for (agent, model, fb), d in sorted(runs.items()):
        cells = {c: [0, 0] for c in ORDER}
        for key, v in d.items():
            c = klass(key)
            for r in v["stale"]:
                cells[c][1] += 1
                cells[c][0] += bool(r["success"])
        table[(agent, model, fb)] = cells
        row = " | ".join(fmt(*cells[c]) for c in ORDER)
        print(f"| `{agent}/{model}/{fb}` | {row} |")

    print("\n## 2. T-near, cell by cell (the confirmatory class)\n")
    print("| condition | " + " | ".join(sorted(T_NEAR)) + " |")
    print("|---|" + "---|" * len(T_NEAR))
    for (agent, model, fb), d in sorted(runs.items()):
        cs = []
        for key in sorted(T_NEAR):
            rs = d[key]["stale"]
            k = sum(bool(r["success"]) for r in rs)
            ts = [r["success_turn"] for r in rs if r["success"]]
            cs.append(f"{k}/{len(rs)}" + (f" (t{min(ts)}-{max(ts)})" if ts else ""))
        print(f"| `{agent}/{model}/{fb}` | " + " | ".join(cs) + " |")

    print("\n## 3. Controls\n")
    print("| control | expected | observed |")
    print("|---|---|---|")
    for (agent, model, fb), d in sorted(runs.items()):
        fresh_k = sum(bool(r["success"]) for v in d.values() for r in v["fresh"])
        fresh_n = sum(len(v["fresh"]) for v in d.values())
        t1 = sum(1 for v in d.values() for r in v["fresh"]
                 if r["success"] and r["success_turn"] == 1)
        print(f"| NC2 solvability `{agent}/{model}/{fb}` | 100% at turn 1 | "
              f"{fmt(fresh_k, fresh_n)}, {t1} at turn 1 |")

    print("\n## 4. Instrument health\n")
    print("| condition | cell-runs | malformed turns | transport errors |")
    print("|---|---|---|---|")
    for (agent, model, fb), d in sorted(runs.items()):
        n = sum(len(v[a]) for v in d.values() for a in ("stale", "fresh"))
        mal = sum(r["malformed"] for v in d.values()
                  for a in ("stale", "fresh") for r in v[a])
        terr = sum(1 for v in d.values() for a in ("stale", "fresh")
                   for r in v[a] for t in r["turns"]
                   if t["status"].startswith("transport"))
        print(f"| `{agent}/{model}/{fb}` | {n} | {mal} | {terr} |")

    print("\n## 4b. Feedback channel: OFF vs ON within model, by cell class\n")
    print("| model | class | OFF | ON | difference | Fisher p |")
    print("|---|---|---|---|---|---|")
    models = sorted({m for (_a, m, _f) in table})
    for m in models:
        for c in ORDER:
            off = table.get(("LLM", m, "OFF"), {}).get(c)
            on = table.get(("LLM", m, "ON"), {}).get(c)
            if not off or not on:
                continue
            p_ = fisher(off[0], off[1] - off[0], on[0], on[1] - on[0])
            diff = on[0] / on[1] - off[0] / off[1] if off[1] and on[1] else 0
            print(f"| `{m}` | {c} | {fmt(*off)} | {fmt(*on)} | "
                  f"{diff:+.3f} | {p_:.4g} |")

    print("\n## 5. Falsifier 1 — any escape in T-far\n")
    hits = []
    for (agent, model, fb), d in sorted(runs.items()):
        for key in sorted(T_FAR):
            for i, r in enumerate(d[key]["stale"]):
                if r["success"]:
                    hits.append(f"{agent}/{model}/{fb} {key} rep{i} "
                                f"turn {r['success_turn']}")
    print(f"T-far escapes observed: **{len(hits)}** (predicted 0)")
    for h in hits:
        print(f"- {h}")


if __name__ == "__main__":
    main()
