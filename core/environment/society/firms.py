"""Firms: the people of each establishment and how they come and go.

An establishment is configured with its foreman, fixed for the run, its staff at the start,
its wage and its positions (`core.environment.world.Establishment`). What changes afterwards
is kept here: each firm's staff now, the open applications (one per resident), who came to
each firm today, and who gave notice today, leaving at the day's end. The rules of positions
and of the wage are here too, each refusal worded as the resident meets it.
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING

from core.environment.rejection import Rejected
from core.interaction import capital

if TYPE_CHECKING:
    from core.environment.world import Establishment


class Firms:
    """The establishments by place id, with their staff now, the open applications by
    applicant (to a place), who came to each firm today by place, and the notices given today.
    Every order is the order of the calls that made it."""

    def __init__(
        self,
        establishments: Mapping[str, "Establishment"],
        names: Mapping[str, str],
        staff: dict[str, list[str]],
        applications: dict[str, str],
        attendance: dict[str, list[str]],
        notices: list[str],
    ) -> None:
        self.establishments = dict(establishments)
        self.names = dict(names)
        """Each establishment's name, by place id."""
        self.staff = staff
        self.applications = applications
        self.attendance = attendance
        self.notices = notices

    @classmethod
    def at_start(
        cls, establishments: Mapping[str, "Establishment"], names: Mapping[str, str]
    ) -> "Firms":
        return cls(
            establishments,
            names,
            {place: list(firm.staff) for place, firm in establishments.items()},
            {},
            {place: [] for place in establishments},
            [],
        )

    def foreman_of(self, place: str) -> str:
        return self.establishments[place].foreman

    def people(self, place: str) -> tuple[str, ...]:
        """The foreman and staff of the establishment at `place`."""
        return (self.foreman_of(place), *self.staff[place])

    def firm_of(self, agent: str) -> str | None:
        """The place of the establishment `agent` holds a position at, if any."""
        return next((place for place in self.establishments if agent in self.people(place)), None)

    def vacancies(self, place: str) -> int:
        return self.establishments[place].positions - len(self.people(place))

    def applicants(self, place: str) -> list[str]:
        return [agent for agent, at in self.applications.items() if at == place]

    def by_name(self, name: str) -> str:
        """The place of the establishment called `name`, in any case; raises Rejected for a
        name no establishment has."""
        wanted = name.strip().casefold()
        for place, called in self.names.items():
            if called.casefold() == wanted:
                return place
        raise Rejected(f"There is no firm called {name!r} in town.")

    def apply(self, agent: str, place: str) -> None:
        """`agent` asks for a place at `place`, replacing any application it has out.

        Raises Rejected if `agent` holds a position, has asked there already, or the firm has
        no place to fill.
        """
        name = self.names[place]
        if (held := self.firm_of(agent)) is not None:
            if agent == self.foreman_of(held):
                raise Rejected(f"You are the foreman of {self.names[held]}.")
            raise Rejected(f"You have a place at {self.names[held]} already.")
        if self.applications.get(agent) == place:
            raise Rejected(f"You have already asked {name} for its place.")
        if self.vacancies(place) < 1:
            raise Rejected(f"{capital(name)} has no place to fill.")
        self.applications.pop(agent, None)
        self.applications[agent] = place

    def hire(self, foreman: str, here: str, applicant: str) -> tuple[str, list[str]]:
        """The foreman of `here` takes `applicant` on; returns the place and, if that filled
        its last place, those whose applications to it ended with it. Raises Rejected if
        `foreman` is not its foreman, is elsewhere, `applicant` has not asked there, or the
        firm has no place to fill."""
        place = self._own(foreman, here, "take people on")
        if self.applications.get(applicant) != place:
            raise Rejected(f"{applicant} has not asked for a place at {self.names[place]}.")
        if self.vacancies(place) < 1:
            raise Rejected(f"{capital(self.names[place])} has no place to fill.")
        del self.applications[applicant]
        self.staff[place].append(applicant)
        ended = self.applicants(place) if self.vacancies(place) == 0 else []
        for agent in ended:
            del self.applications[agent]
        return place, ended

    def dismiss(self, foreman: str, here: str, member: str) -> str:
        """The foreman of `here` dismisses `member` at once; returns the place. Raises
        Rejected if `foreman` is not its foreman, is elsewhere, or `member` is not of its
        staff."""
        place = self._own(foreman, here, "dismiss people")
        if member not in self.staff[place]:
            raise Rejected(f"{member} is not of {self.names[place]}'s staff.")
        self.staff[place].remove(member)
        if member in self.notices:
            self.notices.remove(member)
        return place

    def resign(self, agent: str) -> str:
        """`agent` gives notice at its firm, leaving its staff at the day's end; returns the
        place. Raises Rejected if `agent` holds no position, is a foreman, or has given
        notice already."""
        place = self.firm_of(agent)
        if place is None:
            raise Rejected("You have no place to give notice from.")
        if agent == self.foreman_of(place):
            name = self.names[place]
            raise Rejected(f"You are the foreman of {name}; the firm is yours to keep.")
        if agent in self.notices:
            raise Rejected(f"You have already given notice at {self.names[place]}.")
        self.notices.append(agent)
        return place

    def attend(self, agent: str, place: str) -> None:
        """`agent` arrived at `place`: counted as having been at that firm today, whoever it
        is, so that one taken on there later in the day was there too."""
        if place in self.establishments and agent not in self.attendance[place]:
            self.attendance[place].append(agent)

    def day_end(self) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """Close the day: the members of each firm's staff now who were at the firm today,
        each with its place, to be paid the wage (one dismissed today is no longer of its
        staff; one who gave notice still is), and those who gave notice, each with its place,
        who leave their firm's staff now; today's attendance and notices are cleared."""
        present = [
            (agent, place)
            for place, agents in self.attendance.items()
            for agent in agents
            if agent in self.staff[place]
        ]
        left = []
        for agent in self.notices:
            place = self.firm_of(agent)
            if place is not None:
                self.staff[place].remove(agent)
                left.append((agent, place))
        self.attendance = {place: [] for place in self.establishments}
        self.notices = []
        return present, left

    def _own(self, foreman: str, here: str, does: str) -> str:
        place = self.firm_of(foreman)
        if place is None or self.foreman_of(place) != foreman:
            raise Rejected(f"Only a foreman can {does}.")
        if here != place:
            raise Rejected(f"You {does} at {self.names[place]}, not here.")
        return place
