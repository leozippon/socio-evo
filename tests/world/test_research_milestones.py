"""Collective reviews, real checkpoint restoration and failure-before-payment behavior."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent.directory import AgentDirectory
from experiments.config import load_experiment
from infrastructure.llm import ScriptedClient, StructuredOutputError
from simulation.run import run
from world import research_milestones
from world.clock import ManualClock
from world.config import ResearchSettings
from world.research import NoTasks, milestone_terms
from world.world import World

CONFIG = Path(__file__).resolve().parents[2] / "experiments/configs/research.yaml"
PROPOSAL = "A falsifiable question with a controlled comparison."


def review_reply(scores=(4, 3, 2, 1)):
    return {
        **{
            name: {
                "score": score,
                "rationale": "Supported at this stage, with stated gaps.",
                "citations": [{"path": "files/proposal.md", "quote": "A falsifiable question"}],
            }
            for name, score in zip(research_milestones.DIMENSIONS, scores, strict=True)
        },
        "summary": "A feasible proposal, with remaining literature and procedure gaps.",
    }


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    config = load_experiment(CONFIG)
    settings = ResearchSettings(
        judge={
            "base_url": "https://judge.invalid/v1",
            "api_key_env": "JUDGE_KEY",
            "model": "judge",
        },
        milestones=[
            {"id": "proposal", "day": 7, "artifact": "proposal.md", "max_reward_per_resident": 100}
        ],
    )
    config = config.model_copy(
        update={"town": config.town.model_copy(update={"research": settings})}
    )
    for resident in config.residents:
        AgentDirectory.create(
            tmp_path / "agents" / resident.name, background=resident.background_path.read_text()
        )
    world = World(config.town, tmp_path, NoTasks(), clock=ManualClock())
    world.research.initialize(world)
    (world.research.files / "proposal.md").write_text(PROPOSAL)
    world.research.repo.commit("Save proposal", date=datetime.now(UTC))
    calls = []
    client = ScriptedClient(lambda request: calls.append(request) or review_reply())
    monkeypatch.setattr(research_milestones, "create_client", lambda _: client)
    return config, world, calls


async def test_collective_score_grant_checkpoint_resume_and_review_cache(prepared):
    config, world, calls = prepared
    before = world.snapshot()
    starting = {name: r.inventory.money for name, r in world.residents.items()}
    await world.research.review(world, 6)
    assert calls == []
    await world.research.review(world, 7)
    paid = world.snapshot()
    for name, resident in world.residents.items():
        assert resident.inventory.money == starting[name] + 62
    record = json.loads((world.research.records / "milestone-proposal.json").read_text())
    assert record["score"] == 62.5
    assert record["reward_total"] == 62 * 8
    assert record["judge_model"] == "judge"
    assert len(calls) == 1
    for state in (paid, before):
        restored = World(config.town, world.research.root.parent, NoTasks(), clock=ManualClock())
        restored.restore(state)
        await restored.research.review(restored, 7)
        for name, resident in restored.snapshot()["residents"].items():
            assert resident["inventory"] == paid["residents"][name]["inventory"]
            assert sum(p["kind"] == "research_milestone" for p in resident["held"]) == 1
    assert len(calls) == 1  # Replaying before payment reuses the exact successful review.
    audit = world.research.root.parent / record["audit"]
    assert (
        json.loads((audit / "input.json").read_text())["packet"]["documents"]["files/proposal.md"]
        == PROPOSAL
    )
    attempt = json.loads((audit / "attempts.jsonl").read_text())
    assert attempt["response"]["text"]
    assert "replica" not in attempt["request"] or attempt["request"]["replica"] is None


async def test_missing_deliverable_is_zero_without_calling_judge(prepared):
    _, world, calls = prepared
    (world.research.files / "proposal.md").unlink()
    world.research.repo.commit("No proposal submitted", date=datetime.now(UTC))
    before = {name: r.inventory.money for name, r in world.residents.items()}
    await world.research.review(world, 7)
    assert calls == []
    assert {name: r.inventory.money for name, r in world.residents.items()} == before
    record = json.loads((world.research.records / "milestone-proposal.json").read_text())
    assert record["status"] == "missing_deliverable" and record["reward_total"] == 0


async def test_checkpoint_holds_clock_and_saves_grant_before_handover(prepared, monkeypatch):
    _, world, _ = prepared
    saved = []

    def respond(request):
        assert world.clock.held
        assert world._all_resting()
        return review_reply()

    async def checkpoint(day, state):
        assert world.clock.held
        saved.append(state)

    monkeypatch.setattr(research_milestones, "create_client", lambda _: ScriptedClient(respond))
    world._on_checkpoint, world._until = checkpoint, 7
    waiters = [asyncio.create_task(r.port.wait()) for r in world.residents.values()]
    try:
        await asyncio.sleep(0)
        await world._checkpoint(7)
        assert saved[0]["research"] == world.research.repo.head()
        for resident in saved[0]["residents"].values():
            assert ["received", 62, "research grant proposal"] in resident["inventory"]["moves"]
    finally:
        for task in waiters:
            task.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)


@pytest.mark.parametrize("fault", ["malformed", "ungrounded", "transport"])
async def test_failed_judge_keeps_purses_unchanged_and_retains_audit(prepared, monkeypatch, fault):
    _, world, _ = prepared
    before = world.snapshot()

    def respond(request):
        if fault == "transport":
            raise RuntimeError("judge service failed")
        if fault == "malformed":
            return "not JSON"
        result = review_reply()
        result["evidence"]["citations"][0]["quote"] = "invented evidence"
        return result

    monkeypatch.setattr(research_milestones, "create_client", lambda _: ScriptedClient(respond))
    with pytest.raises((StructuredOutputError, ValueError, RuntimeError)):
        await world.research.review(world, 7)
    assert world.snapshot() == before
    assert not (world.research.records / "milestone-proposal.json").exists()
    assert list((world.research.root.parent / "research_reviews").rglob("failure.json"))
    assert list((world.research.root.parent / "research_reviews").rglob("attempts.jsonl"))


def test_dossier_redacts_authors_and_declares_omissions(prepared):
    _, world, _ = prepared
    research = world.research
    (research.files / "notes.md").write_text("Mei and Aisha examined a negative result.")
    (research.files / "large.txt").write_text("x" * research_milestones.INPUT_CHARACTERS)
    (research.records / "operation.json").write_text(
        json.dumps(
            {
                "actor": "Mei",
                "sim_time": 500,
                "real_time": "today",
                "tool": "shell",
                "arguments": {"command": "python study.py"},
                "result": {"returncode": 0},
            }
        )
    )
    packet = research_milestones.dossier(
        research, research.settings.milestones[0], list(world.residents)
    )
    assert (
        packet["documents"]["files/notes.md"] == "[author] and [author] examined a negative result."
    )
    evidence = json.loads(packet["documents"]["records/operation.json"])
    assert set(evidence) == {"tool", "arguments", "result"}
    assert next(row for row in packet["manifest"] if row["path"] == "files/large.txt")["omitted"]
    assert "28" not in milestone_terms(research.settings)


async def test_same_model_judge_and_missing_credentials_fail_before_run_creation(
    prepared, tmp_path
):
    config, _, _ = prepared
    settings = config.town.research
    same = settings.model_copy(
        update={"judge": settings.judge.model_copy(update={"model": config.llm.model})}
    )
    with pytest.raises(ValueError, match="must differ"):
        await run(
            config.model_copy(update={"town": config.town.model_copy(update={"research": same})}),
            tmp_path,
        )
    with pytest.raises(ValueError, match="JUDGE_KEY"):
        await run(config, tmp_path)
    assert not (tmp_path / config.name).exists()
