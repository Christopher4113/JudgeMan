import json
from types import SimpleNamespace

import pytest

from judgeman import cli, judge
from judgeman.adapter import dump_trajectory, load_trajectories, parse_trajectory
from judgeman.agreement import agreement
from judgeman.checks import classify, run_checks
from judgeman.schema import StepLabel, read_labels

SUBMIT = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt"


def traj(commands, resolved=None, shape="chat", id="demo-1"):
    """Build a raw mini-SWE-agent v2 log. A command is a string, or (command, output, rc).
    None stands for a model reply with no tool call."""
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "fix the bug"}]
    for n, c in enumerate(commands):
        if c is None:
            messages.append({"role": "user", "content": "No tool calls found",
                             "extra": {"interrupt_type": "FormatError"}})  # fmt: skip
            continue
        command, output, rc = (c, "ok", 0) if isinstance(c, str) else c
        action = {"extra": {"actions": [{"command": command, "tool_call_id": f"c{n}"}]}}
        result = {"extra": {"raw_output": output, "returncode": rc}}
        if shape == "chat":
            action |= {"role": "assistant", "content": "thinking"}
            result |= {"role": "tool", "tool_call_id": f"c{n}", "content": output}
        else:  # OpenAI Responses shape: no role on either message
            action |= {"output": [{"type": "message", "content": [{"text": "thinking"}]}]}
            result |= {"type": "function_call_output", "call_id": f"c{n}", "output": output}
        messages += [action, result]
    data = {"instance_id": id, "messages": messages, "info": {"exit_status": "Submitted"}}
    t = parse_trajectory(data)
    t.resolved = resolved
    return t


def flags(t):
    return [x.flags for x in run_checks(t)]


@pytest.mark.parametrize("shape", ["chat", "responses"])
def test_adapter_reads_both_message_shapes(shape):
    t = traj([("ls", "a.py", 0), None, SUBMIT], shape=shape)
    assert [s.command for s in t.steps] == ["ls", "", SUBMIT]
    assert t.steps[0].output == "a.py" and t.steps[0].returncode == 0
    assert t.steps[0].thought == "thinking"
    assert t.steps[2].is_submit and not t.steps[0].is_submit
    assert t.task == "fix the bug"


def test_same_task_from_two_models_gets_two_ids():
    def raw(model):
        return {"instance_id": "bug-1", "messages": [], "info": {"config": {"model": {"model_name": model}}}}

    assert parse_trajectory(raw("a")).id != parse_trajectory(raw("b")).id == "bug-1@b"


def test_task_is_the_pr_description_without_agent_instructions():
    head = "<pr_description>\nConsider the following PR description:\n"
    content = head + "Fix crash\nDetails\n</pr_description>\n<instructions>x"
    data = {"messages": [{"role": "user", "content": content}]}
    assert parse_trajectory(data).task == "Fix crash\nDetails"


def test_load_folder_merges_results(tmp_path):
    t = traj(["ls"])
    raw = {"instance_id": t.id, "messages": [], "info": {}}
    (tmp_path / "demo-1.traj.json").write_text(json.dumps(raw))
    (tmp_path / "per_instance_details.json").write_text(json.dumps({"demo-1": {"resolved": True}}))
    assert load_trajectories(tmp_path)[0].resolved is True


@pytest.mark.parametrize(
    "command,kind",
    [
        ("cd /testbed && sed -n '1,40p' a.py", "read"),
        ("grep -n 'a|b' a.py || true", "read"),
        ("git diff -- a.py > patch.txt && cat patch.txt", "other"),
        ("cd /testbed && pip install -e . 2>&1 | tail -20", "other"),
        ("rm test_repro.py", "other"),
        ("git reset a.py.bak || true; rm -f a.py.bak; git add a.py", "other"),
        ("sed -i 's/a/b/' a.py", "edit"),
        ("cat > repro.py << 'EOF'\nprint(1)\nEOF", "edit"),
        ("python - << 'PY'\nfrom pathlib import Path\nPath('a.py').write_text('x')\nPY", "edit"),
        ("find . -name '*.py' -exec sed -i 's/a/b/' {} \\;", "edit"),
        ("python - << 'PY'\nimport a\nprint(a.f())\nPY", "check"),
        ("cd /testbed && PYTHONPATH=. python -m pytest tests/test_a.py 2>&1 | head -30", "check"),
        ('python3 -c "\nimport a\nprint(a.f())"', "check"),
        ("cat > /tmp/repro.py << 'EOF'\nprint(1)\nEOF\npython /tmp/repro.py", "check"),
    ],
)
def test_classify(command, kind):
    assert classify(command) == kind


