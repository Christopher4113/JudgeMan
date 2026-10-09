"""`judgeman calibrate`: how far to trust each judge layer on *your* agent.

After `judgeman judge` has run, a person labels a small blind sample of the same steps: half of
them steps some layer flagged, half unflagged, mixed so the labeler cannot tell which. Each
layer is then scored against those labels, weighted back to the whole run set.
"""

import random
from collections import defaultdict

from .schema import AXES, StepLabel

PROBLEM = {"progress": False, "redundant": True, "risky": True, "unverified_completion": True,
           "outcome_process_mismatch": True}  # the value that means "something is wrong"  # fmt: skip


def problems(label: StepLabel) -> set[str]:
    return {a for a, bad in PROBLEM.items() if getattr(label, a) is bad}


def pick_sample(final: list[StepLabel], n: int, seed: int = 0) -> tuple[list[tuple[str, int]], dict]:
    """n steps, half flagged by the layered verdict and half not, plus the stratum weights."""
    rng = random.Random(seed)
    flagged = [(x.trajectory_id, x.step) for x in final if problems(x)]
    plain = [(x.trajectory_id, x.step) for x in final if not problems(x)]
    take_f = min(len(flagged), n // 2)
    take_p = min(len(plain), n - take_f)
    chosen = rng.sample(flagged, take_f) + rng.sample(plain, take_p)
    weights = {}
    for k in chosen:
        pool, taken = (flagged, take_f) if k in set(flagged) else (plain, take_p)
        weights[k] = len(pool) / taken
    return sorted(chosen), weights


def score(human: dict, judged: dict, weights: dict, axis: str) -> dict | None:
    """Weighted agreement of one source with the human labels on one axis."""
    bad = PROBLEM[axis]
    cell = defaultdict(float)
    n = 0
    for k, w in weights.items():
        h, j = human.get(k), judged.get(k)
        if h is None or j is None or getattr(h, axis) is None or getattr(j, axis) is None:
            continue
        cell[getattr(h, axis) is bad, getattr(j, axis) is bad] += w
        n += 1
    if not n:
        return None
    total = sum(cell.values())
    pos, neg = cell[True, True] + cell[True, False], cell[False, True] + cell[False, False]
    po = (cell[True, True] + cell[False, False]) / total
    p_j = (cell[True, True] + cell[False, True]) / total
    pe = pos / total * p_j + neg / total * (1 - p_j)
    return {
        "n": n,
        "problems": sum(1 for k in weights if k in human and getattr(human[k], axis) is bad),
        "agreement": po,
        "kappa": (po - pe) / (1 - pe) if pe < 1 else None,
        "caught": cell[True, True] / pos if pos else None,
        "left_alone": cell[False, False] / neg if neg else None,
    }


def advice(reports: dict[str, dict[str, dict | None]]) -> list[str]:
    """One plain sentence per axis about which layer to trust, from the scores."""
    lines = []
    for axis in AXES:
        best = None
        for source, by_axis in reports.items():
            r = by_axis.get(axis)
            if r and r["kappa"] is not None and r["problems"] >= 5:
                if best is None or r["kappa"] > best[1]["kappa"]:
                    best = (source, r)
        if best is None:
            lines.append(f"{axis}: too few examples in your sample to say; label more steps.")
            continue
        source, r = best
        level = "trust" if r["kappa"] >= 0.6 else "use with care" if r["kappa"] >= 0.4 else "do not rely on"
        lines.append(f"{axis}: {level} {source} (kappa {r['kappa']:.2f}, catches {r['caught']:.0%}, "
                     f"leaves {r['left_alone']:.0%} of fine steps alone).")  # fmt: skip
    return lines
