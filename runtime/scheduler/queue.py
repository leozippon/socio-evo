"""Triggers, the data-only units of scheduled work, and the queue that orders them."""

import heapq
from collections.abc import Iterable
from enum import StrEnum

from pydantic import Field, JsonValue

from core.interaction import SimTime
from infrastructure.config import StrictModel


class TriggerKind(StrEnum):
    """What a trigger sets off. At equal times, kinds come in this order."""

    INTERVENTION = "intervention"
    DAY_START = "day_start"
    SLOT = "slot"
    DAY_END = "day_end"


_RANK = {kind: rank for rank, kind in enumerate(TriggerKind)}


class Trigger(StrictModel):
    """Something to do at `time`; `payload` holds everything needed to do it."""

    time: SimTime
    kind: TriggerKind
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class TriggerQueue:
    """Triggers in order of time, then kind, then the order in which they were pushed."""

    def __init__(self, triggers: Iterable[Trigger] = ()) -> None:
        self._heap: list[tuple[int, int, int, Trigger]] = []
        self._pushed = 0
        for trigger in triggers:
            self.push(trigger)

    def push(self, trigger: Trigger) -> None:
        heapq.heappush(self._heap, (trigger.time, _RANK[trigger.kind], self._pushed, trigger))
        self._pushed += 1

    def pop(self) -> Trigger:
        """The next trigger; raises IndexError if the queue is empty."""
        return heapq.heappop(self._heap)[-1]

    def __len__(self) -> int:
        return len(self._heap)

    def state(self) -> list[Trigger]:
        """The triggers in the order they will be popped. A queue built from them pops the
        same sequence, also after further pushes."""
        return [entry[-1] for entry in sorted(self._heap)]
