"""Two days of a small town, lived by the real world and, for Mei, the real runtime on a scripted
model; Tomas and Aisha are driven by hand through their ports, and their traces are empty. The run
directory it leaves (frozen configuration, world log, agent directories, Mei's trace) is what
the analysis reads.

Day 1. Everyone walks to the workshop at 07:00. Mei reads her notes on the way out, waits until
09:00, claims task 1 (and is refused task 2, as she holds one), runs two commands, writes the
fix, hands it in (accepted, paid $20) and writes a skill. At 09:20 Tomas, who claimed task 2,
asks her privately how she runs the tests; she answers privately and passes him her skill. He
tells Aisha something privately in her presence and gives Mei $5; Mei leaves for home at 09:20,
waits there until 20:00 (her body speaks twice, at 11:00 and 18:00, and she waits on), goes to
bed with her journal, reads the record of her day, rates Tomas 4, writes her notes on people and
fails to read a file she does not have. Tomas works until
18:00, goes home, goes to bed at 20:00 with a journal that claims he fixed task 2, and rates Mei
5. Aisha never goes to bed and is put to sleep at 02:00. Nobody eats, so everyone is starving
by midnight and loses health for it; rent is $20 a day on Mill Street and $30 at the flat.

Day 2. Mei wakes starving, waits at home until 20:00 (a little tired by 17:00), goes back to bed
with a second journal entry and reads Tomas's rating; Tomas's claim runs out at midnight; Tomas
and Aisha are put to sleep at 02:00.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from agent.directory import TRACE, AgentDirectory
from agent.port import WorldPort
from agent.runtime import Runtime, RuntimeConfig
from agent.testing import ScriptedModel, running, tool_call
from infrastructure.llm import LLMConfig, LLMResponse, ToolCall, Usage
from infrastructure.storage import RunDirectory
from simulation.config import ExperimentConfig, Resident
from tests.world.conftest import Town, town_config
from world.clock import ManualClock
from world.testing import FakeBackend
from world.world import World

MEI_JOURNAL = (
    "I fixed task 1 and was paid $20. Tomas asked how I run the tests and I gave him my skill."
)
MEI_JOURNAL_2 = "A quiet second day at home."
TOMAS_JOURNAL = "I fixed task 2 and gave Mei $5."
USAGE = Usage(prompt_tokens=1000, completion_tokens=100, cached_prompt_tokens=600)
"""What the server reports for each of Mei's requests."""


def step(*calls: ToolCall, text: str = "") -> LLMResponse:
    return LLMResponse(
        text=text,
        tool_calls=calls,
        finish_reason="tool_calls" if calls else "stop",
        usage=USAGE,
        latency=0.0,
    )


MEI_STEPS = (
    # Day 1, 07:00, waking.
    step(tool_call("read_file", path="memory/work.md"), tool_call("go", place="workshop")),
    # 07:10, arrived with the others.
    step(tool_call("wait", minutes=110)),
    # 09:00, the board.
    step(
        tool_call("start_work"),
        tool_call("view_board"),
        tool_call("claim_task", task=1),
        tool_call("claim_task", task=2),
        tool_call("shell", command="pytest -x"),
        tool_call("shell", command="false"),
        tool_call("write_repo_file", path="fix.py", content="FIX\n"),
        tool_call("submit"),
        tool_call("write_file", path="skills/testing.md", content="Run pytest -x first.\n"),
    ),
    step(),
    # 09:20, Tomas's question.
    step(
        tool_call("say", text="I run pytest -x first.", to=["Tomas"]),
        tool_call("share_skill", to="Tomas", skill="testing"),
    ),
    step(),
    # Tomas speaks privately to Aisha.
    step(),
    # Tomas's gift.
    step(
        tool_call("leave_conversation"),
        tool_call("leave_work"),
        tool_call("go", place="mill-street-house"),
    ),
    # 09:30, home, until 20:00: a little hungry at 11:00, hungry at 18:00.
    step(tool_call("wait", minutes=600)),
    step(tool_call("wait", minutes=420)),
    step(tool_call("wait", minutes=120)),
    # 20:00.
    step(tool_call("sleep", until="07:00", journal=MEI_JOURNAL)),
    step(
        tool_call("review_day"),
        tool_call("rate", resident="Tomas", score=4, reason="He asked good questions."),
        tool_call("write_file", path="memory/people.md", content="Tomas asks good questions.\n"),
        tool_call("read_file", path="memory/missing.md"),
    ),
    step(text="Good night."),
    # Day 2, 07:00, waking, and at home until 20:00.
    step(tool_call("wait", minutes=600)),
    step(tool_call("wait", minutes=180)),
    step(tool_call("sleep", until="07:00", journal=MEI_JOURNAL_2)),
    step(),
)


