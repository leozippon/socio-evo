import json
from pathlib import Path

import pytest

from experiments.config import load_experiment
from frontend.publish import Publisher
from frontend.research_server import ResearchData
from infrastructure.storage import RunDirectory
from simulation.run import _create
from world.clock import DAY
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


async def test_delayed_commission_replays_living_allowance_only_at_start(tmp_path):
    config = load_experiment(
        Path(__file__).resolve().parents[2] / "experiments/configs/ai-lab.yaml"
    )
    runs = tmp_path / "runs"
    directory = RunDirectory.create(runs, config.name, config=config, code_revision="test")
    world = _create(
        directory, config, NoTasks(),
        {r.name: r.background_path.read_text() for r in config.residents},
    )
    def balances():
        snapshot = ResearchData(runs).snapshot(config.name)
        actual = {r.name: r.inventory.money for r in world.residents.values()}
        assert {p["name"]: p["money"] for p in snapshot["people"]} == actual
        return actual

    assert set(balances().values()) == {200 + config.town.research.allowance}
    snapshot = ResearchData(runs).snapshot(config.name)
    assert snapshot["paper_artifact"] == "paper.tex"
    assert [s["day"] for s in snapshot["scheduled_milestones"]] == [28, 49, 70]
    resident = world.residents["Aisha"]
    resident.base, resident.place = Idle(), "store"
    await world.call(resident, "buy", {"item": "bread"})
    before = balances()
    world.clock.set(7 * DAY + 7 * 3600)
    world.research.announce(world)
    assert balances() == before


async def test_academy_dashboard_and_publisher_need_no_service_residents(tmp_path):
    config = load_experiment(
        Path(__file__).resolve().parents[2] / "experiments/configs/autoresearch-academy.yaml"
    )
    runs = tmp_path / "runs"
    directory = RunDirectory.create(runs, config.name, config=config, code_revision="test")
    world = _create(
        directory,
        config,
        NoTasks(),
        {r.name: r.background_path.read_text() for r in config.residents},
    )
    resident = world.residents["Aisha"]
    resident.base, resident.place = Idle(), "store"
    await world.call(resident, "buy", {"item": "bread"})
    resident.place = "hospital"
    await world.call(resident, "seek_care", {"service": "examination"})
    await world.call(resident, "seek_care", {"service": "treatment"})
    grant = {
        "stage": "proposal",
        "day": 7,
        "score": 50,
        "reward_per_resident": 315,
        "reward_total": 1260,
        "status": "reviewed",
        "summary": "Feasible question.",
        "review": {"evidence": ["files/proposal.md"]},
        "audit": "research_reviews/proposal",
    }
    for person in world.residents.values():
        person.inventory.receive(315, "received", "research grant proposal")
    world.record("research_milestone", lambda w: "Proposal reviewed.", payload=grant)
    snapshot = ResearchData(runs).snapshot(config.name)
    assert {p["name"] for p in snapshot["people"]} == {"Mei", "Aisha", "Ravi", "Kofi"}
    assert {p["occupation"] for p in snapshot["people"]} == {"teacher", "student"}
    assert {p["name"]: p["money"] for p in snapshot["people"]} == {
        p.name: p.inventory.money for p in world.residents.values()
    }
    assert snapshot["milestones"][0]["review"]["evidence"] == ["files/proposal.md"]
    assert snapshot["milestones"][0]["record"] == "records/milestone-proposal.json"
    assert snapshot["comparison"][0]["scores"] == {"proposal": 50}
    assert snapshot["comparison"][0]["reward_total"] == 1260
    site = tmp_path / "site"
    Publisher(runs, site).publish()
    bundle = json.loads((site / "data" / "runs" / config.name / "world.json").read_text())
    assert len(bundle["residents"]) == 4
    assert {r["occupation"] for r in bundle["residents"]} == {"teacher", "student"}
