"""Reads OpenAI Agents SDK session items into a Trajectory.

Accepts the list returned by `session.get_items()` / `result.to_input_list()`, or a JSON object
holding it under "items" (optionally with "task" and "model"). A step is one `function_call` and
its `function_call_output`. Tools named like run_bash / read_file / write_file become commands
the checks understand; anything else keeps its name and arguments.
"""

import json
import re
from pathlib import Path

from .schema import Step, Trajectory

RETURNCODE = re.compile(r"<returncode>(-?\d+)</returncode>")


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text") or b.get("summary") or "" for b in content if isinstance(b, dict)
        )
    return ""


def command_for(name: str, args: dict) -> str:
    low = name.lower()
    if any(k in low for k in ("bash", "shell", "terminal", "exec")):
        return str(args.get("command") or args.get("cmd") or json.dumps(args))
    path = args.get("path") or args.get("file_path") or args.get("filename") or ""
    if "read" in low and path:
        return f"Read {path}"
    if any(k in low for k in ("write", "edit", "replace", "patch")) and path:
        return f"Edit {path}"
    return f"{name} {json.dumps(args, sort_keys=True)[:200]}"


def parse_items(items: list[dict], session_id: str, task: str = "", model: str = "") -> Trajectory:
    outputs = {i.get("call_id"): i for i in items if i.get("type") == "function_call_output"}
    steps: list[Step] = []
    thought = ""
    for item in items:
        kind = item.get("type") or item.get("role")
        if kind == "user" and not task:
            task = _text(item.get("content"))
        elif kind in ("message", "reasoning"):
            text = _text(item.get("content") or item.get("summary"))
            thought = text or thought
        elif kind == "function_call":
            try:
                args = json.loads(item.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"raw": item.get("arguments")}
            out = outputs.get(item.get("call_id"), {})
            output = _text(out.get("output"))
            m = RETURNCODE.search(output)
            steps.append(
                Step(
                    index=len(steps),
                    thought=thought,
                    command=command_for(str(item.get("name")), args),
                    output=RETURNCODE.sub("", output, count=1).strip() if m else output,
                    returncode=int(m[1]) if m else (1 if "error" in str(out.get("status", "")) else 0),
                )
            )
            thought = ""
    return Trajectory(id=f"{session_id}@{model}" if model else session_id, task=task, steps=steps,
                      exit_status="ended", model=model)  # fmt: skip


def load_items(path: Path) -> Trajectory:
    data = json.loads(path.read_text())
    items = data["items"] if isinstance(data, dict) else data
    meta = data if isinstance(data, dict) else {}
    return parse_items(items, path.name.split(".")[0], meta.get("task", ""), meta.get("model", ""))
