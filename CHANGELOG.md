# Changelog

## 0.1.1 (2026-10-09)
- `judge` keeps its partial verdicts when the provider refuses a call for credit or key-limit reasons, and reports how many flagged steps the frontier judge did not reach.
- The Claude Code adapter skips tool-loading calls, which are harness plumbing rather than agent steps.

## 0.1.0 (2026-10-09)
- First release: adapters for Claude Code, OpenAI Agents SDK, OpenTelemetry and mini-SWE-agent; `judge`, `report`, `gate`, `calibrate`, `show`, `eval`, `label`, `agree`, `fetch`, `demo`.
