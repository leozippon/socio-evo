"""The Evolver: maps a trigger to the enabled operators and commits each step."""

from dataclasses import dataclass

from core.agent import prompts
from core.agent.agent import Agent
from core.agent.evolution.config import EvolutionConfig, Mode
from core.agent.evolution.history import History, Version
from core.agent.evolution.levels import Level, Trigger
from core.agent.evolution.operators import (
    Context,
    MemoryOperator,
    Operator,
    PolicyOperator,
    RevisionOperator,
    SkillOperator,
)
from core.interaction import day_of
from infrastructure.config import ConfigError
from infrastructure.llm import StructuredOutputError


@dataclass(frozen=True)
class Lapse:
    """A step skipped because no valid reply of the agent's could be obtained; `error` says
    how each attempt failed. Nothing was committed for it, and whatever it had written was
    discarded."""

    level: Level
    trigger: Trigger
    error: StructuredOutputError


class Evolver:
    """Applies `config` to agents. Raises ConfigError if an enabled level has no operator."""

    def __init__(self, config: EvolutionConfig) -> None:
        memory = MemoryOperator(config.retention_days, config.max_insights)
        operators: dict[Level, Operator] = {
            Level.L0: memory,
            Level.L1: SkillOperator(),
            Level.L2: PolicyOperator(),
        }
        missing = sorted(set(config.levels) - operators.keys())
        if missing:
            raise ConfigError(f"evolution levels enabled without an operator: {', '.join(missing)}")
        self.config = config
        self._operators = operators
        self._revision = RevisionOperator(memory)

    async def evolve(self, agent: Agent, trigger: Trigger, time: int) -> list[Version | Lapse]:
        """Apply the enabled levels `trigger` schedules, in level order, each as one commit,
        followed by any step the agent requested in its reflection; returns those commits,
        and the lapse of each step for which no valid reply could be obtained.

        If any level applies, pending experience is committed first so that each step's commit
        holds only that step's changes; a step that changes no file is an empty commit. A level
        already applied at `time`, such as one the agent requested earlier that night, is not
        applied again. In the free mode only the night (`daily`) applies, as `_revise` says.
        """
        if trigger is Trigger.SELF:
            raise ValueError("self-triggered steps are requested by reflection, not fired")
        if self.config.mode is Mode.FREE:
            return await self._revise(agent, time) if trigger is Trigger.DAILY else []
        levels = sorted(set(self.config.schedule.get(trigger, ())) & set(self.config.levels))
        if not levels:
            return []
        history = History(agent.path, agent.setting.start_date)
        history.commit_experience(time)
        versions: list[Version | Lapse] = []
        for level in levels:
            if not any(v.level is level and v.time == time for v in history.log()):
                versions += await self._step(agent, history, level, trigger, time, None)
        return versions

    async def _revise(self, agent: Agent, time: int) -> list[Version | Lapse]:
        """The free mode's night: after pending experience is committed, the diary and the
        one question, whose reply is filed level by level, each level that changed as one
        commit triggered `daily` (see `RevisionOperator.file`). When no valid reply can be
        obtained the night lapses as its L0 step, with nothing committed; an agent left
        without an account of itself is asked for one again the next night."""
        history = History(agent.path, agent.setting.start_date)
        history.commit_experience(time)
        try:
            revision = await self._revision.apply(agent, Context(Trigger.DAILY, time))
        except StructuredOutputError as error:
            history.reset(history.head())
            return [Lapse(Level.L0, Trigger.DAILY, error)]
        return [
            history.commit_step(level, Trigger.DAILY, time, change.subject, change.body)
            for level, change in self._revision.file(agent, revision, day_of(time))
        ]

    async def _step(
        self,
        agent: Agent,
        history: History,
        level: Level,
        trigger: Trigger,
        time: int,
        reason: str | None,
    ) -> list[Version | Lapse]:
        log = history.log()
        context = Context(
            trigger=trigger,
            time=time,
            since=next((version.time for version in log if version.level is level), None),
            requestable=self._requestable(log, time) if level is Level.L0 else (),
            reason=reason,
        )
        try:
            change = await self._operators[level].apply(agent, context)
        except StructuredOutputError as error:
            history.reset(history.head())
            return [Lapse(level, trigger, error)]
        body = change.body if reason is None else f"Requested: {reason}\n\n{change.body}"
        versions: list[Version | Lapse] = [
            history.commit_step(level, trigger, time, change.subject, body)
        ]
        if change.request is not None:
            level = Level(prompts.requested_level(change.request))
            versions += await self._step(
                agent, history, level, Trigger.SELF, time, change.request.why
            )
        return versions

    def _requestable(self, log: list[Version], time: int) -> tuple[Level, ...]:
        """The levels the agent may request now: none while a self-triggered step is more
        recent than the cooldown."""
        settings = self.config.self_trigger
        last = next((version for version in log if version.trigger is Trigger.SELF), None)
        if not settings.enabled or (
            last is not None and day_of(time) - day_of(last.time) < settings.cooldown_days
        ):
            return ()
        return tuple(sorted(set(settings.levels) & set(self.config.levels)))
