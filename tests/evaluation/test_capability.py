"""The capability harness on the fake backend with a scripted model: the rows, the resolved rate
and its interval, the turn budget, the export left untouched, failures of the machinery kept
apart from the resident's, and a stopped evaluation continued from the command line while
another or a finished one is refused."""

import json
from pathlib import Path

import pytest

from agent.directory import AgentDirectory
from agent.runtime import RuntimeConfig
from agent.testing import reply, tool_call
from evaluation import capability
from evaluation.capability import evaluate_capability, main
from infrastructure.llm import LLMCallError, LLMRequest, ScriptedClient
from world.solo import SoloConfig
from world.testing import FakeBackend

SCRIPTS = {
    "org/repo1": [
        reply(
            "",
            tool_call("write_repo_file", path="fix.py", content="FIX\n"),
            tool_call("submit"),
            prompt_tokens=1000,
        )
    ],
    "org/repo2": [
        *(reply("", tool_call("shell", command="ls"), prompt_tokens=1000) for _ in range(3)),
        reply("", tool_call("give_up"), prompt_tokens=1000),
    ],
}
"""The second task gives up at its fourth step, beyond a budget of three requests."""


def scripted(request: LLMRequest):
    """The scripted reply of the task the request is about, at its step."""
    opening = request.messages[1].content
    repo = next(repo for repo in SCRIPTS if f"a task in {repo}." in opening)
    return SCRIPTS[repo][sum(message.role == "assistant" for message in request.messages)]


def exported(tmp_path: Path) -> Path:
    """An export with a skill, and with a session and a trace that must not carry over."""
    root = AgentDirectory.create(
        tmp_path / "export" / "Mei", background="You are Mei.", town="The workshop opens at 09:00."
    ).root
    (root / "skills" / "tests-first.md").write_text("Run the tests before changing code.\n")
    (root / "session.jsonl").write_text('{"stale": "session"}\n')
    (root / "trace.jsonl").write_text('{"stale": "trace"}\n')
    return root


