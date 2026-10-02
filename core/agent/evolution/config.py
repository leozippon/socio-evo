"""Which evolution levels run, and when."""

from pydantic import Field, PositiveInt, field_validator

from core.agent.evolution.levels import Level, Trigger
from infrastructure.config import StrictModel


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
    """`levels` are the enabled levels; a trigger runs the levels `schedule` maps it to that
    are also enabled. With no level enabled nothing evolves: the no-evolution baseline.

    L0 consolidation keeps the episodic records of the last `retention_days` days (older
    ones remain in the diary and in git history) and at most `max_insights` insights, the
    most recently written.
    """

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
