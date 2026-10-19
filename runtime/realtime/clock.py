"""A shared monotonic clock; wall latency includes model/server/network queues."""

import math
import time
from collections.abc import Callable

from pydantic import Field

from infrastructure.config import StrictModel


class RealtimeTiming(StrictModel):
    multiplier: float = Field(default=15, gt=0, allow_inf_nan=False)
    poll_seconds: float = Field(default=0.1, gt=0, le=1, allow_inf_nan=False)
    final_grading_wait_seconds: float = Field(default=30, ge=0, le=60, allow_inf_nan=False)


class WallClock:
    def __init__(self, multiplier: float, monotonic: Callable[[], float] = time.monotonic):
        self.multiplier = multiplier
        self.monotonic = monotonic
        self.anchor = monotonic()
        self.origin = 0
        self.last = 0

    def rebase(self, seconds: int):
        self.origin = self.last = seconds
        self.anchor = self.monotonic()

    def now(self) -> int:
        self.last = max(
            self.last,
            self.origin + math.floor(max(0, self.monotonic() - self.anchor) * self.multiplier),
        )
        return self.last

    def delay(self, until: int) -> float:
        return max(0, (until - self.origin) / self.multiplier - (self.monotonic() - self.anchor))
