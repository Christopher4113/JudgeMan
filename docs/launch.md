# Launch material

Drafts to post from, by Christopher Lam. Numbers come from the two reports in `reports/`;
anything in square brackets is for you to fill in or cut. The $29 spend is the whole project,
all three legs, on OpenRouter plus a free Kaggle T4.

## What Leg 3 added (for your own write-up)

Legs 1 and 2 answered "can a judge be trusted on agent steps, and which one". Leg 3 turned that
into something a person can run on their own agent in five minutes:

- **Ingest.** Four log formats read into one step model: Claude Code sessions straight from
  `~/.claude/projects`, OpenAI Agents SDK session items, OpenTelemetry spans (both the
  OpenInference and the GenAI conventions), and mini-SWE-agent trajectories. Non-shell tools
  become pseudo-commands (`Read path`, `Edit path`) so the same rules run on every agent.
- **`judgeman judge`.** The layered pipeline from Leg 2 as one command: rules on every step, a
  9B open judge on every step, a frontier judge only on the third of steps either flagged.
  Dollar-capped, cached, dry-run first.
- **`judgeman calibrate`.** The published trust numbers are for SWE-bench runs. This has you label
  50 blind steps of your own judged runs (half flagged, half not, reweighted) and prints agreement
  per axis and per layer with one line of advice each: trust, use with care, or do not rely on.
- **`judgeman report`.** One HTML file, no JavaScript, no network: every run step by step, flags,
  each judge's verdict, the critique behind a flag, a checkbox for flagged steps only.
- **`judgeman gate`.** Exit 1 in CI on any dangerous or unverified step; opt in to a wasted-step
  budget with the judged labels.
- **Release.** PyPI package, the fine-tuned adapter on Hugging Face with its card, README with
  the trust table and the known gaps.

What is deliberately not in it: no dashboard, no hosted service, no hindsight context (it
lowered agreement), no judging of failed commands (two people agree on those at kappa 0.39, so
they are reported as their own kind instead).

## Show HN

**Title:** Show HN: Judgeman – step-level evals for coding agents, with a measured trust number

judgeman reads every step of an agent run (Claude Code, OpenAI Agents SDK, anything with OTel
spans, mini-SWE-agent) and flags the steps that were wasted, repeated, dangerous, or submitted
without a passing check. The part I care about most: it tells you how often its verdicts match a
person's, and has you measure that on your own agent instead of trusting my number.

How I got the numbers. I hand-labeled 516 steps from published mini-SWE-agent runs on SWE-bench
Verified, got a second person to label 300 of them, and planted 196 mistakes in real runs to
measure recall on things that never happen in a sandbox. Then I ran rules, a 9B open model,
Gemini Flash Lite and Claude Opus 5.5 over the same steps.

Findings:

- Two careful people agree on "was this step wasted" at kappa 0.68. That is the ceiling any judge
  is measured against, and it is lower than I expected.
- Opus alone reaches 0.61 at about $18 per 1,000 steps. A 9B model alone reaches 0.30 at $0.27.
- Rules plus the 9B model on every step, with Opus asked only about the third they flag, reaches
  0.72 at $5.80. That interval overlaps Opus alone and it was tuned on the same labels, so I
  report it as promising, not proven; the calibrate command exists so you can check it on
  your runs.
- Almost all the disagreement, human or model, is about failed commands: was the error useful?
  So judgeman reports failed commands as their own category and does not judge them.
- Showing the judge what the agent did next made it worse. Fine-tuning the 9B model on 400 labels
  did not beat the base model, because it learned the one thing labelers disagree on.

Whole project cost $29 in API credit and a free Kaggle T4. Code, labels, every judge's verdicts
and the two reports are in the repo. `pip install 'judgeman[judge]'`.

https://github.com/Christopher4113/JudgeMan

## r/LocalLLaMA

**Title:** I measured how far you can trust a 9B model to judge coding-agent steps (and when to
escalate to a frontier model). Code, labels and a QLoRA adapter included.

Body:

I built a step-level eval for coding agents and spent most of the effort on one question: when
a judge says "this step was wasted", how often would a person agree?

Setup: 516 hand-labeled steps from public mini-SWE-agent runs on SWE-bench Verified, a second
labeler on 300 of them, 196 runs with planted mistakes (destructive commands, repeats, edited
tests, unverified submissions).

What the small model is and isn't good for:

