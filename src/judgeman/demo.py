"""`judgeman demo`: the whole idea in four screens, from saved results. No API key, no network."""

from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .adapter import load_trajectories
from .agreement import agreement
from .checks import run_checks
from .schema import StepLabel, read_labels

L = Path("labels")
RUNS = Path("runs/20260217_mini-v2.0.0_gpt-5-mini")
STORY = "django__django-14500"  # the run that submitted an empty patch
# dollars per 1,000 judged steps, measured on OpenRouter in October 2026
COST = {"Opus 5.5": 17.93, "Gemini 3.5 Flash Lite": 1.04, "Qwen 3.5 9B": 0.27}
PROBLEMS = (("progress", False, "wasted"), ("redundant", True, "repeat"), ("risky", True, "dangerous"),
            ("unverified_completion", True, "unverified"))  # fmt: skip


def _judge_rows(name: str) -> list[StepLabel]:
    path = L / name
    return [x for x in read_labels(path) if x.source != "checks"]


def _keyed(rows: list[StepLabel]) -> dict:
    return {(x.trajectory_id, x.step): x for x in rows}


def _marks(label: StepLabel | None) -> str:
    return ", ".join(n for axis, value, n in PROBLEMS if label and getattr(label, axis) is value)


def _outcomes(console: Console, trajs) -> None:
    table = Table(title="1. What an outcome-only eval shows")
    for col in ("run", "steps", "hidden tests"):
        table.add_column(col)
    for t in trajs:
        outcome = "[green]pass[/]" if t.resolved else "[red]fail[/]"
        table.add_row(t.id.split("@")[0], str(len(t.steps)), outcome)
    console.print(table)
    console.print("Every [red]fail[/] looks the same here, and so does every [green]pass[/].\n")


def _layers(console: Console, traj) -> None:
    """One run through the three layers: rules, a small judge on every step, Opus only when flagged."""
    small = _keyed(_judge_rows("leg2/qwen-last5-gold.jsonl"))
    frontier = _keyed(_judge_rows("judge-claude-opus-5.5.jsonl"))
    human = _keyed(read_labels(L / "human.jsonl"))
    table = Table(title=f"2. The same failed run, step by step: {STORY}", show_lines=True)
    for col in ("step", "command", "rules", "small judge", "frontier judge", "you"):
        table.add_column(col, overflow="fold")
    table.add_column("why", overflow="fold", ratio=1)
    asked = 0
    for step, check in zip(traj.steps, run_checks(traj), strict=True):
        key = (traj.id, step.index)
        flagged = bool(check.flags) or bool(_marks(small.get(key)))
        asked += flagged
        opus = frontier.get(key) if flagged else None
        why = opus.critique[:200] + "..." if opus and _marks(opus) else ""
        command = escape(step.command.split("\n", 1)[0][:60] or "(no valid command)")
        table.add_row(
            str(step.index), command, f"[yellow]{', '.join(check.flags)}[/]",
            f"[yellow]{_marks(small.get(key))}[/]",
            f"[yellow]{_marks(opus)}[/]" if flagged else "[dim]not asked[/]",
            f"[yellow]{_marks(human.get(key))}[/]", f"[dim]{escape(why)}[/]",
        )  # fmt: skip
    console.print(table)
    n = len(traj.steps)
    console.print(
        f"The rules and the small judge look at all {n} steps. The frontier judge is asked about the "
        f"{asked} they flagged,\nso it costs about ${asked * COST['Opus 5.5'] / 1000:.2f} for this run "
        f"and not ${n * COST['Opus 5.5'] / 1000:.2f}. Step 16 is the story: the submitted patch was empty.\n"
    )


def _kappa(gold: list[StepLabel], rows: list[StepLabel]) -> str:
    r = agreement(gold, rows)["progress"]
    return f"{r['kappa']:.2f}" if r.get("kappa") is not None else "-"


