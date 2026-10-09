"""`judgeman report`: one self-contained HTML file for a set of runs. No dependencies, no network."""

from html import escape

from .checks import run_checks
from .schema import StepLabel, Trajectory

MARKS = (
    ("progress", False, "wasted"),
    ("redundant", True, "repeat"),
    ("risky", True, "dangerous"),
    ("unverified_completion", True, "unverified"),
    ("outcome_process_mismatch", True, "mismatch"),
)
CSS = """
body{font:15px/1.45 -apple-system,Helvetica,Arial,sans-serif;max-width:1100px;margin:2em auto;padding:0 1em;
color:#222}
h1,h2{font-weight:600}h2{margin-top:2.5em}table{border-collapse:collapse;width:100%}
th,td{text-align:left;vertical-align:top;padding:.35em .6em;border-top:1px solid #e3e3e3}th{font-weight:600}
tr.flag{background:#fff6e0}code,pre{font:13px Menlo,Consolas,monospace}pre{white-space:pre-wrap;margin:.3em 0;
background:#f6f6f6;padding:.6em;max-height:24em;overflow:auto}.fail{color:#b00}.pass{color:#080}
.mark{color:#a60}
.dim{color:#777}details summary{cursor:pointer;color:#555}#only:checked~section tr.ok{display:none}
.summary td,.summary th{border:0;padding-right:1.5em}label{user-select:none}
""".strip()


def _marks(label: StepLabel) -> list[str]:
    return [name for axis, value, name in MARKS if getattr(label, axis) is value]


def _outcome(t: Trajectory) -> str:
    if t.resolved is None:
        return ""
    return '<span class="pass">tests pass</span>' if t.resolved else '<span class="fail">tests fail</span>'


def _run(t: Trajectory, sources: dict[str, dict[tuple[str, int], StepLabel]]) -> str:
    checks = run_checks(t)
    rows, flagged_steps = [], 0
    for step, check in zip(t.steps, checks, strict=True):
        key = (t.id, step.index)
        verdicts = [(name, rows_.get(key)) for name, rows_ in sources.items()]
        marks = {name: _marks(v) if v else None for name, v in verdicts}
        flagged = bool(check.flags) or any(marks.values())
        flagged_steps += flagged
        why = next((v.critique for _, v in verdicts if v and _marks(v) and v.critique), "")
        first = escape(step.command.split("\n", 1)[0][:120]) or '<span class="dim">(no valid command)</span>'
        rc = "" if step.returncode in (0, None) else f' <span class="fail">(exit {step.returncode})</span>'
        detail = (
            f"<details><summary><code>{first}</code>{rc}</summary>"
            + (f"<p><b>thought</b></p><pre>{escape(step.thought[:2000])}</pre>" if step.thought else "")
            + (f"<p><b>command</b></p><pre>{escape(step.command)}</pre>" if "\n" in step.command else "")
            + f"<p><b>output</b></p><pre>{escape(step.output[:4000]) or '(empty)'}</pre></details>"
        )
        cells = [str(step.index), detail, f'<span class="mark">{", ".join(check.flags)}</span>']
        for name, _ in verdicts:
            m = marks[name]
            cells.append(
                '<span class="dim">-</span>' if m is None else f'<span class="mark">{", ".join(m)}</span>'
            )
        cells.append(f'<span class="dim">{escape(why)}</span>')
        tds = "".join(f"<td>{c}</td>" for c in cells)
        rows.append(f'<tr class="{"flag" if flagged else "ok"}">{tds}</tr>')
    head = "".join(f"<th>{escape(h)}</th>" for h in ("step", "command", "checks", *sources, "why"))
    task = escape(" ".join(t.task.split())[:600])
    return (
        f"<h2 id={escape(t.id, quote=True)!r}>{escape(t.id)}</h2>"
        f"<p>{_outcome(t)} · {len(t.steps)} steps · {flagged_steps} flagged · {escape(t.exit_status)}</p>"
        f"<details><summary>task</summary><pre>{task}</pre></details>"
        f"<table><tr>{head}</tr>{''.join(rows)}</table>"
    )


def render(trajs: list[Trajectory], labels: list[StepLabel], title: str = "judgeman report") -> str:
    """Every run on one page: step table with check flags and each label source's verdicts."""
    sources: dict[str, dict[tuple[str, int], StepLabel]] = {}
    for x in labels:
        if x.source != "checks":  # the checks are recomputed, they are free
            sources.setdefault(x.source.rsplit("/", 1)[-1], {})[x.trajectory_id, x.step] = x
    if "layered" in sources:  # the final verdict goes first
        sources = {"layered": sources.pop("layered"), **sources}
    final = sources.get("layered") or next(iter(sources.values()), {})
    counts = {name: 0 for _, _, name in MARKS}
    for v in final.values():
        for m in _marks(v):
            counts[m] += 1
    steps = sum(len(t.steps) for t in trajs)
    summary = "".join(
        f"<tr><th>{len(trajs)} runs</th><th>{steps} steps</th>"
        + "".join(f"<td><b>{n}</b> {name}</td>" for name, n in counts.items())
        + "</tr>"
    )
    body = "".join(_run(t, sources) for t in trajs)
    source_note = "the layered judge" if "layered" in sources else "the first label source"
    return (
        f"<!doctype html><meta charset=utf-8><title>{escape(title)}</title><style>{CSS}</style>"
        f"<h1>{escape(title)}</h1><table class=summary>{summary}</table>"
        f'<input type=checkbox id=only><p><label for=only> only flagged steps</label> '
        f'<span class="dim">Counts are from {source_note}; a step is flagged when the checks or any judge '
        "marked it.</span></p>"
        f"<section>{body}</section>"
    )
