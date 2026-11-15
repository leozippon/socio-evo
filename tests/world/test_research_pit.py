"""Exercise the dated laboratory through the resident tools and world clock."""

import asyncio
import json
import threading
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from agent.directory import AgentDirectory
from experiments.config import load_experiment
from world.clock import DAY, ManualClock
from world.config import ConferenceVenue, ResearchSettings
from world.events import Idle
from world.research import NoTasks
from world.world import World

VENUE = {
    "id": "test-2026", "title": "Test IR conference", "scope": "retrieval agents",
    "submission_at": "2026-03-10T23:59:00-12:00",
    "reviews_at": "2026-03-20T00:00:00Z", "rebuttal_at": "2026-03-24T23:59:00Z",
    "notification_at": "2026-03-28T00:00:00Z",
    "camera_ready_at": "2026-04-01T00:00:00Z",
}


@pytest.fixture
def lab(tmp_path):
    config = load_experiment(Path("experiments/configs/ai-lab.yaml"))
    settings = config.town.research.model_dump()
    settings.update(pit=True, network=False, cycles=None, conferences=[VENUE],
                    stipend_per_resident=630, institution="A simulated IR laboratory",
                    background="Background reading: external authors' published work.\n")
    town = config.town.model_copy(update={
        "research": ResearchSettings.model_validate(settings), "start_date": date(2026, 3, 1),
    })
    for resident in town.residents:
        AgentDirectory.create(tmp_path / "agents" / resident.name, background="An IR PhD student.")
    world = World(town, tmp_path, NoTasks(), clock=ManualClock())
    world.research.initialize(world)
    return world


def activate(world):
    world.clock.set(7 * DAY + 7 * 3600)
    world.research.announce(world)
    resident = world.residents["Mei"]
    resident.base, resident.place = Idle(), "office"
    resident.reckoned = world.clock.now()
    resident.living.energy = 100
    return resident


def test_free_week_and_dated_commission(lab):
    assert not lab.research.active
    assert not {"browser", "conference"} & {s.name for s in lab.tool_specs}
    assert not (lab.research.files / "conferences.md").exists()
    assert "rebuttal" not in lab.rules.text("Mei").lower()
    resident = activate(lab)
    assert lab.research.simulated_now(lab) == datetime(2026, 3, 7, 23, tzinfo=UTC)
    assert {"browser", "conference", "shell"} <= {s.name for s in lab.usable(resident)}
    assert not {"curl", "read_source", "search_web", "search_literature"} & {
        s.name for s in lab.usable(resident)
    }
    assert (lab.research.files / "lab-background.md").read_text() == lab.config.research.background
    text = (lab.research.files / "README.md").read_text()
    assert "paper.tex" in text and "rebuttal" in text and "no direct internet" in text
    assert "proposal.md" not in text


async def test_browser_uses_society_instant_and_shared_download(lab, monkeypatch):
    from world import research_browser

    resident = activate(lab)
    seen = []

    class Browser:
        def __init__(self, cache):
            assert cache == lab.research.root.parent / "pit_cache"
            self.cache_dir = cache

        def search(self, provider, query, as_of, page):
            seen.append((provider, query, as_of, page))
            return {"results": [{"url": "https://arxiv.org/abs/2501.00001v1"}]}

        def download(self, url, as_of, destination):
            seen.append((url, as_of))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"%PDF-test")
            return {"path": str(destination), "version": "v1"}

    monkeypatch.setattr(research_browser, "BrowserGateway", Browser)
    result = await lab.call(resident, "browser", {
        "action": "search", "provider": "arxiv", "query": "retrieval", "page": 2,
    })
    assert "2501.00001v1" in result.text
    assert seen[0] == ("arxiv", "retrieval", datetime(2026, 3, 7, 23, tzinfo=UTC), 2)
    args = {"action": "download", "url": "https://arxiv.org/pdf/2501.00001v1",
            "path": "sources/test.pdf", "revision": lab.research.snapshot()}
    result = await lab.call(resident, "browser", args)
    assert '"path": "sources/test.pdf"' in result.text
    assert (lab.research.files / "sources/test.pdf").read_bytes() == b"%PDF-test"
    assert "already exists" in (await lab.call(resident, "browser", {
        **args, "revision": lab.research.snapshot(),
    })).text
    assert "read-only" in (await lab.call(resident, "browser", {
        **args, "path": "records/stolen.json", "revision": lab.research.snapshot(),
    })).text
    assert "revision" in (await lab.call(resident, "browser", {
        "action": "download", "url": args["url"], "path": "another.pdf",
    })).text