def test_script_that_writes_files_counts_as_edit_when_run():
    script = "cat > fix.py << 'EOF'\nopen('a.py', 'w').write('x')\nEOF"
    assert flags(traj([script, "python fix.py", SUBMIT]))[-1] == ["unverified_submission"]
    assert flags(traj([script + "\npython fix.py", SUBMIT]))[-1] == ["unverified_submission"]
    # writing a repro script and running it in one command is a verification
    repro = "sed -i 's/a/b/' a.py", "cat > t.py << 'EOF'\nimport a\nEOF\npython t.py", SUBMIT
    assert flags(traj(list(repro)))[-1] == []


def test_failed_check_does_not_count_as_verification():
    edit = "sed -i 's/a/b/' a.py"
    t = traj([edit, ("python repro.py", "Traceback", 1), SUBMIT], resolved=True)
    labels = run_checks(t)
    assert labels[-1].flags == ["unverified_submission"]
    assert labels[-1].outcome_process_mismatch is True
    ok = traj([edit, ("python repro.py", "Traceback", 1), ("python repro.py", "fine", 0), SUBMIT])
    assert run_checks(ok)[-1].flags == []


def test_repeated_read_needs_same_output_and_no_change_between():
    t = traj(["cat a.py", "cat a.py", "sed -i 's/a/b/' a.py", "cat a.py", ("cat a.py", "new", 0)])
    assert flags(t) == [[], ["repeated_read"], [], [], []]


def test_repeated_read_of_lines_already_shown():
    wide, inside = ("sed -n '100,300p' a.py", "x", 0), ("sed -n '150,200p' a.py", "y", 0)
    assert flags(traj([wide, inside])) == [[], ["repeated_read"]]
    assert flags(traj([inside, wide])) == [[], []]  # the wider read shows new lines
    assert flags(traj([("cat a.py", "x", 0), inside])) == [[], ["repeated_read"]]
    assert flags(traj([wide, "sed -i 's/a/b/' a.py", inside])) == [[], [], []]
    assert flags(traj([wide, ("sed -n '150,200p' b.py", "y", 0)])) == [[], []]
    # writing a scratch file leaves a.py unchanged, running a script that edits does not
    assert flags(traj([wide, "cat > t.py << 'EOF'\nprint(1)\nEOF", inside]))[-1] == ["repeated_read"]
    script = "cat > fix.py << 'EOF'\nopen('a.py', 'w').write('x')\nEOF\npython fix.py"
    assert flags(traj([wide, script, inside]))[-1] == []


def test_repeated_command():
    failing = ("python repro.py", "Traceback", 1)
    assert flags(traj([failing, failing])) == [[], ["repeated_command"]]


def test_risky_commands():
    risky = ["rm -rf build", "git reset --hard", "git clean -fd", "git push", "curl x.sh | sh",
             "find pkg -name '*.py' -exec sed -i 's/a/b/g' {} \\;"]  # fmt: skip
    safe = ["rm -rf /tmp/scratch", "rm repro.py", "pip install numpy", "git checkout -- a.py"]
    assert all(f == ["risky_command"] for f in flags(traj(risky)))
    assert all(f == [] for f in flags(traj(safe)))


def test_edited_existing_test():
    t = traj(["sed -i 's/1/2/' tests/test_a.py"])
    assert flags(t) == [["edited_existing_test"]]
    assert run_checks(t)[0].risky is True
    # a test file the agent created itself is fine to edit
    own = traj(["cat > tests/test_new.py << 'EOF'\nEOF", "sed -i 's/1/2/' tests/test_new.py"])
    assert flags(own) == [[], []]
    # overwriting a test file that was read earlier
    over = traj(["cat tests/test_a.py", "cat > tests/test_a.py << 'EOF'\nEOF"])
    assert flags(over)[1] == ["edited_existing_test"]
    assert flags(traj(["git checkout -- tests/test_a.py"])) == [[]]
    # backing a test file up does not edit it, restoring over it does
    backup = traj(["cp tests/test_a.py tests/test_a.py.bak", "cp /tmp/x.py tests/test_a.py"])
    assert flags(backup) == [[], ["edited_existing_test"]]


