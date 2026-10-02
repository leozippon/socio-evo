from collections.abc import Callable
from typing import Any

import pytest

from core.agent import Agent, AgentSeed, CognitionConfig, ModelSpec, Profile
from core.agent.evolution import History
from core.interaction import EventKind, Observation, Percept, day_of, time_at
from infrastructure.llm import LLMRequest, Sampling, ScriptedClient

SEED = AgentSeed(
    profile=Profile(
        name="Mei",
        age=34,
        occupation="software developer",
        backstory="Mei moved to town last year and writes software for a living.",
    ),
    model=ModelSpec(model="town-model", sampling=Sampling(temperature=0.7)),
)


class Script:
    """A deterministic stand-in for the model that answers by purpose and keeps every request.

    `reflections` and `skills` map a day to that night's operations; `request` is made
    whenever a reflection's reply schema offers one.
    """

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []
        self.reflections: dict[int, list[dict[str, Any]]] = {}
        self.skills: dict[int, list[dict[str, Any]]] = {}
        self.request: dict[str, str] | None = None
        self.client = ScriptedClient(self.reply)

    def reply(self, request: LLMRequest) -> str | dict[str, Any]:
        self.requests.append(request)
        purpose, day = request.metadata["purpose"], day_of(request.metadata["time"])
        if purpose == "act":
            action = {"kind": "speak", "text": "It parses dates now.", "to": "Ben"}
            return {"thought": "Ben asked about the parser.", "action": action}
        if purpose == "diary":
            return f"Diary of day {day}."
        if purpose == "reflect":
            reply: dict[str, Any] = {
                "reflection": f"Looking back on day {day}.",
                "operations": self.reflections.get(day, []),
            }
            if self.request is not None and "request" in request.json_schema["properties"]:
                reply["request"] = self.request
            return reply
        if purpose == "skills":
            return {"reflection": f"Skills on day {day}.", "operations": self.skills.get(day, [])}
        if purpose == "policy":
            return {"rationale": f"Rationale of day {day}.", "policy": f"Policy of day {day}."}
        raise AssertionError(f"unexpected purpose {purpose}")

    def prompts(self, purpose: str) -> list[str]:
        """The user prompts sent for `purpose`, in order."""
        return [r.messages[-1].content for r in self.requests if r.metadata["purpose"] == purpose]


@pytest.fixture
def seed() -> AgentSeed:
    return SEED


@pytest.fixture
def script() -> Script:
    return Script()


@pytest.fixture
def agent(tmp_path, script) -> Agent:
    agent = Agent.create(tmp_path / "Mei", SEED, script.client, CognitionConfig())
    History.init(agent.path, agent.id).commit_experience(0)
    return agent


@pytest.fixture
def observe() -> Callable[..., Observation]:
    """An observation of Mei at the office at 09:00 on `day`, with one remark by Ben."""

    def observe(day: int, remark: str = "Ben says: does the parser handle dates?") -> Observation:
        time = time_at(day, "09:00")
        percept = Percept(
            seq=day,
            time=time - 1,
            kind=EventKind.SPEECH,
            actor="Ben",
            place="office",
            scene=f"office-{day}",
            text=remark,
        )
        return Observation(
            agent="Mei",
            time=time,
            place="office",
            scene=f"office-{day}",
            situation="You are at the office. Ben is here.",
            percepts=(percept,),
            allowed=("speak", "pass"),
        )

    return observe
