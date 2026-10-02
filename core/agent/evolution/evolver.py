"""The Evolver: maps a trigger to the enabled operators and commits each step."""

from core.agent.agent import Agent
from core.agent.evolution.config import EvolutionConfig
from core.agent.evolution.history import History, Version
from core.agent.evolution.levels import Level, Trigger
from core.agent.evolution.operators import (
    Context,
    MemoryOperator,
    Operator,
    PolicyOperator,
    SkillOperator,
)
from core.interaction import day_of
from infrastructure.config import ConfigError


class Evolver:
    """Applies `config` to agents. Raises ConfigError if an enabled level has no operator."""

    def __init__(self, config: EvolutionConfig) -> None:
        operators: dict[Level, Operator] = {
            Level.L0: MemoryOperator(config.retention_days, config.max_insights),
            Level.L1: SkillOperator(),
            Level.L2: PolicyOperator(),
        }
        missing = sorted(set(config.levels) - operators.keys())
        if missing:
            raise ConfigError(f"evolution levels enabled without an operator: {', '.join(missing)}")
        self.config = config
        self._operators = operators

    async def evolve(self, agent: Agent, trigger: Trigger, time: int) -> list[Version]:
        """Apply the enabled levels `trigger` schedules, in level order, each as one commit,
        followed by any step the agent requested in its reflection; returns those commits.

        If any level applies, pending experience is committed first so that each step's commit
        holds only that step's changes. A step that changes no file makes no commit. A level
        already committed at `time`, such as one the agent requested earlier that night, is not
        applied again.
        """
        if trigger is Trigger.SELF:
            raise ValueError("self-triggered steps are requested by reflection, not fired")
        levels = sorted(set(self.config.schedule.get(trigger, ())) & set(self.config.levels))
        if not levels:
            return []
        history = History(agent.path)
        history.commit_experience(time)
        versions: list[Version] = []
        for level in levels:
            if not any(v.level is level and v.time == time for v in history.log()):
                versions += await self._step(agent, history, level, trigger, time, None)
        return versions

    async def _step(
        self,
        agent: Agent,
        history: History,
        level: Level,
        trigger: Trigger,
        time: int,
        reason: str | None,
    ) -> list[Version]:
        log = history.log()
        context = Context(
            trigger=trigger,
            time=time,
            since=next((version.time for version in log if version.level is level), None),
            requestable=self._requestable(log, time) if level is Level.L0 else (),
            reason=reason,
        )
        change = await self._operators[level].apply(agent, context)
        body = change.body if reason is None else f"Requested: {reason}\n\n{change.body}"
        version = history.commit_step(level, trigger, time, change.subject, body)
        versions = [] if version is None else [version]
        if change.request is not None:
            request = change.request
            versions += await self._step(
                agent, history, Level(request.level), Trigger.SELF, time, request.reason
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
