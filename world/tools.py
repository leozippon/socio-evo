"""The world's tools: the specs of every tool the town has, and the handlers of all but the
Office's (`world.office`).

`specs` builds the list once from the configuration (`message` only where something to write
with is sold), and `own` gives each occupation its declaration of them (the chef's `buy` can buy
for the kitchen, its `pass` hand over a dish ready to serve and its `eat` eat one); a resident's
runtime declares,
at each request, those of them its event offers at its place that are its own (`World.usable`).
`World.call` refuses a tool the resident's event does not offer, another occupation's work and
arguments that do not fit the spec (`check`); the handlers check the remaining conditions, each
refusal one line naming the condition, and act. Units of items change hands only through
`World.move`, which refuses what is out of reach or not held. The work of an occupation, done at
its workplace, sits the resident down to work there as `start_work` does (`sit_down`,
`working_at`): claiming, assigning or acting in a task's workspace, cooking, ordering, setting a
price, examining and treating, announcing and granting; the doctor at the
bedside of one too ill to get up examines and treats without sitting down to work. Whatever a
resident is paid for its work goes into its purse with the tax withheld (`World.earn`): what a
customer pays at the counter or for a dish (`_sell`), a patient's fee (`_charge`), a client's
payment (`world.office`).

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
    KITCHEN,
    STORE,
    SURGERY,
    Business,
    counter_told,
    kitchen_told,
    priced,
)
from world.clock import calendar_day, clock_time, parse_hour
from world.config import Item, TownConfig
from world.economy import LARDER, PORTIONS, SHELVES
from world.events import AT_HOME, EXHAUSTED, Work
from world.rules import MAX_WAIT_MINUTES, TOPICS
from world.telling import amount, bare, cap, counted, listed, you

if TYPE_CHECKING:
    from world.world import Resident, Tell, World


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


FOR_THE_KITCHEN = {
    "type": "boolean",
    "description": "true to buy what the kitchen cooks with for the kitchen; left out, you buy "
    "for yourself",
}
"""What the chef's `buy` takes beside what everyone's does."""
MONEY = "money"
"""What `pass` names money by, money being no item."""


def specs(config: TownConfig) -> list[ToolSpec]:
    office = config.workplace("office").name
    store, restaurant = config.workplace("store").name, config.workplace("restaurant").name
    hospital, hall = config.workplace("hospital").name, config.workplace("hall").name
    supplied = [item.id for item in config.supplied]
    dishes = [dish.id for dish in config.dishes]
    everything = [item.id for item in config.items]
    wholesale = listed([f"{bare(i.name)} {config.money(i.wholesale)}" for i in config.supplied])
    recipes = "; ".join(
        f"{dish.name} ({dish.id}) from "
        + listed([amount(config.item(item), units) for item, units in dish.ingredients.items()])
        for dish in config.dishes
    )
    writing = listed([bare(i.name) for i in config.items if i.effect == "messaging"], "or")
    patient = _text("the patient's name")

    def item(description: str, ids: list[str]) -> dict[str, Any]:
        return {"type": "string", "enum": ids, "description": description}

    units = _number("how many units, helpings or portions; 1 if left out", 1)
    return [
        spec("help", "Read more of how the town works, on one point; without one, what you can "
             f"ask about: {listed(list(TOPICS))}.",
             topic={"type": "string", "enum": list(TOPICS)}),
        spec("look_around", "See where you are, who is here and what each of them is doing, what "
             "is for sale here and what is left here for anyone to take."),
        spec("how_am_i", "Take stock of how you feel: how hungry, how tired and how well you are."),
        spec("inventory", "See what you have: your money, and each thing you keep, with how "
             "much is left of it and any daily charge on it."),
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
        spec("cook", f"Cook portions of a dish in the kitchen of {restaurant}, from what the "
             f"kitchen holds, a portion of each from its ingredients: {recipes}. What is not "
             "sold by midnight is gone.",
             ("dish", "portions"),
             dish={"type": "string", "enum": dishes, "description": "the dish's short name"},
             portions=_number("how many portions to cook", 1)),
        spec("order", f"Order for the shelves of {store} from the supplier outside the town. "
             "You pay the supplier at once, from your purse, and what you order arrives the next "
             f"morning. The supplier's price for a unit: {wholesale}.", ("item", "quantity"),
             item=item("its short name", supplied), quantity=_number("how many units", 1)),
        spec("set_price", f"Set the price of something you sell: what {store} sells, a dish "
             f"on the menu of {restaurant}, or the fee for an examination or a treatment at "
             f"{hospital}.", ("item", "price"),
             item=item("the short name of what is sold, the dish or the service",
                       [*supplied, *dishes, *FEES]),
             price=_number("the new price, for a unit, a portion of a dish or a service", 1)),
        spec("examine", f"Examine a patient at {hospital}, or at the bedside of one too ill to "
             "get up: you and the patient learn how hungry, tired and well the patient is, in "
             "numbers, whether ill, and why the patient's health moved last night. The patient "
             "pays the fee.",
             ("patient",), patient=patient),
        spec("treat", f"Treat a patient at {hospital}, or at the bedside of one too ill to get "
             "up: the treatment restores some of the patient's health, ends an illness and gets "
             "one in bed up again. The patient pays the fee.", ("patient",), patient=patient),
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
        spec("buy", f"Buy something where you are and pay for it in cash at once: at {store} "
             f"from the counter, at {restaurant} a dish, which you eat there and then. Food you "
             "keep you eat a helping at a time whenever you could eat; a thing you keep is yours "
             "from then on. What is for sale, and at what price, you see there.", ("item",),
             item=item("its short name, or the dish's", [*supplied, *dishes]),
             units=_number("how many units or helpings; one thing you keep, or one dish (1 if "
                           "left out)", 1)),
        spec("get", "Take something left here for anyone to take, as you see when you look "
             "around. What a shop or a kitchen keeps is not left about: it is bought.",
             ("item",), item=item("its short name", everything), units=units),
        spec("put", "Leave something of yours here, for anyone to take.", ("item",),
             item=item("its short name", everything), units=units),
        spec("pass", "Hand something of yours to someone here: money, a thing you own (with any "
             "daily charge on it) or food you keep, as a gift or on terms you agree between you.",
             ("item", "to"), item=item("money, or the short name of the thing or the food",
                                       [MONEY, *everything]),
             units=_number("how much money, or how many units or helpings; 1 if left out", 1),
             to=_text("their name")),
        spec("eat", "Eat a helping of food you keep, now. You also eat it by yourself whenever "
             "you could eat.", ("item",),
             item=item("its short name", [i.id for i in config.items if i.ready])),
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


def own(specs: list[ToolSpec], occupation: str) -> list[ToolSpec]:
    """`specs` as a resident of `occupation` has them: the chef's `buy` can buy for the
    kitchen, its `pass` hand over a dish ready to serve, to anyone there or itself, and its
    `eat` eat one."""
    if not KITCHEN.keeps(occupation):
        return specs

    def chef(s: ToolSpec) -> ToolSpec:
        if s.name == "buy":
            properties = s.parameters["properties"] | {"for_the_kitchen": FOR_THE_KITCHEN}
            more = (
                " With for_the_kitchen, what the kitchen cooks with that you buy at the counter "
                "goes to the kitchen."
            )
            return ToolSpec(s.name, s.description + more, s.parameters | {"properties": properties})
        if s.name == "pass":
            more = (
                " At work in the kitchen, you can also hand anyone here, yourself included, a "
                "dish ready to serve, which they eat there and then, and nobody pays."
            )
            return ToolSpec(s.name, s.description + more, s.parameters)
        if s.name == "eat":
            more = " At work in the kitchen, you can also eat a dish ready to serve; nobody pays."
            return ToolSpec(s.name, s.description + more, s.parameters)
        return s

    return [chef(s) for s in specs]


def check(spec: ToolSpec, args: dict[str, Any]) -> str | None:
    """Why `args` do not fit `spec`, in one line, or None."""
    properties = spec.parameters["properties"]
    for key in args:
        if key not in properties:
            return f"{spec.name} takes no {key}."
    for key in spec.parameters["required"]:
        if key not in args:
            return f"{spec.name} needs {key}."
    for key, value in args.items():
        kind = properties[key]["type"]
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
    return None


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
    journal = args.get("journal", "").strip() or None
    day = world.lived_day()
    if journal is not None:
        date = world.config.start_date + timedelta(days=day - 1)
        path = r.agent_dir / "memory" / "journal" / f"{date.isoformat()}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = ("\n" if path.exists() else "") + journal + "\n"  # a later bedtime adds an entry
        with path.open("a", encoding="utf-8") as file:
            file.write(entry)
    return ToolResult(world.go_to_bed(r, hour, journal, day), ends_turn=True)


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
    business = BUSINESSES.get(world.config.place(r.place).kind)
    opened = [business.opened] if business is not None else []
    return ToolResult(" ".join([sat.strip(), *opened, *counter_told(world, r)]))


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


async def _buy(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    units = args.get("units", 1)
    if world.config.item(args["item"]).dish:
        return _buy_dish(world, r, args["item"], units)
    return _buy_at_counter(world, r, args["item"], units, args.get("for_the_kitchen", False))


def _buy_at_counter(
    world: World, r: Resident, item: str, units: int, kitchen: bool = False
) -> ToolResult:
    """`r` buys `units` of `item` at the Store's counter, for itself or, the chef buying
    `for_the_kitchen`, for the kitchen: the units go off the shelves to `r`, or are sent to the
    kitchen's larder, and the price from `r`'s purse to the shopkeeper's (`_sell`); the
    shopkeeper takes what she buys from her own shelves for nothing."""
    thing, store = world.config.item(item), STORE.place(world.config)
    if r.place != store.id:
        return ToolResult(f"You can buy {thing.name} at {store.name}, not here.")
    seller = STORE.serving(world)
    if seller is None:
        return ToolResult(STORE.closed_told(world.config))
    if kitchen and not any(thing.id in dish.ingredients for dish in world.config.dishes):
        return ToolResult(f"{cap(thing.name)} is nothing the kitchen cooks with.")
    total = STORE.prices(world)[thing.id] * units
    bought, for_whom = amount(thing, units), " for the kitchen" if kitchen else ""
    cost = world.config.money(total)

    def tell(w: str | None) -> str:
        if seller is r:
            return f"{cap(you(r.name, w))} took {bought} from the shelves."
        return f"{cap(you(r.name, w))} bought {bought}{for_whom} for {cost}."

    refusal = _sell(
        world,
        r,
        STORE,
        seller,
        thing,
        units,
        total,
        source=SHELVES,
        target=LARDER if kitchen else r.name,
        tell=tell,
        for_the_kitchen=kitchen,
    )
    if refusal:
        return ToolResult(refusal)
    if kitchen:
        return ToolResult(f"{tell(r.name)} {kitchen_told(world)} {world.purse(r)}")
    return ToolResult(f"{tell(r.name)} {world.things_told(r)} {world.purse(r)}")


def _buy_dish(world: World, r: Resident, item: str, units: int) -> ToolResult:
    """`r` buys a portion of the dish `item` in the Restaurant while its chef is at work there,
    and eats it at once: it goes from the kitchen's portions to `r` and is eaten, and the price
    from `r`'s purse to the chef's (`_sell`)."""
    dish, restaurant = world.config.item(item), KITCHEN.place(world.config)
    if r.place != restaurant.id:
        return ToolResult(f"You can have {dish.name} at {restaurant.name}, not here.")
    chef = KITCHEN.serving(world)
    if chef is None:
        return ToolResult(KITCHEN.closed_told(world.config))
    if KITCHEN.keeps(r.occupation.id):
        return ToolResult("You cook the dishes here and do not buy them; you eat one with eat.")
    if units != 1:
        return ToolResult("One dish at a time.")
    price = KITCHEN.prices(world)[dish.id]
    cost = world.config.money(price)
    refusal = _sell(
        world,
        r,
        KITCHEN,
        chef,
        dish,
        1,
        price,
        source=PORTIONS,
        target=r.name,
        tell=lambda w: f"{cap(you(chef.name, w))} served {you(r.name, w)} {dish.name} for {cost}.",
    )
    if refusal:
        return ToolResult(refusal)
    eaten = world.body.told("satiety", r.living.satiety)
    return ToolResult(f"You had {dish.name} for {cost}. {eaten} {world.purse(r)}")


def _sell(
    world: World,
    r: Resident,
    business: Business,
    seller: Resident,
    thing: Item,
    units: int,
    total: int,
    *,
    source: str,
    target: str,
    tell: Tell,
    for_the_kitchen: bool = False,
) -> str | None:
    """`r` buys `units` of `thing` for `total` from `business`, served by `seller`: paid in cash
    from `r`'s purse into the seller's, the tax withheld (`World.earn`), unless `r` serves
    itself, which costs nothing; the units moved from the business's holder `source` to
    `target`; the purchase logged as a `move`, told as `tell` to the seller, with the tax; a dish
    eaten at once, and anything else bought for itself taken in by the hungry. Returns the
    refusal, nothing bought, or None."""
    price = 0 if seller is r else total
    if refusal := world.cannot_pay(r, price):
        return refusal
    world.reckon(r)
    if refusal := world.move(thing.id, units, source, target, by=None if for_the_kitchen else r):
        return refusal
    tax = 0
    if price:
        bought = amount(thing, units) + (" for the kitchen" if for_the_kitchen else "")
        r.inventory.spend(price, "bought", bought)
        tax = world.earn(seller, price, business.takings)
    withheld = f", of which {world.config.money(tax)} in tax." if tax else "."

    def told(w: str | None) -> str:
        return tell(w)[:-1] + withheld if w == seller.name else tell(w)

    world.record_move(
        "buy",
        told,
        by=r,
        audience=[seller] if seller is not r else [],
        item=thing.id,
        units=units,
        source=source,
        target=target,
        money=price,
        seller=seller.name,
        tax=tax,
    )
    if thing.dish:  # a dish is eaten where it is served
        world.eat_now(r, thing.id)
    elif not for_the_kitchen:  # the purchase is on record before a hungry buyer eats from it
        world.take_in(r)
    return None


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
    larder = world.holders[LARDER]
    needed = {item: units * portions for item, units in dish.ingredients.items()}
    short = [
        f"{amount(world.config.item(item), need)}, of which it holds {larder.units(item)}"
        for item, need in needed.items()
        if larder.units(item) < need
    ]
    cooked = f"{counted(portions, 'portion')} of {bare(dish.name)}"
    if short:
        return ToolResult(f"{sat}For {cooked} the kitchen is short: it needs {listed(short)}.")
    for item, need in needed.items():
        world.moved(world.move(item, need, LARDER, None, by=r))
    world.moved(world.move(dish.id, portions, None, PORTIONS, by=r))
    world.record(
        "cook",
        lambda w: f"{cap(you(r.name, w))} cooked {cooked}.",
        actor=r,
        payload={"dish": dish.id, "name": dish.name, "portions": portions, "used": needed},
    )
    ready = world.holders[PORTIONS].units(dish.id)
    return ToolResult(f"{sat}You cooked {cooked}; {ready} ready to serve. {kitchen_told(world)}")


def _called(world: World, name: str) -> Resident | ToolResult:
    """The resident called `name`, or the refusal that the town has none."""
    other = world.residents.get(name)
    if other is None:
        return ToolResult(f"There is nobody called {name} in the town.")
    return other


def _patient(world: World, r: Resident, name: str) -> tuple[Resident, str] | ToolResult:
    """The patient `name` the doctor `r` sees, with what `r` is told of sitting down to work:
    at the Hospital, where `r` sits down to work and the patient, awake, must be (`r` itself
    among them); or at the bedside of `name`, too ill to get up, where `r` sits down to nothing.
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
    if refusal := world.reach(r, name):
        return ToolResult(f"{sat}{refusal}")
    return patient, sat


