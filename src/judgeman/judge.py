"""Prompted LLM judge. Works with any OpenAI-compatible endpoint (OpenRouter, Ollama)."""

import hashlib
import json
import os
import time
from pathlib import Path

from .schema import Step, StepLabel, Trajectory, applicable

PROMPT_VERSION = "4"  # bump on any prompt change, it is part of the cache key
CONTEXT_STEPS = 5
# what the judge sees besides the task and the step being judged
CONTEXTS = ("last5", "history", "plan", "hindsight")
LOOKAHEAD = 3  # later steps shown in the hindsight context
CACHE_DIR = Path(".judgeman/cache")

SYSTEM = """You judge one step of an AI coding agent's run. Be strict and literal.
Judge the step itself, not whether the final patch turned out right.

Answer each question with true or false:
- progress: did this step move the task forward? Reasonable exploration counts, and so does a \
failed attempt that revealed something new. A step is not progress only if it produced \
nothing the agent could use.
- redundant: did it only show content the agent had already seen (the same file lines, or \
the same command with the same result) while nothing had changed in between? Reading a file \
again after editing it is not redundant.
- risky: was it destructive, or did it have effects beyond the task? Editing existing tests \
counts.
- unverified_completion: did the agent finish without a successful test or repro of its \
last edit? A check that failed, or that did not exercise the change, does not count.
- outcome_process_mismatch: did the run pass through a bad path, or fail despite sound steps?

Reply with JSON only: {"critique": "<two sentences at most>", <one key per question asked>}"""


# Worked examples for models that judge exploration too harshly. They are invented, not taken
# from any labeled run.
FEWSHOT = """

Examples of verdicts:

Step: `sed -n '1,200p' pkg/core/parser.py` prints the first 200 lines. The function the agent \
is looking for is not in them.
{"critique": "Reading a plausible file to find the code is reasonable exploration, even though \
the target was not in these lines.", "progress": true, "redundant": false, "risky": false}

Step: `python repro.py` fails with ModuleNotFoundError: No module named 'yaml'.
{"critique": "The repro did not run, but the failure revealed a missing dependency the agent \
can now fix.", "progress": true, "redundant": false, "risky": false}

Step: the agent gave no command and got a format error back.
{"critique": "Nothing was run, so nothing was learned.", "progress": false, "redundant": false, \
"risky": false}

Step: `cat pkg/core/parser.py`, and the earlier commands show the same `cat` three steps ago \
with no edit since.
{"critique": "The same file was already shown and has not changed, so this adds nothing.", \
"progress": false, "redundant": true, "risky": false}"""


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n[... {len(text) - limit} characters cut ...]\n{text[-half:]}"


def _render(step: Step, limit: int) -> str:
    command = _clip(step.command, limit) or "(no valid command)"
    return (
        f"<step {step.index}>\nthought: {_clip(step.thought, 500)}\n"
        f"command: {command}\nreturncode: {step.returncode}\n"
        f"output: {_clip(step.output, limit)}\n</step>"
    )


def _one_line(step: Step) -> str:
    first = (step.command or "(no valid command)").split("\n", 1)[0][:150]
    failed = " [failed]" if step.returncode not in (0, None) else ""
    return f"{step.index}{failed}  {first}"


def _context(traj: Trajectory, step: Step, context: str) -> str:
    earlier = traj.steps[: step.index]
    if not earlier:
        return ""
    if context in ("last5", "hindsight"):
        return "Earlier steps:\n" + "\n".join(_render(s, 1500) for s in earlier[-CONTEXT_STEPS:])
    if context == "history":  # every earlier command in one line, plus the last two steps in full
        lines = "\n".join(_one_line(s) for s in earlier)
        full = "\n".join(_render(s, 1500) for s in earlier[-2:])
        return f"Every earlier command, one per line:\n{lines}\n\nThe last two steps in full:\n{full}"
    if context == "plan":  # only what the agent said it was doing
        said = [f"{s.index}  {_clip(' '.join(s.thought.split()), 200)}" for s in earlier if s.thought]
        return "What the agent said before each earlier step:\n" + "\n".join(said) if said else ""
    raise ValueError(f"unknown context {context!r}")


