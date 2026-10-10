# Demo script (about 3 minutes)

Paths are relative to a checkout of the repository.

## The one-command version

```bash
uv run judgeman demo
```

Three screens, Enter to move on, all from saved results (no API key, no network):

1. **What an outcome-only eval shows.** 18 runs, pass or fail.
2. **One failed run, step by step, through three layers.** Rules and a small open judge look at
   every step; the frontier judge is asked only about the steps they flag. The last step shows why
   the run failed: the agent submitted an empty patch.
3. **How far to trust each judge.** Agreement with 516 hand-labeled steps, recall on 196 planted
   mistakes, and cost. The layered setup is the bottom row.

Screens 1 and 2 need the downloaded runs (see setup below). Screen 3 works from the repository alone.
Add `--no-pause` to print everything at once.

## The longer version, command by command

Everything below reads files already in the repo and in `runs/`. No API key, no network.

Setup once: `uv sync`. The runs in `runs/` are not in git; on a new machine re-fetch them with
the same two commands used originally (the sample is seeded, so the files match):

```bash
uv run judgeman fetch 20260217_mini-v2.0.0_gpt-5-mini -n 6
uv run judgeman fetch 20260217_mini-v2.0.0_gpt-5-mini -n 20
```

## 1. The outcome-only view hides everything

```bash
uv run judgeman eval $(grep gpt-5-mini study/labels/review-files.txt)
```

16 runs, pass or fail. Say: "This is what a normal eval tells you. Two runs with `pass` look
identical. So do two with `fail`."

## 2. One failed run, step by step

```bash
uv run judgeman show runs/20260217_mini-v2.0.0_gpt-5-mini/django__django-14500.traj.json \
  --flagged --labels study/labels/human.jsonl --labels study/labels/judge-claude-opus-5.5.jsonl
```

Say: "The agent staged its change with `git add -A`, then built its patch with a plain
`git diff`, which is empty once everything is staged. It submitted a zero-byte patch. The test
harness reports `fail`. The step view reports why." Point at steps 15 and 16.

Every one of the 23 GPT-5 mini runs makes the same staging mistake; most recover, this one did not.

## 3. Can you trust the judge? Measure it

```bash
uv run judgeman agree study/labels/human.jsonl study/labels/judge-claude-opus-5.5.jsonl
uv run judgeman agree study/labels/human.jsonl study/labels/judge-gemini-3.5-flash-lite.jsonl
```

Say: "516 steps labeled by hand. The frontier judge reaches kappa 0.63 on whether a step made
progress; the cheap one 0.45. On repeats neither is close, and that table says so. Rows marked `*` have too few examples to say anything, and the
tool tells you so instead of printing a confident number."

## Numbers to quote

| | Opus 5.5 | Gemini 3.5 Flash Lite | Checks (free) |
|---|---|---|---|
| progress, kappa | 0.63 | 0.45 | only no-command steps, 8 of 8 |
| redundant, kappa | 0.20 (95% CI 0.11 to 0.31) | 0.02 | 0.12 |
| redundant, share of the labeler's repeats caught | 19% | 3% | 9% |
| cost per step | $0.018 | $0.0011 | $0 |

What to say about `redundant`: "Nobody agrees with the labeler on repeats, not even the frontier
judge. When a judge or check does call a repeat it is almost always right (97% or better on
steps the labeler called fine), but the labeler marks about a third of all steps as repeats and
the judges mark far fewer. That is a problem with how the question is defined, and the tool
surfaced it before anyone trained a model on those labels."

Caveats to state if asked: one labeler; the Opus `progress` number comes after a review of the
steps where Opus and the labeler disagreed, with a blind control showing those labels are stable
(1 of 30 changed); the `redundant` numbers use only steps labeled with the run history on screen
(`study/scripts/redundant_estimate.py`); `risky`, `unverified_completion` and
`outcome_process_mismatch` have too few examples to score.
