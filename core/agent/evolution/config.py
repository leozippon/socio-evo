"""Which evolution levels run, and when."""

from enum import StrEnum

from pydantic import Field, PositiveInt, field_validator, model_validator

from core.agent.evolution.levels import Level, Trigger
from infrastructure.config import StrictModel


class Mode(StrEnum):
    """How an agent revises itself at night."""

    SCHEDULED = "scheduled"
    """Each enabled level at its cadence (`schedule`), and L1 or L2 out of cadence when the
    agent's reflection asks (`self_trigger`)."""
    FREE = "free"
    """Every night, after the diary, one question of what the agent would change in what it
    has written about itself and its ways, whose reply is filed at L0, L1 and L2. The reply
    of the first night, and of every night until there is one, holds the agent's account of
    itself, which it reads from then on in place of its profile."""


class SelfTrigger(StrictModel):
    """Out-of-cadence steps the agent may request in its nightly reflection: which levels, and
    how many days must pass after one such step before the next may be requested."""

    enabled: bool = True
    levels: tuple[Level, ...] = (Level.L1, Level.L2)
    cooldown_days: PositiveInt = 7

    @field_validator("levels")
    @classmethod
    def _l0_cannot_be_requested(cls, levels: tuple[Level, ...]) -> tuple[Level, ...]:
        if Level.L0 in levels:
            raise ValueError("L0 makes self-trigger requests and cannot be requested")
        return levels


class EvolutionConfig(StrictModel):
    """In the scheduled `mode` (the default), `levels` are the enabled levels; a trigger runs
    the levels `schedule` maps it to that are also enabled. With no level enabled nothing
    evolves: the no-evolution baseline. The free mode has no cadences: its levels are L0, L1
    and L2, the default, since every night may revise them all, and `schedule` and
    `self_trigger` must be left as they are by default.

    L0 consolidation keeps the episodic records of the last `retention_days` days (older
    ones remain in the diary and in git history) and at most `max_insights` insights, the
    most recently written.
    """

    mode: Mode = Mode.SCHEDULED
    levels: tuple[Level, ...] = (Level.L0, Level.L1, Level.L2)
    schedule: dict[Trigger, tuple[Level, ...]] = Field(
        default_factory=lambda: {
            Trigger.DAILY: (Level.L0,),
            Trigger.WEEKLY: (Level.L1,),
            Trigger.MONTHLY: (Level.L2,),
        }
    )
    self_trigger: SelfTrigger = SelfTrigger()
    retention_days: PositiveInt = 7
    max_insights: PositiveInt = 50

    @field_validator("schedule")
    @classmethod
    def _self_is_not_scheduled(
        cls, schedule: dict[Trigger, tuple[Level, ...]]
    ) -> dict[Trigger, tuple[Level, ...]]:
        if Trigger.SELF in schedule:
            raise ValueError("self-triggered steps are requested by reflection, not scheduled")
        return schedule

    @model_validator(mode="after")
    def _free_mode_has_no_cadences(self) -> "EvolutionConfig":
        if self.mode is not Mode.FREE:
            return self
        if set(self.levels) != {Level.L0, Level.L1, Level.L2}:
            raise ValueError(
                "the free mode revises L0, L1 and L2 every night: levels must be those"
            )
        fields = type(self).model_fields
        if cadences := [
            name
            for name in ("schedule", "self_trigger")
            if getattr(self, name) != fields[name].get_default(call_default_factory=True)
        ]:
            raise ValueError(
                f"the free mode has no cadences: {' and '.join(cadences)} cannot be set"
            )
        return self
