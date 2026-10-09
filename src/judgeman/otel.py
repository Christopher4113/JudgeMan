"""Reads OpenTelemetry spans of an agent run into a Trajectory.

Accepts spans as JSON lines (one span per line, as the OTel SDK's `to_json` writes them), a JSON
list of such spans, or an OTLP export (`{"resourceSpans": [...]}`). Tool calls are recognised by
either convention in use today: OpenInference (`openinference.span.kind = TOOL`) or the OTel GenAI
semantic conventions (`gen_ai.operation.name = execute_tool`). A step is one tool span; its
thought is the text of the model reply that led to it.
"""

import json
from pathlib import Path

from .agents_sdk import RETURNCODE, command_for
from .schema import Step, Trajectory


def _flatten(data) -> list[dict]:
    """Spans in any of the three shapes, as {name, start, parent, attributes} dicts."""
    if isinstance(data, dict) and "resourceSpans" in data:  # OTLP JSON
        out = []
        for rs in data["resourceSpans"]:
            for ss in rs.get("scopeSpans", []):
                for s in ss.get("spans", []):
                    attrs = {a["key"]: _value(a.get("value")) for a in s.get("attributes", [])}
                    start = int(s.get("startTimeUnixNano", 0))
                    out.append({"name": s.get("name"), "start": start, "attributes": attrs})
        return out
    spans = data if isinstance(data, list) else [data]
    return [
        {"name": s.get("name"), "start": s.get("start_time", ""), "attributes": s.get("attributes", {})}
        for s in spans
    ]


def _value(v):
    if not isinstance(v, dict):
        return v
    for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if key in v:
            return v[key]
    return json.dumps(v)


def _is_tool(a: dict) -> bool:
    return a.get("openinference.span.kind") == "TOOL" or a.get("gen_ai.operation.name") == "execute_tool"


def _is_llm(a: dict) -> bool:
    kind, op = a.get("openinference.span.kind"), a.get("gen_ai.operation.name")
    return kind == "LLM" or op in ("chat", "text_completion")


def _llm_reply(a: dict) -> str:
    """The model's visible text in this turn, if any. Tool-call turns usually have none."""
    for i in range(8):  # OpenInference flattens messages into numbered keys
        text = a.get(f"llm.output_messages.{i}.message.content")
        if text:
            return str(text)
    out = a.get("gen_ai.output.messages")
    return "" if out is None or str(out).startswith(("[", "{")) else str(out)[:2000]


def _first_user(a: dict) -> str:
    for i in range(8):
        if a.get(f"llm.input_messages.{i}.message.role") == "user":
            return str(a.get(f"llm.input_messages.{i}.message.content") or "")
    return ""


def parse_spans(data, run_id: str) -> Trajectory:
    spans = sorted(_flatten(data), key=lambda s: str(s["start"]))
    steps: list[Step] = []
    task, model, thought = "", "", ""
    for s in spans:
        a = s["attributes"]
        if _is_llm(a):
            model = model or str(a.get("llm.model_name") or a.get("gen_ai.request.model") or "")
            task = task or _first_user(a) or str(a.get("gen_ai.prompt") or "")
            thought = _llm_reply(a)
        elif _is_tool(a):
            name = str(a.get("tool.name") or a.get("gen_ai.tool.name") or s["name"])
            raw = a.get("input.value") or a.get("gen_ai.tool.call.arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except (json.JSONDecodeError, TypeError, ValueError):
                args = {"raw": str(raw)}
            output = str(a.get("output.value") or a.get("gen_ai.tool.call.result") or "")
            m = RETURNCODE.search(output)
            steps.append(
                Step(
                    index=len(steps),
                    thought=thought,
                    command=command_for(name, args),
                    output=RETURNCODE.sub("", output, count=1).strip() if m else output,
                    returncode=int(m[1]) if m else 0,
                )
            )
            thought = ""
    return Trajectory(id=f"{run_id}@{model}" if model else run_id, task=task, steps=steps,
                      exit_status="ended", model=model)  # fmt: skip


def load_spans(path: Path) -> Trajectory:
    text = path.read_text()
    if path.suffix == ".jsonl":
        data = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        data = json.loads(text)
    return parse_spans(data, path.name.split(".")[0])
