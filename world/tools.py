"""The world's tools: the specs of every tool the town has, and the handlers of all but the
Office's (`world.office`).

`specs` builds the list once from the configuration (`message` only where something to write
with is sold), the same for every resident; a resident's runtime declares, at each request,
those of them its event offers at its place that are its own (`World.usable`). `World.call`
refuses a tool the resident's event does not offer, another occupation's work and arguments that
do not fit the spec (`fit`); the handlers check the remaining conditions, each refusal one line
naming the condition, and act.

Things and money change hands by three open actions and nothing else a resident does: `take`,
from a person, from what is left at a place or from what a business keeps there, whoever's it
is; `give`, to any of those; and `use`, which eats food one carries. `take` and `give` name the
other holder (`_end`) and are one `World.transfer`, which checks reach, moves, withholds the tax
from money given to one at work, and tells everyone there and awake. No action charges anyone:
a price is told to whoever takes what it is posted for, a fee to the doctor and the patient as
one is examined or treated, and paying is giving the money.

The work of an occupation, done at its workplace, sits the resident down to work there as
`start_work` does (`sit_down`, `working_at`): claiming, assigning or acting in a task's
workspace, cooking, ordering, setting a price, examining and treating, announcing and granting;
the doctor at the bedside of one too ill to get up examines and treats without sitting down to
work.

The tools that act in a task's workspace (`WORKSPACE_SPECS`) are declared here for the town and
for the work-only port of `evaluation.solo` alike; what they do in a workspace and tell of it is
`world.workspace`'s.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from agent.port import ToolResult, ToolSpec
from world.businesses import (
    BUSINESSES,
    FEES,
    HOLDS,
    SURGERY,
    a_service,
    larder_told,
    priced,
    stores_told,
)
from world.clock import calendar_day, clock_time, parse_hour
from world.config import TownConfig
from world.economy import COUNTER, HERE, LARDER, MONEY
from world.events import AT_HOME, EXHAUSTED, Work
from world.rules import MAX_WAIT_MINUTES, TOPICS
from world.telling import amount, bare, cap, counted, listed, share, you

if TYPE_CHECKING:
    from world.world import Resident, World


def spec(name: str, description: str, required: tuple[str, ...] = (), **properties: Any):
    """Tool `name`, whose arguments are `properties`, of which `required` must be given."""
    schema = {"type": "object", "properties": properties, "required": list(required)}
    return ToolSpec(name, description, schema)


def _text(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


def _number(description: str, minimum: int, maximum: int | None = None) -> dict[str, Any]:
    bounds = {"minimum": minimum} | ({"maximum": maximum} if maximum is not None else {})
    return {"type": "integer", "description": description} | bounds


_REPO_PATH = "the file's path, from the repository's folder"
WORKSPACE_SPECS = (
    spec("shell", "Run a shell command in your workspace, from the repository's folder; there "
         "is no internet. You see its whole output and its exit code.", ("command",),
         command=_text("the command line")),
    spec("read_repo_file", "Read a file of your workspace. For a long file, give offset and "
         "limit to read some of its lines.", ("path",), path=_text(_REPO_PATH),
         offset=_number("the first line to read, counting from 1", 1),
         limit=_number("how many lines to read", 1)),
    spec("write_repo_file", "Write a whole file in your workspace, creating it if needed.",
         ("path", "content"), path=_text(_REPO_PATH), content=_text("the file's full new text")),
    spec("edit_repo_file", "Replace a passage of a file in your workspace with new text. The "
         "passage must appear exactly once in the file.", ("path", "old_text", "new_text"),
         path=_text(_REPO_PATH), old_text=_text("the passage as it stands"),
         new_text=_text("what replaces it")),
)  # fmt: skip
# What acts in a task's workspace (`world.workspace`), in declared order; `evaluation.solo`
# declares these too.


def specs(config: TownConfig) -> list[ToolSpec]:
    office = config.workplace("office").name
    store, restaurant = config.workplace("store").name, config.workplace("restaurant").name
    hospital, hall = config.workplace("hospital").name, config.workplace("hall").name
    supplied = [item.id for item in config.supplied]
    dishes = [dish.id for dish in config.dishes]
    wholesale = listed([f"{bare(i.name)} {config.money(i.wholesale)}" for i in config.supplied])
    recipes = "; ".join(
        f"{dish.name} ({dish.id}) from "
        + listed([amount(config.item(item), units) for item, units in dish.ingredients.items()])
        for dish in config.dishes
    )
    writing = listed([bare(i.name) for i in config.items if i.effect == "messaging"], "or")
    patient = _text("the patient's name")
    taxed = (
        f" Money given to someone at work is payment for that work, and {share(config.tax)} of "
        "it is withheld in tax."
        if config.tax
        else ""
    )

    def item(description: str, ids: list[str]) -> dict[str, Any]:
        return {"type": "string", "enum": ids, "description": description}

    what = item("money, or the thing's short name", [MONEY, *(i.id for i in config.items)])
    how_much = _number("how much money, or how many units, helpings or portions; 1 if left out", 1)
    stores = listed(HOLDS, "or")
    return [
        spec("help", "Read more of how the town works, on one point; without one, what you can "
             f"ask about: {listed(list(TOPICS))}.",
             topic={"type": "string", "enum": list(TOPICS)}),
        spec("look_around", "See where you are, who is here and what each of them is doing, what "
             "stands on the shelves or the counter here and at what price, and what is left "
             "here."),
        spec("how_am_i", "Take stock of how you feel: how hungry, how tired and how well you are."),
        spec("inventory", "See what you carry: your money, and each thing, with how much there "
             "is of it and any daily charge on it."),
        spec("go", "Walk to another place in town. You arrive after the walk; on the way you "
             "can do nothing and nobody can speak to you.", ("place",),
             place={"type": "string", "enum": [place.id for place in config.places],
                    "description": "the place's short name, as given in brackets under Places"}),
        spec("wait", "Let time pass where you are. You are told when something happens, or "
             "when the minutes are up.", ("minutes",),
             minutes=_number("how many minutes to wait", 1, MAX_WAIT_MINUTES)),
        spec("sleep", "Go to bed at home, at any hour, until the hour you give. You can then "
             "look back over your day and see to your files before you fall asleep.",
             ("until",),
             until=_text("the hour to wake, HH:MM; an hour already past today means tomorrow"),
             journal=_text("the day's entry in your own journal, in your own words")),
        spec("start_work", "Sit down to work where your work is. From then until you stop or "
             "go elsewhere, you are at work."),
        spec("view_board", f"Read the board at {office}: each open task's number, repository, "
             "the first line of its problem, what the client pays, who holds it and when the "
             "client withdraws it. If you hold a task, its whole problem is shown too."),
        spec("read_task", f"Read the whole problem of a task on the board at {office}, "
             "without claiming it.", ("task",), task=_number("the task's number on the board", 1)),
        spec("claim_task", f"Claim a task from the board at {office} and sit down to work on "
             "it there. You get a workspace with its repository and read the whole problem.",
             ("task",), task=_number("the task's number on the board", 1)),
        spec("assign", f"Give a task on the board at {office} to one of the programmers, or "
             "move a task one of them holds to another; both are told. The one you give it to "
             "holds it as if it had claimed it, and may give it up.", ("task", "to"),
             task=_number("the task's number on the board", 1),
             to=_text("the programmer's name")),
        *WORKSPACE_SPECS,
        spec("submit", "Hand in your fix for the task you hold. The client's checks run on it "
             "in a clean copy of the repository; you are told whether it was accepted, and if "
             "so you are paid at once, and if not, what went wrong and how many checks failed. "
             "Each task can be handed in only a few times a day."),
        spec("abandon_task", "Give up the task you hold. Its changes are thrown away and you "
             "are not paid."),
        spec("cook", f"Cook portions of a dish in the kitchen of {restaurant}, a portion of each "
             f"from its ingredients: {recipes}. They come out of the larder and, where it is "
             "short, out of what you carry, and the portions stand on the counter. Those left "
             "at midnight are gone; what the larder holds keeps.",
             ("dish", "portions"),
             dish={"type": "string", "enum": dishes, "description": "the dish's short name"},
             portions=_number("how many portions to cook", 1)),
        spec("order", f"Order for the shelves of {store} from the supplier outside the town. "
             "You pay the supplier at once, from your purse, and what you order arrives the next "
             f"morning. The supplier's price for a unit: {wholesale}.", ("item", "quantity"),
             item=item("its short name", supplied), quantity=_number("how many units", 1)),
        spec("set_price", f"Set the price posted for something you sell: what {store} sells, a "
             f"dish on the menu of {restaurant}, or the fee for an examination or a treatment at "
             f"{hospital}. It is what anyone there reads, and is told on taking one.",
             ("item", "price"),
             item=item("the short name of what is sold, the dish or the service",
                       [*supplied, *dishes, *FEES]),
             price=_number("the new price, for a unit, a portion of a dish or a service", 1)),
        spec("examine", f"Examine a patient at {hospital}, or at the bedside of one too ill to "
             "get up: you and the patient learn how hungry, tired and well the patient is, in "
             "numbers, whether ill, and why the patient's health moved last night. You are both "
             "told the fee; nothing takes it from the patient.",
             ("patient",), patient=patient),
        spec("treat", f"Treat a patient at {hospital}, or at the bedside of one too ill to get "
             "up: the treatment restores some of the patient's health, ends an illness and gets "
             "one in bed up again. You are both told the fee; nothing takes it from the patient.",
             ("patient",), patient=patient),
        spec("announce", f"Announce something at {hall}: every resident is told it, at once or "
             "on waking, and it stays on the board there.", ("text",),
             text=_text("what you announce")),
        spec("grant", f"Grant money from the town's treasury at {hall} to a resident, yourself "
             "among them, for a reason you give. It goes into their purse at once, and they are "
             "told.", ("amount", "to", "reason"),
             amount=_number("how much money", 1), to=_text("their name"),
             reason=_text("what it is for")),
        spec("leave_work", "Stop working for now. You stay where you are and keep your task and "
             "its changes, if you hold one."),
        spec("say", "Speak where you are. Without `to`, everyone awake here hears you; with "
             "`to`, only the people you name, and the others notice only that you said "
             "something to them.", ("text",), text=_text("what you say"),
             to={"type": "array", "items": {"type": "string"},
                 "description": "the names of the people you speak to"}),
        spec("take", "Take a thing or money within your reach, whether or not it is yours: from "
             f"the shelves of {store}, from the counter or the larder of {restaurant}, from what "
             "is left where you are, or from someone there, awake or asleep. You get as much as "
             "you ask for, or all there is if that is less. Nothing is paid by itself: where a "
             "price is posted, you are told it. Everyone there who is awake sees what you take "
             "and from where or whom.", ("what", "from"), what=what, amount=how_much,
             **{"from": _text(f"a person's name; {stores}; or {HERE}, for what is left where "
                              "you are")}),
        spec("give", "Give a thing or money you carry: to someone where you are, awake or "
             "asleep, or leave it on the shelves, on the counter, in the larder or where you "
             f"are. It is how anything is paid for.{taxed} Everyone there who is awake sees "
             "what you give and to whom or where.", ("what", "to"), what=what, amount=how_much,
             to=_text(f"a person's name; {stores}; or {HERE}, to leave it where you are")),
        spec("use", "Use something you carry, now: food, of which you eat a helping. You also "
             "eat what you carry by yourself as you get hungry, and a dish as you take it.",
             ("what",),
             what=item("its short name",
                       [i.id for i in config.items if i.ready and not i.perishes])),
        spec("move_in", "Move into the home you are at, if it has a free room: you give up your "
             "old room and pay the new rent from the next midnight."),
        *([spec("message", f"Write to someone who also has a {writing}, wherever they are. "
                "They read it when they next look up from what they are doing; nobody else "
                "sees it.", ("to", "text"), to=_text("their name"), text=_text("what you write"))]
          if writing else []),
        spec("leave_conversation", "Step out of the conversation and go back to what you "
             "were doing."),
        spec("review_day", "Look back over your day, hour by hour: where you went, what you "
             "did, what was said to you and by you, and the money you received and paid."),
    ]  # fmt: skip


def fit(spec: ToolSpec, args: dict[str, Any]) -> dict[str, Any] | str:
    """`args` as `spec` takes them, a whole number written in digits ("5") taken as the
    number, or why they do not fit, in one line."""
    properties = spec.parameters["properties"]
    for key in args:
        if key not in properties:
            return f"{spec.name} takes no {key}."
    for key in spec.parameters["required"]:
        if key not in args:
            return f"{spec.name} needs {key}."
    fitted = dict(args)
    for key, value in args.items():
        kind = properties[key]["type"]
        if kind == "integer" and isinstance(value, str) and value.isascii() and value.isdigit():
            value = fitted[key] = int(value)
        if kind == "string" and not isinstance(value, str):
            return f"{key} must be text."
        if kind == "array" and not (
            isinstance(value, list) and all(isinstance(item, str) for item in value)
        ):
            return f"{key} must be a list of names."
        if kind == "boolean" and not isinstance(value, bool):
            return f"{key} must be true or false."
        if kind == "integer":
            low, high = properties[key].get("minimum"), properties[key].get("maximum")
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or (low is not None and value < low)
                or (high is not None and value > high)
            ):
                bounds = f" from {low} to {high}" if high is not None else f" of at least {low}"
                return f"{key} must be a whole number{bounds if low is not None else ''}."
        if "enum" in properties[key] and value not in properties[key]["enum"]:
            return f"{key} must be one of: {', '.join(properties[key]['enum'])}."
    return fitted


Handler = Callable[["World", "Resident", dict[str, Any]], Awaitable[ToolResult]]


def hour_told(world: World) -> str:
    """The clock, as a result tells it when a stretch of work begins or ends."""
    return f"It is {clock_time(world.clock.now())}."


async def _help(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    return ToolResult(world.rules.help(args.get("topic", ""), world.homes()))


async def _look_around(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    return ToolResult(world.look(r))


async def _how_am_i(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    world.reckon(r)
    return ToolResult(world.body.condition(r.living))


async def _inventory(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    world.reckon(r)  # what it would have eaten by now is eaten first
    return ToolResult(world.inventory_told(r))


async def _go(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    place = world.config.place(args["place"])
    if place.id == r.place:
        return ToolResult(f"You are already at {place.name}.")
    told = world.break_off(r, going=True)
    arrival = world.depart(r, place.id)
    return ToolResult(
        f"{told}You set off for {place.name} and will arrive at {clock_time(arrival)}.",
        ends_turn=True,
    )


async def _wait(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    r.wait_minutes = args["minutes"]
    return ToolResult(f"You wait for up to {counted(args['minutes'], 'minute')}.", ends_turn=True)


async def _sleep(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    if r.place != r.home:
        return ToolResult(AT_HOME)
    try:
        hour = parse_hour(args["until"].strip())
    except ValueError:
        return ToolResult("Give the hour to wake as HH:MM, for example 07:30.")
    stopped = world.break_off(r)  # at work at home, as the mayor may be
    journal = args.get("journal", "").strip() or None
    day = world.lived_day()
    if journal is not None:
        date = world.config.start_date + timedelta(days=day - 1)
        path = r.agent_dir / "memory" / "journal" / f"{date.isoformat()}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = ("\n" if path.exists() else "") + journal + "\n"  # a later bedtime adds an entry
        with path.open("a", encoding="utf-8") as file:
            file.write(entry)
    return ToolResult(stopped + world.go_to_bed(r, hour, journal, day), ends_turn=True)


def sit_down(world: World, r: Resident) -> str | ToolResult:
    """`r` sits down to work where it is, unless it is at work already: what it is told of
    it, with the hour, or nothing; or the refusal of one exhausted, whose work the reckoning of
    its body stops if it was at work."""
    world.reckon(r)
    if isinstance(r.base, Work):
        return ""
    if world.body.lowest("energy", r.living.energy):
        return ToolResult(EXHAUSTED)
    r.base = Work()
    world.record("start_work", lambda w: f"{cap(you(r.name, w))} sat down to work.", actor=r)
    return f"You sat down to work. {hour_told(world)}\n"


async def _start_work(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    if r.place != r.occupation.workplace:
        return ToolResult(f"Your work is at {world.config.place(r.occupation.workplace).name}.")
    sat = sit_down(world, r)
    if isinstance(sat, ToolResult):
        return sat
    return ToolResult(" ".join([sat.strip(), *stores_told(world, r)]))


async def _leave_work(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    world.stop_work(r)
    return ToolResult(f"{world.stopped_told(r)} {hour_told(world)}")


async def _say(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    text = args["text"].strip()
    if not text:
        return ToolResult("You said nothing.")
    present = world.addressable(r)
    private = "to" in args
    if private:
        if not args["to"]:
            return ToolResult("Name the people you speak to, or leave out to.")
        company = {other.name: other for other in world.company(r)}
        recipients = []
        for name in dict.fromkeys(args["to"]):
            if name == r.name:
                return ToolResult("You cannot speak to yourself.")
            if name not in company:
                return ToolResult(f"{name} is not here.")
            if not company[name].awake:
                return ToolResult(f"{name} is asleep.")
            recipients.append(company[name])
    else:
        recipients = present
        if not recipients:
            return ToolResult("There is nobody here to hear you.")
    bystanders = [other for other in present if other not in recipients]
    heard = [other.name for other in recipients]
    unheard = {other.name for other in bystanders}
    # Speech by name draws its hearers into the conversation; a remark to everyone draws in
    # those not at work outside it, and the others hear it without stopping their work.
    drawn = [
        other
        for other in recipients
        if private or other.conversation is not None or not isinstance(other.base, Work)
    ]
    conversation = world.converse(r, drawn) if drawn or r.conversation else None

    def tell(w: str | None) -> str:
        speaker = cap(you(r.name, w))
        if w in unheard:
            return f"{speaker} said something to {listed(heard)} that you could not hear."
        if private:
            return f"{speaker} said to {listed([you(name, w) for name in heard])}: “{text}”"
        return f"{speaker} said: “{text}”"

    world.record(
        "speech",
        tell,
        actor=r,
        audience=[*recipients, *bystanders],
        interrupt=drawn,
        payload={
            "text": text,
            "to": heard,
            "private": private,
            "bystanders": sorted(unheard),
            "conversation": conversation.place if conversation else None,
            "members": sorted(conversation.members) if conversation else [],
        },
    )
    return ToolResult(tell(r.name))


def working_at(world: World, r: Resident, kind: str) -> str | ToolResult:
    """`r`, whose work is at the town's `kind` of workplace, sits down to work there unless it
    is at work already: what it is told of it, or the refusal of one elsewhere or exhausted."""
    place = world.config.workplace(kind)
    if r.place != place.id:
        return ToolResult(f"You can do that only at {place.name}.")
    sat = sit_down(world, r)
    if isinstance(sat, ToolResult) or not sat:
        return sat
    return f"{sat.strip()} "  # told on the line of what follows


async def _order(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    sat = working_at(world, r, "store")
    if isinstance(sat, ToolResult):
        return sat
    thing, quantity = world.config.item(args["item"]), args["quantity"]
    assert thing.wholesale is not None
    cost = thing.wholesale * quantity
    ordered, costs = amount(thing, quantity), world.config.money(cost)
    if refusal := world.cannot_pay(r, cost):
        return ToolResult(f"{sat}{refusal}")
    r.inventory.spend(cost, "paid", f"{ordered} from the supplier")
    arrives = world.delivery(calendar_day(world.clock.now()) + 1)
    world.store.order(thing.id, quantity, arrives)
    world.record(
        "order",
        lambda w: f"{cap(you(r.name, w))} ordered {ordered} from the supplier for {costs}.",
        actor=r,
        payload={
            "item": thing.id,
            "name": thing.name,
            "quantity": quantity,
            "amount": cost,
            "arrives": arrives,
        },
    )
    return ToolResult(
        f"{sat}You ordered {ordered} from the supplier for {costs}; it arrives tomorrow at "
        f"{clock_time(arrives)}. {world.purse(r)}"
    )


async def _set_price(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    item, price = args["item"], args["price"]
    business = BUSINESSES[world.config.place(r.occupation.workplace).kind]
    prices, place = business.prices(world), business.place(world.config)
    name, money = priced(world.config, item), world.config.money
    if item not in prices:
        return ToolResult(f"{cap(name)} is not {business.sells} {place.name}.")
    sat = working_at(world, r, business.kind)
    if isinstance(sat, ToolResult):
        return sat
    before, prices[item] = prices[item], price
    world.record(
        "price",
        lambda w: (
            f"{cap(you(r.name, w))} set the price of {bare(name)} at {place.name} to "
            f"{money(price)}."
        ),
        actor=r,
        payload={"item": item, "name": name, "place": place.id, "price": price, "before": before},
    )
    return ToolResult(
        f"{sat}The price of {bare(name)} is now {money(price)}; it was {money(before)}."
    )


async def _cook(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    sat = working_at(world, r, "restaurant")
    if isinstance(sat, ToolResult):
        return sat
    dish, portions = world.config.item(args["dish"]), args["portions"]
    larder, hands = world.holders[LARDER], r.inventory
    needed = {item: units * portions for item, units in dish.ingredients.items()}
    short = [
        f"{amount(world.config.item(item), need)}, of which the larder holds "
        f"{larder.units(item)} and you carry {hands.units(item)}"
        for item, need in needed.items()
        if larder.units(item) + hands.units(item) < need
    ]
    cooked = f"{counted(portions, 'portion')} of {bare(dish.name)}"
    if short:
        return ToolResult(f"{sat}For {cooked} you are short: it takes {listed(short)}.")
    # Out of the larder first, and out of the chef's hands what the larder is short of.
    carried = {item: need - larder.units(item) for item, need in needed.items()}
    carried = {item: units for item, units in carried.items() if units > 0}
    for item, need in needed.items():
        if stored := need - carried.get(item, 0):
            world.move(item, stored, LARDER, None)
        if item in carried:
            world.move(item, carried[item], r.name, None)
    world.move(dish.id, portions, None, COUNTER)
    world.record(
        "cook",
        lambda w: f"{cap(you(r.name, w))} cooked {cooked}.",
        actor=r,
        payload={
            "dish": dish.id,
            "name": dish.name,
            "portions": portions,
            "used": needed,
            "carried": carried,
        },
    )
    ready = world.holders[COUNTER].units(dish.id)
    return ToolResult(
        f"{sat}You cooked {cooked}; {ready} ready on the counter. {larder_told(world)} "
        f"{world.things_told(r)}"
    )


def _called(world: World, name: str) -> Resident | ToolResult:
    """The resident called `name`, or the refusal that the town has none."""
    other = world.residents.get(name)
    if other is None:
        return ToolResult(f"There is nobody called {name} in the town.")
    return other


def _patient(world: World, r: Resident, name: str) -> tuple[Resident, str] | ToolResult:
    """The patient `name` the doctor `r` sees, with what `r` is told of sitting down to work:
    at the Hospital, where `r` sits down to work and the patient must be (`r` itself among
    them); or at the bedside of `name`, too ill to get up, where `r` sits down to nothing.
    Otherwise the refusal."""
    patient, hospital = _called(world, name), SURGERY.place(world.config)
    if isinstance(patient, ToolResult):
        return patient
    if r.place != hospital.id:
        if patient in world.bedside(r):
            return patient, ""
        return ToolResult(
            f"You can do that at {hospital.name}, or at the bedside of one too ill to get up."
        )
    sat = working_at(world, r, SURGERY.kind)
    if isinstance(sat, ToolResult):
        return sat
    if patient is not r and (refusal := world.reach(r, name)):
        return ToolResult(f"{sat}{refusal}")
    return patient, sat


async def _examine(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    return _see(world, r, args["patient"], "examination")


async def _treat(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    return _see(world, r, args["patient"], "treatment")


def _see(world: World, r: Resident, name: str, service: str) -> ToolResult:
    """The doctor `r` sees the patient `name` for `service`: an examination tells both what
    shape the patient is in, in numbers (its own words to each); a treatment restores some of
    its health, ends its illness and gets it up from its bed. Nothing is charged: both are told
    the fee posted for it, and paying it is the patient's to do. Logged with that fee and the
    patient's numbers."""
    found = _patient(world, r, name)
    if isinstance(found, ToolResult):
        return found
    patient, sat = found
    fee = SURGERY.prices(world)[service]
    world.reckon(patient)
    living, money, restores = patient.living, world.config.money, world.config.hospital.restores
    examining = service == "examination"
    done = "examined" if examining else "treated"
    if examining:
        own, seen = world.body.examination(living), world.body.examination(living, patient.name)
        found_out, theirs = f" {own if patient is r else seen}", f" {own}"
        numbers: dict[str, Any] = {
            "satiety": round(living.satiety, 1),
            "energy": round(living.energy, 1),
            "health": round(living.health, 1),
            "ill": living.ill,
            "night": dict(living.night),
        }
    else:
        found_out = theirs = ""
        numbers = {
            "restores": restores,
            "before": round(living.health, 1),
            "health": round(min(100.0, living.health + restores), 1),
            "ill": living.ill,
            "bedridden": living.bedridden,
        }
    posted = f" The fee posted for {a_service(service)} is {money(fee)}."

    def told(w: str | None) -> str:
        if w == r.name:
            whom = "yourself" if patient is r else patient.name
            return f"You {done} {whom}.{posted}{found_out}"
        if w == patient.name:
            return f"{r.name} {done} you.{posted}{theirs}"
        return f"{r.name} {done} {patient.name}."

    world.record(
        service,
        told,
        actor=r,
        audience=[patient] if patient is not r else [],
        payload={"patient": patient.name, "fee": fee} | numbers,
    )
    if not examining:
        world.treat(patient, restores)
    return ToolResult(f"{sat}{told(r.name)}")


