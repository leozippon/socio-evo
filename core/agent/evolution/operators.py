"""Evolution operators: each turns the agent's experience into a change of its own files."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from core.agent import prompts
from core.agent.agent import Agent
from core.agent.evolution.levels import Level, Trigger
from core.agent.memory import Insight, Skill, name_of
from core.interaction import MINUTES_PER_DAY, day_of


@dataclass(frozen=True)
class Context:
    """The step an operator performs. `since` is the time of the previous commit at the
    operator's level, if any; `requestable` lists the levels the agent may request tonight
    (offered by L0 only); `reason` is the agent's own reason for a step it requested."""

    trigger: Trigger
    time: int
    since: int | None = None
    requestable: tuple[Level, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class Change:
    """What an operator did, for its commit message, and any step the agent requested."""

    subject: str
    body: str = ""
    request: prompts.Request | None = None


class Operator(Protocol):
    async def apply(self, agent: Agent, context: Context) -> Change: ...


class MemoryOperator:
    """L0: write the day's diary, reflect on the recent diaries into insights, consolidate.

    Consolidation drops episodic records older than `retention_days` days and keeps the
    `max_insights` most recently written insights.
    """

    def __init__(self, retention_days: int, max_insights: int) -> None:
        self.retention_days = retention_days
        self.max_insights = max_insights

    async def apply(self, agent: Agent, context: Context) -> Change:
        memory, limits, day = agent.memory, agent.cognition, day_of(context.time)
        today = [record for record in memory.episodic.read() if day_of(record.time) == day]
        diary = await agent.write(
            "diary", context.time, prompts.diary_prompt(context.time, today, limits)
        )
        memory.diary.write(day, diary)

        insights = memory.insights.read()
        reply = await agent.ask(
            "reflect",
            context.time,
            prompts.reflection_prompt(
                context.time,
                memory.diary.entries(after=day - self.retention_days),
                insights,
                self.max_insights,
                context.requestable,
                limits,
            ),
            prompts.reflection_reply([insight.id for insight in insights], context.requestable),
        )
        updated = _revise_insights(insights, reply.changes, day)
        kept = sorted(updated, key=lambda insight: (insight.day, insight.id))[-self.max_insights :]
        memory.insights.write(sorted(kept, key=lambda insight: insight.id))
        memory.episodic.drop_before((day - self.retention_days) * MINUTES_PER_DAY)
        return Change(
            subject=f"Reflect on Day {day}",
            body=reply.reflection,
            request=getattr(reply, "rethink", None),
        )


class SkillOperator:
    """L1: create, revise or retire skill notes from the diaries and insights written since
    the previous L1 step."""

    async def apply(self, agent: Agent, context: Context) -> Change:
        memory, limits, day = agent.memory, agent.cognition, day_of(context.time)
        after = 0 if context.since is None else day_of(context.since)
        skills = memory.skills.read()
        reply = await agent.ask(
            "skills",
            context.time,
            prompts.skill_prompt(
                context.time,
                memory.diary.entries(after)[-limits.diaries :],
                [insight for insight in memory.insights.read() if insight.day > after],
                skills,
                context.reason,
                limits,
            ),
            prompts.skill_reply([skill.name for skill in skills]),
        )
        for change in reply.changes:
            name = name_of(change.title)
            if isinstance(change, prompts.WriteSkill):
                memory.skills.write(Skill(name=name, description=change.summary, body=change.text))
            else:
                memory.skills.remove(name)
        return Change(subject=f"Review skills on Day {day}", body=reply.reflection)


class PolicyOperator:
    """L2: rewrite the policy after reflecting on the diaries since the previous L2 step and
    on the current insights."""

    async def apply(self, agent: Agent, context: Context) -> Change:
        memory, limits, day = agent.memory, agent.cognition, day_of(context.time)
        after = 0 if context.since is None else day_of(context.since)
        reply = await agent.ask(
            "policy",
            context.time,
            prompts.policy_prompt(
                context.time,
                memory.diary.entries(after)[-limits.diaries :],
                memory.insights.read(),
                context.reason,
                limits,
            ),
            prompts.PolicyRewrite,
        )
        agent.parameters.write_policy(reply.resolutions)
        return Change(subject=f"Rewrite policy on Day {day}", body=reply.reflection)


def _revise_insights(
    insights: Sequence[Insight], changes: Sequence[object], day: int
) -> list[Insight]:
    by_id = {insight.id: insight for insight in insights}
    next_id = max(by_id, default=0) + 1
    for change in changes:
        if isinstance(change, prompts.AddInsight):
            by_id[next_id] = Insight(id=next_id, day=day, text=change.belief, subject=change.about)
            next_id += 1
        elif isinstance(change, prompts.ReviseInsight):
            by_id[change.number] = by_id[change.number].model_copy(
                update={"text": change.belief, "day": day}
            )
        elif isinstance(change, prompts.RemoveInsight):
            del by_id[change.number]
    return list(by_id.values())