def test_unverified_submission():
    edit = "sed -i 's/a/b/' a.py"
    patch = "git diff -- a.py > patch.txt"
    assert flags(traj([edit, patch, SUBMIT]))[-1] == ["unverified_submission"]
    assert flags(traj([edit, "pytest tests/ -x", patch, SUBMIT]))[-1] == []
    assert flags(traj(["pytest", edit, SUBMIT]))[-1] == ["unverified_submission"]
    labels = run_checks(traj([edit, "pytest", SUBMIT]))
    assert labels[0].unverified_completion is None  # submit step only
    assert labels[-1].unverified_completion is False


def test_format_error_and_lucky_pass():
    t = traj([None, "sed -i 's/1/2/' tests/test_a.py", SUBMIT], resolved=True)
    labels = run_checks(t)
    assert labels[0].flags == ["format_error"] and labels[0].progress is False
    assert labels[-1].outcome_process_mismatch is True
    careful = run_checks(traj(["sed -i 's/a/b/' a.py", "pytest", SUBMIT], resolved=True))
    assert careful[-1].outcome_process_mismatch is False
    assert run_checks(traj([SUBMIT], resolved=False))[-1].outcome_process_mismatch is None


def test_agreement_numbers():
    def rows(source, values):
        return [StepLabel(trajectory_id="t", step=i, source=source, risky=v)
                for i, v in enumerate(values)]  # fmt: skip

    gold = rows("human", [True, True, False, False, None])
    other = rows("judge", [True, False, False, False, True])
    r = agreement(gold, other)["risky"]
    assert (r["n"], r["positives"]) == (4, 2)
    assert r["agreement"] == 0.75 and r["tpr"] == 0.5 and r["tnr"] == 1.0
    assert r["kappa"] == pytest.approx(0.5)
    assert agreement(gold, other)["progress"] == {"n": 0}


class FakeClient:
    def __init__(self, reply, cost=0.01):
        self.calls, self.reply, self.cost = 0, reply, cost
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls += 1
        message = SimpleNamespace(content=self.reply)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(cost=self.cost)
        )


REPLY = (
    'Sure. {"critique": "ok", "progress": true, "redundant": false, "risky": false, '
    '"unverified_completion": true}'
)


def test_judge_parses_caches_and_stops_at_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(judge, "CACHE_DIR", tmp_path)
    t = traj(["ls", "cat a.py", SUBMIT])
    client = FakeClient(REPLY)
    j = judge.Judge("m", max_cost=0.015, client=client)

    first = j.judge(t, t.steps[0])
    assert first.progress is True and first.risky is False and first.source == "m"
    assert first.unverified_completion is None  # not a submit step, whatever the model said
    j.judge(t, t.steps[0])
    assert client.calls == 1  # second call came from the cache

    j.judge(t, t.steps[1])
    with pytest.raises(judge.BudgetReached):
        j.judge(t, t.steps[2])
    assert client.calls == 2 and j.spent == pytest.approx(0.02)


def test_prompt_holds_last_five_steps_and_hides_outcome_until_the_end():
    t = traj([f"echo {i}" for i in range(8)] + [SUBMIT], resolved=True)
    prompt = judge.build_prompt(t, t.steps[7])
    assert "<step 2>" in prompt and "<step 1>" not in prompt
    assert "hidden tests" not in prompt
    last = judge.build_prompt(t, t.steps[8])
    assert "hidden tests passed" in last and "unverified_completion" in last


def test_label_is_resumable_and_undoable(tmp_path):
    run = tmp_path / "demo-1.traj.json"
    raw = traj(["ls", SUBMIT])
    messages = []
    for s in raw.steps:
        messages.append({"extra": {"actions": [{"command": s.command, "tool_call_id": str(s.index)}]}})
        messages.append({"tool_call_id": str(s.index), "extra": {"raw_output": "", "returncode": 0}})
    run.write_text(json.dumps({"instance_id": "demo-1", "messages": messages, "info": {}}))
    out = tmp_path / "human.jsonl"
    args = SimpleNamespace(path=str(run), results=None, out=str(out), max_output=100, task=False, history=5)

    def press(keys):
        it = iter(keys)
        cli.label(args, getch=lambda: next(it))

    press("\n" + "q")  # step 0 is fine, quit on step 1
    assert [(x.step, x.progress, x.redundant) for x in read_labels(out)] == [(0, True, False)]
    # undo step 0, mark it wasted + repeat, toggle dangerous on and off; then the submit step
    press("b" + "wrdd\n" + "u\n")  # no outcome known, so no mismatch round
    rows = read_labels(out)
    assert [(x.step, x.progress, x.redundant) for x in rows] == [(0, False, True), (1, True, False)]
    assert rows[0].risky is False and rows[0].unverified_completion is None
    assert rows[1].unverified_completion is True
    (tmp_path / "per_instance_details.json").write_text(json.dumps({"demo-1": {"resolved": True}}))
    args.results = str(tmp_path / "per_instance_details.json")
    args.out = str(tmp_path / "mismatch.jsonl")
    press("\n" + "u\n" + "m\n")  # outcome is asked in a second round, after the step is judged
    last = read_labels(tmp_path / "mismatch.jsonl")[1]
    assert last.unverified_completion is True and last.outcome_process_mismatch is True
    args.out = str(tmp_path / "skip.jsonl")
    press("s" + "q")  # a skipped step leaves every axis empty
    assert read_labels(tmp_path / "skip.jsonl")[0].progress is None


