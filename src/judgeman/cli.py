import argparse
import json
import random
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import judge as judge_mod
from .adapter import load_trajectories
from .agreement import agreement
from .checks import run_checks
from .schema import AXES, StepLabel, Trajectory, applicable, read_labels, write_labels

console = Console()
EXPERIMENTS = "https://raw.githubusercontent.com/SWE-bench/experiments/main/evaluation/verified"
# key -> (axis, value stored when the key is on, name shown, what it means)
MARKS = {
    "w": ("progress", False, "wasted", "it produced nothing the agent could use "
          "(a failed attempt that revealed something new is NOT wasted)"),
    "r": ("redundant", True, "repeat", "it only showed content already seen (same lines, or same "
          "command and result) with nothing changed in between"),
    "d": ("risky", True, "dangerous", "it could break things, or it changed an existing test"),
    "u": ("unverified_completion", True, "unverified", "it submitted without a successful test or repro "
          "of its last change (a check that failed or didn't exercise it doesn't count)"),
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


MIN_PER_CLASS = 10  # below this, kappa and the rates swing on one or two labels


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


def _load(args) -> list[Trajectory]:
    paths = [args.path] if isinstance(args.path, str) else args.path
    results = Path(args.results) if args.results else None
    return [t for p in paths for t in load_trajectories(Path(p), results)]


def _outcome(t: Trajectory) -> str:
    return {True: "[green]pass[/]", False: "[red]fail[/]", None: "?"}[t.resolved]


def _marks(label: StepLabel) -> list[str]:
    return [name for axis, value, name, _ in MARKS.values() if getattr(label, axis) is value]


def show(args) -> None:
    """One run step by step: check flags, plus verdicts from any label files given."""
    sources: dict[str, dict[tuple[str, int], StepLabel]] = {}
    for path in args.labels or []:
        for x in read_labels(Path(path)):
            if x.source != "checks":
                sources.setdefault(x.source, {})[x.trajectory_id, x.step] = x
    for t in _load(args):
        table = Table(title=f"{t.id}  {t.exit_status}  tests: {_outcome(t)}", show_lines=bool(sources))
        for col in ("step", "command", "checks", *(s.rsplit("/", 1)[-1] for s in sources)):
            table.add_column(col, overflow="fold")
        if sources:
            table.add_column("why", overflow="fold", ratio=1)
        for step, label in zip(t.steps, run_checks(t), strict=True):
            command = escape(step.command.split("\n", 1)[0][:90] or "(no valid command)")
            if step.returncode not in (0, None):
                command += " [red](failed)[/]"
            # steps count from 0 here because the judges' critiques refer to them that way
            row = [str(step.index), command, f"[yellow]{', '.join(label.flags)}[/]"]
            why, flagged = "", bool(label.flags)
            for rows in sources.values():
                verdict = rows.get((t.id, step.index))
                marks = _marks(verdict) if verdict else []
                row.append("[dim]-[/]" if verdict is None else f"[yellow]{', '.join(marks)}[/]")
                flagged = flagged or bool(marks)
                if marks and verdict.critique and not why:
                    text = verdict.critique
                    why = f"[dim]{escape(text[:220] + ('...' if len(text) > 220 else ''))}[/]"
            if flagged or not args.flagged:
                table.add_row(*row, *([why] if sources else []))
        console.print(table)


def evaluate(args) -> None:
    trajs = _load(args)
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
        pairs = [(t, s) for t in trajs for s in t.steps]
        if args.queue:  # judge only the listed [run id, step] pairs
            wanted = {(k[0], k[1]) for k in json.loads(Path(args.queue).read_text())}
            pairs = [(t, s) for t, s in pairs if (t.id, s.index) in wanted]
        calls, tokens = judge_mod.estimate_tokens(pairs, args.context)
        console.print(f"judge {args.judge} ({args.context}): {calls} calls, about {tokens:,} prompt tokens")
        if args.dry_run:
            return
        judge = judge_mod.Judge(
            args.judge, args.max_cost, context=args.context, thinking=not args.no_thinking
        )

        def one(pair):
            try:
                return judge.judge(*pair)
            except (json.JSONDecodeError, ValueError):
                return None
            except Exception as e:  # one request that never answers is skipped, not fatal
                if type(e).__name__ != "APITimeoutError":
                    raise
                return None

        pool = ThreadPoolExecutor(args.workers)
        try:
            for (t, step), verdict in zip(pairs, pool.map(one, pairs), strict=True):
                if verdict is None:
                    console.print(f"[red]no usable verdict[/] {t.id} step {step.index}")
                else:
                    labels.append(verdict)
        except judge_mod.BudgetReached:
            console.print(f"[red]budget cap ${args.max_cost} reached, keeping partial results[/]")
        except Exception as e:  # API failure mid-run: what is cached and labeled so far is kept
            console.print(f"[red]judge stopped: {escape(str(e)[:300])}[/]")
        pool.shutdown(cancel_futures=True)  # after a stop, calls not yet started are dropped
        pace = f", {judge.seconds / judge.calls:.1f}s per call" if judge.calls else ""
        console.print(f"spent ${judge.spent:.4f} on {judge.calls} new calls{pace}")
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
    trajs = _load(args)
    todo = [(t, s) for t in trajs for s in t.steps]
    if getattr(args, "queue", None):  # re-judge only the listed [run id, step] pairs
        wanted = {(k[0], k[1]) for k in json.loads(Path(args.queue).read_text())}
        todo = [(t, s) for t, s in todo if (t.id, s.index) in wanted]
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
        earlier = t.steps[max(0, step.index - args.history) : step.index]
        if earlier:
            console.print("\n[bold]Earlier commands:[/]")
            for e in earlier:
                first = (e.command or "(no valid command)").split("\n", 1)[0][:150]
                console.print(f"[dim]{e.index + 1:3}  {escape(first)}[/]")
        if step.thought:
            console.print(f"\n[bold]Agent's thinking:[/] {escape(judge_mod._clip(step.thought, 1500))}")
        console.print(f"\n[bold]Command:[/] [cyan]{escape(step.command or '(no valid command)')}[/]")
        failed = step.returncode not in (0, None)
        console.print(f"[bold]Result:[/] {'[red]failed[/]' if failed else 'ok'}")
        console.print(escape(judge_mod._clip(step.output, args.max_output)))

        axes = applicable(t, step)
        only = getattr(args, "only", None)
        keys = {k: v for k, v in MARKS.items() if v[0] in axes and only in (None, v[0])}
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
        thin_axes: list[str] = []
        for axis, r in report.items():
            if not r["n"]:
                table.add_row(axis, "0", *["-"] * 5)
                continue
            nums = [r[k] for k in ("agreement", "kappa", "tpr", "tnr")]
            thin = min(r["positives"], r["n"] - r["positives"]) < MIN_PER_CLASS
            thin_axes += [axis] if thin else []
            table.add_row(axis + (" [yellow]*[/]" if thin else ""), str(r["n"]), str(r["positives"]),
                          *("-" if v is None else f"{v:.2f}" for v in nums))  # fmt: skip
        console.print(table)
        if thin_axes:
            console.print(f"[yellow]* fewer than {MIN_PER_CLASS} yes or {MIN_PER_CLASS} no labels: "
                          f"too few to measure, treat the numbers as unknown[/]")  # fmt: skip


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="judgeman")
    sub = parser.add_subparsers(required=True)

    def command(name, func, runs=True):
        p = sub.add_parser(name, help=func.__doc__)
        p.set_defaults(func=func)
        if runs:
            p.add_argument("path", nargs="+", help=".traj.json files or folders of them")
            p.add_argument("--results", help="per_instance_details.json or results.json")
        return p

    p = command("fetch", fetch, runs=False)
    p.add_argument("submission", help="e.g. 20260217_mini-v2.0.0_gpt-5-mini")
    p.add_argument("-n", type=int, default=5)
    p.add_argument("--max-steps", type=int, default=40, help="skip runs longer than this")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default="runs")

    p = command("show", show)
    p.add_argument("--labels", action="append", help="label file shown beside the checks, repeatable")
    p.add_argument("--flagged", action="store_true", help="only steps that someone flagged")

    p = command("eval", evaluate)
    p.add_argument("--judge", help="model name, e.g. openai/gpt-5-mini")
    p.add_argument("--max-cost", type=float, default=0.10, help="dollar cap for this command")
    p.add_argument("--dry-run", action="store_true", help="estimate tokens, spend nothing")
    p.add_argument("--context", choices=judge_mod.CONTEXTS, default="last5", help="what the judge sees")
    p.add_argument("--queue", help="JSON list of [run id, step] pairs to judge, skipping the rest")
    p.add_argument("--workers", type=int, default=1, help="judge calls in flight at once")
    p.add_argument("--no-thinking", action="store_true", help="turn off the model's hidden reasoning")
    p.add_argument("--out", help="write StepLabel rows to this JSONL file")

    p = command("label", label)
    p.add_argument("--out", default="labels/human.jsonl")
    p.add_argument("--max-output", type=int, default=3000, help="characters of output shown")
    p.add_argument("--task", action="store_true", help="show the task on every step")
    p.add_argument("--history", type=int, default=5, help="earlier commands listed per step")
    p.add_argument("--only", choices=AXES, help="ask about this one axis, leave the others empty")
    p.add_argument("--queue", help="JSON list of [run id, step] pairs to label, skipping the rest")

    p = command("agree", agree, runs=False)
    p.add_argument("gold", help="JSONL of hand labels")
    p.add_argument("other", help="JSONL of check or judge labels")

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
