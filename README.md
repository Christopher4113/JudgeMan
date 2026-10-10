# judgeman

Step-level evals for AI coding agents, with a measured number for how far to trust the judge.

Most agent evals score the final result. judgeman reads every step of a run, flags the ones that
were wasted, repeated, dangerous or submitted unverified, and tells you how often its verdicts
match a person's: on public runs, and on your own agent after a 20-minute calibration.

Works on logs you already have: **Claude Code** sessions, **OpenAI Agents SDK** sessions,
**OpenTelemetry** traces, **mini-SWE-agent** trajectories.

## Setup

```bash
pip install 'judgeman[judge]'        # or: uv tool install 'judgeman[judge]'
export OPENROUTER_API_KEY=sk-or-...  # https://openrouter.ai/keys, a few dollars of credit is plenty
```

Any OpenAI-compatible endpoint works instead of OpenRouter: set `JUDGEMAN_BASE_URL` and
`OPENAI_API_KEY`. For a local model through Ollama, `JUDGEMAN_BASE_URL=http://localhost:11434/v1`
and pass `--small <model>` below.

## Quickstart

Point it at a folder of logs. For Claude Code that is your project's folder under `~/.claude/projects`.

```bash
LOGS=~/.claude/projects/-Users-you-code-myproject

judgeman judge $LOGS --dry-run                    # how many steps, roughly how many tokens, $0
judgeman judge $LOGS --out judged.jsonl           # rules + a 9B judge on every step, Opus on the flagged third; capped at $1
judgeman report $LOGS --labels judged.jsonl --out report.html   # one HTML file, open it in a browser
judgeman calibrate $LOGS --judged judged.jsonl    # label 50 blind steps, get trust per layer and axis
judgeman gate $LOGS --labels judged.jsonl         # exit 1 on any dangerous or unverified step; for CI
```

Costs, measured: the small judge is about 27 cents per 1,000 steps, the frontier judge about $18
per 1,000 of the steps it sees. A 400-step session runs to about $3.50. Calls are cached, so
re-running is free.

No key yet? `judgeman demo` shows the whole thing from saved results, and the four recorded runs
in `examples/agents-sdk/` come with their verdicts:

```bash
judgeman report examples/agents-sdk --labels examples/agents-sdk/judged.jsonl --out report.html
```

## Where your logs are

| Agent | Point judgeman at |
|---|---|
| Claude Code | `~/.claude/projects/<project>/` or one `<session>.jsonl` inside it |
| OpenAI Agents SDK | a JSON file of `session.get_items()` (or `result.to_input_list()`), named `*.items.json` |
| Anything with OpenTelemetry | spans as JSON lines, a JSON list, or an OTLP export; `*.jsonl`, `*.spans.json`, `*.otel.json` |
| mini-SWE-agent | `*.traj.json`; `judgeman fetch <submission> -n 20` downloads published SWE-bench runs |

A step is one tool call and its result. The format is sniffed from the file, so a folder can mix
them. Pass or fail per run comes from a `<run>.result.json` beside the log (`{"resolved": true}`)
or a `per_instance_details.json`; without it the outcome axis is skipped.

## What it judges, and how far to trust it

Five yes/no axes per step: `progress`, `redundant`, `risky`, `unverified_completion`, and
`outcome_process_mismatch` on the last step. Free rules fire first; a small open model looks at
every step; a frontier model is asked only about what they flag. [docs/axes.md](docs/axes.md)
has the definitions, the rules and the known gaps.

| Judge of "was this step wasted" | Kappa vs hand labels | Cost per 1,000 steps |
|---|---|---|
| Two people vs each other (the ceiling) | 0.68 | |
| **Layered: rules + Qwen 3.5 9B on all, Opus 5.5 on the flagged third** | **0.72** (0.50 to 0.86) | **$5.80** |
| Claude Opus 5.5 on every step | 0.61 | $17.93 |
| Qwen 3.5 9B alone | 0.30 | $0.27 |

Measured on 516 hand-labeled SWE-bench steps; the layered row was tuned on the same labels, so
treat it as promising rather than proven. On a real Claude Code session the layered verdict reached
kappa 0.70 on dangerous steps. [docs/results.md](docs/results.md) has every number, what did not
help, and the calibration run; the three PDF reports in [reports/](reports/) have the method.

## Every command

| | |
|---|---|
| `judge` | the layered pipeline; `--small`, `--frontier`, `--max-cost`, `--dry-run`, `--out` |
| `report` | one HTML file for a set of runs; `--labels` adds judge verdicts |
| `calibrate` | label a blind sample of your judged steps, get trust per layer and axis |
| `gate` | exit 1 past a limit; `--max-dangerous 0 --max-unverified 0` by default, `--max-wasted`, `--max-repeat` |
| `show` | a run step by step in the terminal; `--flagged` for the flagged steps only |
| `eval` | one judge (or the rules) on every step, for studies; `--context`, `--fewshot`, `--no-thinking` |
| `label` | blind hand-labeling, one keypress per axis, resumable |
| `agree` | Cohen's kappa, true-positive and true-negative rate between two label files |
| `fetch` | download published mini-SWE-agent runs on SWE-bench Verified |
| `demo` | three screens from saved results; no key, no network |

## Repository

| | |
|---|---|
| `src/judgeman/` | the package: one adapter per format, `checks.py`, `judge.py`, `layered.py`, `calibration.py`, `report.py`, `gate.py`, `cli.py` |
| `examples/agents-sdk/` | four recorded runs in two formats, with their layered verdicts |
| `docs/` | [axes and rules](docs/axes.md), [results](docs/results.md), [demo script](docs/demo.md), [launch notes](docs/launch.md) |
| `reports/` | the Leg 1, 2 and 3 reports as PDF |
| `study/` | every hand label, every judge's verdict, the scripts that produce the tables, the fine-tune notebook; see [study/README.md](study/README.md) |

## Develop

```bash
uv sync --extra judge
uv run ruff check . && uv run pytest -q
```

Fine-tuned judge adapter: [Christopher4113/judgeman-qwen3.5-9b-judge](https://huggingface.co/Christopher4113/judgeman-qwen3.5-9b-judge).
Changes: [CHANGELOG.md](CHANGELOG.md). Apache-2.0.
