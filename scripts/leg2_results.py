"""Leg 2 tables: three judge tiers x three contexts, scored on the gold set and the injected set.

Gold comparisons use the 150-step subset every tier judged, weighted back to the 516 gold steps
(60 of 80 suspected repeats, 90 of 436 others). `redundant` uses the 90 strict-rule labels.
Run: uv run python scripts/leg2_results.py
"""

import json
from collections import defaultdict
from pathlib import Path

from judgeman.judge import CACHE_DIR, PROMPT_VERSION
from judgeman.schema import read_labels

L = Path("labels")
TIERS = ("opus", "gemini", "qwen", "qwen-fewshot", "qwen-kaggle-base", "qwen-ft", "qwen-kaggle-base2", "qwen-ft2")
CONTEXTS = ("last5", "history", "plan")
AXIS_OF = {"repeat": "redundant", "unverified": "unverified_completion"}

subset = json.loads((L / "leg2-subset.json").read_text())
weight = {}
for stratum in ("suspected_repeat", "random"):
    for k in subset[stratum]:
        weight[k[0], k[1]] = subset["pool"][stratum] / len(subset[stratum])
strict_n = defaultdict(int)
strict = {(x.trajectory_id, x.step): x.redundant for x in read_labels(L / "redundant-strict.jsonl")}
for k in strict:
    strict_n[weight[k]] += 1
# 45 of each stratum were relabeled, so the weights are pool / 45
strict_weight = {k: subset["pool"]["suspected_repeat" if weight[k] < 2 else "random"] / 45 for k in strict}
human = {(x.trajectory_id, x.step): x for x in read_labels(L / "human.jsonl")}
injected = read_labels(L / "injected.jsonl")


def judged(tier: str, context: str, kind: str) -> dict:
    path = L / "leg2" / f"{tier}-{context}-{kind}.jsonl"
    rows = read_labels(path) if path.exists() else []
    return {(x.trajectory_id, x.step): x for x in rows if x.source != "checks"}


def stats(pairs: list[tuple[bool, bool, float]]) -> dict | None:
    """Weighted agreement between gold (first) and a source (second)."""
    if not pairs:
        return None
    cell = defaultdict(float)
    for a, b, w in pairs:
        cell[a, b] += w
    n = sum(cell.values())
    pos, neg = cell[True, True] + cell[True, False], cell[False, True] + cell[False, False]
    po = (cell[True, True] + cell[False, False]) / n
    p_other = (cell[True, True] + cell[False, True]) / n
    pe = pos / n * p_other + neg / n * (1 - p_other)
    return {
        "n": len(pairs),
        "agreement": po,
        "kappa": (po - pe) / (1 - pe) if pe < 1 else None,
        "tpr": cell[True, True] / pos if pos else None,
        "tnr": cell[False, False] / neg if neg else None,
    }


def fmt(v) -> str:
    return "  -  " if v is None else f"{v:5.2f}"


def line(name: str, r: dict | None) -> None:
    if r is None:
        print(f"{name:26} (no results yet)")
        return
    print(f"{name:26} n={r['n']:3}  agree {fmt(r['agreement'])}  kappa {fmt(r['kappa'])}  "
          f"TPR {fmt(r['tpr'])}  TNR {fmt(r['tnr'])}")  # fmt: skip


print("== progress: not-wasted vs wasted, on the 150-step subset, weighted to all 516 steps")
print("   (yes = the step was wasted, so TPR is the share of wasted steps caught)")
for tier in TIERS:
    for context in CONTEXTS:
        rows = judged(tier, context, "gold")
        pairs = [(not human[k].progress, not rows[k].progress, w) for k, w in weight.items()
                 if k in rows and rows[k].progress is not None]  # fmt: skip
        line(f"{tier} / {context}", stats(pairs))

print("\n== redundant: 90 strict-rule labels, weighted (TPR = share of real repeats caught)")
for tier in TIERS:
    for context in CONTEXTS:
        rows = judged(tier, context, "gold")
        pairs = [(bool(strict[k]), bool(rows[k].redundant), strict_weight[k]) for k in strict
                 if k in rows and rows[k].redundant is not None]  # fmt: skip
        line(f"{tier} / {context}", stats(pairs))
checks = {(x.trajectory_id, x.step): x for x in read_labels(L / "checks.jsonl")}
line("checks", stats([(bool(strict[k]), bool(checks[k].redundant), strict_weight[k]) for k in strict
                      if k in checks and checks[k].redundant is not None]))  # fmt: skip

print("\n== injected mistakes: share caught, by kind")
kinds = sorted({g.flags[0] for g in injected})
print(f"{'':26}" + "".join(f"{k:>17}" for k in kinds))
check_inj = {(x.trajectory_id, x.step): x for x in read_labels(L / "checks-injected.jsonl")}
sources = {"checks": check_inj}
sources |= {f"{t} / {c}": judged(t, c, "injected") for t in TIERS for c in CONTEXTS}
for name, rows in sources.items():
    cells = []
    for kind in kinds:
        gold = [g for g in injected if g.flags[0] == kind and (g.trajectory_id, g.step) in rows]
        axis = AXIS_OF.get(kind.split("-")[0], "risky")
        hit = sum(bool(getattr(rows[g.trajectory_id, g.step], axis)) for g in gold)
        cells.append(f"{hit:>3}/{len(gold):<3} {hit / len(gold):4.0%}" if gold else "-")
    if any(c != "-" for c in cells):
        print(f"{name:26}" + "".join(f"{c:>17}" for c in cells))

print("\n== progress agreement by position in the run (150-step subset, unweighted)")
buckets = ((0, 9), (10, 19), (20, 29), (30, 999))
print(f"{'':26}" + "".join(f"{f'steps {a}-{b}' if b < 999 else f'steps {a}+':>14}" for a, b in buckets))
for tier in TIERS:
    for context in CONTEXTS:
        rows = judged(tier, context, "gold")
        cells = []
        for a, b in buckets:
            ks = [k for k in weight if k in rows and a <= k[1] <= b and rows[k].progress is not None]
            agree = sum(human[k].progress == rows[k].progress for k in ks)
            cells.append(f"{agree / len(ks):.2f} (n={len(ks)})" if ks else "-")
        if rows:
            print(f"{tier + ' / ' + context:26}" + "".join(f"{c:>14}" for c in cells))

print(f"\n== cost and speed per judge call (prompt version {PROMPT_VERSION}, from the cache)")
calls = defaultdict(list)
for f in CACHE_DIR.glob("*.json"):
    r = json.loads(f.read_text())
    if "seconds" in r:
        name = r["model"] + ("" if r.get("thinking", True) else " (no thinking)")
        name += " +fewshot" if r.get("fewshot") else ""
        calls[name, r["context"]].append(r)
for (model, context), rs in sorted(calls.items()):
    n = len(rs)
    tokens = sum(r["prompt_tokens"] or 0 for r in rs) / n
    secs = sorted(r["seconds"] for r in rs)
    print(f"{model:44} {context:8} {n:5} calls  ${1000 * sum(r['cost'] for r in rs) / n:6.2f} per 1k  "
          f"{tokens:6.0f} prompt tokens  median {secs[n // 2]:5.1f}s")  # fmt: skip
