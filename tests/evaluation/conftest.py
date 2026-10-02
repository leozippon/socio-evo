import itertools
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from core.agent import Agent, AgentSeed, CognitionConfig, Profile, prompts
from core.agent.evolution import History
from evaluation import DEFAULT_CONFIG, EvaluationConfig
from infrastructure.config import load_config
from infrastructure.llm import LLMClient, LLMRequest, ScriptedClient

NEUTRAL = {
    "submit_work": {"task_id": "task-9001", "solution": "pass\n", "report": "Delivered."},
    "speak": {"text": "See you at the cafe at nine."},
    "plan_day": {
        "itinerary": {"morning": "cafe", "afternoon": "office", "evening": "home"},
        "intention": "Meet Rosa, then work.",
    },
}
"""Decision fields for every kind a probe allows, in words that steer nothing."""


CHOOSE = re.compile(re.escape(prompts.CHOOSE).replace(re.escape("{kinds}"), "(.+?)"))


def allowed(prompt: str) -> list[str]:
    """The action kinds a decision prompt offers."""
    return CHOOSE.search(prompt)[1].split(", ")


class Agents:
    """A scripted stand-in for the evaluated agents' model that keeps every request.

    `actions` maps an action kind to the fields of the action taken whenever that kind is
    allowed: a dict, or a function of the user prompt returning one. An allowed kind given
    here is preferred; otherwise the first allowed kind with a NEUTRAL action is taken.
    """

    def __init__(self, **actions: dict[str, Any] | Callable[[str], dict[str, Any]]) -> None:
        self.actions = actions
        self.requests: list[LLMRequest] = []
        self.client = ScriptedClient(self.reply)

    def reply(self, request: LLMRequest) -> dict[str, Any]:
        self.requests.append(request)
        prompt = request.messages[-1].content
        kinds = allowed(prompt)
        kind = next((k for k in kinds if k in self.actions), None) or next(
            k for k in kinds if k in NEUTRAL
        )
        action = {**NEUTRAL, **self.actions}[kind]
        fields = action(prompt) if callable(action) else action
        return {"thought": "Time to decide.", "action": {"kind": kind, **fields}}

    def prompts(self, kind: str) -> list[str]:
        """The user prompts of the decisions on which `kind` was allowed, in order."""
        texts = [request.messages[-1].content for request in self.requests]
        return [text for text in texts if kind in allowed(text)]


def judge_client(*markers: str) -> ScriptedClient:
    """A judge that answers yes, quoting the first of `markers` found in the judged reply, and
    no without quotes otherwise."""

    def reply(request: LLMRequest) -> dict[str, Any]:
        judged = re.search(r"## Reply\n(.*)\n\n## Question", request.messages[-1].content, re.S)
        found = [marker for marker in markers if marker in judged[1]]
        return {"evidence": found[:1], "answer": bool(found)}

    return ScriptedClient(reply)


@pytest.fixture
def agents() -> type[Agents]:
    return Agents


@pytest.fixture
def judge() -> Callable[..., ScriptedClient]:
    return judge_client


@pytest.fixture
def make_agent(tmp_path) -> Callable[..., Agent]:
    """Create agent `name` in `root` (by default a new directory) answering through `client`,
    as a repository whose initial version is dated 0."""
    roots = (tmp_path / f"agents-{number}" for number in itertools.count())

    def make(name: str = "Mei", root: Path | None = None, client: LLMClient | None = None) -> Agent:
        seed = AgentSeed(
            profile=Profile(
                name=name,
                age=31,
                occupation="software developer",
                backstory=f"{name} lives in town and writes software for a living.",
            )
        )
        path = (root or next(roots)) / name
        agent = Agent.create(path, seed, client or Agents().client, CognitionConfig())
        History.init(agent.path, name).commit_experience(0)
        return agent

    return make


@pytest.fixture
def config() -> Callable[..., EvaluationConfig]:
    """The default evaluation config with `changes`."""
    default = load_config(DEFAULT_CONFIG, EvaluationConfig)

    def make(**changes: Any) -> EvaluationConfig:
        return EvaluationConfig.model_validate({**default.model_dump(), **changes})

    return make
