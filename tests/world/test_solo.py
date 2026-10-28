"""The work-only world of the capability evaluation: a resident's runtime on a scripted model
working one task on the fake backend with the town's workspace tools and time limits, the
endings, budgets and safety stop, and the guard over every text the resident reads."""

from __future__ import annotations

import asyncio
import contextlib

from agent.directory import AgentDirectory
from agent.port import ToolResult
from agent.runtime import Runtime
from agent.testing import ScriptedModel, reply, running, tool_call
from agent.wording import offences
from experiments.config import PROJECT_ROOT, load_experiment
from infrastructure.storage import read_jsonl
from world import solo as texts
from world.solo import SoloConfig, SoloPort
from world.testing import FakeBackend

FAILED = (
    "2 of the 3 checks your change should make pass did not pass and 1 of the 10 checks that "
    "passed before failed"
)


def solo(**config) -> tuple[SoloPort, FakeBackend]:
    backend = FakeBackend()
    return SoloPort(backend.tasks[0], backend, SoloConfig(**config), name="Mei"), backend


async def work(port: SoloPort, model: ScriptedModel, tmp_path) -> list[str]:
    """Run the resident on `port` until its task is over; the results of its tool calls."""
    directory = AgentDirectory.create(tmp_path / "Mei", background="You are Mei.")
    async with running(Runtime(directory, port, model)):
        async with asyncio.timeout(5):
            await port.done.wait()
        await asyncio.sleep(0.01)
    await port.close()
    records = read_jsonl(directory.trace_path)
    return [record["text"] for record in records if record["kind"] == "tool_result"]


async def test_a_task_runs_from_the_first_command_to_acceptance(tmp_path):
    port, backend = solo()
    model = ScriptedModel(
        reply("", tool_call("shell", command="ls")),
        reply("", tool_call("write_repo_file", path="fix.py", content="BUG\n")),
        reply("", tool_call("edit_repo_file", path="fix.py", old_text="BUG", new_text="FIX")),
        reply("", tool_call("submit"), tool_call("shell", command="pwd")),
    )
    results = await work(port, model, tmp_path)

    assert port.ending == "accepted" and len(model.requests) == 4
    system, opening = model.requests[0].messages
    assert "How this work goes.\n\nYou have one task" in system.content
    assert "You can submit at most 2 times. Your work on the task ends when" in system.content
    assert opening.content == (
        "Your work on the task begins.\n\nYou are at work on a task in org/repo1. What you can "
        "do now: shell, read_repo_file, write_repo_file, edit_repo_file, submit, give_up.\n\nThe "
        "problem:\n\nProblem 1 goes wrong.\nDetails of 1."
    )
    assert results == [
        "ran ls\nExit code 0.",
        "You wrote fix.py (4 characters).",
        "You changed fix.py.",
        "Accepted. Your work on the task is done.",
        "Your work on the task is over.",
    ]
    [workspace] = backend.opened
    assert workspace.commands == ["ls"] and workspace.closed
    assert backend.accepted == [("org__repo-1", '{"fix.py": "FIX\\n"}')]


async def test_a_task_takes_two_submissions_at_most(tmp_path):
    port, backend = solo()
    model = ScriptedModel(
        reply(
            "", tool_call("write_repo_file", path="a.py", content="almost\n"), tool_call("submit")
        ),
        reply("I will think it over."),
        reply("", tool_call("submit"), tool_call("submit")),
    )
    results = await work(port, model, tmp_path)

    assert port.ending == "rejected" and len(backend.accepted) == 2
    assert [submission.verdict.status for submission in port.submissions] == ["failed_tests"] * 2
    assert results[1:] == [
        f"Not accepted: {FAILED}. You can hand it in 1 more time.",
        f"Not accepted: {FAILED}. You cannot hand it in again; your work on the task is over.",
        "Your work on the task is over.",
    ]
    told = model.requests[2].messages[-1].content
    assert told.startswith("Time passed.\n\nYou are at work on a task in org/repo1.")
    assert (
        f"You have handed in your change 1 time; the last time it was not accepted: {FAILED}. "
        "You can hand it in 1 more time." in told
    )


async def test_giving_up_ends_the_task(tmp_path):
    port, backend = solo()
    model = ScriptedModel(reply("", tool_call("give_up"), tool_call("shell", command="ls")))
    results = await work(port, model, tmp_path)
    assert port.ending == "gave_up" and backend.opened == []
    assert results == ["You gave up the task; your work on it is over.", texts.OVER]


async def test_the_last_turn_is_carried_out_and_then_the_budget_ends_the_task():
    port, backend = solo(max_requests=2)
    assert [percept.kind for percept in await port.wait()] == ["start"]
    port.spend(100)
    assert not (await port.call("shell", {"command": "ls"})).ends_turn
    port.spend(100)
    assert await port.call("shell", {"command": "pwd"}) == ToolResult(
        "ran pwd\nExit code 0.", ends_turn=True
    )
    assert port.ending is None
    waiting = asyncio.create_task(port.wait())
    await asyncio.sleep(0.01)
    assert port.ending == "requests" and port.done.is_set() and not waiting.done()
    waiting.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await waiting
    assert (await port.call("shell", {"command": "ls"})).text == texts.OVER
    assert backend.opened[0].commands == ["ls", "pwd"]
    assert (port.requests, port.completion_tokens) == (2, 200)


async def test_the_safety_stop_of_real_time_ends_the_task_as_an_error():
    port, backend = solo(max_seconds=0.05)
    await port.wait()
    await asyncio.sleep(0.06)
    assert await port.call("shell", {"command": "ls"}) == ToolResult(texts.OVER, ends_turn=True)
    assert port.ending == "error" and backend.opened == []
    assert port.error == "the safety stop of 0.05 seconds of real time was reached"


async def test_commands_and_acceptances_have_the_towns_time_limits():
    work = load_experiment(PROJECT_ROOT / "experiments" / "configs" / "town.yaml").town.work
    config = SoloConfig()
    assert (config.shell_timeout_s, config.acceptance_timeout_s) == (
        work.shell_timeout_s,
        work.acceptance_timeout_s,
    )
    port, _ = solo()
    told = (await port.call("shell", {"command": "sleep forever"})).text
    assert told == f"The command was stopped after {work.shell_timeout_s} seconds."


async def test_nothing_the_resident_reads_offends():
    port, _ = solo()
    read = [port.rules()]
    for spec in port.tool_specs():
        read.append(spec.description)
        read += [value.get("description", "") for value in spec.parameters["properties"].values()]
    read += [percept.text for percept in await port.wait()]
    read.append(port.situation())
    read.append((await port.call("submit", {})).text)
    await port.call("write_repo_file", {"path": "a.py", "content": "x\n"})
    read.append((await port.call("submit", {})).text)
    read.append(port.situation())
    read += [percept.text for percept in await port.wait()]
    read.append((await port.call("submit", {})).text)
    read += [port.situation(), (await port.call("give_up", {})).text]
    read += [texts.ACCEPTED, texts.GAVE_UP, texts.BROKEN]
    assert [(text, offences(text)) for text in read if offences(text)] == []