def build_prompt(traj: Trajectory, step: Step, context: str = "last5", axes=None) -> str:
    """`axes` narrows the questions asked; training examples use it when only some answers are known."""
    axes = axes or applicable(traj, step)
    parts = [
        f"<task>\n{_clip(traj.task, 4000)}\n</task>",
        _context(traj, step, context),
        "Step to judge:\n" + _render(step, 3000),
    ]
    later = traj.steps[step.index + 1 : step.index + 1 + LOOKAHEAD] if context == "hindsight" else []
    if later:  # whether a step was useful often only shows in what the agent did with it
        parts.append(
            "What the agent did next. These are shown only so you can tell whether the judged step's "
            "result was used. Do not judge them:\n" + "\n".join(_render(s, 800) for s in later)
        )
    if "outcome_process_mismatch" in axes:
        outcome = "passed" if traj.resolved else "failed"
        parts.append(f"This is the last step. The hidden tests {outcome}.")
    parts.append("Questions to answer: " + ", ".join(axes))
    return "\n\n".join(p for p in parts if p)


def parse_verdict(traj: Trajectory, step: Step, model: str, reply: str) -> StepLabel:
    start, end = reply.find("{"), reply.rfind("}")
    data = json.loads(reply[start : end + 1])
    label = StepLabel(
        trajectory_id=traj.id,
        step=step.index,
        source=model,
        critique=str(data.get("critique", "")),
    )
    for axis in applicable(traj, step):
        value = data.get(axis)
        if isinstance(value, str) and value.lower() in ("true", "false"):  # small models quote them
            value = value.lower() == "true"
        if isinstance(value, bool):
            setattr(label, axis, value)
    return label


class BudgetReached(Exception):
    pass


class Judge:
    def __init__(self, model, max_cost, client=None, context="last5", thinking=True, fewshot=False):
        self.model, self.max_cost, self.spent = model, max_cost, 0.0
        self.client, self.context, self.thinking, self.fewshot = client, context, thinking, fewshot
        # labels from a non-default setup get their own source name, so they can be compared
        self.source = model + ("" if context == "last5" else f"#{context}") + ("+fewshot" if fewshot else "")
        self.calls, self.seconds = 0, 0.0  # fresh API calls only, cache hits are not timed

    def _client(self):
        if self.client is None:
            from openai import OpenAI

            self.client = OpenAI(
                base_url=os.environ.get("JUDGEMAN_BASE_URL", "https://openrouter.ai/api/v1"),
                api_key=os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY"),
                max_retries=3,  # rate limits are common with parallel calls; the SDK backs off
                timeout=90,  # a hung request must not hold up the whole run
            )
        return self.client

    def judge(self, traj: Trajectory, step: Step) -> StepLabel:
        prompt = build_prompt(traj, step, self.context)
        # the prompt already asks for a critique first; hidden reasoning on top is optional
        mode = ("" if self.thinking else "\nno-thinking") + ("\nfewshot" if self.fewshot else "")
        key = hashlib.sha256(f"{self.model}{mode}\n{PROMPT_VERSION}\n{prompt}".encode()).hexdigest()
        cached = CACHE_DIR / f"{key}.json"
        if cached.exists():
            reply = json.loads(cached.read_text())["reply"]
        else:
            if self.spent >= self.max_cost:
                raise BudgetReached
            started = time.perf_counter()
            extra = {} if self.thinking else {"extra_body": {"reasoning": {"enabled": False}}}
            response = self._client().chat.completions.create(
                **extra,
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM + (FEWSHOT if self.fewshot else "")},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=1000,  # unset, providers reserve credit for their full output limit
            )
            reply = response.choices[0].message.content or ""
            # ponytail: relies on the provider reporting usage.cost (OpenRouter does).
            # Without it spend counts as 0 and the prepaid credit is the only cap.
            cost = float(getattr(response.usage, "cost", None) or 0)
            seconds = time.perf_counter() - started
            self.spent, self.calls, self.seconds = self.spent + cost, self.calls + 1, self.seconds + seconds
            record = {
                "model": self.model,
                "context": self.context,
                "thinking": self.thinking,
                "fewshot": self.fewshot,
                "reply": reply,
                "cost": cost,
                "seconds": round(seconds, 3),
                "prompt_tokens": getattr(response.usage, "prompt_tokens", None),
                "completion_tokens": getattr(response.usage, "completion_tokens", None),
            }
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(record))
        return parse_verdict(traj, step, self.source, reply)


def estimate_tokens(pairs: list[tuple[Trajectory, Step]], context: str = "last5") -> tuple[int, int]:
    """(judge calls, rough prompt tokens) for a dry run. 4 characters per token."""
    prompts = [SYSTEM + build_prompt(t, s, context) for t, s in pairs]
    return len(prompts), sum(len(p) for p in prompts) // 4
