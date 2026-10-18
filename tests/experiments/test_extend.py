import random
from pathlib import Path

import pytest

from experiments.config import ExperimentConfig
from experiments.extend import fork_completed
from infrastructure.config import load_config
from infrastructure.storage import RunDirectory, RunStatus
from runtime.scheduler import TriggerKind
from runtime.simulation.simulation import Checkpoint


@pytest.fixture
def completed(tmp_path):
    config = load_config(
        Path(__file__).parents[2] / "experiments/configs/zenith/swebench-town.yaml",
        ExperimentConfig,
    )
    run = RunDirectory.create(tmp_path, config.name, 0, config=config, code_revision="test")
    run.events_path.write_text('{"day": 1}\n')
    checkpoint = Checkpoint(
        day=1,
        environment={"event_count": 1, "balances": {"Mei": 80}},
        queue=(),
        rng=random.Random(0).getstate(),
        agents={"Mei": "original-commit"},
    )
    run.checkpoint_path(1).write_text(checkpoint.model_dump_json())
    run.update_manifest(status=RunStatus.COMPLETED)
    repository = run.root / "repositories/workspaces/example"
    repository.mkdir(parents=True)
    (repository / "working.patch").write_text("saved patch")
    return run


def test_extension_preserves_source_state_and_schedules_next_day(completed):
    before = {
        p.relative_to(completed.root): p.read_bytes()
        for p in completed.root.rglob("*")
        if p.is_file()
    }
    result, config = fork_completed(completed.root, "continued", 3)
    checkpoint = Checkpoint.model_validate_json(result.checkpoint_path(1).read_text())
    assert config.simulation.days == 3
    assert checkpoint.environment["balances"] == {"Mei": 80}
    assert checkpoint.agents == {"Mei": "original-commit"}
    assert checkpoint.queue[0].kind == TriggerKind.DAY_START
    assert checkpoint.queue[0].time == config.simulation.calendar.start(2)
    assert result.events_path.read_bytes() == completed.events_path.read_bytes()
    assert (
        result.root / "repositories/workspaces/example/working.patch"
    ).read_text() == "saved patch"
    assert all((completed.root / p).read_bytes() == data for p, data in before.items())
    with pytest.raises(FileExistsError):
        fork_completed(completed.root, "continued", 3)


def test_rejects_uncheckpointed_events(completed):
    with completed.events_path.open("a") as stream:
        stream.write('{"day": 2}\n')
    with pytest.raises(ValueError, match="beyond"):
        fork_completed(completed.root, "continued", 3)


def test_rejects_partial_runs(completed):
    completed.update_manifest(status=RunStatus.INTERRUPTED)
    with pytest.raises(ValueError, match="completed"):
        fork_completed(completed.root, "continued", 3)


def test_rejects_shorter_duration(completed):
    with pytest.raises(ValueError, match="exceed"):
        fork_completed(completed.root, "continued", 1)