def files(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


async def test_two_tasks_make_rows_and_a_rate_with_its_interval(tmp_path):
    root, backend, out = exported(tmp_path), FakeBackend(2), tmp_path / "out"
    before = files(root)
    result = await evaluate_capability(
        root,
        backend.tasks,
        ScriptedClient(scripted),
        RuntimeConfig(),
        SoloConfig(max_requests=3),
        concurrency=2,
        out_dir=out,
        backend=backend,
    )

    rows = [row.model_dump(exclude={"seconds"}) for row in result.tasks]
    common = {"cached_tokens": 0, "lapses": 0, "error": None}
    assert rows == [
        {
            "instance_id": "org__repo-1",
            "resolved": True,
            "status": "accepted",
            "submissions": 1,
            "verdicts": ("resolved",),
            "steps": 1,
            "prompt_tokens": 1000,
            "completion_tokens": 1,
            **common,
        },
        {
            "instance_id": "org__repo-2",
            "resolved": False,
            "status": "requests",
            "submissions": 0,
            "verdicts": (),
            "steps": 3,
            "prompt_tokens": 3000,
            "completion_tokens": 3,
            **common,
        },
    ]
    assert (result.evaluated, result.resolved, result.errors) == (2, 1, 0)
    assert result.resolved_rate == 0.5
    assert result.interval == pytest.approx((0.0945, 0.9055), abs=1e-4)
    assert files(root) == before
    copy = out / "org__repo-1" / "agent"
    assert (copy / "skills" / "tests-first.md").is_file()
    assert "stale" not in (copy / "session.jsonl").read_text() + (copy / "trace.jsonl").read_text()
    assert (out / "org__repo-1" / "submission-1.patch").read_text() == '{"fix.py": "FIX\\n"}'
    assert len(backend.opened) == 2 and all(workspace.closed for workspace in backend.opened)


class Unstartable(FakeBackend):
    """A backend whose first task's container cannot start."""

    async def open(self, task, name):
        if task.instance_id == "org__repo-1":
            raise RuntimeError("cannot start a container of org__repo-1")
        return await super().open(task, name)


def failing(request: LLMRequest):
    """A model that answers on the first task and fails on the second."""
    if "a task in org/repo1." in request.messages[1].content:
        return reply("", tool_call("shell", command="ls"), prompt_tokens=10)
    raise LLMCallError("the server answered 500")


async def test_failures_of_the_machinery_are_errors_and_not_the_residents(tmp_path):
    backend = Unstartable(2)
    result = await evaluate_capability(
        exported(tmp_path),
        backend.tasks,
        ScriptedClient(failing),
        RuntimeConfig(model_attempts=2, retry_wait=0.01),
        SoloConfig(),
        concurrency=2,
        out_dir=tmp_path / "out",
        backend=backend,
    )

    unstarted, unanswered = result.tasks
    assert (unstarted.status, unstarted.resolved, unstarted.steps) == ("error", False, 1)
    assert unstarted.error == "shell: RuntimeError: cannot start a container of org__repo-1"
    assert (unanswered.status, unanswered.steps, unanswered.lapses) == ("error", 0, 1)
    assert unanswered.error == (
        "the model failed 2 times in a row: LLMCallError: the server answered 500"
    )
    assert (result.evaluated, result.errors, result.resolved_rate, result.interval) == (
        0,
        2,
        None,
        None,
    )


async def test_error_rows_are_worked_again_when_the_evaluation_is_continued(tmp_path):
    export = exported(tmp_path)

    async def failing_pass() -> int:
        backend = Unstartable(2)
        result = await evaluate_capability(
            export,
            backend.tasks,
            ScriptedClient(failing),
            RuntimeConfig(model_attempts=2, retry_wait=0.01),
            SoloConfig(),
            concurrency=2,
            out_dir=tmp_path / "out",
            backend=backend,
        )
        assert result.errors == 2
        return result.resumed

    assert await failing_pass() == 0
    assert await failing_pass() == 0  # the error rows were not kept, both tasks ran again


def command(monkeypatch, export, out, *options, model=scripted):
    """`evaluation.capability` from the command line on the fake backend's two tasks of the
    train split, one at a time, with the scripted `model`; the backend it worked through."""
    backend = FakeBackend(2)
    monkeypatch.setattr(capability, "SwebenchBackend", lambda: backend)
    monkeypatch.setattr(capability, "create_client", lambda config: ScriptedClient(model))
    config = out.with_name("model.yaml")
    config.write_text("base_url: http://127.0.0.1:9\napi_key_env: NO_KEY\nmodel: resident\n")
    main(
        [str(export), "--split", "train", "--out", str(out), "--model", str(config)]
        + ["--concurrency", "1", *options]
    )
    return backend


def stopping(request: LLMRequest):
    """The scripted model, stopped as a process is at the third step of the second task."""
    steps = sum(message.role == "assistant" for message in request.messages)
    if "a task in org/repo2." in request.messages[1].content and steps == 2:
        raise KeyboardInterrupt
    return scripted(request)


def stopped(monkeypatch, export, out):
    """`out` as an evaluation stopped while the second task was worked leaves it."""
    with pytest.raises(KeyboardInterrupt):
        command(monkeypatch, export, out, model=stopping)


def report(out: Path) -> dict:
    """The results.json of `out` without the times taken."""
    doc = json.loads((out / "results.json").read_text())
    del doc["seconds"]
    for row in doc["tasks"]:
        del row["seconds"]
    return doc


def test_a_stopped_evaluation_is_continued_by_the_same_command(tmp_path, monkeypatch):
    export, out = exported(tmp_path), tmp_path / "out"
    stopped(monkeypatch, export, out)
    first, cut_off = out / "org__repo-1", out / "org__repo-2"
    assert (first / "result.json").is_file() and not (cut_off / "result.json").exists()
    assert (cut_off / "agent" / "trace.jsonl").is_file() and not (out / "results.json").exists()

    backend = command(monkeypatch, export, out)
    assert [workspace.task.instance_id for workspace in backend.opened] == ["org__repo-2"]
    command(monkeypatch, export, tmp_path / "whole")
    resumed, whole = report(out), report(tmp_path / "whole")
    assert (resumed.pop("resumed"), whole.pop("resumed")) == (1, 0)
    assert resumed == whole
    assert [(row["status"], row["steps"]) for row in resumed["tasks"]] == [
        ("accepted", 1),
        ("gave_up", 4),
    ]
    for row in json.loads((out / "results.json").read_text())["tasks"]:
        assert json.loads((out / row["instance_id"] / "result.json").read_text()) == row
    assert json.loads((out / "evaluation.json").read_text()) == {
        "export": str(export.resolve()),
        "split": "train",
        "model": "resident",
        "reasoning_effort": "medium",
    }


def test_the_command_line_refuses_a_directory_of_another_evaluation(tmp_path, monkeypatch, capsys):
    export, out = exported(tmp_path), tmp_path / "out"
    stopped(monkeypatch, export, out)
    before = files(out)
    other = tmp_path / "export" / "Tomas"
    with pytest.raises(SystemExit):
        command(monkeypatch, other, out, "--reasoning", "low")
    assert capsys.readouterr().err.endswith(
        f"error: would overwrite {out}: it was begun with export {export.resolve()}, not "
        f"{other.resolve()}; reasoning_effort medium, not low\n"
    )
    record = json.loads((out / "evaluation.json").read_text())
    (out / "evaluation.json").write_text(json.dumps({**record, "split": "eval"}))
    with pytest.raises(SystemExit):
        command(monkeypatch, export, out)
    assert capsys.readouterr().err.endswith(
        f"error: would overwrite {out}: it was begun with split eval, not train\n"
    )
    (out / "evaluation.json").unlink()
    with pytest.raises(SystemExit):
        command(monkeypatch, export, out)
    assert capsys.readouterr().err.endswith(
        f"error: would overwrite {out}: it holds no evaluation.json to say what it evaluates\n"
    )
    del before[Path("evaluation.json")]
    assert files(out) == before


def test_the_command_line_refuses_a_finished_evaluation(tmp_path, monkeypatch, capsys):
    export, out = exported(tmp_path), tmp_path / "out"
    command(monkeypatch, export, out, "--limit", "1")
    before = files(out)
    with pytest.raises(SystemExit):
        command(monkeypatch, export, out, "--limit", "1")
    assert capsys.readouterr().err.endswith(
        f"error: would overwrite {out}: its evaluation is finished\n"
    )
    with pytest.raises(SystemExit):
        command(monkeypatch, export, out)
    assert capsys.readouterr().err.endswith(
        f"error: would overwrite {out}: its evaluation is finished, without 1 of the tasks "
        "chosen; a finished evaluation is not extended\n"
    )
    assert files(out) == before
