"""Two days of a small town, lived by the real world and, for Mei, the real runtime on a scripted
model; Tomas and Aisha, programmers like Mei, and Ravi the team leader, Olga the shopkeeper, Jonas
the chef, Lucia the doctor and Vera the mayor, who share Tomas's flat, are driven by hand through
their ports, and their traces are empty. The run directory it leaves (frozen configuration, world
log, checkpoints, agent directories, Mei's trace) is what the analysis reads.

Day 1. Everyone walks to the workshop at 07:00. Mei reads her notes on the way out, waits until
09:00 (the tasks coming in at 08:00 are told to her and she waits on), claims task 1 (and is
refused task 2, as she holds one), then, the task's actions offered once it is held, runs two
commands, writes the fix, hands it in (accepted, paid $20) and writes a skill. At 09:20 Tomas,
who claimed task 2, asks her privately how she runs the tests; she answers privately. He tells
Aisha something privately in her presence and passes Mei $5; Mei leaves the conversation, then
her work, for home at 09:20, waits there until 20:00 (her body speaks
twice, at 12:00 and 20:00, and she waits on), goes to bed with her journal, reads the record of
her day, writes her notes on people and fails to read a file she does not have. Tomas works until
18:00, goes home and goes to bed at 20:00 with a journal that claims he fixed task 2. Aisha never
goes to bed and is put to sleep at 02:00. None of the three eats, so
each is hungry by the first midnight and starving by the second, which costs health; rent is
$20 a day on Mill Street and $30 at the flat.

The others spend the day at home, and once Mei is asleep and Tomas in bed, at 20:00, go to work.
Olga orders 5 helpings of bread at the store and sells Jonas 2 units of vegetables for the kitchen
and Vera a helping of bread, which she eats; Ravi, at the workshop, gives the open task 3 to
Aisha, who is still there, and walks to the clinic, where Lucia examines him at 20:20; Jonas cooks
a portion of vegetable soup at the café, which Lucia eats there at 20:30; Vera announces at the
hall at 20:20, which Mei and Tomas, asleep, are told on waking. Those at work at 02:00 are stopped
by the forced sleep, which puts the five to sleep.

Day 2. Mei wakes starving, waits at home until 20:00 (a little tired by 17:00) and goes back to
bed with a second journal entry; the bread Olga ordered arrives at 08:00; Tomas's task and
Aisha's are withdrawn at midnight; everyone but Mei is put to sleep at 02:00.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import yaml

from agent.directory import TRACE, AgentDirectory
from agent.port import WorldPort
from agent.runtime import Runtime, RuntimeConfig
from agent.testing import ScriptedModel, running, tool_call
from infrastructure.llm import LLMConfig, LLMResponse, ToolCall, Usage
from infrastructure.storage import RunDirectory
from simulation.config import ExperimentConfig, Resident
from tests.world.conftest import CARE, RESIDENTS, TRADES, Town, opening, town_config
from world.clock import ManualClock
from world.testing import FakeBackend
from world.world import World

MEI_JOURNAL = (
    "I fixed task 1 and was paid $20. Tomas asked how I run the tests and I told him my method."
)
MEI_JOURNAL_2 = "A quiet second day at home."
TOMAS_JOURNAL = "I fixed task 2 and gave Mei $5."
ANNOUNCEMENT = "The hall is open in the evenings."
LEADER = ({"name": "Ravi", "home": "college-flat", "occupation": "team-leader", "purse": 100},)
OTHERS = tuple(r["name"] for r in LEADER + TRADES + CARE)
"""The residents who go to work in the evening."""
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
    # 08:00, the tasks come in.
    step(tool_call("wait", minutes=60)),
    # 09:00, the board.
    step(
        tool_call("view_board"),
        tool_call("claim_task", task=1),
        tool_call("claim_task", task=2),
    ),
    # The task's actions, offered once the task is held.
    step(
        tool_call("shell", command="pytest -x"),
        tool_call("shell", command="false"),
        tool_call("write_repo_file", path="fix.py", content="FIX\n"),
        tool_call("submit"),
        tool_call("write_file", path="skills/testing.md", content="Run pytest -x first.\n"),
    ),
    step(),
    # 09:20, Tomas's question.
    step(tool_call("say", text="I run pytest -x first.", to=["Tomas"])),
    step(),
    # Tomas speaks privately to Aisha.
    step(),
    # Tomas's gift: out of the conversation, then, back at work, away from it.
    step(tool_call("leave_conversation")),
    step(tool_call("leave_work"), tool_call("go", place="mill-street-house")),
    # 09:30, home, until 20:00: a little hungry at 12:00, hungry at 20:00.
    step(tool_call("wait", minutes=600)),
    step(tool_call("wait", minutes=420)),
    step(tool_call("wait", minutes=120)),
    # 20:00.
    step(tool_call("sleep", until="07:00", journal=MEI_JOURNAL)),
    step(
        tool_call("review_day"),
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


def before_occupations(run_dir: Path, root: Path) -> Path:
    """A copy at `root` of the run at `run_dir` whose frozen configuration is of the town before
    occupations, as the runs of that design froze it: settings it had that today's configuration
    no longer takes, and none of those it has added."""
    copy = Path(shutil.copytree(run_dir, root))
    frozen = yaml.safe_load((copy / "config.yaml").read_text(encoding="utf-8"))
    town = frozen["town"]
    for resident in town["residents"]:
        del resident["occupation"]
        resident["ties"] = {}
    for added in ("occupations", "fund", "items", "store", "hospital"):
        del town[added]
    town["goods"], town["work"]["board_size"], frozen["skills_writable"] = [], 4, True
    (copy / "config.yaml").write_text(yaml.safe_dump(frozen), encoding="utf-8")
    return copy


async def resting(port: WorldPort) -> None:
    """Until the runtime waits on `port` with nothing pending."""
    async with asyncio.timeout(5):
        while not port.waiting or port.has_pending:  # type: ignore[attr-defined]
            await asyncio.sleep(0.01)


async def live(root: Path) -> None:
    """Live the two days into a new run directory at `root`."""
    town = town_config(residents=RESIDENTS + LEADER + TRADES + CARE)
    config = ExperimentConfig(
        name=root.name,
        llm=LLMConfig(backend="scripted", base_url="-", api_key_env="-", model="scripted"),
        runtime=RuntimeConfig(),
        town=town,
        residents=tuple(
            Resident(name=r.name, background=Path(f"experiments/residents/{r.name.lower()}.md"))
            for r in town.residents
        ),
        days=2,
    )
    run = RunDirectory.create(root.parent, root.name, config=config, code_revision="test")
    mei = AgentDirectory.create(run.agent_dir("Mei"), background="You are Mei.")
    (mei.root / "memory" / "work.md").write_text("Notes on my work.\n", encoding="utf-8")
    for name in ("Tomas", "Aisha", *OTHERS):
        for folder in ("memory", "skills"):
            (run.agent_dir(name) / folder).mkdir(parents=True)
        (run.agent_dir(name) / TRACE).touch()
    world = World(town, run.root, FakeBackend(), clock=ManualClock())
    opening(world)
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

    async def does(name: str, tool: str, told: str, **args: object) -> None:
        result = await harness.call(name, tool, **args)
        assert told in result.text, result.text

    async with running(Runtime(mei, port, model)):
        await settled("07:00")
        await harness.call("Tomas", "go", place="workshop")
        await harness.call("Aisha", "go", place="workshop")
        await settled("07:10")
        await settled("09:00")
        await tomas("claim_task", task=2)
        await tomas("shell", command="false")
        await settled("09:20")
        await tomas("say", text="Mei, how do you run the tests?", to=["Mei"])
        await tomas("say", text="Do not tell Mei about task 2.", to=["Aisha"])
        await tomas("pass", item="money", units=5, to="Mei")
        await settled("09:30")
        await settled("18:00")
        await tomas("leave_work")
        await tomas("go", place="college-flat")
        await settled("18:10")
        await settled("19:30")
        await settled("20:00")
        await tomas("sleep", until="07:30", journal=TOMAS_JOURNAL)
        harness.rest("Tomas", "Aisha")
        await resting(world.ports["Tomas"])  # asleep
        going = {"Ravi": "workshop", "Olga": "store", "Jonas": "store", "Lucia": "clinic"}
        for name, place in (going | {"Vera": "store"}).items():
            await does(name, "go", "You set off", place=place)
        await settled("20:10")
        await does("Olga", "order", "You ordered 5 helpings of bread", item="bread", quantity=5)
        await does("Jonas", "buy", "for the kitchen", item="vegetables", units=2,
                   for_the_kitchen=True)  # fmt: skip
        await does("Vera", "buy", "You bought 1 helping of bread", item="bread")
        await does("Ravi", "assign", "You gave task 3", task=3, to="Aisha")
        for name, place in (("Ravi", "clinic"), ("Jonas", "cafe"), ("Vera", "hall")):
            await does(name, "go", "You set off", place=place)
        await does("Lucia", "start_work", "You sat down to work")
        await settled("20:20")
        await does("Lucia", "examine", "You examined Ravi", patient="Ravi")
        await does("Jonas", "cook", "You cooked 1 portion", dish="soup", portions=1)
        await does("Vera", "announce", "You announced", text=ANNOUNCEMENT)
        await does("Lucia", "go", "You set off", place="cafe")
        await settled("20:30")
        await does("Lucia", "buy", "You had vegetable soup", item="soup")
        harness.rest(*OTHERS)
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
    for day, state in harness.checkpoints:  # as a run saves them
        run.checkpoint_path(day).write_text(json.dumps(state) + "\n", encoding="utf-8")