- Qwen 3.5 9B alone on "wasted step": kappa 0.30 vs humans, $0.27 per 1,000 steps, 1.9 s a step.
  Not enough to act on by itself.
- Qwen 9B as a *filter*: rules + Qwen flag about a third of steps, Claude Opus 5.5 looks only at
  those. Kappa 0.72 vs 0.61 for Opus on everything, at a third of the cost. Caveat: tuned and
  measured on the same labels, interval 0.50 to 0.86.
- QLoRA fine-tune (unsloth, Kaggle T4, 295 to 400 labels): did not beat base on wasted steps
  (0.22 and 0.18 vs 0.20). Both runs learned "failed command = fine", which is exactly where the
  two human labelers disagree (kappa 0.39 on failed commands, 0.66 on commands that ran). Lesson:
  do not fine-tune on an axis your labelers have not settled.
- The fine-tuned model is good at one thing: with the rules, it caught 97 to 100% of planted
  destructive commands it had never seen, with 4 false alarms in 513 clean steps. Adapter on HF:
  https://huggingface.co/Christopher4113/judgeman-qwen3.5-9b-judge
- No-thinking mode matters for the 9B judge: with reasoning on it burned the whole output budget
  before answering.

Works with Ollama (`JUDGEMAN_BASE_URL=http://localhost:11434/v1`), Claude Code session logs,
Agents SDK, OTel spans. `judgeman calibrate` has you label 50 of your own steps and tells you how
far to trust each layer on your agent, which is the number I would actually use.

Repo with labels, every verdict and two PDF reports: https://github.com/Christopher4113/JudgeMan

## LinkedIn

I spent two weeks and $29 finding out how far you can trust an LLM to grade an AI coding agent's
work step by step.

The result is judgeman, an open-source tool that reads an agent's run (Claude Code, OpenAI Agents
SDK, OpenTelemetry, SWE-bench trajectories), flags wasted, repeated, dangerous and unverified
steps, and, the part I think matters, tells you how often a person would agree with it.

Three things I learned:

1. People agree with each other less than you'd hope. Two careful labelers hit kappa 0.68 on
   "was this step wasted". Any judge is measured against that ceiling, not against perfection.
2. The expensive model is not the best setup. Rules and a 9B open model on every step, with the
   frontier model consulted only on the third they flag, matched or beat the frontier model alone
   at a third of the cost.
3. Fine-tuning on labels people disagree about teaches the model the disagreement. Settle the
   rule first, then train.

It ships with a calibration command so you measure trust on your own agent instead of taking my
number. pip install judgeman. Repo, labels and both reports in the comments.

[comment: https://github.com/Christopher4113/JudgeMan]

## X

1/ I hand-labeled 516 steps of coding-agent runs to find out how far an LLM judge can be trusted
on each step. Built it into a tool: judgeman. Thread.

2/ Two people agree on "was this step wasted" at kappa 0.68. That's the ceiling. Claude Opus 5.5
alone: 0.61. A 9B open model alone: 0.30.

3/ Rules + the 9B model on every step, Opus only on the third they flag: 0.72 at a third of the
cost. (Tuned on the same labels, wide interval, so: promising, and there's a calibrate command
to check it on your own agent.)

4/ Nearly all disagreement, human or model, is about failed commands. Was the error useful? So
judgeman reports them as their own kind and refuses to judge them.

5/ Showing the judge what the agent did next made it worse. Fine-tuning the 9B on 400 labels
didn't beat base: it learned the one thing labelers disagree on.

6/ Reads Claude Code sessions, OpenAI Agents SDK, OTel spans, SWE-bench runs. HTML report, CI
gate, $29 total spend. pip install judgeman
https://github.com/Christopher4113/JudgeMan

## Discord (short, same text for each server, adjust the first line to the channel)

Sharing something I built: judgeman, step-level evals for coding agents with a measured trust
number. It reads Claude Code / Agents SDK / OTel logs, flags wasted, repeated, dangerous and
unverified steps, and has a calibrate command that tells you how far to trust each judge layer on
your own agent after you label 50 steps. Main findings from 516 hand labels: two humans agree at
kappa 0.68, Opus alone 0.61, a 9B model as a filter in front of Opus 0.72 at a third of the cost,
and failed commands are where everyone disagrees. Code, labels, verdicts and reports:
https://github.com/Christopher4113/JudgeMan. Happy to answer questions about the labeling or the
fine-tune that didn't work.

[server 1: thread link]
[server 2: thread link]
[server 3: thread link]