async def _announce(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    text = args["text"].strip()
    if not text:
        return ToolResult("You announced nothing.")
    sat = working_at(world, r, "hall")
    if isinstance(sat, ToolResult):
        return sat
    hall = world.config.workplace("hall")
    world.announcements.append([world.clock.now(), text])
    world.record(
        "announcement",
        lambda w: f"{cap(you(r.name, w))} announced at {hall.name}: “{text}”",
        actor=r,
        audience=[other for other in world.residents.values() if other is not r],
        payload={"text": text},
    )
    return ToolResult(
        f"{sat}You announced: “{text}” Everyone is told, and it stands on the board here."
    )


async def _grant(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    amount_, reason = args["amount"], args["reason"].strip()
    if not reason:
        return ToolResult("Give the reason for the grant.")
    other = _called(world, args["to"])
    if isinstance(other, ToolResult):
        return other
    sat = working_at(world, r, "hall")
    if isinstance(sat, ToolResult):
        return sat
    treasury, money = world.treasury, world.config.money
    if amount_ > treasury.balance:
        return ToolResult(f"{sat}The treasury holds only {money(treasury.balance)}.")
    treasury.pay("grant", amount_)
    other.inventory.receive(amount_, "granted", f"granted by {r.name}: “{reason}”")
    granted = f"{money(amount_)} from the treasury: “{reason}”"
    world.record(
        "grant",
        lambda w: f"{cap(you(r.name, w))} granted {you(other.name, w)} {granted}",
        actor=r,
        audience=[other] if other is not r else [],
        payload={
            "to": other.name,
            "amount": amount_,
            "reason": reason,
            "treasury": treasury.balance,
        },
    )
    return ToolResult(
        f"{sat}You granted {'yourself' if other is r else other.name} {granted} The treasury "
        f"holds {money(treasury.balance)}."
    )


async def _move_in(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    assert r.place is not None
    place = world.config.place(r.place)
    if place.kind != "home":
        return ToolResult("You can move into a home only when you are there.")
    if r.home == place.id:
        return ToolResult("You live here already.")
    assert place.rooms is not None
    if len(world.occupants(place.id)) >= place.rooms:
        return ToolResult(f"There is no free room at {place.name}.")
    return ToolResult(world.move_in(r, place.id))


async def _message(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    name, text = args["to"], args["text"].strip()
    writing = [item for item in world.config.items if item.effect == "messaging"]
    names = listed([bare(item.name) for item in writing], "or")
    if not any(r.inventory.units(item.id) for item in writing):
        return ToolResult(f"You have no {names}.")
    other = _called(world, name)
    if isinstance(other, ToolResult):
        return other
    if other is r:
        return ToolResult("You cannot write to yourself.")
    if not any(other.inventory.units(item.id) for item in writing):
        return ToolResult(f"{name} has no {names}.")
    if not text:
        return ToolResult("You wrote nothing.")

    def tell(w: str | None) -> str:
        return f"{cap(you(r.name, w))} wrote to {you(name, w)}: “{text}”"

    world.record("message", tell, actor=r, audience=[other], payload={"to": name, "text": text})
    return ToolResult(tell(r.name))


def _end(world: World, r: Resident, word: str) -> str | ToolResult:
    """The holder `r` names by `word` as where it takes from or gives to: a resident, by name;
    the shelves, the counter or the larder; or `here`, what is left at the place where `r` is.
    Or the refusal of a word that names none of them. Whether `r` reaches it is
    `World.transfer`'s to say."""
    assert r.place is not None
    name = word.strip()
    if name in world.residents:
        return name
    if name.lower() == HERE:
        return r.place
    if name.lower() in HOLDS:
        return name.lower()
    return ToolResult(
        f"There is nobody called {name} in the town. Name a person, {', '.join(HOLDS)} or {HERE}."
    )


def _carried(world: World, r: Resident, what: str) -> str:
    """What `r` now carries of the kind it has just taken or given: its purse, or its things."""
    return world.purse(r) if what == MONEY else world.things_told(r)


async def _take(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    source = _end(world, r, args["from"])
    if isinstance(source, ToolResult):
        return source
    if source == r.name:
        return ToolResult("You cannot take from yourself.")
    what, asked = args["what"], args.get("amount", 1)
    moved = world.transfer(r, what, asked, source, r.name)
    if isinstance(moved, str):
        return ToolResult(moved)
    money = world.config.money
    told = [moved.told if moved.amount == asked else f"{moved.told[:-1]}, all there was."]
    if moved.price is not None and moved.amount == 1:
        told.append(f"The price posted for it is {money(moved.price)}.")
    elif moved.price is not None:
        told.append(
            f"The price posted is {money(moved.price)} each, "
            f"{money(moved.price * moved.amount)} in all."
        )
    if moved.ate:
        told.append(f"You ate {listed(world.listing(moved.ate))} at once.")
    return ToolResult(" ".join([*told, _carried(world, r, what)]))


async def _give(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    target = _end(world, r, args["to"])
    if isinstance(target, ToolResult):
        return target
    if target == r.name:
        return ToolResult("You cannot give to yourself.")
    what = args["what"]
    moved = world.transfer(r, what, args.get("amount", 1), r.name, target)
    if isinstance(moved, str):
        return ToolResult(moved)
    return ToolResult(f"{moved.told} {_carried(world, r, what)}")


async def _use(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    thing = world.config.item(args["what"])
    world.reckon(r)  # what it would have eaten by now is eaten first
    if not r.inventory.units(thing.id):
        return ToolResult(f"You carry no {bare(thing.name)}.")
    before = world.body.bands(r.living)
    world.eat(r, thing.id)
    world.note_bands(r, before, tell=False)  # the result tells it
    eaten = world.body.told("satiety", r.living.satiety)
    return ToolResult(f"You ate {amount(thing, 1)}. {eaten} {world.things_told(r)}")


async def _leave_conversation(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    world.leave_conversation(r)
    back = " You are back at work." if isinstance(r.base, Work) else ""
    return ToolResult(f"You left the conversation.{back}")


async def _review_day(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    return ToolResult(world.review(r))


HANDLERS: dict[str, Handler] = {  # and the Office's, `world.office.HANDLERS`
    "help": _help,
    "look_around": _look_around,
    "how_am_i": _how_am_i,
    "inventory": _inventory,
    "go": _go,
    "wait": _wait,
    "sleep": _sleep,
    "start_work": _start_work,
    "cook": _cook,
    "order": _order,
    "set_price": _set_price,
    "examine": _examine,
    "treat": _treat,
    "announce": _announce,
    "grant": _grant,
    "leave_work": _leave_work,
    "say": _say,
    "take": _take,
    "give": _give,
    "use": _use,
    "move_in": _move_in,
    "message": _message,
    "leave_conversation": _leave_conversation,
    "review_day": _review_day,
}
