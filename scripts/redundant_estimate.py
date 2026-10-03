"""Leg 1: agreement on `redundant`, using only steps labeled with the history list on screen.

Two strata among the 473 steps Opus judged: 102 steps where Opus and the first-pass hand
label disagreed (all re-seen), and 371 others (100 re-seen at random: 30 control + 70).
The random stratum is weighted up to stand for all 371. Run: uv run python scripts/redundant_estimate.py
"""

import json
import random
from pathlib import Path

from judgeman.schema import read_labels

L = Path("labels")
queue = json.loads((L / "review-queue.json").read_text())
disputed = {(k[0], k[1]) for k in queue["disputed"]}
sampled = {(k[0], k[1]) for k in queue["control"]}
sampled |= {(k[0], k[1]) for k in json.loads((L / "redundant-queue.json").read_text())}
human = {(x.trajectory_id, x.step): x.redundant for x in read_labels(L / "human.jsonl")}


def source(*files, name=None):
    rows = [x for f in files for x in read_labels(L / f)]
    rows = [x for x in rows if (x.source == "checks") == (name == "checks")]
    return {(x.trajectory_id, x.step): x.redundant for x in rows}


opus = source("judge-claude-opus-5.5.jsonl", "judge-claude-opus-5.5-deepseek.jsonl")
others = len(opus) - len(disputed)


def stats(pairs_d, pairs_s):
    w = others / len(pairs_s)
    cell = {(a, b): 0.0 for a in (True, False) for b in (True, False)}
    for a, b in pairs_d:
        cell[a, b] += 1
    for a, b in pairs_s:
        cell[a, b] += w
    n = sum(cell.values())
    pos, neg = cell[True, True] + cell[True, False], cell[False, True] + cell[False, False]
    po = (cell[True, True] + cell[False, False]) / n
    p_other = (cell[True, True] + cell[False, True]) / n
    pe = pos / n * p_other + neg / n * (1 - p_other)
    kappa = (po - pe) / (1 - pe) if pe < 1 else float("nan")
    return po, kappa, cell[True, True] / pos if pos else float("nan"), cell[False, False] / neg, pos / n


def report(name, other):
    d = [(human[k], other[k]) for k in sorted(disputed) if other.get(k) is not None]
    s = [(human[k], other[k]) for k in sorted(sampled) if other.get(k) is not None]
    po, kappa, tpr, tnr, rate = stats(d, s)
    rng = random.Random(0)
    boots = sorted(stats(rng.choices(d, k=len(d)), rng.choices(s, k=len(s)))[1] for _ in range(2000))
    lo, hi = boots[50], boots[1949]
    print(f"{name:28} agreement {po:.2f}  kappa {kappa:.2f} (95% CI {lo:.2f} to {hi:.2f})  "
          f"TPR {tpr:.2f}  TNR {tnr:.2f}  repeat rate {rate:.0%}")  # fmt: skip


print(f"{len(disputed)} disputed + {len(sampled)} random of {others} others")
report("claude-opus-5.5", opus)
report("gemini-3.5-flash-lite", source("judge-gemini-3.5-flash-lite.jsonl"))
report("checks", source("checks.jsonl", name="checks"))
