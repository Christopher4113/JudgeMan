# How far to trust it

Measured on 516 hand-labeled steps from published mini-SWE-agent runs on SWE-bench Verified
(six models), 300 of them labeled by a second person, plus 196 runs with planted mistakes. The
full method and tables are in the three reports: [Leg 1](../reports/leg1-report.pdf) built the
framework and the gold set, [Leg 2](../reports/leg2-report.pdf) compared the judges,
[Leg 3](../reports/leg3-report.pdf) turned the result into the tool and calibrated it on a real
agent.

## Wasted steps, on SWE-bench runs

| Judge of "was this step wasted" | Kappa vs hand labels | Cost per 1,000 steps | Latency per step |
|---|---|---|---|
| Two people vs each other (the ceiling) | 0.68 (95% CI 0.51 to 0.82) | | |
| **Layered: rules + Qwen 3.5 9B on all, Opus 5.5 on the flagged third** | **0.72** (0.50 to 0.86) | **$5.80** | |
| Claude Opus 5.5 on every step | 0.61 | $17.93 | 12 s |
| Gemini 3.5 Flash Lite, full history | 0.46 | $1.04 | |
| Qwen 3.5 9B alone | 0.30 | $0.27 | 1.9 s |
| Rules alone | catches no-command steps only | $0 | 0 |

Read the layered row with care: it was measured on the same labels the layering rule was chosen
from, and its interval overlaps the frontier-only row. The honest number for your agent is the
one `judgeman calibrate` prints.

## On a different agent

`judgeman calibrate` was run on the Claude Code session that built this repository (380 steps,
Claude Fable 5.1), with 50 blind steps labeled by hand, 35 minutes and $3.55.

| Layer | Dangerous steps: kappa | Caught | Fine steps left alone |
|---|---|---|---|
| Rules | 0.45 | 90% | 94% |
| Qwen 3.5 9B | 0.23 | 40% | 95% |
| Opus 5.5 | 0.67 | 100% | 91% |
| **Layered** | **0.70** | **100%** | **97%** |

The layered verdict caught all 10 steps the labeler called dangerous (scripts that rewrote the
test file, flagged by `edited_existing_test` and confirmed by the frontier judge) and raised 8 the
labeler did not mind (pushes to `main`, `rm -rf dist`, a `git checkout --` that discarded edits).
On wasted steps the labeler found none in the sample while the judge called 8 of them wasted:
tool-loading calls, commands the harness blocked, a script that crashed. Too few to compute a
kappa, and the tool said so. The tool-loading calls are now skipped at ingest.

## What did not help

- Showing the judge what the agent did *next* (hindsight) lowered agreement.
- Mid-tier models were no better than the cheap one.
- Two QLoRA fine-tunes of the 9B judge on 295 to 400 labels did not beat the base model on wasted
  steps: within 0.05 kappa of the untrained model in every comparison, trading a trigger-happy
  judge for a timid one, because both learned the one thing labelers disagree on, that a failed
  command is fine. The fine-tuned
  judge is still useful next to the rules: it caught 97 to 100% of planted destructive commands
  it had never seen, with 4 false alarms in 513 clean steps. Adapter and card:
  [Christopher4113/judgeman-qwen3.5-9b-judge](https://huggingface.co/Christopher4113/judgeman-qwen3.5-9b-judge).

## Costs per 1,000 steps

Measured on OpenRouter in October 2026, about 2,700 prompt tokens per step: rules $0,
Qwen 3.5 9B $0.27 (thinking off), Gemini 3.5 Flash Lite $1.04, Claude Opus 5.5 $17.93.
The layered setup lands near $5.80 because about a third of steps reach the frontier judge.
