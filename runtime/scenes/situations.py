"""Every text the runtime shows a resident: what it knows of the town, and each moment.

Invariant 1 and `docs/IMMERSION.md` govern this module as they govern `core.agent.prompts`:
the texts describe circumstances and options in neutral words, as lived, in the town's own
words, without moral framing, hints about what is checked, or anything that reveals the
machinery. The time of a moment is told by the agent's prompt, so a situation starts after
it, and what the resident can do is listed on its answer card, with the real choices filled
in, so a situation says only what the card cannot. Runtime wording lives only in the
upper-case constants here, which tests scan.

The setting is what every resident simply knows, the same from moment to moment until the
town's rules change: the backdrop the configuration gives the town, its places, the shape of
its days, and how work and the ledger go. A moment is short: where you are, who is here, how
long until closing and, at work, until the next moment, your purse and job, and the board,
which says when new notices go up if it is empty; at night, what is still on your desk. Money
is told in the town's currency, and the words of others are quoted.
"""

from collections.abc import Sequence

from core.environment import Environment, PlaceKind, Trade
from core.interaction import Telling, Witness, capital, clock_of, day_of, job_name, listed
from runtime.scheduler import Calendar

TOWN = "You live in {home}. Elsewhere in {town}:\n{places}"
IN_TOWN = "town"
"""How the setting names a town that has no name."""
PLACE = "- {name}, {use}{hours}.{description}"
USES = {
    PlaceKind.WORK: "where you can take jobs from the board and work at a desk",
    PlaceKind.SOCIAL: "where you can sit and talk with whoever else is there",
}
FIRM = "a firm doing {work}, with a job sheet of its own for its people and {foreman} as foreman"
WORK_OF = {
    Trade.PROGRAMMING: "programming jobs",
    Trade.QUERIES: "queries",
    Trade.CALCULATION: "calculations",
}
"""The work of a firm of each trade."""
HOURS = ", open {spans}"
SPAN = "from {opens} to {closes}"
UNTIL = ", open until {closes}"
"""The hours of a place that keeps none of its own: it closes when the day ends."""
PART = "{name} from {start}"
DAY = (
    "Your days run the same way. At {start} you decide where to spend each part of the day: "
    "{parts}. New notices go up on the board at {postings}. Before you sleep you can mark the "
    "people you spent time with that day in the clerk's ledger."
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
NEXT = "Whatever you do now will take you to {clock}."
UNTIL_CLOSING = "Whatever you do now will take you to {clock}, when {place} closes."
UNTIL_THE_END = "Whatever you do now will take you to {clock}, when this part of the day ends."
"""How long what a resident does at work takes: until the next moment it decides, or until
the place closes or the part of the day ends."""
NO_NOTICES = "{board} New notices go up at {clock}."
NO_NOTICES_TOMORROW = "{board} New notices go up tomorrow at {clock}."
"""An empty board, and when the next notices go up."""
CONVERSATION = "You are at {place} with {people}. {purse}"

REVIEW = (
    "You are home for the night. Today you spent time with {people}. Before you sleep, the "
    "clerk's ledger is open to you.{desk}"
)

NOTICE = (
    "The clerk has put up a notice: a meeting at {place} at {clock} today, on the question "
    '"{question}" Whoever comes can have their say. At the end the clerk asks each person '
    "there, privately, for an answer, {options}; an answer given by more than half of them "
    "carries, and holds from the next morning."
)
OPENING = (
    'The clerk opens the meeting and reads out the question: "{question}" The answers are '
    "{options}."
)
ANSWERS = (
    "You are at {place}, and the talk is over. The clerk asks each person here, privately, for "
    'an answer to the question "{question}" The answers are {options}. An answer given by more '
    "than half of those here carries."
)
COUNT = (
    'The clerk has posted the count from the meeting at {place} on the question "{question}" '
    "{count}. {outcome}"
)
COUNTED = "{number} answered {option}"
UNANSWERED = "{number} gave no answer"
CARRIED = "The answer {option} carries, from tomorrow morning."
UNDECIDED = "No answer was given by more than half of those there, so things stay as they are."
NOBODY_CAME = (
    'The clerk has posted a word on the meeting at {place} on the question "{question}" Nobody '
    "came, so things stay as they are."
)

DRAW = (
    "{people} reached for the notice of {job} at the same moment, and the clerk drew lots: {order}."
)
FIRST = "{person} first"
THEN = "then {person}"


def setting(env: Environment, calendar: Calendar, postings: Sequence[str], agent: str) -> str:
    """What `agent` knows of the town: the backdrop of its setting, if it has one; its places
    with their hours, a place without hours of its own being open until the day ends; the
    shape of its days with the slots named in `postings` as the moments new notices go up;
    and the rules of work and the ledger."""
    places = [
        PLACE.format(
            name=capital(place.name),
            use=USES[place.kind]
            if place.establishment is None
            else FIRM.format(work=WORK_OF[place.trade], foreman=place.establishment.foreman),
            hours=HOURS.format(
                spans=listed([SPAN.format(opens=o, closes=c) for o, c in place.spans()])
            )
            if place.hours
            else UNTIL.format(closes=calendar.day_end),
            description=f" {place.description.strip()}" if place.description.strip() else "",
        )
        for place in env.world.places.values()
        if place.kind is not PlaceKind.HOME
    ]
    starts = {slot.name: slot.start for slot in calendar.slots}
    day = DAY.format(
        start=calendar.day_start,
        parts=_parts(calendar),
        postings=listed([starts[slot] for slot in postings]),
    )
    home = env.world.places[env.config.homes[agent]].name
    world = env.config.setting
    town = TOWN.format(home=home, town=world.name or IN_TOWN, places="\n".join(places))
    sections = (world.backdrop.strip(), town, day, env.rules_view())
    return "\n\n".join(section for section in sections if section)


def place_names(env: Environment, agent: str) -> dict[str, str]:
    """The names `agent` knows the town's places by, by id: its own home is `home`."""
    names = {place.id: place.name for place in env.world.places.values()}
    return {**names, env.config.homes[agent]: HOME}


def next_posting(calendar: Calendar, postings: Sequence[str], time: int) -> int | None:
    """When new notices next go up after `time`: at the first of the slots `postings` to
    start later that day, or else the next day; None if notices never go up."""
    for day in (day_of(time), day_of(time) + 1):
        times = calendar.slot_times(day)
        if later := [start for slot, start in times if slot in postings and start > time]:
            return later[0]
    return None


def planning(env: Environment, agent: str, now: int, posting: int | None) -> str:
    """The planning moment at `now`, with the notices `agent` would face at its own board (its
    firm's job sheet, or the board); `posting` is when new notices next go up, if known."""
    standings = env.esteem_view(agent)
    at = env.firms.firm_of(agent)
    return PLANNING.format(
        status=env.status_view(agent),
        board=_board(env, agent, at, now, posting),
        standings="" if standings is None else f"\n\n{standings}",
    )


def work(
    env: Environment,
    place: str,
    others: Sequence[str],
    agent: str,
    *,
    now: int,
    following: int,
    until: int,
    closes: bool,
    posting: int | None,
) -> str:
    """A moment at work at `now`: the next moment is at `following`, and the session lasts
    `until` the place closes (`closes`) or the part of the day ends; `posting` is when new
    notices next go up, if known."""
    name, clock = env.world.places[place].name, clock_of(until)
    if following < until:
        ends = (
            CLOSES.format(place=capital(name), clock=clock) if closes else ENDS.format(clock=clock)
        )
        told = f"{ends} {NEXT.format(clock=clock_of(following))}"
    elif closes:
        told = UNTIL_CLOSING.format(clock=clock, place=name)
    else:
        told = UNTIL_THE_END.format(clock=clock)
    return WORK.format(
        place=name,
        company=COMPANY.format(people=listed(others)) if others else ALONE,
        until=told,
        status=env.status_view(agent),
        board=_board(env, agent, place, now, posting),
    )


def conversation(env: Environment, place: str, others: Sequence[str], agent: str) -> str:
    return CONVERSATION.format(
        place=env.world.places[place].name, people=listed(others), purse=env.purse_view(agent)
    )


def review(env: Environment, agent: str, people: Sequence[str]) -> str:
    """The night's moment: whom `agent` met today, and what is still on its desk."""
    desk = env.desk_view(agent)
    return REVIEW.format(people=listed(people), desk="" if desk is None else f"\n\n{desk}")


def notice(env: Environment, place: str, clock: str, question: str, options: Sequence[str]) -> str:
    """The notice of a meeting at `place` at `clock` today on `question`, put up at dawn."""
    name = env.world.places[place].name
    return NOTICE.format(place=name, clock=clock, question=question, options=_either(options))


def opening(question: str, options: Sequence[str]) -> str:
    """The clerk's opening of a meeting, for those present."""
    return OPENING.format(question=question, options=_either(options))


def answers(env: Environment, place: str, question: str, options: Sequence[str]) -> str:
    """The moment the clerk asks those still at a meeting for their answers."""
    return ANSWERS.format(
        place=env.world.places[place].name, question=question, options=_either(options)
    )


def count(
    env: Environment,
    place: str,
    question: str,
    counts: dict[str, int],
    asked: int,
    carried: str | None,
) -> str:
    """The count of a meeting at `place` on `question`, posted that night: `counts` of each
    answer among the `asked` people still there at the end, and the answer that `carried`."""
    name = env.world.places[place].name
    if not asked:
        return NOBODY_CAME.format(place=name, question=question)
    told = [COUNTED.format(number=n, option=option) for option, n in counts.items()]
    if unanswered := asked - sum(counts.values()):
        told.append(UNANSWERED.format(number=unanswered))
    outcome = UNDECIDED if carried is None else CARRIED.format(option=carried)
    return COUNT.format(place=name, question=question, count=capital(listed(told)), outcome=outcome)


def draw(order: Sequence[str], task_id: str) -> Telling:
    """The news that the agents in `order` asked for one job at once, and in what order the
    lots put them, as each of them is told it."""

    def drawn(you: Witness) -> str:
        first, *then = (you(person) for person in order)
        steps = [FIRST.format(person=first), *(THEN.format(person=person) for person in then)]
        return DRAW.format(
            people=capital(you.listed(sorted(order))), job=job_name(task_id), order=", ".join(steps)
        )

    return drawn


def _board(env: Environment, agent: str, place: str | None, now: int, posting: int | None) -> str:
    """The notices `agent` faces at `place` (its own board, if None) at `now`; if there are
    none and `posting` is known, when new notices go up."""
    board = env.board_view(agent) if place is None else env.board_view(agent, place)
    if env.notices_for(agent, place) or posting is None or not board.startswith("There are no"):
        return board
    told = NO_NOTICES if day_of(posting) == day_of(now) else NO_NOTICES_TOMORROW
    return told.format(board=board, clock=clock_of(posting))


def _either(options: Sequence[str]) -> str:
    """`yes or no`, `lot, choice or neither`."""
    return " or ".join([", ".join(options[:-1]), options[-1]])


def _parts(calendar: Calendar) -> str:
    return listed([PART.format(name=slot.name, start=slot.start) for slot in calendar.slots])
