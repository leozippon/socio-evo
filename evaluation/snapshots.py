"""Frozen agents: the version an agent was at the end of a day, exported for one use, whole or
with parts of what it wrote for itself taken out."""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path

from core.agent import Agent, CognitionConfig
from core.agent.evolution import History, Version
from core.interaction import MINUTES_PER_DAY, Setting
from infrastructure.llm import LLMClient


class Variant(StrEnum):
    """What of a resident an export keeps: everything; all but what it has resolved (its
    policy); all but what it has come to believe (its insights); or neither of the two, with
    its recollections, diary and notebook kept, which matches the full export in what it
    remembers and so in the length of its memory. Every variant keeps the account of itself a
    resident writes in the free mode of evolution (`parameters/self.md`), if it has one:
    without it the resident would be told its profile instead, a substitution rather than a
    removal, so no variant takes it out."""

    FULL = "full"
    NO_POLICY = "no-policy"
    NO_INSIGHTS = "no-insights"
    NEITHER = "no-policy-no-insights"


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
    history: History,
    commit: str,
    client: LLMClient,
    cognition: CognitionConfig,
    setting: Setting,
    variant: Variant = Variant.FULL,
) -> Iterator[Agent]:
    """The agent at `commit`, living in a town of `setting`, exported as `variant` into a
    temporary directory that is removed afterwards; nothing it does reaches the repository."""
    with tempfile.TemporaryDirectory(prefix="frozen-agent-") as scratch:
        path = Path(scratch) / "agent"
        history.export(commit, path)
        agent = Agent.load(path, client, cognition, setting)
        if variant in (Variant.NO_POLICY, Variant.NEITHER):
            agent.parameters.write_policy("")
        if variant in (Variant.NO_INSIGHTS, Variant.NEITHER):
            agent.memory.insights.write([])
        yield agent
