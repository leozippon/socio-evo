"""An agent: a directory of human-readable files, and the cognition that reads them."""

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

from core.agent import prompts
from core.agent.config import AgentSeed, CognitionConfig, Profile
from core.agent.memory import Memory, Record, Retriever
from core.agent.parameters import Parameters
from core.interaction import Card, Decision, Observation, Percept, form
from infrastructure.config import load_config
from infrastructure.llm import (
    LLMClient,
    LLMRequest,
    Message,
    complete_structured,
    complete_text,
)

T = TypeVar("T", bound=BaseModel)


class Agent:
    """The agent stored at `path`.

    The files are the source of truth and are read whenever needed, so the object stays valid
    when its directory is reset to an earlier commit. Every model call goes through `client`
    with `agent`, `purpose` and `time` in its metadata.
    """

    def __init__(
        self, path: Path, profile: Profile, client: LLMClient, cognition: CognitionConfig
    ) -> None:
        self.path = path
        self.profile = profile
        self.client = client
        self.cognition = cognition
        self.memory = Memory(path / "memory")
        self.parameters = Parameters(path / "parameters")
        self._retriever = Retriever(cognition)

    @classmethod
    def create(
        cls,
        path: Path,
        seed: AgentSeed,
        client: LLMClient,
        cognition: CognitionConfig,
    ) -> "Agent":
        """Write a new agent directory at `path` from `seed` and open it.

        Raises FileExistsError if `path` exists. Version history is separate: see
        `core.agent.evolution.History`.
        """
        path.mkdir(parents=True)
        _write_yaml(path / "profile.yaml", seed.profile)
        (path / "parameters").mkdir()
        Parameters(path / "parameters").write_policy(seed.policy)
        _write_yaml(path / "parameters" / "model.yaml", seed.model)
        (path / "memory").mkdir()
        for store in ("episodic.jsonl", "insights.jsonl"):
            (path / "memory" / store).touch()
        return cls.load(path, client, cognition)

    @classmethod
    def load(cls, path: Path, client: LLMClient, cognition: CognitionConfig) -> "Agent":
        """Open the agent directory at `path`, which need not be a git repository."""
        return cls(path, load_config(path / "profile.yaml", Profile), client, cognition)

    @property
    def id(self) -> str:
        return self.profile.name

    async def act(self, observation: Observation) -> Decision:
        """Store the new percepts, recall memories, answer on the moment's card, and record
        the decision the answer means.

        Raises ValueError if the observation is addressed to another agent.
        """
        if observation.agent != self.id:
            raise ValueError(f"observation for {observation.agent!r} given to {self.id!r}")
        memory = self.memory
        earlier = memory.episodic.read()
        self.perceive(observation.percepts, observation.places)
        skills = memory.skills.read()
        recall = self._retriever.recall(observation, earlier, memory.insights.read(), skills)
        system = prompts.system_prompt(
            self.profile,
            self.parameters.read_policy(),
            self.cognition,
            setting=observation.setting,
            skills=skills,
        )
        card = Card(observation.allowed)
        reply = await self.ask(
            "act",
            observation.time,
            prompts.decision_prompt(observation, recall, self.cognition),
            card.model,
            system=system,
        )
        decision = card.decision(reply)
        memory.episodic.append(
            [
                Record(
                    time=observation.time,
                    place=observation.place,
                    where=observation.places.get(observation.place),
                    text=prompts.recollection(decision),
                )
            ]
        )
        return decision

    def perceive(
        self, percepts: Iterable[Percept], places: Mapping[str, str] | None = None
    ) -> None:
        """Store percepts in the episodic stream, naming their places as `places` (by id) do;
        `act` does so for an observation's percepts, and this is for those witnessed when no
        decision follows, such as late in the day."""
        self.memory.episodic.append(Record.of(percept, places) for percept in percepts)

    async def ask(
        self, purpose: str, time: int, prompt: str, reply: type[T], *, system: str | None = None
    ) -> T:
        """A validated `reply` to `prompt`, after which the form of the reply is shown. The
        system prompt defaults to identity and policy."""
        request = self._request(purpose, time, system, f"{prompt}\n\n{form(reply)}")
        return await complete_structured(self.client, request, reply)

    async def write(self, purpose: str, time: int, prompt: str) -> str:
        """Free text in reply to `prompt`, with identity and policy as the system prompt."""
        text = await complete_text(self.client, self._request(purpose, time, None, prompt))
        return text.strip()

    def _request(self, purpose: str, time: int, system: str | None, prompt: str) -> LLMRequest:
        spec = self.parameters.read_model()
        if system is None:
            system = prompts.system_prompt(
                self.profile, self.parameters.read_policy(), self.cognition
            )
        return LLMRequest(
            messages=(
                Message(role="system", content=system),
                Message(role="user", content=prompt),
            ),
            model=spec.model,
            sampling=spec.sampling,
            metadata={"agent": self.id, "purpose": purpose, "time": time},
        )


def _write_yaml(path: Path, model: BaseModel) -> None:
    path.write_text(
        yaml.safe_dump(model.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