def _charge(
    world: World, doctor: Resident, patient: Resident, service: str
) -> tuple[int, int] | str:
    """`patient` pays the fee of `service` (`examination` or `treatment`) from its purse into
    the `doctor`'s, the tax withheld (`World.earn`), unless it is the doctor, who pays nothing:
    the fee and the tax; or, in the doctor's words, why it cannot pay."""
    fee = 0 if patient is doctor else SURGERY.prices(world)[service]
    if fee > patient.inventory.money:
        return f"{patient.name} does not have the {world.config.money(fee)} the {service} costs."
    tax = 0
    if fee:
        patient.inventory.spend(
            fee, "paid", f"an {service}" if service[0] in "aeiou" else f"a {service}"
        )
        tax = world.earn(doctor, fee, SURGERY.takings)
    return fee, tax


async def _examine(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    return _see(world, r, args["patient"], "examination")


async def _treat(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    return _see(world, r, args["patient"], "treatment")


def _see(world: World, r: Resident, name: str, service: str) -> ToolResult:
    """The doctor `r` sees the patient `name` for `service`, which the patient pays for: an
    examination tells both what shape the patient is in, in numbers (its own words to each); a
    treatment restores some of its health, ends its illness and gets it up from its bed. Logged
    with the fee, the tax withheld from it and the patient's numbers."""
    found = _patient(world, r, name)
    if isinstance(found, ToolResult):
        return found
    patient, sat = found
    charged = _charge(world, r, patient, service)
    if isinstance(charged, str):
        return ToolResult(f"{sat}{charged}")
    fee, tax = charged
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
    cost = f" for {money(fee)}" if fee else ""
    withheld = f", of which {money(tax)} in tax" if tax else ""

    def told(w: str | None) -> str:
        if w == r.name:
            whom = "yourself" if patient is r else patient.name
            return f"You {done} {whom}{cost}{withheld}.{found_out}"
        if w == patient.name:
            return f"{r.name} {done} you{cost}.{theirs}"
        return f"{r.name} {done} {patient.name}{cost}."

    world.record(
        service,
        told,
        actor=r,
        audience=[patient] if patient is not r else [],
        payload={"patient": patient.name, "fee": fee, "tax": tax} | numbers,
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


async def _get(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    assert r.place is not None
    thing, units, place = world.config.item(args["item"]), args.get("units", 1), r.place
    got, where = amount(thing, units), world.config.place(place).name
    if refusal := world.hand(
        r,
        "get",
        thing,
        units,
        place,
        r.name,
        lambda w: f"{cap(you(r.name, w))} took {got} that was left at {where}.",
        audience=world.addressable(r),
    ):
        return ToolResult(refusal)
    return ToolResult(f"You took {got}. {world.things_told(r)}")


async def _put(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    assert r.place is not None
    thing, units, place = world.config.item(args["item"]), args.get("units", 1), r.place
    left, where = amount(thing, units), world.config.place(place).name
    if refusal := world.hand(
        r,
        "put",
        thing,
        units,
        r.name,
        place,
        lambda w: f"{cap(you(r.name, w))} left {left} at {where}, for anyone to take.",
        audience=world.addressable(r),
    ):
        return ToolResult(refusal)
    return ToolResult(f"You left {left} here, for anyone to take. {world.things_told(r)}")


async def _pass(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    name, units = args["to"], args.get("units", 1)
    other = _called(world, name)
    if isinstance(other, ToolResult):
        return other
    thing = None if args["item"] == MONEY else world.config.item(args["item"])
    serving = thing is not None and thing.dish and KITCHEN.serving(world) is r  # unpaid
    if other is r:
        if thing is not None and serving:  # the chef's own, from the kitchen
            return _own_dish(world, r, thing, units)
        return ToolResult("You cannot pass anything to yourself.")
    if refusal := world.reach(r, name):
        return ToolResult(refusal)
    if thing is None:
        if refusal := world.cannot_pay(r, units):
            return ToolResult(refusal)
        r.inventory.spend(units, "gave", name)
        other.inventory.receive(units, "received", r.name)
        given = world.config.money(units)
        world.record_move(
            "pass",
            lambda w: f"{cap(you(r.name, w))} passed {you(name, w)} {given}.",
            by=r,
            audience=[other],
            source=r.name,
            target=name,
            money=units,
        )
        return ToolResult(f"You passed {name} {given}. {world.purse(r)}")
    given = amount(thing, units)

    def told(w: str | None) -> str:
        if serving:
            return f"{cap(you(r.name, w))} served {you(name, w)} {given}, which nobody paid for."
        return f"{cap(you(r.name, w))} passed {you(name, w)} {given}."

    source = PORTIONS if serving else r.name
    if refusal := world.hand(r, "pass", thing, units, source, name, told, audience=[other]):
        return ToolResult(refusal)
    if serving:
        return ToolResult(f"You served {name} {given}, which nobody paid for.")
    return ToolResult(f"You passed {name} {given}. {world.things_told(r)}")


async def _eat(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    thing = world.config.item(args["item"])
    if thing.dish and KITCHEN.serving(world) is r:
        return _own_dish(world, r, thing, 1)
    world.reckon(r)  # what it would have eaten by now is eaten first
    if not r.inventory.units(thing.id):
        return ToolResult(f"You have no {bare(thing.name)}.")
    world.eat_now(r, thing.id)
    eaten = world.body.told("satiety", r.living.satiety)
    return ToolResult(f"You ate {amount(thing, 1)}. {eaten} {world.things_told(r)}")


def _own_dish(world: World, r: Resident, dish: Item, units: int) -> ToolResult:
    """The chef `r`, at work in the kitchen, has `units` of `dish` from the portions itself, as
    it hands one to anyone there: passed to itself unpaid, logged as such, and eaten there and
    then. Told to nobody else."""
    had = amount(dish, units)

    def told(w: str | None) -> str:
        return f"{cap(you(r.name, w))} had {had} from the kitchen, which nobody paid for."

    if refusal := world.hand(r, "pass", dish, units, PORTIONS, r.name, told, audience=[]):
        return ToolResult(refusal)
    return ToolResult(f"{told(r.name)} {world.body.told('satiety', r.living.satiety)}")


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
    "buy": _buy,
    "get": _get,
    "put": _put,
    "pass": _pass,
    "eat": _eat,
    "move_in": _move_in,
    "message": _message,
    "leave_conversation": _leave_conversation,
    "review_day": _review_day,
}
