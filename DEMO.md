# Demo script (about 3 minutes)

Everything below reads files already in the repo and in `runs/`. No API key, no network.

Setup once: `uv sync`. The runs in `runs/` are not in git; on a new machine re-fetch them with
the same two commands used originally (the sample is seeded, so the files match):

```bash
uv run judgeman fetch 20260217_mini-v2.0.0_gpt-5-mini -n 6
uv run judgeman fetch 20260217_mini-v2.0.0_gpt-5-mini -n 20
```

## 1. The outcome-only view hides everything

```bash
uv run judgeman eval $(grep gpt-5-mini labels/review-files.txt)
```

16 runs, pass or fail. Say: "This is what a normal eval tells you. Two runs with `pass` look
identical. So do two with `fail`."

## 2. One failed run, step by step

```bash
uv run judgeman show runs/20260217_mini-v2.0.0_gpt-5-mini/django__django-14500.traj.json \
  --flagged --labels labels/human.jsonl --labels labels/judge-claude-opus-5.5.jsonl
```

Say: "The agent staged its change with `git add -A`, then built its patch with a plain
`git diff`, which is empty once everything is staged. It submitted a zero-byte patch. The test
harness reports `fail`. The step view reports why." Point at steps 15 and 16.

Every one of the 23 GPT-5 mini runs makes the same staging mistake; most recover, this one did not.

## 3. Can you trust the judge? Measure it

```bash
uv run judgeman agree labels/human.jsonl labels/judge-claude-opus-5.5.jsonl
uv run judgeman agree labels/human.jsonl labels/judge-gemini-3.5-flash-lite.jsonl
```

Say: "516 steps labeled by hand. The frontier judge reaches kappa 0.63 on whether a step made
progress; the cheap one 0.45. Rows marked `*` have too few examples to say anything, and the
tool tells you so instead of printing a confident number."

## Numbers to quote

| | Opus 5.5 | Gemini 3.5 Flash Lite | Checks (free) |
|---|---|---|---|
| progress, kappa | 0.63 | 0.45 | only no-command steps, 8 of 8 |
| redundant, kappa (provisional) | 0.63 | 0.12 | 0.24 |
| cost per step | $0.018 | $0.0011 | $0 |

Caveats to state if asked: one labeler; the Opus numbers come after a review of the steps where
Opus and the labeler disagreed, with a blind control showing `progress` labels are stable and
`redundant` labels are not yet; `risky` has no positives in this data.
