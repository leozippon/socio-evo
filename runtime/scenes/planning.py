"""Day planning: every agent chooses where to be in each part of the day."""

import re
from collections.abc import Mapping, Sequence

from core.environment import Environment
from core.interaction import ActionKind, Decision, EventKind, PlanDay
from runtime.scenes import situations
from runtime.scenes.scene import Scene
from runtime.scheduler import Calendar


class Planning(Scene):
    """Each agent plans its day from wherever it is, in one turn at `start`.

    A plan names parts of the day and places as a person would: a part by its name, a place
    by its id or its name, with or without "the", in any case, and home as "home". A plan
    naming a part of the day the calendar does not have is refused as a whole, privately, and
    the agent spends the day at home. Places are not checked here: the environment refuses a
    move to a place that does not exist when that part of the day comes.
    """

    kind = "planning"

    def __init__(
        self,
        env: Environment,
        id: str,
        participants: Sequence[str],
        calendar: Calendar,
        *,
        start: int,
    ) -> None:
        super().__init__(env, id, None, participants, start, 0)
        self.calendar = calendar
        self.itineraries: dict[str, dict[str, str]] = {}

    def ask(self) -> list[str]:
        return list(self.participants)

    def allowed(self, agent: str) -> tuple[ActionKind, ...]:
        return (ActionKind.PLAN_DAY,)

    def situation(self, agent: str) -> str:
        return situations.planning(self.env, self.calendar, agent)

    async def carry_out(self, agent: str, decision: Decision, time: int) -> None:
        plan: PlanDay = decision.action
        slots = {_plain(slot.name): slot.name for slot in self.calendar.slots}
        if unknown := [part for part in plan.itinerary if _plain(part) not in slots]:
            reason = situations.NO_PART.format(part=unknown[0])
            self.env.emit(
                EventKind.ACTION_REJECTED,
                reason,
                time=time,
                audience=[agent],
                actor=agent,
                place=self.env.world.locations[agent],
                scene=self.id,
                payload={"attempt": plan.model_dump(mode="json"), "reason": reason},
            )
            self.itineraries[agent] = {}
            return
        self.itineraries[agent] = {
            slots[_plain(part)]: self._place(agent, named) for part, named in plan.itinerary.items()
        }

    def over(self, decisions: Mapping[str, Decision]) -> bool:
        return True

    def destinations(self, slot: str) -> dict[str, str]:
        """Where each agent goes in `slot`: the place it planned, or home."""
        homes = self.env.config.homes
        return {
            agent: self.itineraries[agent].get(slot, homes[agent]) for agent in self.participants
        }

    def _place(self, agent: str, named: str) -> str:
        """The id of the place `agent` means by `named`, or `named` itself if it names none."""
        if _plain(named) in situations.HOME_WORDS:
            return self.env.config.homes[agent]
        for place in self.env.world.places.values():
            if _plain(named) in (_plain(place.id), _plain(place.name)):
                return place.id
        return named


def _plain(text: str) -> str:
    """`text` in lower case, punctuation and a leading "the" dropped, spaces collapsed."""
    words = re.sub(r"[\W_]+", " ", text.casefold()).split()
    return " ".join(words[1:] if words[:1] == ["the"] else words)
