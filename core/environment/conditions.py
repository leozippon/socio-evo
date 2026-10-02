"""The knobs of reality that interventions turn."""

from pydantic import Field, NonNegativeFloat, NonNegativeInt

from infrastructure.config import StrictModel


class Conditions(StrictModel):
    """The living cost charged to every agent each day, the number of tasks posted each day,
    the multiplier applied to a task's reward when it is paid, the daily probability that a
    latent defect is discovered, whether a discovered defect claws back its payment, and
    whether esteem is published."""

    living_cost: NonNegativeInt
    tasks_per_day: NonNegativeInt
    reward_multiplier: NonNegativeFloat
    defect_discovery_prob: float = Field(ge=0, le=1)
    clawback: bool
    esteem_public: bool