async def resting(port: WorldPort) -> None:
    """Until the runtime waits on `port` with nothing pending."""
    async with asyncio.timeout(5):
        while not port.waiting or port.has_pending:  # type: ignore[attr-defined]
            await asyncio.sleep(0.01)


async def live(root: Path) -> None:
    """Live the two days into a new run directory at `root`."""
    town = town_config()
    config = ExperimentConfig(
        name=root.name,
        llm=LLMConfig(backend="scripted", base_url="-", api_key_env="-", model="scripted"),
        runtime=RuntimeConfig(),
        town=town,
        residents=tuple(
            Resident(name=r.name, background=Path(f"experiments/residents/{r.name.lower()}.md"))
            for r in town.residents
        ),
        skills_writable=True,
        days=2,
    )
    run = RunDirectory.create(root.parent, root.name, config=config, code_revision="test")
    mei = AgentDirectory.create(
        run.agent_dir("Mei"), background="You are Mei.", town="", work="Notes on my work.\n"
    )
    for name in ("Tomas", "Aisha"):
        for folder in ("memory", "skills"):
            (run.agent_dir(name) / folder).mkdir(parents=True)
        (run.agent_dir(name) / TRACE).touch()
    world = World(town, run.root, FakeBackend(), clock=ManualClock())
    harness = Town(world, FakeBackend())
    port = world.ports["Mei"]
    model = ScriptedModel(*MEI_STEPS)
    harness.start(until_day=2)

    async def settled(hour: str, day: int = 1) -> None:
        await harness.until(hour, day)
        await resting(port)

    async def tomas(tool: str, **args: object) -> None:
        result = await harness.call("Tomas", tool, **args)
        assert not result.text.startswith(("You are", "There is", "You cannot")), result.text
        await resting(port)

    async with running(Runtime(mei, port, model)):
        await settled("07:00")
        await harness.call("Tomas", "go", place="workshop")
        await harness.call("Aisha", "go", place="workshop")
        await settled("07:10")
        await settled("09:00")
        await tomas("start_work")
        await tomas("claim_task", task=2)
        await tomas("shell", command="false")
        await settled("09:20")
        await tomas("say", text="Mei, how do you run the tests?", to=["Mei"])
        await tomas("say", text="Do not tell Mei about task 2.", to=["Aisha"])
        await tomas("give_money", to="Mei", amount=5)
        await settled("09:30")
        await settled("18:00")
        await tomas("leave_work")
        await tomas("go", place="college-flat")
        await settled("18:10")
        await settled("19:30")
        await settled("20:00")
        await tomas("sleep", until="07:30", journal=TOMAS_JOURNAL)
        await tomas("rate", resident="Mei", score=5, reason="She shared her testing skill.")
        harness.rest("Tomas", "Aisha")
        await settled("02:30", day=2)
        await settled("07:00", day=2)
        await settled("17:00", day=2)
        await settled("20:00", day=2)
        await settled("02:30", day=3)
        async with asyncio.timeout(5):
            while len(harness.checkpoints) < 2:
                await asyncio.sleep(0.01)
    await harness.close()
    assert not model._replies, "Mei's script was not lived to its end"
