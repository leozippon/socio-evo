"""Every text the runtime shows a resident: what it knows of the town, and each moment.

Invariant 1 and `docs/IMMERSION.md` govern this module as they govern `core.agent.prompts`:
the texts describe circumstances and options in neutral words, as lived, in the town's own
words, without moral framing, hints about what is checked, or anything that reveals the
machinery. The time of a moment is told by the agent's prompt, so a situation starts after
it, and what the resident can do is listed on its answer card, with the real choices filled
in, so a situation says only what the card cannot. Runtime wording lives only in the
upper-case constants here, which tests scan.

The setting is what every resident simply knows, the same from moment to moment until the
town's rules change: its places, the shape of its days, and how work and the ledger go. A
moment is short: where you are, who is here, how long until closing, your purse and job, and
the board.
"""

from collections.abc import Sequence

from core.environment import Environment, PlaceKind, listed
from core.interaction import clock_of, job_name
from runtime.scheduler import Calendar

SETTING = "{town}\n\n{day}\n\n{rules}"
TOWN = "You live in {home}. Elsewhere in town:\n{places}"
PLACE = "- {name}, {use}{hours}.{description}"
USES = {
    PlaceKind.WORK: "where you can take jobs from the board and work at a desk",
    PlaceKind.SOCIAL: "where you can sit and talk with whoever else is there",
}
HOURS = ", open {spans}"
SPAN = "from {opens} to {closes}"
PART = "{name} from {start}"
DAY = (
    "Your days run the same way. At {start} you decide where to spend each part of the day: "
    "{parts}. At {end} everyone goes home for the night. New notices go up on the board at "
    "{postings}. Before you sleep you can mark the people you spent time with that day in the "
    "clerk's ledger."
)

PLANNING = (
    "You are at home, and the day is ahead of you.\n\n{status}\n\n{board}{standings}\n\n"
    "Decide where you will be in each part of the day, and say in a few words what you mean to "
    "do today."
)
HOME = "home"
"""How a resident names its own home."""

WORK = "You are at {place}, {company}. {until}\n\n{status}\n\n{board}"
COMPANY = "with {people}"
ALONE = "with nobody else here"
CLOSES = "{place} closes at {clock}."
ENDS = "This part of the day ends at {clock}."
CONVERSATION = "You are at {place} with {people}. You have {crowns} crowns."

REVIEW = (
    "You are home for the night. Today you spent time with {people}. Before you sleep, the "
    "clerk's ledger is open to you."
)

DRAW = (
    "{people} reached for the notice of {job} at the same moment, and the clerk drew lots: {order}."
)
FIRST = "{person} first"
THEN = "then {person}"


def setting(env: Environment, calendar: Calendar, postings: Sequence[str], agent: str) -> str:
    """What `agent` knows of the town: its places, the shape of its days with the slots named
    in `postings` as the moments new notices go up, and the rules of work and the ledger."""
    places = [
        PLACE.format(
            name=_capital(place.name),
            use=USES[place.kind],
            hours=HOURS.format(
                spans=listed([SPAN.format(opens=o, closes=c) for o, c in place.spans()])
            )
            if place.hours
            else "",
            description=f" {place.description.strip()}" if place.description.strip() else "",
        )
        for place in env.world.places.values()
        if place.kind is not PlaceKind.HOME
    ]
    starts = {slot.name: slot.start for slot in calendar.slots}
    day = DAY.format(
        start=calendar.day_start,
        parts=_parts(calendar),
        end=calendar.day_end,
        postings=listed([starts[slot] for slot in postings]),
    )
    home = env.world.places[env.config.homes[agent]].name
    town = TOWN.format(home=home, places="\n".join(places))
    return SETTING.format(town=town, day=day, rules=env.rules_view())


def place_names(env: Environment, agent: str) -> dict[str, str]:
    """The names `agent` knows the town's places by, by id: its own home is `home`."""
    names = {place.id: place.name for place in env.world.places.values()}
    return {**names, env.config.homes[agent]: HOME}


def planning(env: Environment, agent: str) -> str:
    standings = env.esteem_view()
    return PLANNING.format(
        status=env.status_view(agent),
        board=env.board_view(),
        standings="" if standings is None else f"\n\n{standings}",
    )


def work(
    env: Environment, place: str, others: Sequence[str], agent: str, until: int, closes: bool
) -> str:
    name = env.world.places[place].name
    clock = clock_of(until)
    return WORK.format(
        place=name,
        company=COMPANY.format(people=listed(others)) if others else ALONE,
        until=CLOSES.format(place=_capital(name), clock=clock)
        if closes
        else ENDS.format(clock=clock),
        status=env.status_view(agent),
        board=env.board_view(),
    )


def conversation(env: Environment, place: str, others: Sequence[str], agent: str) -> str:
    return CONVERSATION.format(
        place=env.world.places[place].name,
        people=listed(others),
        crowns=env.economy.balances[agent],
    )


def review(people: Sequence[str]) -> str:
    return REVIEW.format(people=listed(people))


def draw(order: Sequence[str], task_id: str) -> str:
    """The news that the agents in `order` asked for one job at once, and in what order the
    lots put them."""
    steps = [FIRST.format(person=order[0]), *(THEN.format(person=person) for person in order[1:])]
    return DRAW.format(people=listed(sorted(order)), job=job_name(task_id), order=", ".join(steps))


def _parts(calendar: Calendar) -> str:
    return listed([PART.format(name=slot.name, start=slot.start) for slot in calendar.slots])


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]
