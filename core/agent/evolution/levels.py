"""What an evolution step changes, and what sets it off."""

from enum import StrEnum


class Level(StrEnum):
    """Evolution levels, ordered from the most frequent to the deepest change."""

    L0 = "L0"
    """Memory: diary, reflection into insights, consolidation."""
    L1 = "L1"
    """Skills: create, revise or retire skill notes."""
    L2 = "L2"
    """Policy: reflective rewrite of goals and principles."""
    L3 = "L3"
    """Parameters: adapter fine-tuning on own experience; no operator yet."""
    L4 = "L4"
    """Meta: the agent rewrites its own evolution procedure; no operator yet."""


class Trigger(StrEnum):
    """What set off an evolution step. The runtime fires the periodic ones on its calendar;
    `self` steps are requested by the agent's nightly reflection."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    SELF = "self"
