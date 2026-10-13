import pytest

from core.agent.evolution import History, Level, Trigger
from core.agent.memory import Insight, Record
from core.interaction import time_at
from evaluation import Variant, frozen, version_at


def test_each_day_selects_the_newest_version_made_by_its_end(make_agent):
    agent = make_agent()
    history = History(agent.path, agent.setting.start_date)
    [initial] = history.log()

    def experience(time):
        agent.memory.episodic.append([Record(time=time, text=f"Something at {time}.")])
        return history.commit_experience(time)

    experience(time_at(1, "22:00"))
    agent.memory.diary.write(1, "A quiet day.")
    reflected = history.commit_step(Level.L0, Trigger.DAILY, time_at(1, "22:00"), "Reflect")
    midnight = experience(time_at(4, "00:00"))

    assert [version_at(history, day) for day in (0, 1, 2, 3)] == [
        initial,
        reflected,
        reflected,
        midnight,
    ]
    for day in (-1, 4):
        with pytest.raises(ValueError):
            version_at(history, day)


def test_ablated_exports_take_out_resolutions_or_beliefs_and_leave_the_original(make_agent):
    """Every variant keeps the account of itself a resident wrote in the free mode."""
    agent = make_agent()
    agent.parameters.write_policy("Keep a tidy desk.")
    account = agent.path / "parameters" / "self.md"
    account.write_text("I keep to myself and finish what I start.\n", encoding="utf-8")
    agent.memory.insights.write([Insight(id=1, day=1, text="Mornings are quiet.")])
    agent.memory.episodic.append([Record(time=time_at(1, "09:00"), text="A quiet morning.")])
    history = History(agent.path, agent.setting.start_date)
    commit = history.commit_experience(time_at(1, "22:00")).commit
    files = {path: path.read_bytes() for path in agent.path.rglob("*") if path.is_file()}
    kept = {}
    for variant in Variant:
        frozen_as = (history, commit, agent.client, agent.cognition, agent.setting, variant)
        with frozen(*frozen_as) as export:
            export.memory.episodic.append([Record(time=time_at(2, "09:00"), text="Later.")])
            kept[variant] = (
                export.parameters.read_policy(),
                [insight.text for insight in export.memory.insights.read()],
                len(export.memory.episodic.read()),
            )
            assert (export.path / "parameters" / "self.md").read_bytes() == account.read_bytes()
    assert kept == {
        Variant.FULL: ("Keep a tidy desk.", ["Mornings are quiet."], 2),
        Variant.NO_POLICY: ("", ["Mornings are quiet."], 2),
        Variant.NO_INSIGHTS: ("Keep a tidy desk.", [], 2),
        Variant.NEITHER: ("", [], 2),
    }
    assert {path: path.read_bytes() for path in agent.path.rglob("*") if path.is_file()} == files
    assert history.head() == commit
