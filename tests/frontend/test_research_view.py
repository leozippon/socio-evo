import json
from pathlib import Path

import pytest

from experiments.config import load_experiment
from frontend.research_server import ResearchData
from infrastructure.storage import RunDirectory
from simulation.run import _create
from world.events import Idle
from world.research import NoTasks


@pytest.fixture
def prepared(tmp_path):
    config = load_experiment(
        Path(__file__).resolve().parents[2] / "experiments/configs/research-zenith.yaml"
    )
    runs = tmp_path / "runs"
    directory = RunDirectory.create(runs, config.name, config=config, code_revision="test")
    world = _create(
        directory,
        config,
        NoTasks(),
        {r.name: r.background_path.read_text() for r in config.residents},
    )
    return ResearchData(runs), world, config.name


def test_initial_research_snapshot_includes_real_allowance_and_eight_residents(prepared):
    store, world, name = prepared
    value = store.snapshot(name)
    assert value["run"] == name
    assert len(value["people"]) == 8
    assert next(p for p in value["people"] if p["name"] == "Aisha")["money"] == 620
    assert value["counts"] == {}
    assert not any(f["path"] == "files/paper.md" for f in value["files"])
    assert value["activity"][0]["kind"] == "research_brief"
    assert "Choose the question" in value["activity"][0]["text"]


@pytest.mark.asyncio
async def test_dashboard_links_to_exact_committed_paper_and_evidence(prepared):
    store, world, name = prepared
    r = world.residents["Aisha"]
    r.base, r.place = Idle(), "office"
    await world.call(
        r,
        "write_repo_file",
        {"path": "paper.md", "content": "# Test question\n", "revision": world.research.snapshot()},
    )
    value = store.snapshot(name)
    assert value["counts"]["write_repo_file"] == 1
    assert value["records"][0]["actor"] == "Aisha"
    evidence = store.file(name, value["records"][0]["path"], value["revision"])
    assert json.loads(evidence["text"])["arguments"]["content"] == "# Test question\n"
    (world.research.files / "paper.md").write_text("uncommitted half-write")
    assert store.file(name, "files/paper.md", value["revision"])["text"] == "# Test question\n"


def test_dashboard_does_not_expose_private_files_or_outside_runs(prepared):
    store, world, name = prepared
    for path in ("../model-api-key", "agents/Aisha/background.md", "../.git/config"):
        with pytest.raises(FileNotFoundError):
            store.file(name, path)
    with pytest.raises(ValueError):
        store.snapshot("../other")
    with pytest.raises(ValueError):
        store.file(name, "files/README.md", "--help")


def test_viewer_waits_cleanly_before_first_run(tmp_path):
    assert ResearchData(tmp_path).snapshot() == {"runs": [], "waiting": True}
