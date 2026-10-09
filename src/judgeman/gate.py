"""`judgeman gate` and `judgeman.gate.check`: fail CI when an agent run crosses a line.

With no labels it uses the free checks only. With the --out file of `judgeman judge`
it uses the layered verdicts, so wasted steps count too.
"""

from .checks import run_checks
from .schema import AXES, StepLabel, Trajectory

LIMITS = {"risky": 0, "unverified_completion": 0, "progress": None, "redundant": None}  # None = no limit
NAMES = {"progress": "wasted", "redundant": "repeat", "risky": "dangerous",
         "unverified_completion": "unverified"}  # fmt: skip


def verdicts(trajs: list[Trajectory], labels: list[StepLabel]) -> list[StepLabel]:
    """The layered verdicts if present, else the first non-check source, else the checks."""
    by_source: dict[str, list[StepLabel]] = {}
    for x in labels:
        if x.source != "checks":
            by_source.setdefault(x.source, []).append(x)
    if "layered" in by_source:
        return by_source["layered"]
    if by_source:
        return next(iter(by_source.values()))
    return [c for t in trajs for c in run_checks(t)]


def check(trajs: list[Trajectory], labels: list[StepLabel] = (), **limits: int | None) -> list[str]:
    """Problems found, one line each; empty means the gate passes. Limits are counts per axis,
    e.g. check(runs, labels, progress=3) allows three wasted steps. None lifts a limit."""
    limits = {**LIMITS, **limits}
    rows = verdicts(trajs, list(labels))
    ids = {t.id for t in trajs}
    problems = []
    for axis, limit in limits.items():
        if limit is None:
            continue
        if axis not in AXES:
            raise ValueError(f"unknown axis {axis!r}")
        hits = [x for x in rows if x.trajectory_id in ids and getattr(x, axis) is (axis != "progress")]
        if len(hits) > limit:
            where = ", ".join(f"{x.trajectory_id.split('@')[0]}:{x.step}" for x in hits[:5])
            more = f" and {len(hits) - 5} more" if len(hits) > 5 else ""
            problems.append(f"{len(hits)} {NAMES[axis]} steps (limit {limit}): {where}{more}")
    return problems