def _caught(rows: dict, kind: str, axis: str, also: dict | None = None) -> str:
    planted = [g for g in read_labels(L / "injected.jsonl") if g.flags[0] == kind]
    planted = [g for g in planted if (g.trajectory_id, g.step) in rows]
    hit = sum(
        bool(getattr(rows[g.trajectory_id, g.step], axis))
        or bool(also and getattr(also[g.trajectory_id, g.step], axis))
        for g in planted
    )
    return f"{hit / len(planted):.0%}" if planted else "-"


def _scoreboard(console: Console) -> None:
    opus = _judge_rows("leg2/opus-last5-gold.jsonl")
    subset = set(_keyed(opus))  # the 150 steps every judge here has seen
    gold = [x for x in read_labels(L / "human.jsonl") if (x.trajectory_id, x.step) in subset]
    judges = {
        "Qwen 3.5 9B": "qwen-last5",
        "Qwen 3.5 9B, fine-tuned": "qwen-ft-last5",
        "Gemini 3.5 Flash Lite": "gemini-last5",
        "Opus 5.5": "opus-last5",
    }
    rules = _keyed(read_labels(L / "checks-injected.jsonl"))
    title = "3. How far to trust each judge (against 516 hand-labeled steps and 196 planted mistakes)"
    table = Table(title=title)
    for col in ("judge", "wasted steps: kappa", "new destructive commands caught", "untested submissions caught",
                "$ per 1,000 steps"):  # fmt: skip
        table.add_column(col)
    table.add_row("Rules only", "-", _caught(rules, "risky-unknown", "risky"),
                  _caught(rules, "unverified", "unverified_completion"), "0")  # fmt: skip
    for name, stem in judges.items():
        planted = _keyed(_judge_rows(f"leg2/{stem}-injected.jsonl"))
        cost = f"{COST[name]:.2f}" if name in COST else "runs locally"
        table.add_row(name, _kappa(gold, _judge_rows(f"leg2/{stem}-gold.jsonl")),
                      _caught(planted, "risky-unknown", "risky"),
                      _caught(planted, "unverified", "unverified_completion"), cost)  # fmt: skip

    small = _keyed(_judge_rows("leg2/qwen-last5-gold.jsonl"))
    cascade = []  # wasted only if the small judge flags it and Opus agrees
    for x in opus:
        flagged = small[x.trajectory_id, x.step].progress is False
        cascade.append(x.model_copy(update={"progress": not (flagged and x.progress is False)}))
    share = sum(small[k].progress is False for k in subset) / len(subset)
    tuned = _keyed(_judge_rows("leg2/qwen-ft-last5-injected.jsonl"))
    table.add_row(
        "[bold]Layered: rules + small judge, Opus on flagged steps[/]",
        f"[bold]{_kappa(gold, cascade)}[/]",
        _caught(tuned, "risky-unknown", "risky", also=rules),
        _caught(tuned, "unverified", "unverified_completion", also=rules),
        f"about {COST['Qwen 3.5 9B'] + share * COST['Opus 5.5']:.2f}",
    )
    console.print(table)
    console.print(
        "Kappa is agreement beyond chance: 0 is chance, 1 is perfect. No single judge wins every column.\n"
        "The layered setup matches or beats Opus on each one for about a third of its cost.\n"
        "These combinations were chosen after seeing the results, so treat them as promising, not proven.\n"
    )


def demo(args) -> None:
    """Walk through the idea using saved results: no API key, no network."""
    console = Console()

    def pause():
        if not args.no_pause:
            console.input("[dim]Press Enter to continue[/]")

    console.rule("[bold]judgeman[/]: judge every step of a run, and measure how far to trust the judge")
    wanted = {x.trajectory_id for x in read_labels(L / "human.jsonl")}
    trajs = [t for t in load_trajectories(RUNS) if t.id in wanted] if RUNS.exists() else []
    if trajs:
        _outcomes(console, trajs)
        pause()
        _layers(console, next(t for t in trajs if t.id.startswith(STORY)))
        pause()
    else:
        console.print(f"[yellow]{RUNS} is not here, so the run walkthrough is skipped. "
                      "Fetch the runs as described in DEMO.md to see it.[/]\n")  # fmt: skip
    _scoreboard(console)
