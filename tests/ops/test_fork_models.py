"""A model-capability fork retains the completed history, never the source's partial day."""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from experiments.config import load_experiment
from infrastructure.git import Repository
from infrastructure.storage import RunDirectory, RunStatus
from ops.research.fork_models import fork_models
from ops.research.run_pair import configuration
from simulation.run import _create, _save
from world.research import NoTasks


@pytest.fixture
def stopped(tmp_path):
    config = configuration(Path("experiments/configs/ir-lab.yaml"), 20260302, None)
    source = RunDirectory.create(tmp_path / "old/runs", config.name,
                                 config=config, code_revision="old-code")
    world = _create(source, config, NoTasks(), {r.name: "A PhD peer." for r in config.residents})
    for resident in config.residents:
        (source.agent_dir(resident.name) / "memory/saved.md").write_text("completed-day memory")
    (world.research.files / "paper.tex").write_text("completed-day paper")
    world.research.repo.commit("Saved paper", date=datetime.now(UTC))
    world.clock.set(86400 + 16200)
    state = world.snapshot()
    world.record("checkpoint", lambda _: "saved", payload={"day": 1})
    _save(source, config.town, 1, state)
    for resident in config.residents:
        directory = source.agent_dir(resident.name)
        (directory / "memory/saved.md").write_text("partial-day memory")
        Repository(directory).commit("Partial day", date=datetime.now(UTC))
        (directory / "memory/untracked.md").write_text("unfinished")
    (world.research.files / "paper.tex").write_text("partial-day paper")
    world.research.repo.commit("Partial paper", date=datetime.now(UTC))
    world.clock.set(86400 + 20000)
    world.record("speech", lambda _: "partial-day conversation")
    runtime = source.root / "research_runtime/python"
    runtime.mkdir(parents=True)
    (runtime / "dependency.py").write_text("cached = True")
    source.update_manifest(status=RunStatus.INTERRUPTED, pid=None)
    return source, config, state


def invoke(source, tmp_path, **updates):
    return fork_models(
        source.root, tmp_path / "new/runs", name="ir-lab-models", inference_python=sys.executable,
        code_revision="new-code", launch_config=tmp_path / "new/profiles/models.yaml", **updates,
    )


def test_fork_is_exact_at_checkpoint_and_normal_launcher_can_resume(stopped, tmp_path):
    source, old_config, state = stopped
    old_log = source.world_log_path.read_bytes()
    old_head = Repository(source.root / "research").head()
    destination = invoke(source, tmp_path)
    fork = RunDirectory.open(destination)
    frozen = load_experiment(fork.config_path)
    launch = configuration(tmp_path / "new/profiles/models.yaml", old_config.town.seed, None)
    assert launch == frozen
    assert frozen.name == "ir-lab-models-seed-20260302"
    assert frozen.town.research.models_enabled
    assert frozen.town.research.inference_python == sys.executable
    old_data, new_data = old_config.model_dump(), frozen.model_dump()
    new_data["name"] = old_data["name"]
    for field in ("models_enabled", "inference_python"):
        new_data["town"]["research"][field] = old_data["town"]["research"][field]
    assert new_data == old_data  # schedule, identities, balances, seed and protocol unchanged
    assert json.loads(fork.checkpoint_path(1).read_text()) == state
    assert fork.latest_checkpoint() == 1
    assert fork.read_manifest().status == RunStatus.INTERRUPTED
    assert fork.read_manifest().code_revision == "new-code"
    events = [json.loads(line) for line in fork.world_log_path.read_text().splitlines()]
    assert events[-1]["kind"] == "checkpoint" and events[-1]["payload"]["day"] == 1
    assert b"partial-day conversation" not in fork.world_log_path.read_bytes()
    assert (fork.root / "research/files/paper.tex").read_text() == "completed-day paper"
    for resident in frozen.residents:
        directory = fork.agent_dir(resident.name)
        assert (directory / "memory/saved.md").read_text() == "completed-day memory"
        assert not (directory / "memory/untracked.md").exists()
        repo = Repository(directory)
        assert repo._git("tag", "--list").splitlines() == ["day-00", "day-01"]
        assert "Partial day" not in repo._git("log", "--all", "--format=%s")
    assert (fork.root / "research_runtime/python/dependency.py").is_file()
    lineage = json.loads((fork.root / "lineage.json").read_text())
    assert lineage["research_revision"] == state["research"]
    assert lineage["world_last_seq"] == events[-1]["seq"]
    assert "not checkpoint-versioned" in lineage["cache_semantics"]
    assert source.world_log_path.read_bytes() == old_log
    assert Repository(source.root / "research").head() == old_head
    assert (source.root / "research/files/paper.tex").read_text() == "partial-day paper"


def test_live_source_is_refused_before_any_copy(stopped, tmp_path):
    source, _, _ = stopped
    source.update_manifest(status=RunStatus.RUNNING, pid=os.getpid())
    with pytest.raises(ValueError, match="Stop the source"):
        invoke(source, tmp_path)
    assert not (tmp_path / "new").exists()
    source.update_manifest(status=RunStatus.INTERRUPTED)
    with pytest.raises(ValueError, match="live process"):
        invoke(source, tmp_path)


def test_incomplete_checkpoint_does_not_publish_fork(stopped, tmp_path):
    source, _, _ = stopped
    source.world_log_path.write_text("")
    with pytest.raises(ValueError, match="No world-log checkpoint"):
        invoke(source, tmp_path)
    assert not (tmp_path / "new").exists()


def test_existing_fork_is_never_overwritten(stopped, tmp_path):
    source, _, _ = stopped
    path = invoke(source, tmp_path)
    original = (path / "lineage.json").read_bytes()
    with pytest.raises(FileExistsError):
        invoke(source, tmp_path)
    assert (path / "lineage.json").read_bytes() == original
