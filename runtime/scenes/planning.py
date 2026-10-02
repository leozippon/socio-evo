"""Day planning: every agent chooses where to be in each slot."""

from collections.abc import Mapping, Sequence

from core.environment import Environment
from core.interaction import ActionKind, Decision, EventKind, PlanDay
from runtime.scenes import situations
from runtime.scenes.scene import Scene
from runtime.scheduler import Calendar


class Planning(Scene):
    """Each agent plans its day from wherever it is, in one turn.

    A plan naming a slot the calendar does not have is rejected as a whole, privately, and
    the agent spends the day at home. Places are not checked here: the environment rejects
    a move to an unknown place when the slot comes.
    """

    kind = "planning"
    allowed = (ActionKind.PLAN_DAY,)

    def __init__(
        self, env: Environment, id: str, participants: Sequence[str], calendar: Calendar, day: int
    ) -> None:
        super().__init__(env, id, None, participants)
        self.calendar = calendar
        self.day = day
        self.itineraries: dict[str, dict[str, str]] = {}

    def ask(self) -> list[str]:
        return list(self.participants)

    def situation(self, agent: str) -> str:
        return situations.planning(self.env, self.calendar, self.day, agent)

    async def carry_out(self, agent: str, decision: Decision, time: int) -> None:
        plan: PlanDay = decision.action
        if unknown := sorted(set(plan.itinerary) - {slot.name for slot in self.calendar.slots}):
            reason = situations.NO_SLOT.format(slot=unknown[0])
            self.env.emit(
                EventKind.ACTION_REJECTED,
                situations.REJECTED.format(kind=plan.kind, reason=reason),
                time=time,
                audience=[agent],
                actor=agent,
                place=self.env.world.locations[agent],
                scene=self.id,
                payload={"attempt": plan.model_dump(mode="json"), "reason": reason},
            )
        self.itineraries[agent] = {} if unknown else dict(plan.itinerary)

    def over(self, decisions: Mapping[str, Decision]) -> bool:
        return True

    def destinations(self, slot: str) -> dict[str, str]:
        """Where each agent goes in `slot`: the place it planned, or home."""
        homes = self.env.config.homes
        return {
            agent: self.itineraries[agent].get(slot, homes[agent]) for agent in self.participants
        }
