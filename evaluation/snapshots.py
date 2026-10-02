"""Frozen agents: the version an agent was at the end of a day, exported for one use."""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from core.agent import Agent, CognitionConfig
from core.agent.evolution import History, Version
from core.interaction import MINUTES_PER_DAY
from infrastructure.llm import LLMClient


def version_at(history: History, day: int) -> Version:
    """The agent as it stood at the end of `day`: its newest version dated no later than
    `day` × MINUTES_PER_DAY, the midnight that ends the day. Day 0 ends at time 0, so it is
    the initial version.

    Raises ValueError for a negative day, and for a day the history does not reach because
    nothing was recorded after the end of the day before.
    """
    if day < 0:
        raise ValueError(f"no day {day}")
    versions = history.log()
    if day > 0 and versions[0].time <= (day - 1) * MINUTES_PER_DAY:
        raise ValueError(f"the history ends before day {day}")
    end = day * MINUTES_PER_DAY
    for version in versions:
        if version.time <= end:
            return version
    raise ValueError(f"no version by the end of day {day}")


@contextmanager
def frozen(
    history: History, commit: str, client: LLMClient, cognition: CognitionConfig
) -> Iterator[Agent]:
    """The agent at `commit`, exported into a temporary directory that is removed afterwards;
    nothing it does reaches the repository."""
    with tempfile.TemporaryDirectory(prefix="frozen-agent-") as scratch:
        path = Path(scratch) / "agent"
        history.export(commit, path)
        yield Agent.load(path, client, cognition)
