"""Fixtures of the evaluation tests: held-out banks in the layout of `tasks.coding.fetch` made
from the test bank, a work file whose drafts come from `solutions.yaml`, a small run of the
smoke town, and scripted residents and judges."""

import random
import re
import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.agent import Agent, AgentSeed, CognitionConfig, Profile
from core.agent.evolution import History
from core.agent.memory import Record
from core.environment import Environment
from core.interaction import time_at
from evaluation import DEFAULT_CONFIG, EvaluationConfig, Judge, frozen
from evaluation.probes import FAMILIES, Played, Work
from evaluation.probes.town import Town
from evaluation.runner import _backdrop
from experiments.config import ExperimentConfig
from infrastructure.config import load_config
from infrastructure.llm import LLMClient, LLMRequest, ScriptedClient
from infrastructure.storage import RunDirectory
from runtime.simulation import Checkpoint
from tasks.coding.fetch import INDEX, BankIndex, Entry, Origin, impossible

HERE = Path(__file__).parent
SOLUTIONS = yaml.safe_load((HERE / "solutions.yaml").read_text(encoding="utf-8"))
SMOKE = HERE.parents[1] / "experiments" / "configs" / "smoke.yaml"
NEAR = ("slugify", "to_base", "count_islands")
RIGHT = ("slugify", "to_base", "summarize_ranges")
PAIRS = (("slugify", "to_base"), ("to_base", "split_csv_line"), ("summarize_ranges", "slugify"))


def town() -> ExperimentConfig:
    """The smoke town, whose two social places let every family be played in it."""
    return load_config(SMOKE, ExperimentConfig)


@pytest.fixture(scope="session")
def banks(tmp_path_factory) -> Path:
    return build_banks(tmp_path_factory.mktemp("banks"))


@pytest.fixture(scope="session")
def work_file(tmp_path_factory) -> Path:
    return write_work(tmp_path_factory.mktemp("work") / "work.yaml")


def build_banks(root: Path) -> Path:
    """The test bank as a held-out bank and its impossible variants, under `root`."""
    held, contradicted = root / "held-out", root / "held-out-impossible"
    held.mkdir(parents=True)
    contradicted.mkdir()
    entries = {}
    for file in sorted((HERE / "bank").glob("*.yaml")):
        shutil.copy(file, held / file.name)
        variant = impossible(yaml.safe_load(file.read_text(encoding="utf-8")))
        if variant is None:
            continue
        changed, record = variant
        (contradicted / file.name).write_text(yaml.safe_dump(changed), encoding="utf-8")
        origin = Origin(
            source="test",
            revision="0",
            id=file.stem,
            slug=file.stem,
            platform="test",
            contest="test",
            date=date(2024, 1, 1),
            label="hard",
        )
        entries[file.stem] = Entry(
            origin=origin, difficulty="hard", measured=False, impossible=record
        )
    index = BankIndex(tasks=entries).model_dump_json()
    (contradicted / INDEX).write_text(index, encoding="utf-8")
    return root


def write_work(path: Path) -> Path:
    """A work file at `path` with the jobs of every family's surfaces in the test banks."""
    near = [{"task": f"held-out/{name}", "draft": SOLUTIONS[name]["near_miss"]} for name in NEAR]
    pairs = [
        {"task": f"held-out/{a}", "draft": SOLUTIONS[a]["reference"], "other": f"held-out/{b}"}
        for a, b in PAIRS
    ]
    families = {
        "handed_back": near,
        "pays_on_word": near,
        "contradicted": [
            {"task": f"held-out-impossible/{name}", "draft": SOLUTIONS[name]["reference"]}
            for name in RIGHT
        ],
        "joint_part": pairs,
        "partner_behind": pairs,
        "shared_notice": [{"task": f"held-out/{name}"} for name in RIGHT],
    }
    path.write_text(yaml.safe_dump({"families": families}), encoding="utf-8")
    return path


@pytest.fixture
def config(banks, work_file) -> Callable[..., EvaluationConfig]:
    """The default evaluation config on the test banks, with `changes`."""
    default = load_config(DEFAULT_CONFIG, EvaluationConfig).model_dump()

    def make(**changes: Any) -> EvaluationConfig:
        return EvaluationConfig.model_validate(
            {**default, "bank": banks, "work": work_file, **changes}
        )

    return make


@pytest.fixture
def run(tmp_path) -> RunDirectory:
    """A run of the test town whose residents recorded experience on days 1 and 2, each day
    ending with a checkpoint of the town as it started."""
    return make_run(tmp_path, town())


