"""Reads Claude Code session logs (~/.claude/projects/<project>/<session>.jsonl) into Trajectories.

A step is one tool call and its result. Bash calls keep their command; other tools become a
pseudo-command the checks understand, such as `Read path`, `Edit path` or `Grep pattern`, so the
same rules run on every agent. Subagent side chains are skipped.
"""

import json
from pathlib import Path

from .schema import Step, Trajectory

READ_TOOLS = {"Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch", "NotebookRead"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Harness plumbing, not a decision of the agent. Calibrating on a real session, every "wasted"
# verdict on one of these was rejected by the labeler: they load tool schemas and print nothing.
PLUMBING = {"ToolSearch"}


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return ""


def pseudo_command(name: str, args: dict) -> str:
    """One line the checks can classify. Bash is passed through unchanged."""
    if name == "Bash":
        return str(args.get("command", ""))
    path = args.get("file_path") or args.get("notebook_path") or args.get("path") or ""
    if name == "Read" and args.get("offset") is not None:
        end = int(args["offset"]) + int(args.get("limit") or 2000) - 1
        return f"Read {path} {args['offset']}-{end}"
    if name in READ_TOOLS | EDIT_TOOLS:
        target = path or args.get("pattern") or args.get("url") or args.get("query") or ""
        return f"{name} {target}".strip()
    short = json.dumps(args, sort_keys=True)[:200]
    return f"{name} {short}"


def parse_session(lines: list[dict], session_id: str) -> Trajectory:
    results: dict[str, dict] = {}
    for row in lines:
        for block in (row.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                results[block.get("tool_use_id")] = block
    steps: list[Step] = []
    task, model = "", ""
    for row in lines:
        if row.get("isSidechain") or row.get("type") not in ("user", "assistant"):
            continue
        message = row.get("message") or {}
        content = message.get("content") or []
        if row["type"] == "user" and not task and isinstance(content, (str, list)):
            if not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content or []):
                task = _text(content).strip()
            continue
        if row["type"] != "assistant":
            continue
        model = model or str(message.get("model") or "")
        thought = _text(content).strip()
        for block in content if isinstance(content, list) else []:
            if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                continue
            if block.get("name") in PLUMBING:
                continue
            result = results.get(block.get("id"), {})
            output = _text(result.get("content"))
            failed = bool(result.get("is_error"))
            steps.append(
                Step(
                    index=len(steps),
                    thought=thought,
                    command=pseudo_command(str(block.get("name")), block.get("input") or {}),
                    output=output,
                    returncode=1 if failed else 0,
                )
            )
    return Trajectory(id=f"{session_id}@{model}" if model else session_id, task=task, steps=steps,
                      exit_status="ended", model=model)  # fmt: skip


def load_session(path: Path) -> Trajectory:
    lines = []
    for line in path.read_text().splitlines():
        try:
            lines.append(json.loads(line))
        except json.JSONDecodeError:  # a session still being written ends mid-line
            continue
    return parse_session(lines, path.stem)
