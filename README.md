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

Any OpenAI-compatible endpoint works instead of OpenRouter; step 3 below shows Ollama.

## Step by step

Six steps. The first depends on your agent; the rest are the same for everyone. The keyless path
at the end lets you see the output before you spend anything.

### 1. Get your agent's logs into a folder

judgeman reads one tool call and its result as a step. It needs a folder of log files it can
read; the format is sniffed per file, so a folder can mix them.

**Claude Code.** Nothing to do. Every session is already in
`~/.claude/projects/<your project folder, with slashes as dashes>/`. Point at the folder for every
session, or at one `<session>.jsonl` inside it.

**OpenAI Agents SDK.** Save the session items after a run, one file per run, named `*.items.json`:

```python
import json
from agents import Runner, SQLiteSession

session = SQLiteSession("run-1")
result = await Runner.run(agent, task, session=session)
items = await session.get_items()
json.dump({"task": task, "model": "gpt-5-mini", "items": items}, open("logs/run-1.items.json", "w"))
```

**Anything that emits OpenTelemetry.** LangChain, LlamaIndex, CrewAI, the Agents SDK and most
frameworks have an OpenInference or OTel GenAI instrumentation. Add an exporter that writes one
span per line and point judgeman at the file:

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

out = open("logs/run-1.spans.jsonl", "w")
exporter = ConsoleSpanExporter(out=out, formatter=lambda span: span.to_json(indent=None) + "\n")
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)
# then instrument your framework as its docs say, e.g. LangChainInstrumentor().instrument()
```

An OTLP JSON export (`{"resourceSpans": [...]}`) saved as `*.otel.json` works too.

**mini-SWE-agent.** Its `*.traj.json` files work as they are. `judgeman fetch <submission> -n 20`
downloads published SWE-bench runs to try on.

**Anything else.** Build the steps yourself in ten lines of Python; see
[Another format?](#another-format) below.

**Did the run succeed?** Optional. Put `{"resolved": true}` in `<run>.result.json` beside the
log, or a `per_instance_details.json` in the folder. With it, judgeman also judges whether the
process matched the outcome; without it that one axis is skipped.

### 2. Dry run: count the steps, spend nothing

```bash
export LOGS=~/.claude/projects/-Users-you-code-myproject   # or your logs/ folder
judgeman judge $LOGS --dry-run
```

Prints how many runs and steps it found and roughly how many tokens the judges will read. If the
run count looks wrong, the logs are not being read the way you expect: `judgeman show $LOGS`
lists every run step by step.

### 3. Judge

```bash
export OPENROUTER_API_KEY=sk-or-...        # https://openrouter.ai/keys, a few dollars is plenty
judgeman judge $LOGS --out judged.jsonl
```

Three layers run: free rules on every step, a 9B open judge on every step, and a frontier judge
only on the third of steps either of those flagged. Spend is capped at $1 per judge by default
(`--max-cost`); a 400-step session comes to about $3.50. Every call is cached under
`.judgeman/cache/`, so re-running the same steps is free. The table it prints is a count per run
of wasted, repeated, dangerous and unverified steps.

Any OpenAI-compatible endpoint works instead of OpenRouter. For a local model through Ollama:

```bash
export JUDGEMAN_BASE_URL=http://localhost:11434/v1 OPENAI_API_KEY=ollama
judgeman judge $LOGS --small qwen3.5:9b --frontier '' --out judged.jsonl
```

### 4. Read the report

```bash
judgeman report $LOGS --labels judged.jsonl --out report.html
```

One HTML file, no JavaScript, no network. Every run step by step with four possible marks:

| Mark | Means |
|---|---|
| `wasted` | the step gave the agent nothing it went on to use |
| `repeat` | it only showed content the agent had already seen, with nothing changed in between |
| `dangerous` | it could break things, or it changed an existing test |
| `unverified` | the agent finished without a passing test or repro of its last change |

Tick "only flagged steps", expand a step to see the agent's thought, the full command and its
output, and read the critique in the last column: that is the judge's reason. Failed commands are
listed as their own kind and never flagged on their own, because people do not agree on whether a
failure was useful. `judgeman show $LOGS --labels judged.jsonl --flagged` is the same view in the
terminal.

### 5. Calibrate: find out how far to trust it on your agent

```bash
judgeman calibrate $LOGS --judged judged.jsonl
```

The published trust numbers below were measured on SWE-bench runs. This measures them on yours.
It shows you 50 of your own steps, blind, half of them flagged and half not, and asks for one
keypress per axis: about 20 minutes. Then it prints, per layer and per axis, how often it agreed
with you and one line of advice each: **trust**, **use with care**, or **do not rely on**. Act on
the axes it says to trust. Where it says "too few examples to say", it means that; label more
steps with `-n 100` or treat that axis as unknown.

### 6. Gate your CI

```bash
judgeman gate $LOGS --labels judged.jsonl                    # exit 1 on any dangerous or unverified step
judgeman gate $LOGS --labels judged.jsonl --max-wasted 5     # once calibrate says to trust "wasted"
```

Without `--labels` it runs the free rules only, which costs nothing and needs no key. From Python
the same check is `judgeman.gate(runs, labels)`, which returns the problems as a list of strings.

### No key yet? See it on recorded runs first

The four runs in `examples/agents-sdk/` come with their verdicts, and `judgeman demo` replays the
study's results from saved files:

```bash
git clone https://github.com/Christopher4113/JudgeMan && cd JudgeMan && uv sync
uv run judgeman report examples/agents-sdk --labels examples/agents-sdk/judged.jsonl --out report.html
uv run judgeman demo
```

### Another format?

A run is a `Trajectory` of `Step`s, and every command works on that. Build it yourself and hand it
to the same pipeline:

```python
from judgeman import Step, Trajectory, judge_runs, gate, render, write_labels
from judgeman.judge import Judge
from pathlib import Path

run = Trajectory(id="run-1", task="fix the failing test", resolved=True, steps=[
    Step(index=0, thought="look first", command="cat app.py", output="...", returncode=0),
    Step(index=1, thought="run it", command="pytest -q", output="1 passed", returncode=0),
])
labels, final, _ = judge_runs([run], Judge("qwen/qwen3.5-9b", 0.5, thinking=False),
                              Judge("anthropic/claude-opus-5.5", 1.0))
Path("report.html").write_text(render([run], labels))
assert not gate([run], labels)        # [] when nothing dangerous or unverified
write_labels(Path("judged.jsonl"), labels)
```

`returncode` is the one field the rules lean on: non-zero means the command failed. Render
non-shell tools as a short pseudo-command such as `Read path` or `Edit path`, as the built-in
adapters do, so the free rules can classify them. Pass `None` for either judge to skip that
layer; `run_checks(run)` is the free rules alone.

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

## Repository

| | |
|---|---|
| `src/judgeman/` | the package: one adapter per format, `checks.py`, `judge.py`, `layered.py`, `calibration.py`, `report.py`, `gate.py`, `cli.py` |
| `examples/agents-sdk/` | four recorded runs, each in Agents SDK and OTel form, with their layered verdicts |
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
