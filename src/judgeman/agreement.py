from .schema import AXES, StepLabel


def agreement(gold: list[StepLabel], other: list[StepLabel]) -> dict[str, dict]:
    """Per-axis agreement on steps where both sources gave a yes/no."""
    theirs = {(x.trajectory_id, x.step): x for x in other}
    report = {}
    for axis in AXES:
        pairs = [
            (getattr(g, axis), getattr(theirs[g.trajectory_id, g.step], axis))
            for g in gold
            if (g.trajectory_id, g.step) in theirs
        ]
        pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
        n = len(pairs)
        if not n:
            report[axis] = {"n": 0}
            continue
        tp = sum(a and b for a, b in pairs)
        tn = sum(not a and not b for a, b in pairs)
        pos, neg = sum(a for a, _ in pairs), sum(not a for a, _ in pairs)
        po = (tp + tn) / n
        p_gold, p_other = pos / n, sum(b for _, b in pairs) / n
        pe = p_gold * p_other + (1 - p_gold) * (1 - p_other)
        report[axis] = {
            "n": n,
            "positives": pos,
            "agreement": po,
            "kappa": (po - pe) / (1 - pe) if pe < 1 else None,  # undefined with one class
            "tpr": tp / pos if pos else None,
            "tnr": tn / neg if neg else None,
        }
    return report
