import pytest

from core.agent.evolution import History, Level, Trigger
from core.agent.memory import Record
from core.interaction import time_at
from evaluation import version_at


def test_each_day_selects_the_newest_version_made_by_its_end(make_agent):
    agent = make_agent()
    history = History(agent.path)
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
