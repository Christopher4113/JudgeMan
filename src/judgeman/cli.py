import argparse
import json
import random
import re
import sys
import urllib.request
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import judge as judge_mod
from .adapter import load_trajectories
from .agreement import agreement
from .checks import run_checks
from .schema import StepLabel, Trajectory, applicable, read_labels, write_labels

console = Console()
EXPERIMENTS = "https://raw.githubusercontent.com/SWE-bench/experiments/main/evaluation/verified"
# key -> (axis, value stored when the key is on, name shown, what it means)
MARKS = {
    "w": ("progress", False, "wasted", "it produced nothing the agent could use "
          "(a failed attempt that revealed something new is NOT wasted)"),
    "r": ("redundant", True, "repeat", "it redid something it had already done or seen"),
    "d": ("risky", True, "dangerous", "it could break things, or it changed an existing test"),
    "u": ("unverified_completion", True, "unverified", "it submitted without testing its last change"),
    "m": ("outcome_process_mismatch", True, "mismatch",
          "tests passed but the work was sloppy, or tests failed but the work was sound"),
}  # fmt: skip
GUIDE = """[bold]How labeling works[/]
You are reading one AI agent's attempt to fix a bug, one step at a time.
Each step shows what the agent was thinking, the command it ran, and what came back.
Most steps are fine. If a step is fine, press [bold]Enter[/].
If something is wrong with it, press the letter for each problem first, then Enter.
Pressing a letter again turns it off. There are no right answers to guess: it is your judgment.
  [bold]s[/] skip this step (you can't tell)   [bold]b[/] go back one step   \
[bold]q[/] save and quit   [bold]?[/] show this again
"""


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def fetch(args) -> None:
    """Download published mini-SWE-agent runs, half resolved and half not."""
    out = Path(args.out) / args.submission
    out.mkdir(parents=True, exist_ok=True)
    base = f"{EXPERIMENTS}/{args.submission}"
    details_raw = _get(f"{base}/per_instance_details.json")
    (out / "per_instance_details.json").write_bytes(details_raw)
    match = re.search(r"trajs:\s*s3://([^/\s]+)/(\S+)", _get(f"{base}/metadata.yaml").decode())
    if not match:
        sys.exit("no s3 trajs location in metadata.yaml")
    bucket, prefix = match.groups()

    details = json.loads(details_raw)
    pool = [i for i in sorted(details) if details[i].get("api_calls", 0) <= args.max_steps]
    rng = random.Random(args.seed)
    passed = [i for i in pool if details[i]["resolved"]]
    failed = [i for i in pool if not details[i]["resolved"]]
    picked = rng.sample(passed, min(args.n // 2, len(passed)))
    picked += rng.sample(failed, min(args.n - len(picked), len(failed)))
    for i in picked:
        target = out / f"{i}.traj.json"
        if not target.exists():
            target.write_bytes(_get(f"https://{bucket}.s3.amazonaws.com/{prefix}/{i}/{i}.traj.json"))
        console.print(f"{i}  resolved={details[i]['resolved']}")
    console.print(f"{len(picked)} runs in {out}")


def _outcome(t: Trajectory) -> str:
    return {True: "[green]pass[/]", False: "[red]fail[/]", None: "?"}[t.resolved]


def show(args) -> None:
    for t in load_trajectories(Path(args.path), args.results and Path(args.results)):
        table = Table(title=f"{t.id}  {t.exit_status}  tests: {_outcome(t)}")
        for col in ("step", "rc", "command", "flags"):
            table.add_column(col, overflow="fold")
        for step, label in zip(t.steps, run_checks(t), strict=True):
            command = step.command.split("\n", 1)[0][:90] or "(no valid command)"
            flags = f"[yellow]{', '.join(label.flags)}[/]"
            table.add_row(str(step.index), str(step.returncode), escape(command), flags)
        console.print(table)


def evaluate(args) -> None:
    trajs = load_trajectories(Path(args.path), args.results and Path(args.results))
    labels = [x for t in trajs for x in run_checks(t)]
    table = Table(title=f"{len(trajs)} runs, {len(labels)} steps")
    for col in ("run", "steps", "exit", "tests", "checks flagged"):
        table.add_column(col, overflow="fold")
    for t in trajs:
        flags = [f for x in labels if x.trajectory_id == t.id for f in x.flags]
        counts = ", ".join(f"{f} x{flags.count(f)}" for f in dict.fromkeys(flags))
        table.add_row(t.id, str(len(t.steps)), t.exit_status, _outcome(t), counts or "-")
    console.print(table)

    if args.judge:
        calls, tokens = judge_mod.estimate_tokens(trajs)
        console.print(f"judge {args.judge}: {calls} calls, about {tokens:,} prompt tokens")
        if args.dry_run:
            return
        judge = judge_mod.Judge(args.judge, args.max_cost)
        try:
            for t in trajs:
                for step in t.steps:
                    try:
                        labels.append(judge.judge(t, step))
                    except (json.JSONDecodeError, ValueError):
                        console.print(f"[red]unparseable verdict[/] {t.id} step {step.index}")
        except judge_mod.BudgetReached:
            console.print(f"[red]budget cap ${args.max_cost} reached, keeping partial results[/]")
        console.print(f"spent ${judge.spent:.4f}")
    if args.out:
        write_labels(Path(args.out), labels)
        console.print(f"wrote {len(labels)} labels to {args.out}")


def _getch() -> str:
    try:
        import termios
        import tty
    except ImportError:  # Windows
        import msvcrt

        return msvcrt.getwch()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def label(args, getch=_getch) -> None:
    """Blind hand labeling: check and judge verdicts are never shown."""
    out = Path(args.out)
    trajs = load_trajectories(Path(args.path), args.results and Path(args.results))
    todo = [(t, s) for t in trajs for s in t.steps]
    done = {(x.trajectory_id, x.step) for x in read_labels(out)}
    console.print(GUIDE)
    i = 0
    while i < len(todo):
        t, step = todo[i]
        if (t.id, step.index) in done:
            i += 1
            continue
        console.rule(f"{t.id}  step {step.index + 1}/{len(t.steps)}  ({len(done)} labeled)")
        title = t.task.strip().split("\n", 1)[0]
        console.print(f"[bold]Bug being fixed:[/] {escape(title)}")
        if step.index == 0 or args.task:
            console.print(f"[dim]{escape(judge_mod._clip(t.task, 3000))}[/]")
        if step.thought:
            console.print(f"\n[bold]Agent's thinking:[/] {escape(judge_mod._clip(step.thought, 1500))}")
        console.print(f"\n[bold]Command:[/] [cyan]{escape(step.command or '(no valid command)')}[/]")
        failed = step.returncode not in (0, None)
        console.print(f"[bold]Result:[/] {'[red]failed[/]' if failed else 'ok'}")
        console.print(escape(judge_mod._clip(step.output, args.max_output)))

        axes = applicable(t, step)
        keys = {k: v for k, v in MARKS.items() if v[0] in axes}
        console.print()
        # the outcome is revealed only after the step itself is judged, so it can't sway that
        rounds = [{k: v for k, v in keys.items() if k != "m"}]
        if "m" in keys:
            rounds.append({"m": keys["m"]})
        on: set[str] = set()
        for stage, round_keys in enumerate(rounds):
            if stage == 1:
                console.print(f"\nThis is the last step. Hidden tests: {_outcome(t)}")
            for k, (_, _, name, meaning) in round_keys.items():
                console.print(f"  [bold]{k}[/] {name}: {meaning}")
            while True:
                marked = ", ".join(keys[k][2] for k in keys if k in on) or "fine"
                console.print(f"[bold]> {marked}[/]  (Enter to save)")
                key = getch().lower()
                if key in round_keys:
                    on ^= {key}
                elif key == "?":
                    console.print(GUIDE)
                elif key in ("\r", "\n", "s", "b", "q"):
                    break
            if key != "\r" and key != "\n":
                break
        if key == "q":
            break
        if key == "b":
            rows = read_labels(out)
            if rows:
                done.discard((rows[-1].trajectory_id, rows[-1].step))
                write_labels(out, rows[:-1])
                i = next(n for n, (tt, ss) in enumerate(todo)
                         if (tt.id, ss.index) == (rows[-1].trajectory_id, rows[-1].step))  # fmt: skip
            continue
        row = StepLabel(trajectory_id=t.id, step=step.index, source="human")
        if key != "s":  # a skipped step keeps every axis empty
            for k, (axis, value, _, _) in keys.items():
                setattr(row, axis, value if k in on else not value)
        write_labels(out, [row], append=True)
        done.add((t.id, step.index))
        i += 1
    console.print(f"{len(done)} steps labeled in {out}")


def agree(args) -> None:
    gold = read_labels(Path(args.gold))
    other = read_labels(Path(args.other))
    for source in sorted({x.source for x in other}):
        report = agreement(gold, [x for x in other if x.source == source])
        table = Table(title=f"{source} vs {args.gold}")
        for col in ("axis", "n", "positives", "agreement", "kappa", "TPR", "TNR"):
            table.add_column(col)
        for axis, r in report.items():
            if not r["n"]:
                table.add_row(axis, "0", *["-"] * 5)
                continue
            nums = [r[k] for k in ("agreement", "kappa", "tpr", "tnr")]
            table.add_row(axis, str(r["n"]), str(r["positives"]),
                          *("-" if v is None else f"{v:.2f}" for v in nums))  # fmt: skip
        console.print(table)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="judgeman")
    sub = parser.add_subparsers(required=True)

    def command(name, func, runs=True):
        p = sub.add_parser(name, help=func.__doc__)
        p.set_defaults(func=func)
        if runs:
            p.add_argument("path", help="a .traj.json file or a folder of them")
            p.add_argument("--results", help="per_instance_details.json or results.json")
        return p

    p = command("fetch", fetch, runs=False)
    p.add_argument("submission", help="e.g. 20260217_mini-v2.0.0_gpt-5-mini")
    p.add_argument("-n", type=int, default=5)
    p.add_argument("--max-steps", type=int, default=40, help="skip runs longer than this")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default="runs")

    command("show", show)

    p = command("eval", evaluate)
    p.add_argument("--judge", help="model name, e.g. openai/gpt-5-mini")
    p.add_argument("--max-cost", type=float, default=0.10, help="dollar cap for this command")
    p.add_argument("--dry-run", action="store_true", help="estimate tokens, spend nothing")
    p.add_argument("--out", help="write StepLabel rows to this JSONL file")

    p = command("label", label)
    p.add_argument("--out", default="labels/human.jsonl")
    p.add_argument("--max-output", type=int, default=3000, help="characters of output shown")
    p.add_argument("--task", action="store_true", help="show the task on every step")

    p = command("agree", agree, runs=False)
    p.add_argument("gold", help="JSONL of hand labels")
    p.add_argument("other", help="JSONL of check or judge labels")

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
