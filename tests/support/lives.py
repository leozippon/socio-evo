"""Residents' lives for the learning tests: an agent directory in a repository tagged as a run's
checkpoints tag it, and turns lived on the real runtime against a scripted model and a port driven
by hand, so that the trace and the session are what the runtime writes."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent import files
from agent.directory import AgentDirectory
from agent.port import ToolResult
from agent.runtime import Runtime, RuntimeConfig
from infrastructure.git import Repository
from infrastructure.llm import LLMRequest, LLMResponse
from infrastructure.llm.scripted import reply, tool_call
from infrastructure.storage import day_tag
from tests.support.doubles import FakePort, ScriptedModel, running

BACKGROUND = "I am Ana, thirty-four, the baker. I moved here in spring and live above the shop."
DAY = 86_400


@dataclass(frozen=True)
class Step:
    """One request of a turn: the model's `reply` (or the error it raises), the port's answers to
    the reply's calls of the world's actions in order, and news delivered while it is in flight,
    `interrupting` or not."""

    reply: LLMResponse | BaseException
    results: Sequence[ToolResult] = ()
    meanwhile: Sequence[str] = ()
    interrupting: bool = False


@dataclass(frozen=True)
class Turn:
    """What the resident is `told` at simulated time `at`, asleep or not, and the `steps` its
    runtime takes on it until it rests."""

    at: int
    told: Sequence[str]
    steps: Sequence[Step] = ()
    asleep: bool = False


def resident(root: Path, background: str = BACKGROUND) -> AgentDirectory:
    """A new agent directory at `root`, a repository tagged `day-00`."""
    directory = AgentDirectory.create(root, background=background)
    Repository.init(root, user_name=root.name, user_email="resident@town.invalid")
    checkpoint(root, 0)
    return directory


def checkpoint(root: Path, day: int) -> None:
    """Commit the agent directory at `root` and tag it as day `day`'s checkpoint."""
    repository = Repository(root)
    moment = datetime(2026, 3, 2, 4, 30, tzinfo=UTC) + timedelta(days=day)
    repository.commit(day_tag(day), date=moment, allow_empty=True)
    repository.tag(day_tag(day), force=True)


async def live(
    directory: AgentDirectory, turns: Sequence[Turn], config: RuntimeConfig | None = None
) -> list[LLMRequest]:
    """Live `turns` on the runtime of `directory`; the requests the model was asked."""
    answers: list[ToolResult] = []
    names = {
        call.name
        for turn in turns
        for step in turn.steps
        if isinstance(step.reply, LLMResponse)
        for call in step.reply.tool_calls
        if call.name not in files.NAMES
    }
    port = FakePort(results={name: lambda args: answers.pop(0) for name in names})

    def respond(step: Step):
        def reply(request: LLMRequest) -> LLMResponse:
            for news in step.meanwhile:
                port.deliver(news, interrupt=step.interrupting)
            if isinstance(step.reply, BaseException):
                raise step.reply
            answers.extend(step.results)
            return step.reply

        return reply

    model = ScriptedModel(*(respond(step) for turn in turns for step in turn.steps))
    async with running(Runtime(directory, port, model, config)):
        for turn in turns:
            await _settle(port)
            port.asleep, port.clock = turn.asleep, turn.at
            for text in turn.told:
                port.deliver(text)
        await _settle(port)
    return model.requests


def at(day: int, hour: int, minute: int = 0) -> int:
    """The simulated time of `hour`:`minute` on day `day`."""
    return (day - 1) * DAY + hour * 3600 + minute * 60


async def a_day(directory: AgentDirectory, day: int, *, friend: str = "Ben") -> None:
    """Day `day` of an ordinary life, lived and checkpointed: three waking turns (waking and
    setting off, a word with `friend` at work, going to bed), then falling asleep."""
    await live(
        directory,
        [
            Turn(
                at(day, 7),
                ["You woke up at home."],
                [
                    Step(reply("", tool_call("look_around")), [ToolResult("You are at home.")]),
                    Step(
                        reply("Off to work.", tool_call("go", place="work")),
                        [ToolResult("You set off for work.", ends_turn=True)],
                    ),
                ],
            ),
            Turn(
                at(day, 8),
                [f"You arrived at work. {friend} is here."],
                [
                    Step(
                        reply("", tool_call("say", text=f"Morning, {friend}.")),
                        [ToolResult(f"You said to {friend}: “Morning, {friend}.”")],
                    ),
                    Step(reply("Back to the ovens.")),
                ],
            ),
            Turn(
                at(day, 22),
                ["It is getting late."],
                [Step(reply("", tool_call("sleep")), [ToolResult("You went to bed.", True)])],
            ),
            Turn(at(day, 22, 30), ["You fell asleep."], asleep=True),
        ],
    )
    checkpoint(directory.root, day)


async def _settle(port: FakePort) -> None:
    await asyncio.wait_for(port.waiting.wait(), 5)
