"""`judgeman judge`: the layered pipeline from Leg 2 in one call.

1. Rules on every step (free).
2. A small open judge on every step (cents).
3. A frontier judge only on the steps either of those flagged (about one step in three).

The final verdict per step is the frontier judge's where it was asked, otherwise the rules'.
"""

import json
from concurrent.futures import ThreadPoolExecutor

from .checks import run_checks
from .judge import BudgetReached, Judge
from .schema import AXES, StepLabel, Trajectory

INFO_FLAGS = {"failed_command"}  # reported, never a reason to escalate on its own


def flagged(check: StepLabel, small: StepLabel | None) -> bool:
    if set(check.flags) - INFO_FLAGS:
        return True
    if small is None:
        return False
    return small.progress is False or any(getattr(small, a) for a in AXES if a != "progress")


def judge_runs(trajs: list[Trajectory], small: Judge | None, frontier: Judge | None, workers: int = 4):
    """Returns (labels from every layer, final layered verdicts, how many steps reached the frontier)."""
    checks = {(t.id, s.index): c for t in trajs for s, c in zip(t.steps, run_checks(t), strict=True)}
    pairs = [(t, s) for t in trajs for s in t.steps]
    layers: dict[str, dict] = {"checks": checks, "small": {}, "frontier": {}}

    def ask(judge: Judge, work: list) -> dict:
        def one(pair):
            try:
                return judge.judge(*pair)
            except (json.JSONDecodeError, ValueError):
                return None

        out = {}
        with ThreadPoolExecutor(workers) as pool:
            try:
                for (t, s), verdict in zip(work, pool.map(one, work), strict=True):
                    if verdict is not None:
                        out[t.id, s.index] = verdict
            except BudgetReached:
                pool.shutdown(cancel_futures=True)
        return out

    if small:
        layers["small"] = ask(small, pairs)
    small_rows = layers["small"]
    escalate = [(t, s) for t, s in pairs if flagged(checks[t.id, s.index], small_rows.get((t.id, s.index)))]
    if frontier:
        layers["frontier"] = ask(frontier, escalate)

    final = []
    for t, s in pairs:
        key = (t.id, s.index)
        check = checks[key]
        base = layers["frontier"].get(key)
        row = StepLabel(trajectory_id=t.id, step=s.index, source="layered", flags=list(check.flags))
        if base is not None:  # the frontier judge decided
            for a in AXES:
                setattr(row, a, getattr(base, a))
            row.critique = base.critique
        else:  # not escalated: the rules' view, and "progress" means nothing was found
            for a in AXES:
                setattr(row, a, getattr(check, a))
            row.progress = check.progress if check.progress is not None else True
        final.append(row)
    all_labels = [x for layer in layers.values() for x in layer.values()] + final
    return all_labels, final, len(escalate)