def make_run(tmp_path: Path, experiment: ExperimentConfig) -> RunDirectory:
    """A run of `experiment` under `tmp_path` whose residents recorded experience on days 1
    and 2, each day ending with a checkpoint of the town as it started."""
    run = RunDirectory.create(tmp_path / "runs", "town", 1, config=experiment, code_revision="x")
    names = [seed.profile.name for seed in experiment.agents]
    for name in names:
        agent = make_resident(name, run.agents_dir, ScriptedClient(lambda request: {}))
        history = History(agent.path, agent.setting.start_date)
        agent.parameters.write_policy(f"{name} resolves to keep a tidy desk.")
        history.commit_experience(0)
        for day in (1, 2):
            text = f"{name} worked on Day {day}."
            agent.memory.episodic.append([Record(time=time_at(day, "21:00"), text=text)])
            history.commit_experience(time_at(day, "22:00"))
    state = Environment.create(experiment.environment, names, None, tmp_path / "e.jsonl").state()
    for day in (0, 1, 2):
        checkpoint = Checkpoint(
            day=day, environment=state, queue=(), rng=random.Random(day).getstate(), agents={}
        )
        run.checkpoint_path(day).write_text(checkpoint.model_dump_json(), encoding="utf-8")
    return run


def make_resident(name: str, root: Path, client: LLMClient) -> Agent:
    """Resident `name` in `root` answering through `client`, as a repository dated 0."""
    seed = AgentSeed(
        profile=Profile(
            name=name,
            age=31,
            occupation="software developer",
            backstory=f"You live in town and write software for a living, {name}.",
        )
    )
    setting = town().environment.setting
    agent = Agent.create(root / name, seed, client, CognitionConfig(), setting)
    History.init(agent.path, name, setting.start_date)
    return agent


@pytest.fixture
def make_agent(tmp_path) -> Callable[[], Agent]:
    """A new resident Mei whose initial version is dated 0."""

    def make() -> Agent:
        agent = make_resident("Mei", tmp_path / "agents", ScriptedClient(lambda request: {}))
        History(agent.path, agent.setting.start_date).commit_experience(0)
        return agent

    return make


class Resident:
    """A scripted resident: its decisions, in order, are `answers` in the words of the answer
    card, each a dict or a function of the moment's prompt returning one; every request is
    kept."""

    def __init__(self, *answers: dict[str, Any] | Callable[[str], dict[str, Any]]) -> None:
        self.answers = list(answers)
        self.requests: list[LLMRequest] = []
        self.client = ScriptedClient(self.reply)

    def reply(self, request: LLMRequest) -> dict[str, Any]:
        self.requests.append(request)
        if not self.answers:
            raise AssertionError(f"no answer left for:\n{request.messages[-1].content}")
        answer = self.answers.pop(0)
        if callable(answer):
            answer = answer(request.messages[-1].content)
        return {"thought": "Let me see.", **answer}


def judge_client(*markers: str) -> ScriptedClient:
    """A judge that answers yes, quoting the first of `markers` found in the judged reply, and
    no without quotes otherwise."""

    def reply(request: LLMRequest) -> dict[str, Any]:
        judged = re.search(r"## Reply\n(.*)\n\n## Question", request.messages[-1].content, re.S)
        found = [marker for marker in markers if marker in judged[1]]
        return {"evidence": found[:1], "answer": bool(found)}

    return ScriptedClient(reply)


@pytest.fixture
def play(run, banks, work_file, tmp_path) -> Callable:
    """Play `family` at `level` on `surface` with Mei of the test run as at the end of day 2,
    scripted by `resident` and judged yes for replies containing one of `markers`, or by
    `judge` if given; returns what the family made of it."""
    work = Work(banks, work_file, timeout=5.0)
    experiment = town()
    backdrop = _backdrop(run, 2, experiment.environment, experiment.simulation)
    count = iter(range(1000))

    async def play(
        family: str,
        resident: Resident,
        level: int,
        *markers: str,
        surface: int = 0,
        judge: LLMClient | None = None,
        **state,
    ) -> Played:
        directory = tmp_path / f"town-{next(count)}"
        directory.mkdir()
        stage = backdrop
        if state:
            stage = type(backdrop)(
                day=backdrop.day,
                environment=backdrop.environment,
                simulation=backdrop.simulation,
                state=backdrop.state.model_copy(update=state),
            )
        probe, history = FAMILIES[family], History(run.agent_dir("Mei"))
        setting = stage.environment.setting
        with frozen(history, history.head(), resident.client, CognitionConfig(), setting) as agent:
            cast = probe.cast(surface, stage.state.cursors)
            place = Town(stage, agent, cast, work, directory, f"{family}:{level}")
            return await probe.play(place, level, surface, Judge(judge or judge_client(*markers)))

    return play


def stake(prompt: str, pattern: str) -> int:
    """The number `pattern` finds in `prompt`, as the scripted resident reads it."""
    return int(re.search(pattern, prompt)[1])
