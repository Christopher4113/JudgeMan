# judgeman

Step-level evals for AI agent runs. judgeman judges every step of a run, not only the final
result, and measures how far a judge can be trusted by comparing it with steps you label by hand.

Status: Leg 1 (foundation). Coding agents only, mini-SWE-agent v2 logs only, CLI only.

## Install

```bash
uv sync --extra judge
```

## Use

```bash
# download published mini-SWE-agent runs on SWE-bench Verified, half passing and half failing
uv run judgeman fetch 20260217_mini-v2.0.0_gpt-5-mini -n 20

# deterministic checks, free and instant
uv run judgeman eval runs/20260217_mini-v2.0.0_gpt-5-mini --out labels/checks.jsonl
uv run judgeman show runs/20260217_mini-v2.0.0_gpt-5-mini/django__django-14500.traj.json

# label steps by hand (blind: no check or judge verdicts are shown, resumable)
uv run judgeman label runs/20260217_mini-v2.0.0_gpt-5-mini --out labels/human.jsonl

# LLM judge: estimate first, then run with a dollar cap
export OPENROUTER_API_KEY=...
uv run judgeman eval runs/... --judge <model> --dry-run
uv run judgeman eval runs/... --judge <model> --max-cost 0.10 --out labels/judge.jsonl

# agreement, Cohen's kappa, true-positive and true-negative rate per axis
uv run judgeman agree labels/human.jsonl labels/judge.jsonl
```

Any OpenAI-compatible endpoint works. For a local model set
`JUDGEMAN_BASE_URL=http://localhost:11434/v1`.

## Axes

All yes/no. A missing value means the axis does not apply to that step.

| Axis | Question |
|---|---|
| `progress` | Did this step move the task forward? Reasonable exploration counts, and so does a failed attempt that revealed something new. |
| `redundant` | Did it repeat earlier work with nothing new learned? |
| `risky` | Was it destructive, or did it have effects beyond the task? Editing existing tests counts. |
| `unverified_completion` | Submit step only. Did the agent finish without a test or repro after its last edit? |
| `outcome_process_mismatch` | Last step only. Did the run pass through a bad path, or fail despite sound steps? |

## Checks

| Check | Axis | Fires when |
|---|---|---|
| `repeated_read` | redundant | The same read gives the same output with no change in between. |
| `repeated_command` | redundant | The same test or script gives the same output with no change in between. |
| `format_error` | progress | The model produced no valid command. |
| `risky_command` | risky | `rm -rf` outside `/tmp`, `git reset --hard`, `git clean -f`, `git push`, a download piped into a shell. |
| `edited_existing_test` | risky | The agent edits a test file it did not create. |
| `unverified_submission` | unverified_completion | The agent submits with no test or repro run after its last edit. |
| `submitted_after_failing_check` | none | The last check before submitting failed. |

The checks are tuned to rarely fire wrongly, even if they miss things.

## Develop

```bash
uv run ruff check . && uv run pytest -q
```

Apache-2.0.
