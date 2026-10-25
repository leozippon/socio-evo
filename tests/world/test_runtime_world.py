"""A resident's real runtime, on a scripted model, living a day in the world: the port's inbox,
turn endings, going to bed and falling asleep, and the checkpoint that waits for it."""

from __future__ import annotations

import asyncio

from agent.directory import AgentDirectory
from agent.runtime import Runtime
from agent.testing import ScriptedModel, reply, running, tool_call
from tests.world.conftest import FakeBackend, Town, make_agent_dirs, town_config
from world.clock import ManualClock
from world.world import World


async def resting(port) -> None:
    """Until the runtime waits on `port` with nothing pending."""
    async with asyncio.timeout(5):
        while not port.waiting or port.has_pending:
            await asyncio.sleep(0.01)


async def test_a_runtime_lives_a_day_in_the_world(tmp_path):
    config = town_config()
    background = "You are Mei, thirty-four, a programmer who came to town last spring."
    directory = AgentDirectory.create(tmp_path / "agents" / "Mei", background=background, town="")
    make_agent_dirs(tmp_path, config)
    world = World(config, tmp_path, FakeBackend(), clock=ManualClock())
    model = ScriptedModel(
        reply("", tool_call("go", place="workshop")),
        reply("", tool_call("wait", minutes=110)),
        reply(
            "",
            tool_call("start_work"),
            tool_call("claim_task", task=1),
            tool_call("write_repo_file", path="fix.py", content="FIX\n"),
            tool_call("submit"),
            tool_call("leave_work"),
            tool_call("go", place="mill-street-house"),
        ),
        reply("", tool_call("wait", minutes=600)),
        reply("", tool_call("wait", minutes=50)),
        reply("", tool_call("sleep", until="07:00", journal="I fixed task 1 and was paid.")),
        reply("", tool_call("review_day")),
        reply("Good night."),
    )
    town = Town(world, FakeBackend())
    port = world.ports["Mei"]
    town.start(until_day=1)
    town.rest("Tomas", "Aisha")
    async with running(Runtime(directory, port, model)):
        await resting(port)
        for hour in ("07:00", "07:10", "09:00", "09:10", "19:10", "20:00"):
            await town.until(hour)
            await resting(port)
        assert world.residents["Mei"].suspended
        await town.until("02:30", day=2)
        async with asyncio.timeout(5):
            while not town.checkpoints:
                await asyncio.sleep(0.01)
    await town.close()

    assert not model._replies and world.economy.purses["Mei"] == 120 + 20 - 30
    assert (directory.root / "memory" / "journal" / "2001-01-01.md").read_text() == (
        "I fixed task 1 and was paid.\n"
    )
    seen = "\n".join(str(message.content) for message in model.requests[-1].messages)
    assert "Accepted. You were paid $20." in seen
    assert "For task 1 you wrote 1 file." in seen  # what review_day told
    assert "You are in bed and will wake at 07:00" in seen
    trace = directory.trace_path.read_text()
    assert '"percept_kind": "time"' in trace and '"percept_kind": "sleep"' in trace
