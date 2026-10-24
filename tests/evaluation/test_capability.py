"""The capability harness on the fake backend with a scripted model: the rows, the resolved rate
and its interval, the turn budget, the export left untouched, and failures of the machinery kept
apart from the resident's."""

from pathlib import Path

import pytest

from agent.directory import AgentDirectory
from agent.runtime import RuntimeConfig
from agent.testing import reply, tool_call
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
        reply("", tool_call("shell", command="ls"), prompt_tokens=1000) for _ in range(3)
    ],
}


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


def test_the_command_line_refuses_to_overwrite_results(tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(SystemExit):
        main([str(exported(tmp_path)), "--split", "eval", "--out", str(out), "--model", "m.yaml"])
    assert f"would overwrite {out}" in capsys.readouterr().err
