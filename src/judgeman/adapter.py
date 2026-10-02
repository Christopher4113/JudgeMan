"""Reads mini-SWE-agent v2 trajectories (tool-call format) into Trajectory objects.

Message shape differs by provider (OpenAI Responses, chat completions), so this
reads only the `extra` block that mini-SWE-agent itself writes.
"""

import json
import re
from pathlib import Path

from .schema import Step, Trajectory

SUBMIT_MARKER = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text") or "" for p in content if isinstance(p, dict))
    return ""


def _thought(msg: dict) -> str:
    parts = [msg.get("reasoning_content") or msg.get("reasoning") or "", _text(msg.get("content"))]
    for item in msg.get("output") or []:  # OpenAI Responses shape
        if isinstance(item, dict) and item.get("type") == "message":
            parts.append(_text(item.get("content")))
    return "\n".join(p.strip() for p in parts if isinstance(p, str) and p.strip())


def _task(messages: list[dict]) -> str:
    text = next((_text(m.get("content")) for m in messages if m.get("role") == "user"), "")
    # mini-SWE-agent wraps the issue in tags and follows it with agent instructions
    match = re.search(r"<pr_description>(.*?)</pr_description>", text, re.S)
    if not match:
        return text
    return match.group(1).replace("Consider the following PR description:", "", 1).strip()


def parse_trajectory(data: dict, fallback_id: str = "") -> Trajectory:
    messages = data["messages"]
    info = data.get("info", {})
    outputs = {}
    for m in messages:
        call_id = m.get("tool_call_id") or m.get("call_id")
        if call_id and "returncode" in m.get("extra", {}):
            outputs[call_id] = m

    steps: list[Step] = []
    for m in messages:
        extra = m.get("extra") or {}
        if extra.get("interrupt_type") == "FormatError":
            # the rejected model reply is not saved, only the error sent back
            steps.append(Step(index=len(steps), output=_text(m.get("content"))))
        for action in extra.get("actions") or []:
            out = outputs.get(action.get("tool_call_id"), {})
            out_extra = out.get("extra", {})
            command = action.get("command", "")
            rc = out_extra.get("returncode")
            steps.append(
                Step(
                    index=len(steps),
                    thought=_thought(m),
                    command=command,
                    output=out_extra.get("raw_output") or _text(out.get("content")),
                    returncode=int(rc) if rc is not None else None,
                    is_submit=SUBMIT_MARKER in command,
                )
            )

    config = info.get("config", {})
    model = str(config.get("model", {}).get("model_name", ""))
    instance = data.get("instance_id") or fallback_id
    return Trajectory(
        # the same task is attempted by several models, so the model is part of the id
        id=f"{instance}@{model}" if model else instance,
        task=_task(messages),
        steps=steps,
        exit_status=info.get("exit_status") or "",
        submission=info.get("submission") or "",
        model=model,
    )


def load_results(path: Path) -> dict[str, bool]:
    """Accepts per_instance_details.json ({id: {resolved}}) or {"resolved": [ids]}."""
    data = json.loads(path.read_text())
    if isinstance(data.get("resolved"), list):
        return {i: True for i in data["resolved"]} | {
            i: False for i in data.get("unresolved", []) + data.get("no_generation", [])
        }
    return {k: bool(v["resolved"]) for k, v in data.items() if isinstance(v, dict)}


def load_trajectories(path: Path, results: Path | None = None) -> list[Trajectory]:
    files = sorted(path.rglob("*.traj.json")) if path.is_dir() else [path]
    beside = (path if path.is_dir() else path.parent) / "per_instance_details.json"
    if results is None and beside.exists():
        results = beside
    resolved = load_results(results) if results else {}
    trajs = []
    for f in files:
        t = parse_trajectory(json.loads(f.read_text()), fallback_id=f.name.split(".")[0])
        t.resolved = resolved.get(t.id.split("@")[0])
        trajs.append(t)
    return trajs
