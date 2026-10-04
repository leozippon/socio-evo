"""Day planning: every agent chooses where to be in each part of the day."""

from collections.abc import Mapping, Sequence

from core.environment import Environment, PlaceKind
from core.interaction import Allowance, Decision, MayPlan, PlanDay
from runtime.scenes import situations
from runtime.scenes.scene import Scene
from runtime.scheduler import Calendar


class Planning(Scene):
    """Each agent plans its day from wherever it is, in one turn at `start`, on a card that
    offers for each part of the day the places open when it begins, and home."""

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

    def allowed(self, agent: str) -> tuple[Allowance, ...]:
        names = situations.place_names(self.env, agent)
        home = self.env.config.homes[agent]
        places = {
            slot.name: {
                **{
                    names[place.id]: place.id
                    for place in self.env.world.places.values()
                    if place.kind is not PlaceKind.HOME and place.is_open(slot.start)
                },
                names[home]: home,
            }
            for slot in self.calendar.slots
        }
        return (MayPlan(places=places),)

    def situation(self, agent: str) -> str:
        return situations.planning(self.env, agent)

    async def carry_out(self, agent: str, decision: Decision, time: int) -> None:
        plan: PlanDay = decision.action
        self.itineraries[agent] = dict(plan.itinerary)

    def over(self, decisions: Mapping[str, Decision]) -> bool:
        return True

    def destinations(self, slot: str) -> dict[str, str]:
        """Where each agent goes in `slot`: the place it planned, or home."""
        homes = self.env.config.homes
        return {
            agent: self.itineraries[agent].get(slot, homes[agent]) for agent in self.participants
        }
