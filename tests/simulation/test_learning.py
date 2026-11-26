"""A town that learns, end to end: its days played by the dry run's scripted residents, its nights
by a scripted choice beside them, with a fake trainer and a fake model server. Each resident wakes
on its own adapter, a resumed run puts it back on it, and a night that cannot be completed fails
the run, which resuming then completes."""

from __future__ import annotations

import json
import re

import pytest

import simulation.run as simulation
from experiments.config import PROJECT_ROOT, load_experiment
from infrastructure.llm import LLMRequest, ScriptedClient
from infrastructure.llm.scripted import reply, tool_call
from infrastructure.storage import RunDirectory
from learning.adapters import fitted
from learning.fit import TrainerError
from simulation.dry_run import DryRunModel
from tests.support.server import KEY, FakeServer
from tests.support.trainer import fake_trainer
from world.config import SEARCH_KEY
from world.testing import FakeBackend
from world.world import World

RESIDENTS = ("Mei", "Aisha", "Olga", "Jonas", "Lucia", "Marek")


class Town:
    """The model of a town that learns: by day the dry run's residents; by night each resident
    keeps the last moment of its last day and then stops, and every generalising is answered
    alike. It keeps every request."""

    def __init__(self, config) -> None:
        self.day = DryRunModel(config.town)
        self.requests: list[LLMRequest] = []

    def __call__(self, request: LLMRequest):
        self.requests.append(request)
        if request.json_schema:
            return {"situation": "You start work early.", "response": "I begin at once."}
        if not _choosing(request):
            return self.day(request)
        if request.messages[-1].role == "tool":
            return reply("That is all.")
        last = re.findall(r"moments \d+ to (\d+)", request.messages[1].content)[-1]
        return reply("", tool_call("keep", moment=int(last)))

    def steps(self) -> list[tuple[str, str | None]]:
        """Each request of a resident's day: its name and the model it asked."""
        return [(_resident(r), r.model) for r in self.requests if r.tools and not _choosing(r)]

    def choices(self) -> list[tuple[str, str | None]]:
        return [(_resident(r), r.model) for r in self.requests if _choosing(r)]


@pytest.fixture
def server(monkeypatch):
    """The model server, the fake work backend, the web's key (the town has the web, which its
    scripted residents never use), and the world's numbers, as a stand-in."""
    monkeypatch.setenv(SEARCH_KEY, "a key")
    monkeypatch.setattr(
        simulation, "SwebenchBackend", lambda: FakeBackend(simulation.DRY_RUN_TASKS)
    )
    monkeypatch.setattr(World, "liked_by", lambda w: {n: 1 for n in w.residents}, raising=False)
    with FakeServer() as running:
        monkeypatch.setenv(KEY, running.key)
        yield running


def learning_town(tmp_path, server, monkeypatch, *, days: int):
    """The smoke town learning on the Social arm's settings over `days` days, on the dry run's
    clock, its trainer and server the fakes; and its model."""
    config = load_experiment(PROJECT_ROOT / "experiments" / "configs" / "smoke.yaml")
    town = config.town
    clock = town.clock.model_copy(update=simulation.DRY_RUN_SPEEDS)
    trainer = config.learning.trainer.model_copy(update={"python": fake_trainer(tmp_path)})
    config = config.model_copy(
        update={
            "name": "smoke-learning",
            "days": days,
            "llm": config.llm.model_copy(update={"base_url": server.url, "api_key_env": KEY}),
            "town": town.model_copy(update={"clock": clock}),
            "learning": config.learning.model_copy(update={"trainer": trainer}),
        }
    )
    model = Town(config)
    monkeypatch.setattr(simulation, "_client", lambda config, dry_run: ScriptedClient(model))
    return config, model


async def test_each_resident_wakes_on_its_own_adapter_and_a_resumed_run_puts_it_back(
    tmp_path, server, monkeypatch
):
    config, model = learning_town(tmp_path, server, monkeypatch, days=2)
    root, status = await simulation.run(config, tmp_path / "runs", until_day=1)
    assert status == "interrupted"
    run = RunDirectory.open(root)
    first = {name: fitted(root, name, 1).name for name in RESIDENTS}
    assert all(first[n].startswith(f"smoke-learning-{n}-night-01-") for n in RESIDENTS)
    assert set(server.loaded) == set(first.values())
    assert {model for _, model in model.steps()} == {None}  # the first day, on the base
    assert {model for _, model in model.choices()} == {None}
    done = json.loads((run.night_dir(1) / "done.json").read_text())["residents"]
    assert {name: summary["adapter"] for name, summary in done.items()} == first

    model.requests.clear()
    root, status = await simulation.run(config, tmp_path / "runs", resume=True)
    assert status == "completed"
    # The resumed run put every resident back on the adapter of night 1: its day and its choice
    # of night 2 ask that adapter, and the night switched it to its adapter of night 2.
    assert set(model.steps()) == set(first.items())
    assert set(model.choices()) == set(first.items())
    second = {fitted(root, name, 2).name for name in RESIDENTS}
    assert set(server.loaded) == second
    log = run.run_log_path.read_text()
    assert "lived night 1 in" in log and "night 2 complete" in log
    for name in RESIDENTS:
        requests = [r for r in _trace(run.agent_dir(name)) if r["kind"] == "request" and r["model"]]
        assert {r["model"] for r in requests} == {first[name]}


async def test_a_night_that_cannot_be_completed_fails_the_run_and_resuming_completes_it(
    tmp_path, server, monkeypatch
):
    config, model = learning_town(tmp_path, server, monkeypatch, days=1)
    monkeypatch.setenv("FAKE_TRAINER_FAIL", "1")
    with pytest.raises(TrainerError, match="exited with 3"):
        await simulation.run(config, tmp_path / "runs")
    run = RunDirectory.open(tmp_path / "runs" / "smoke-learning")
    assert (run.read_manifest().status, run.read_manifest().pid) == ("failed", None)
    assert run.checkpoint_path(1).is_file() and not (run.night_dir(1) / "done.json").exists()
    assert "the run failed" in run.run_log_path.read_text() and server.loaded == {}
    chosen = len(model.choices())

    monkeypatch.delenv("FAKE_TRAINER_FAIL")
    root, status = await simulation.run(config, tmp_path / "runs", resume=True)
    assert status == "completed" and (run.night_dir(1) / "done.json").is_file()
    assert len(model.choices()) == chosen  # the choices were made already, and are kept
    assert set(server.loaded) == {fitted(root, name, 1).name for name in RESIDENTS}
    with pytest.raises(ValueError, match="already saved day 1"):
        await simulation.run(config, tmp_path / "runs", resume=True)


def _choosing(request: LLMRequest) -> bool:
    return any(tool["function"]["name"] == "look_back" for tool in request.tools)


def _resident(request: LLMRequest) -> str:
    return re.search(r"\bI am (\w+)", request.messages[0].content)[1]


def _trace(agent):
    return [json.loads(line) for line in (agent / "trace.jsonl").read_text().splitlines()]
