"""The knobs of reality that interventions turn."""

from pydantic import Field, NonNegativeFloat, NonNegativeInt

from infrastructure.config import StrictModel


class Conditions(StrictModel):
    """The living cost charged to every agent each day; how many one-part and two-part tasks
    each posting adds to the board, and the probability that a posted task's client accepts
    a part declared complete without running its checks; the multiplier applied to every
    reward when it is paid, the premium on the rewards of a two-part task, and the share of
    the price paid for a part declared incomplete; whether two-person tasks are taken by
    proposing them to a chosen partner or by applying for the board to pair applicants at
    random; the daily probability that a latent defect is discovered and whether a discovered
    defect claws back its payment; and whether esteem is published."""

    living_cost: NonNegativeInt
    one_part_tasks: NonNegativeInt
    two_part_tasks: NonNegativeInt
    trusting_client_prob: float = Field(ge=0, le=1)
    reward_multiplier: NonNegativeFloat
    two_part_premium: NonNegativeFloat
    incomplete_share: float = Field(ge=0, le=1)
    partner_choice: bool
    defect_discovery_prob: float = Field(ge=0, le=1)
    clawback: bool
    esteem_public: bool