async def test_stipends_survive_checkpoint_replay_without_double_payment(lab):
    lab.research.announce(lab)
    money = lab.residents["Mei"].inventory.money
    lab.clock.set(21 * DAY + lab.checkpoint_hour)
    before = lab.snapshot()
    await lab.research.review(lab, 21)
    paid = lab.snapshot()
    assert lab.residents["Mei"].inventory.money == money + 630
    assert json.loads((lab.research.records / "stipend-0021.json").read_text())["allowance"] == 630
    for state in (paid, before):
        again = World(lab.config, lab.research.root.parent, NoTasks(), clock=ManualClock())
        again.restore(state)
        await again.research.review(again, 21)
        assert again.residents["Mei"].inventory.money == money + 630
        await again.research.review(again, 22)
        assert again.residents["Mei"].inventory.money == money + 630


async def test_cancelled_download_cannot_write_after_checkpoint(lab, monkeypatch):
    from world import research_browser

    resident = activate(lab)
    entered, finished = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    class Browser:
        def __init__(self, cache):
            self.cache_dir = cache

        def download(self, url, now, destination):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise TimeoutError("Test download was not released")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"a late network response")
            loop.call_soon_threadsafe(finished.set)
            return {"path": str(destination)}

    monkeypatch.setattr(research_browser, "BrowserGateway", Browser)
    task = asyncio.create_task(lab.call(resident, "browser", {
        "action": "download", "url": "https://arxiv.org/pdf/2501.00001v1",
        "path": "late.pdf", "revision": lab.research.snapshot(),
    }))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
    await asyncio.wait_for(finished.wait(), 2)
    assert not (lab.research.files / "late.pdf").exists()
    assert not lab.research.repo.has_changes()


async def test_conference_mail_arrives_without_opening_desk(lab, monkeypatch):
    from world.research_conferences import ConferenceDesk

    activate(lab)
    seen = []

    async def advance(desk, world):
        seen.append(world.research.simulated_now(world))

    monkeypatch.setattr(ConferenceDesk, "advance", advance)
    # 00:00 UTC is 08:00 in Beijing, not the next day's checkpoint.
    lab.research.schedule(lab, 20)
    timer = next(t for t in lab._timers if t.t == 19 * DAY + 8 * 3600)
    lab.clock.set(timer.t)
    await timer.fn()
    assert seen == [datetime(2026, 3, 20, tzinfo=UTC)]


def test_invalid_calendar_and_network_combinations_fail_before_launch():
    with pytest.raises(ValueError, match="timezone"):
        ConferenceVenue.model_validate({**VENUE, "reviews_at": "2026-03-20T00:00:00"})
    with pytest.raises(ValueError, match="sequence"):
        ConferenceVenue.model_validate({**VENUE, "rebuttal_at": "2026-03-30T00:00:00Z"})
    with pytest.raises(ValueError, match="gateway"):
        ResearchSettings(pit=True, network=True, semantic_scholar=False)
    with pytest.raises(ValueError, match="replace"):
        ResearchSettings(conferences=[VENUE], cycles={}, judge={
            "model": "judge", "base_url": "https://judge.invalid/v1", "api_key_env": "KEY",
        })


def test_new_run_has_historical_reading_before_the_collective_assignment(tmp_path):
    from infrastructure.storage import RunDirectory
    from simulation.run import _create

    config = load_experiment(Path("experiments/configs/ir-lab.yaml"))
    directory = RunDirectory.create(tmp_path, config.name, config=config, code_revision="test")
    world = _create(directory, config, NoTasks(), {
        r.name: r.background_path.read_text() for r in config.residents
    })
    for resident in world.residents.values():
        notes = resident.agent_dir / "memory" / "lab-background.md"
        assert notes.read_text() == config.town.research.background
        assert "2503.09516v5" in notes.read_text()
        assert "rebuttal" not in notes.read_text().lower()
    assert not world.research.active
    assert not (world.research.files / "conferences.md").exists()
