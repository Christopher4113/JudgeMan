# Changelog

## Unreleased
- Steps carry the token count of the model call that made them, read from OTel spans and Claude Code sessions. `show` and `report` price the flagged steps: how many of the run's tokens went to them.

## 0.1.2 (2026-10-10)
- A judgeman label file (`--out`) sitting beside the logs is no longer read as a run.
- The example runs count once each; their OTel copies now name the same model as the Agents SDK copies.
- `judgeman show` puts the layered verdict and its critique first, as the HTML report does.
- `from judgeman import Trajectory, Step, judge_runs, gate, render` for logs in any other format.

## 0.1.1 (2026-10-09)
- `judge` keeps its partial verdicts when the provider refuses a call for credit or key-limit reasons, and reports how many flagged steps the frontier judge did not reach.
- The Claude Code adapter skips tool-loading calls, which are harness plumbing rather than agent steps.

## 0.1.0 (2026-10-09)
- First release: adapters for Claude Code, OpenAI Agents SDK, OpenTelemetry and mini-SWE-agent; `judge`, `report`, `gate`, `calibrate`, `show`, `eval`, `label`, `agree`, `fetch`, `demo`.