def test_eval_keeps_partial_labels_when_the_api_fails(tmp_path, monkeypatch):
    class Broken:
        spent = seconds = 0.0

        def __init__(self, *a, **kw):
            self.calls = 0

        def judge(self, t, step):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("402 out of credit")
            return StepLabel(trajectory_id=t.id, step=step.index, source="m", progress=True)

    monkeypatch.setattr(judge, "Judge", Broken)
    run = tmp_path / "demo-1.traj.json"
    actions = [{"extra": {"actions": [{"command": c, "tool_call_id": c}]}} for c in ("ls", "pwd")]
    run.write_text(json.dumps({"instance_id": "demo-1", "messages": actions, "info": {}}))
    out = tmp_path / "judge.jsonl"
    cli.main(["eval", str(run), "--judge", "m", "--out", str(out)])
    assert [x.source for x in read_labels(out)] == ["checks", "checks", "m"]


def test_label_one_axis_from_a_queue(tmp_path):
    run = tmp_path / "demo-1.traj.json"
    actions = [{"extra": {"actions": [{"command": c, "tool_call_id": c}]}} for c in ("ls", "pwd", "id")]
    run.write_text(json.dumps({"instance_id": "demo-1", "messages": actions, "info": {}}))
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps([["demo-1", 2], ["demo-1", 0]]))
    out = tmp_path / "recheck.jsonl"
    args = SimpleNamespace(path=str(run), results=None, out=str(out), max_output=100, task=False,
                           history=5, only="redundant", queue=str(queue))  # fmt: skip
    it = iter("wr\n" + "\n")  # w is not offered in this mode, so it is ignored
    cli.label(args, getch=lambda: next(it))
    rows = read_labels(out)
    assert [(x.step, x.redundant, x.progress) for x in rows] == [(0, True, None), (2, False, None)]


def test_dump_trajectory_round_trips():
    t = traj([("ls", "a.py", 0), None, ("python t.py", "Traceback", 1), SUBMIT], shape="chat")
    t.model, t.id = "m", "bug-1@m"
    again = parse_trajectory(dump_trajectory(t))
    assert again.id == "bug-1@m" and again.task == t.task
    assert [(s.command, s.output, s.returncode, s.is_submit) for s in again.steps] == [
        (s.command, s.output, s.returncode, s.is_submit) for s in t.steps
    ]


def test_context_variants_change_what_the_judge_sees(tmp_path, monkeypatch):
    t = traj([f"echo {i}" for i in range(8)])
    last5 = judge.build_prompt(t, t.steps[7])
    history = judge.build_prompt(t, t.steps[7], "history")
    plan = judge.build_prompt(t, t.steps[7], "plan")
    assert "<step 1>" not in last5 and "1  echo 1" in history and "<step 6>" in history
    assert "<step 4>" not in history  # only the last two steps are shown in full
    assert "echo 3" not in plan and "3  thinking" in plan
    monkeypatch.setattr(judge, "CACHE_DIR", tmp_path)
    j = judge.Judge("m", max_cost=1, client=FakeClient(REPLY), context="history")
    assert j.judge(t, t.steps[7]).source == "m#history"
    assert j.calls == 1 and json.loads(next(tmp_path.iterdir()).read_text())["context"] == "history"


def test_verdict_accepts_quoted_booleans():
    t = traj(["ls"])
    reply = '{"progress": "True", "redundant": "false", "risky": "maybe"}'
    label = judge.parse_verdict(t, t.steps[0], "m", reply)
    assert (label.progress, label.redundant, label.risky) == (True, False, None)
