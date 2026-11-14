"""A delayed commission stays absent until its scheduled morning, including on resume."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from agent.directory import AgentDirectory
from experiments.config import load_experiment
from infrastructure.llm import ScriptedClient
from tests.support.towns import Town
from world import research_milestones
from world.clock import DAY, ManualClock
from world.config import ResearchSettings
from world.events import Idle
from world.research import DISABLED, RESEARCH_NAMES, NoTasks
from world.world import World

CONFIG = Path(__file__).resolve().parents[2] / "experiments/configs/ai-lab.yaml"


@pytest.fixture
def lab(tmp_path):
    config = load_experiment(CONFIG)
    for resident in config.residents:
        AgentDirectory.create(
            tmp_path / "agents" / resident.name, background=resident.background_path.read_text()
        )
    world = World(config.town, tmp_path, NoTasks(), clock=ManualClock())
    world.research.initialize(world)
    return world


def visible(world):
    """The actual prompt, all help topics, tool schemas, held events and shared initial text."""
    texts = [json.dumps(world.rules.topics()), (world.research.files / "README.md").read_text()]
    texts += [json.dumps([asdict(s) for s in world.tool_specs])]
    for name, resident in world.residents.items():
        texts.append(AgentDirectory(resident.agent_dir).system_prompt(world.ports[name].rules()))
        texts.extend(p.text for p in [*resident.port.held, *resident.port.pending()])
    return "\n".join(texts).lower()


def assert_uncommissioned(world):
    assert not world.research.active
    assert "research" not in world.rules.topics()
    assert not {s.name for s in world.tool_specs} & (set(RESEARCH_NAMES) | DISABLED)
    text = visible(world)
    for secret in (
        "paper", "proposal", "shared project", "research project", "research grant",
        "external review", "milestone", "reward", "day 8", "day 28", "630", "840",
    ):
        assert secret not in text, secret
    assert not any(e["kind"] == "research_brief" for e in world.log.entries())


async def test_free_life_has_no_future_commission_in_prompts_tools_files_or_services(lab):
    assert_uncommissioned(lab)
    allowance, = lab.log.entries()
    assert allowance["kind"] == "living_allowance"
    assert allowance["payload"]["allowance"] == lab.config.research.allowance
    for resident in lab.residents.values():
        assert resident.inventory.money == 200 + lab.config.research.allowance
        resident.base, resident.place = Idle(), "office"
        assert not set(RESEARCH_NAMES) & {s.name for s in lab.usable(resident)}
        assert not lab.knows(resident, "list_research_files")
        assert "work" in (await lab.call(resident, "start_work", {})).text
        read = await lab.call(resident, "read_repo_file", {"path": "README.md"})
        assert "unavailable" in read.text
        assert "project" not in (await lab.call(resident, "view_board", {})).text
        resident.place = "linde"
        resident.living.satiety = 0
        assert "pancakes" in (await lab.call(resident, "buy", {"item": "pancakes"})).text
        resident.place = "hospital"
        resident.living.health = 50
        assert "treatment" in (await lab.call(resident, "seek_care", {"service": "treatment"})).text
    assert_uncommissioned(lab)


async def test_seven_complete_days_then_morning_eight_release_and_restore_once(lab):
    town = Town(lab, NoTasks())
    town.rest()
    runner = town.start(until_day=7)
    try:
        for day in range(1, 8):
            await town.until("23:00", day=day)
            assert_uncommissioned(lab)
        await town.until("04:30", day=8)
        await runner
        assert [day for day, _ in town.checkpoints] == list(range(1, 8))
        state = town.checkpoints[-1][1]
        assert_uncommissioned(lab)
    finally:
        await town.close()

    restored = World(lab.config, lab.research.root.parent, NoTasks(), clock=ManualClock())
    restored.restore(state)
    assert_uncommissioned(restored)
    next_day = Town(restored, NoTasks())
    next_day.rest()
    runner = next_day.start(until_day=8)
    try:
        await next_day.until("06:59", day=8)
        assert_uncommissioned(restored)
        await next_day.until("07:00", day=8)
        events = [e for e in restored.log.entries() if e["kind"] == "research_brief"]
        assert len(events) == 1 and events[0]["sim_time"] == 7 * DAY + 7 * 3600
        assert events[0]["payload"]["allowance"] == 0
        assert "artificial intelligence" in events[0]["text"]
        assert "Discuss candidate questions together today" in events[0]["text"]
        assert "28" in events[0]["text"] and "21" in events[0]["text"]
        assert "paper.tex" in events[0]["text"]
        assert "research" in restored.rules.topics()
        assert "artificial intelligence" in restored.ports["Mei"].rules()
        resident = restored.residents["Mei"]
        resident.base, resident.place = Idle(), "office"
        assert {"search_web", "curl", "shell"} <= {s.name for s in restored.usable(resident)}
        assert not restored.knows(resident, "search_literature")
        before = resident.inventory.money
        restored.research.announce(restored)
        assert resident.inventory.money == before
        assert sum(e["kind"] == "research_brief" for e in restored.log.entries()) == 1
        await next_day.until("04:30", day=9)
        await runner
        saved = next_day.checkpoints[-1][1]
        assert not list(restored.research.records.glob("milestone-*.json"))
    finally:
        await next_day.close()

    again = World(lab.config, lab.research.root.parent, NoTasks(), clock=ManualClock())
    again.restore(saved)
    assert again.research.active
    revision = again.research.snapshot()
    again.research.announce(again)
    await again.research.review(again, 8)
    assert again.research.snapshot() == revision
    assert sum(e["kind"] == "research_brief" for e in again.log.entries()) == 1
    # Replaying an earlier checkpoint removes the publication and re-hides every surface.
    again.restore(state)
    assert not again.research.active
    assert "research" not in again.rules.topics()
    assert "paper" not in visible(again)


async def test_domain_is_in_actual_judge_request_and_archived_input(lab, monkeypatch):
    lab.research.settings = lab.research.settings.model_copy(update={"review_style": "standard"})
    lab.research.announce(lab)
    resident = lab.residents["Mei"]
    resident.base, resident.place = Idle(), "office"
    await lab.call(resident, "write_repo_file", {
        "path": "paper.tex", "content": (
            r"\documentclass{article}\begin{document}"
            r"A controlled study of model generalisation.\end{document}"
        ),
        "revision": lab.research.snapshot(),
    })
    calls = []

    def reply(request):
        calls.append(request)
        return {
            **{name: {"score": 3, "rationale": "A relevant proposed controlled comparison.",
                      "citations": [{"path": "files/paper.tex", "quote": "model generalisation"}]}
               for name in research_milestones.DIMENSIONS},
            "summary": "Feasible AI question; the empirical work remains to be done.",
        }

    monkeypatch.setattr(research_milestones, "create_client", lambda _: ScriptedClient(reply))
    await lab.research.review(lab, 28)
    assert "research in artificial intelligence" in calls[0].messages[0].content
    assert "not keyword presence" in calls[0].messages[0].content
    path = next((lab.research.root.parent / "research_reviews").rglob("input.json"))
    packet = json.loads(path.read_text())
    assert packet["rubric"] == calls[0].messages[0].content
    assert lab.research.settings.judge.model == "gpt-6.1-sol"


def test_independent_profile_and_milestone_order():
    lab = load_experiment(CONFIG)
    assert lab.llm.model == "qwen3.8-27b-fp8" and not lab.llm.extra_body
    assert lab.town.research.persistent_runtime and lab.town.research.gpus == "device=1"
    assert [s.day for s in lab.town.research.stages_through(lab.days)] == [28, 49, 70]
    assert lab.town.research.stages_due(91)[0].id == "cycle-004"
    assert not lab.town.research.stages_due(8)
    legacy = load_experiment(CONFIG.with_name("autoresearch-academy.yaml"))
    assert legacy.town.research.start_day == 1 and legacy.town.research.domain == ""
    assert [s.day for s in legacy.town.research.milestones] == [7, 28]
    invalid = lab.town.research.model_dump()
    invalid["cycles"] = None
    invalid["milestones"] = [
        {"id": "early", "day": 7, "artifact": "paper.tex", "max_reward_per_resident": 0}
    ]
    with pytest.raises(ValueError, match="cannot precede"):
        ResearchSettings.model_validate(invalid)
