"""Evolution operators: each turns the agent's experience into a change of its own files."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from core.agent import prompts
from core.agent.agent import Agent
from core.agent.evolution.levels import Level, Trigger
from core.agent.memory import Insight
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
        day = day_of(context.time)
        await _write_diary(agent, context.time)
        insights = agent.memory.insights.read()
        reply = await agent.ask(
            "reflect",
            context.time,
            prompts.reflection_prompt(
                context.time,
                self.diaries(agent, day),
                insights,
                self.max_insights,
                context.requestable,
                agent.cognition,
                agent.setting,
            ),
            prompts.reflection_reply([insight.id for insight in insights], context.requestable),
        )
        self.file(agent, reply.changes, day)
        return Change(
            subject=f"Reflect on Day {day}",
            body=reply.reflection,
            request=getattr(reply, "rethink", None),
        )

    def diaries(self, agent: Agent, day: int) -> list[tuple[int, str]]:
        """The diary entries reflected on at the end of `day`: those of the retention window."""
        return agent.memory.diary.entries(after=day - self.retention_days)

    def file(self, agent: Agent, changes: Sequence[object], day: int) -> None:
        """Apply the changes to the agent's beliefs made at the end of `day`, then
        consolidate."""
        memory = agent.memory
        updated = _revise_insights(memory.insights.read(), changes, day)
        kept = sorted(updated, key=lambda insight: (insight.day, insight.id))[-self.max_insights :]
        memory.insights.write(sorted(kept, key=lambda insight: insight.id))
        memory.episodic.drop_before((day - self.retention_days) * MINUTES_PER_DAY)


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
                agent.setting,
            ),
            prompts.skill_reply([skill.title for skill in skills]),
        )
        self.file(agent, reply.changes, time=context.time)
        return Change(subject=f"Review skills on Day {day}", body=reply.reflection)

    @staticmethod
    def file(agent: Agent, changes: Sequence[prompts.WriteSkill | prompts.RetireSkill], *, time=0):
        for change in changes:
            agent.personal_skills.revise(change, time=time)


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
                agent.parameters.read_policy(),
                context.reason,
                limits,
                agent.setting,
            ),
            prompts.PolicyRewrite,
            system=prompts.system_prompt(agent.profile, None, limits),
        )
        agent.parameters.write_policy(reply.resolutions)
        return Change(subject=f"Rewrite policy on Day {day}", body=reply.reflection)


class RevisionOperator:
    """The free mode's night: the diary, then one question of what the agent would change in
    what it has written about itself and its ways (its account of itself, its policy, its
    skill notes and its insights), whose reply `file` files by level. While the agent has
    no account of itself, as on its first night, the reply must hold one.

    The account of itself is filed at L2 with the policy: both are the self-authored texts
    read at every decision, rewritten by reflection at the same depth.
    """

    def __init__(self, memory: MemoryOperator) -> None:
        self.memory = memory

    async def apply(self, agent: Agent, context: Context) -> prompts.Revision:
        """Write the diary and ask the question; returns the reply, of which nothing but the
        diary has been written yet. The question shows the account and the policy, so its
        system prompt leaves them out: it names the agent, or tells its profile while there
        is no account."""
        day = day_of(context.time)
        await _write_diary(agent, context.time)
        account, insights = agent.parameters.read_account(), agent.memory.insights.read()
        skills = agent.memory.skills.read()
        return await agent.ask(
            "revise",
            context.time,
            prompts.revision_prompt(
                context.time,
                self.memory.diaries(agent, day),
                account,
                agent.parameters.read_policy(),
                skills,
                insights,
                self.memory.max_insights,
                agent.cognition,
                agent.setting,
            ),
            prompts.revision_reply(
                [insight.id for insight in insights],
                [skill.title for skill in skills],
                first=not account,
            ),
            system=prompts.system_prompt(
                agent.profile, None, agent.cognition, account=None if account else ""
            ),
        )

    def file(
        self, agent: Agent, revision: prompts.Revision, day: int
    ) -> Iterator[tuple[Level, Change]]:
        """File `revision`, made at the end of `day`, level by level, yielding each level's
        change once its files are written and before the next level's are, so that the caller
        can commit each level on its own: L0 always (the diary, the insights and
        consolidation), L1 if the skill notes changed, L2 if the account or the policy did.
        Every change carries the agent's reflection as its reasoning."""
        reasoning = revision.reflection
        self.memory.file(agent, revision.beliefs, day)
        yield Level.L0, Change(subject=f"Reflect on Day {day}", body=reasoning)
        if revision.notebook:
            SkillOperator.file(agent, revision.notebook, time=day * MINUTES_PER_DAY - 1)
            yield Level.L1, Change(subject=f"Review skills on Day {day}", body=reasoning)
        rewritten = []
        if revision.account is not None:
            agent.parameters.write_account(revision.account)
            rewritten.append("account of itself")
        if revision.resolutions is not None:
            agent.parameters.write_policy(revision.resolutions)
            rewritten.append("policy")
        if rewritten:
            subject = f"Rewrite {' and '.join(rewritten)} on Day {day}"
            yield Level.L2, Change(subject=subject, body=reasoning)


async def _write_diary(agent: Agent, time: int) -> None:
    """Write the agent's diary entry for the day of `time`, from that day's episodic records."""
    day = day_of(time)
    today = [record for record in agent.memory.episodic.read() if day_of(record.time) == day]
    if agent.cognition.work_notes.enabled:
        today = agent.memory.work.project(today)
    diary = await agent.write(
        "diary", time, prompts.diary_prompt(time, today, agent.cognition, agent.setting)
    )
    agent.memory.diary.write(day, diary)


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
