"""Recurring manuscripts preserve feedback, funding and inputs across checkpoints."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent.directory import AgentDirectory
from experiments.config import load_experiment
from infrastructure.llm import ScriptedClient
from world import research_milestones
from world.clock import ManualClock
from world.config import ResearchSettings
from world.events import Idle
from world.research import NoTasks
from world.world import World

CONFIG = Path(__file__).resolve().parents[2] / "experiments/configs/ai-lab.yaml"
PAPER = r"\documentclass{article}\begin{document}A controlled comparison.\end{document}"


@pytest.fixture
def cyclic_lab(tmp_path, monkeypatch):
    config = load_experiment(CONFIG)
    settings = ResearchSettings(
        start_day=8, domain="artificial intelligence", cycles={}, review_style="conference",
        judge={"model": "independent-judge", "base_url": "https://judge.invalid/v1",
               "api_key_env": "JUDGE_KEY"},
    )
    config = config.town.model_copy(update={"research": settings})
    for resident in config.residents:
        AgentDirectory.create(tmp_path / "agents" / resident.name, background="A researcher.")
    world = World(config, tmp_path, NoTasks(), clock=ManualClock())
    world.research.initialize(world)
    calls = []

    def respond(request):
        calls.append(request)
        citation = {"path": "files/paper.tex", "quote": "A controlled comparison."}
        return {
            **{name: {"score": 3, "rationale": "Useful with remaining gaps.",
                      "citations": [citation]}
               for name in ("technical_quality", "novelty", "significance", "evidence",
                            "reproducibility")},
            **{name: [{"text": "Check the controls and limitations.", "citations": [citation]}]
               for name in ("strengths", "weaknesses", "questions", "required_revisions")},
            "overall": 6, "confidence": 3, "summary": "Promising; revise the controls.",
        }

    monkeypatch.setattr(research_milestones, "create_client", lambda _: ScriptedClient(respond))
    return world, calls


async def test_cycle_brief_has_no_same_day_proposal_or_fixed_final_deadline(cyclic_lab):
    world, calls = cyclic_lab
    assert (world.research.files / "README.md").read_text() == "Shared files.\n"
    await world.research.review(world, 28)
    assert calls == []  # No review is possible before the commission.
    world.research.announce(world)
    text = (world.research.files / "README.md").read_text()
    assert "paper.tex" in text and "day 28" in text and "every 21 days" in text
    assert "ICML" in text and "ICLR" in text
    assert "doctoral students in an AI institute" in text and "teachers" not in text
    assert "proposal.md" not in text and "paper.md" not in text
    assert "overall rating from 1 to 10" in text
    assert "changing topics is not required" in text
    assert "latexmk -pdf -interaction=nonstopmode -halt-on-error paper.tex" in text
    assert "actual generated PDF" in text
    for day in (8, 27, 29):
        await world.research.review(world, day)
    assert calls == []


async def test_successive_reviews_archive_full_manuscript_feedback_and_pay_once(cyclic_lab):
    world, calls = cyclic_lab
    world.research.announce(world)
    (world.research.files / "paper.tex").write_text(PAPER)
    world.research.repo.commit("First manuscript", date=datetime.now(UTC))
    before = world.snapshot()
    money = world.residents["Aisha"].inventory.money
    await world.research.review(world, 28)
    paid = world.snapshot()
    assert world.residents["Aisha"].inventory.money == money + 700
    path = world.research.records / "milestone-cycle-001.json"
    first = json.loads(path.read_text())
    assert first["review"]["overall"] == 6
    assert first["review"]["required_revisions"]
    audit = world.research.root.parent / first["audit"]
    assert json.loads((audit / "input.json").read_text())["packet"]["documents"][
        "files/paper.tex"
    ] == PAPER
    announcement = next(e for e in world.log.entries() if e["kind"] == "research_milestone")
    assert "records/milestone-cycle-001.json" in announcement["text"]
    assert "day 29" in announcement["text"] and "day 49" in announcement["text"]
    assert "6/10" in announcement["text"] and "3/5" in announcement["text"]
    for resident in world.residents.values():
        assert any(p.kind == "research_milestone" for p in resident.port.held)
    resident = world.residents["Aisha"]
    resident.base, resident.place = Idle(), "office"
    feedback = await world.call(resident, "read_repo_file", {"path": "records/" + path.name})
    assert "required_revisions" in feedback.text
    for state in (paid, before):
        restored = World(world.config, world.research.root.parent, NoTasks(), clock=ManualClock())
        restored.restore(state)
        await restored.research.review(restored, 28)
        assert restored.residents["Aisha"].inventory.money == money + 700
    assert len(calls) == 1
    (restored.research.files / "paper.tex").write_text(
        PAPER.replace("comparison.", "comparison. Revised.")
    )
    restored.research.repo.commit("Revised manuscript", date=datetime.now(UTC))
    await restored.research.review(restored, 49)
    assert len(calls) == 2
    assert restored.residents["Aisha"].inventory.money == money + 1400
    assert (restored.research.records / "milestone-cycle-002.json").exists()
    assert json.loads(path.read_text()) == first
    assert json.loads((audit / "input.json").read_text())["packet"]["documents"][
        "files/paper.tex"
    ] == PAPER
