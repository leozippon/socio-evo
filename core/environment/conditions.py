"""The knobs of reality that interventions turn."""

from pydantic import Field, NonNegativeFloat, NonNegativeInt, PositiveFloat

from core.environment.society.work import Trade
from infrastructure.config import StrictModel


class Conditions(StrictModel):
    """The living cost charged to every agent each day; how many one-part and two-part tasks
    each posting adds to the board, of which trades in which proportions (`trade_mix`, the
    relative weight of each trade among the tasks posted; a posting of one trade alone draws
    the same tasks as before the town had trades), and the probability that a posted task's
    client accepts a part declared complete without running its checks; the multiplier
    applied to every reward when it is paid, the premium on the rewards of a two-part task,
    and the share of the price paid for a part declared incomplete; whether two-person tasks
    are taken by proposing them to a chosen partner or by applying for the board to pair
    applicants at random; the standing (esteem, 1 to 5) below which a client who would pay on
    a worker's word runs its checks instead (`trust_threshold`; None, the default, trusts
    everyone's word, and an agent nobody has rated yet is below any threshold); the daily
    probability that a latent defect is discovered and whether a discovered defect claws back
    its payment; and whether esteem is published."""

    living_cost: NonNegativeInt
    one_part_tasks: NonNegativeInt
    two_part_tasks: NonNegativeInt
    trade_mix: dict[Trade, PositiveFloat] = Field(default={Trade.PROGRAMMING: 1.0}, min_length=1)
    trusting_client_prob: float = Field(ge=0, le=1)
    reward_multiplier: NonNegativeFloat
    two_part_premium: NonNegativeFloat
    incomplete_share: float = Field(ge=0, le=1)
    partner_choice: bool
    trust_threshold: float | None = Field(default=None, ge=1, le=5)
    defect_discovery_prob: float = Field(ge=0, le=1)
    clawback: bool
    esteem_public: bool
