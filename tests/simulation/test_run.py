"""A town run dry, end to end: the run directory a day writes, stopping after a day and resuming,
and the ways a run refuses to start or fails."""

from __future__ import annotations

import asyncio
import json

import pytest

import simulation.run as simulation
from agent.runtime import Runtime
from experiments.config import PROJECT_ROOT, load_experiment
from infrastructure.git import Repository
from infrastructure.llm import LLMConfigError
from infrastructure.storage import RunDirectory, read_jsonl


def smoke(**changes):
    config = load_experiment(PROJECT_ROOT / "experiments" / "configs" / "smoke.yaml")
    return config.model_copy(update=changes)


@pytest.fixture(scope="module")
def smoke_run(tmp_path_factory):
    """The smoke town's day, run dry once for the tests that only read it."""
    runs = tmp_path_factory.mktemp("runs")
    root, status = asyncio.run(simulation.run(smoke(), runs, dry_run=True))
    return runs, root, status


def kinds(root) -> list[str]:
    return [entry["kind"] for entry in read_jsonl(root / "world.jsonl")]


def test_a_dry_day_writes_the_whole_run_directory(smoke_run):
    runs, root, status = smoke_run
    assert root == runs / "smoke-dry-run" and status == "completed"
    run = RunDirectory.open(root)
    manifest = run.read_manifest()
    assert manifest.status == "completed" and manifest.ended_at is not None
    assert load_experiment(run.config_path) == simulation.as_dry_run(smoke())
    assert sorted(path.name for path in run.checkpoints_dir.iterdir()) == [
        "day-00.json",
        "day-01.json",
    ]
    saved = json.loads(run.checkpoint_path(1).read_text())
    assert set(saved["residents"]) == {"Mei", "Tomas"}
    log = kinds(root)
    for kind in ("wake", "claim", "verdict", "payment", "speech", "sleep", "settlement"):
        assert kind in log, kind
    assert log[-1] == "checkpoint" and "forced_sleep" not in log
    for name in ("Mei", "Tomas"):
        agent = run.agent_dir(name)
        repository = Repository(agent)
        assert [c.subject for c in repository.log()] == [
            "day-01: Tuesday 3 March, 02:30",
            "day-00: Monday 2 March, 02:30",
        ]
        assert repository.tree("day-01") and not repository.has_changes()
        assert (agent / "memory" / "journal" / "2026-03-02.md").read_text().strip()
        assert repository.read_file("day-00", "memory/town.md").startswith("How the town works.")
        assert repository.read_file("day-00", "memory/people.md") == "# People\n"
        assert repository.read_file("day-00", "background.md").startswith(f"You are {name}, ")
        assert "session.jsonl" in repository.tree("day-01")
    assert "saved day 1" in run.run_log_path.read_text()


def test_an_existing_run_is_not_created_again_nor_resumed_with_another_configuration(smoke_run):
    runs, root, _ = smoke_run
    with pytest.raises(FileExistsError):
        asyncio.run(simulation.run(smoke(), runs, dry_run=True))
    with pytest.raises(ValueError, match="differs from the one frozen"):
        asyncio.run(simulation.run(smoke(days=2), runs, resume=True, dry_run=True))
    with pytest.raises(ValueError, match="already saved day 1"):
        asyncio.run(simulation.run(smoke(), runs, resume=True, dry_run=True))
    assert RunDirectory.open(root).read_manifest().status == "completed"


async def test_a_run_stopped_after_a_day_resumes_where_it_stopped(tmp_path):
    config = smoke(days=2)
    root, status = await simulation.run(config, tmp_path, until_day=1, dry_run=True)
    assert status == "interrupted"
    assert RunDirectory.open(root).read_manifest().status == "interrupted"
    first = len(kinds(root))

    root, status = await simulation.run(config, tmp_path, resume=True, dry_run=True)
    assert status == "completed"
    entries = list(read_jsonl(root / "world.jsonl"))
    assert [entry["seq"] for entry in entries] == list(range(1, len(entries) + 1))
    resume = entries[first]
    assert resume["kind"] == "resume" and resume["payload"]["day"] == 1
    assert [entry["kind"] for entry in entries].count("checkpoint") == 2
    for name in ("Mei", "Tomas"):
        agent = RunDirectory(root).agent_dir(name)
        assert Repository(agent).tree("day-02")
        assert sorted(path.name for path in (agent / "memory" / "journal").iterdir()) == [
            "2026-03-02.md",
            "2026-03-03.md",
        ]


async def test_a_runtime_that_ends_fails_the_run_instead_of_hanging_it(tmp_path, monkeypatch):
    class SecondDies(Runtime):
        built = 0

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            SecondDies.built += 1
            self.dies = SecondDies.built == 2

        async def run(self) -> None:
            if self.dies:
                await asyncio.sleep(0.5)
                raise OSError("the disk is gone")
            await super().run()

    monkeypatch.setattr(simulation, "Runtime", SecondDies)
    async with asyncio.timeout(60):
        with pytest.raises(RuntimeError, match="the runtime of Tomas ended") as raised:
            await simulation.run(smoke(), tmp_path, dry_run=True)
    assert isinstance(raised.value.__cause__, OSError)
    run = RunDirectory.open(tmp_path / "smoke-dry-run")
    assert run.read_manifest().status == "failed"
    assert "the run failed" in run.run_log_path.read_text()


async def test_nothing_is_written_when_a_background_or_the_model_is_missing(tmp_path, monkeypatch):
    config = smoke()
    lost = config.residents[0].model_copy(update={"background": "experiments/residents/x.md"})
    with pytest.raises(FileNotFoundError):
        await simulation.run(
            config.model_copy(update={"residents": (lost, *config.residents[1:])}),
            tmp_path,
            dry_run=True,
        )
    monkeypatch.delenv("VLLM_BASE_URL", raising=False)
    with pytest.raises(LLMConfigError, match="unset variable"):
        await simulation.run(config, tmp_path)
    monkeypatch.setenv("VLLM_BASE_URL", "http://127.0.0.1:9/v1")
    llm = config.llm.model_copy(update={"api_key_env": "SOCIO_EVO_NO_SUCH_KEY"})
    with pytest.raises(LLMConfigError, match="SOCIO_EVO_NO_SUCH_KEY is not set"):
        await simulation.run(config.model_copy(update={"llm": llm}), tmp_path)
    assert list(tmp_path.iterdir()) == []
