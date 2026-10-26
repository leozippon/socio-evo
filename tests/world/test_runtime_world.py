"""A resident's real runtime, on a scripted model, living a day in the world: the port's inbox,
turn endings, going to bed and falling asleep, the checkpoint that waits for it, and the order in
which it reads what happened around its own calls."""

from __future__ import annotations

import asyncio

from agent.directory import AgentDirectory
from agent.runtime import Runtime
from agent.testing import ScriptedModel, reply, running, tool_call
from infrastructure.storage import read_jsonl
from tests.world.conftest import FakeBackend, Town, make_agent_dirs, town_config
from world.clock import ManualClock
from world.events import Work
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

    assert not model._replies and world.economy.purses["Mei"] == 120 + 20 - 20  # the rent
    assert (directory.root / "memory" / "journal" / "2001-01-01.md").read_text() == (
        "I fixed task 1 and was paid.\n"
    )
    seen = "\n".join(str(message.content) for message in model.requests[-1].messages)
    assert "Accepted. You were paid $20." in seen
    assert "For task 1 you wrote 1 file." in seen  # what review_day told
    assert "You are in bed and will wake at 07:00" in seen
    trace = directory.trace_path.read_text()
    assert '"percept_kind": "time"' in trace and '"percept_kind": "sleep"' in trace


def _mei(tmp_path) -> tuple[AgentDirectory, World, Town]:
    config = town_config()
    background = "You are Mei, thirty-four, a programmer who came to town last spring."
    directory = AgentDirectory.create(tmp_path / "agents" / "Mei", background=background, town="")
    make_agent_dirs(tmp_path, config)
    world = World(config, tmp_path, FakeBackend(), clock=ManualClock())
    return directory, world, Town(world, FakeBackend())


async def test_a_partner_who_left_is_told_before_what_one_said_after_and_only_once(tmp_path):
    directory, world, town = _mei(tmp_path)
    aisha = world.residents["Aisha"]

    def aisha_leaves_meanwhile(request):
        world.leave_conversation(aisha)
        return reply(
            "", tool_call("say", text="Did you sleep well?"), tool_call("leave_conversation")
        )

    model = ScriptedModel(aisha_leaves_meanwhile, reply("Off to work, then."))
    port = world.ports["Mei"]
    town.start()
    await town.until("07:00")
    await town.call("Aisha", "say", text="Morning, Mei.", to=["Mei"])
    async with running(Runtime(directory, port, model)):
        await resting(port)
    await town.close()

    seen = model.requests[-1].messages
    said, left = [m.content for m in seen if m.role == "tool"]
    assert said == (
        "At 07:00 Aisha left the conversation.\n\nAt 07:00 the conversation ended.\n\n"
        "You said: “Did you sleep well?”"
    )
    assert left == "You left the conversation."
    assert seen[-1].role == "tool"  # nothing told after she left herself
    assert sum("Aisha left the conversation" in str(m.content) for m in seen) == 1
    kinds = [r["kind"] for r in read_jsonl(directory.trace_path)]
    first_call = kinds.index("tool_call")
    assert kinds[first_call : first_call + 4] == ["tool_call", "percept", "percept", "tool_result"]


async def test_a_remark_to_everyone_reaches_a_working_resident_with_its_next_result(tmp_path):
    directory, world, town = _mei(tmp_path)

    def tomas_greets_meanwhile(request):
        asyncio.get_running_loop().create_task(town.call("Tomas", "say", text="Morning, all."))
        thinking = " ".join(["Let me run the checks before I change anything."] * 3)
        return reply(thinking, tool_call("shell", command="pytest"))

    model = ScriptedModel(tomas_greets_meanwhile, reply("Back to it."), delay=0.01)
    port = world.ports["Mei"]
    town.start()
    await town.until("07:00")
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="workshop")
    await town.until("07:10")
    await town.call("Mei", "start_work")
    await town.call("Mei", "claim_task", task=1)
    async with running(Runtime(directory, port, model)):
        await resting(port)
    await town.close()

    records = list(read_jsonl(directory.trace_path))
    assert not [r for r in records if r["kind"] == "interruption" or r.get("aborted")]
    (shell,) = [m.content for m in model.requests[-1].messages if m.role == "tool"]
    assert shell == "Tomas said: “Morning, all.”\n\nran pytest\nExit code 0."
    mei = world.residents["Mei"]
    assert isinstance(mei.event, Work) and mei.conversation is None
