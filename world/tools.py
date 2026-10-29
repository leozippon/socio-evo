"""The world's tools: the specs of every tool the town has, and their handlers.

`specs` builds the list once from the configuration (`message` only where something to write
with is sold), and `own` gives each occupation its declaration of them (the chef's `buy` can buy
for the kitchen, and its `pass` hand over a dish ready to serve); a resident's runtime declares,
at each request, those of them its event offers at its place that are its own (`World.usable`).
`World.call` refuses a tool the resident's event does not offer, another occupation's work and
arguments that do not fit the spec; the handlers here check the remaining conditions, each
refusal one line naming the condition, and act. Units of items change hands only through
`World.move`, which refuses what is out of reach or not held. The
work of an occupation, done at its workplace, sits the resident down to work there as
`start_work` does: claiming, assigning or acting in a task's workspace, cooking, ordering,
setting a price, examining and treating, reading the report and announcing; the doctor at the
bedside of one too ill to get up examines and treats without sitting down to work. Outputs of
shell commands and repository files
are passed through whole (a file in part when the resident asks for some of its lines); the
runtime truncates what enters its context.

The tools that act in a task's workspace (`WORKSPACE_SPECS`) are declared and answered here
for the town and for the work-only port of `world.solo` alike: what they do in a workspace and
tell of it is `told_command`, `read_repo`, `write_repo` and `edit_repo`, and the town's handlers
add the claim they need and the log entry. A command stopped by its limit of real time, which the
town's clock outruns, is told in the town as having run too long, with the hour.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from agent.port import ToolResult, ToolSpec
from world.backend import ExecResult, Workspace
from world.board import Claim, failure
from world.clock import DAY, calendar_day, clock_time, parse_hour, tell_date
from world.config import TownConfig
from world.economy import LARDER, PORTIONS, SHELVES, add
from world.events import AT_HOME, EXHAUSTED, Work
from world.rules import MAX_WAIT_MINUTES, TOPICS, amount, bare
from world.telling import cap, counted, listed, you

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
# What acts in a task's workspace, in declared order; `world.solo` declares these too.


FEES = ("examination", "treatment")
"""The Hospital's services, each with its fee, which `set_price` sets."""
FOR_THE_KITCHEN = {
    "type": "boolean",
    "description": "true to buy for the kitchen, which the fund pays; left out, you buy for "
    "yourself",
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
    money = config.currency
    wholesale = listed([f"{bare(i.name)} {money}{i.wholesale}" for i in config.supplied])
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
             "go elsewhere, you are at work, and your time at work at your own place of work is "
             "paid by the hour."),
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
             "The fund pays the supplier at once, if it can, and what you order arrives the next "
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
        spec("report", f"Read the town's report at {hall}: the fund, the work at each place of "
             "work, and how each resident is doing."),
        spec("announce", f"Announce something at {hall}: every resident is told it, at once or "
             "on waking, and it stays on the board there.", ("text",),
             text=_text("what you announce")),
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
    kitchen, and its `pass` hand over a dish ready to serve."""
    if occupation != "chef":
        return specs

    def chef(s: ToolSpec) -> ToolSpec:
        if s.name == "buy":
            properties = s.parameters["properties"] | {"for_the_kitchen": FOR_THE_KITCHEN}
            more = " With for_the_kitchen, what you buy at the counter goes to the kitchen, and "
            return ToolSpec(
                s.name,
                s.description + more + "the fund pays.",
                s.parameters | {"properties": properties},
            )
        if s.name == "pass":
            more = (
                " At work in the kitchen, you can also hand anyone here a dish ready to serve, "
                "which they eat there and then, and nobody pays."
            )
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


def told_command(result: ExecResult, stopped: str) -> str:
    """What `shell` tells of a command's outcome: its outputs whole, then its exit code, or
    `stopped`, which tells that it ran too long and was stopped."""
    parts = [result.stdout.rstrip("\n")] if result.stdout else []
    if result.stderr:
        parts.append("stderr:\n" + result.stderr.rstrip("\n"))
    if result.timed_out:
        parts.append(stopped)
    else:
        parts.append(f"Exit code {result.exit_code}.")
    return "\n".join(parts)


async def read_repo(workspace: Workspace, args: dict[str, Any]) -> tuple[str, bool]:
    """What `read_repo_file` with `args` tells in `workspace`, and whether the file was read:
    the whole file, or, given `offset` (the first line, from 1) or `limit` (how many lines),
    those lines as the resident's own `read_file` gives them."""
    path = args["path"]
    try:
        content = await workspace.read_file(path)
    except OSError as error:
        return f"You could not read {path}: {error}", False
    offset, limit = args.get("offset"), args.get("limit")
    if offset is None and limit is None:
        return content or f"{path} is empty.", True
    lines = content.splitlines(keepends=True)
    first = offset or 1
    if first > len(lines):
        return f"{path} has {counted(len(lines), 'line')}; there is no line {first}.", True
    chosen = lines[first - 1 : None if limit is None else first - 1 + limit]
    last = first + len(chosen) - 1
    return f"Lines {first} to {last} of {len(lines)} in {path}:\n\n{''.join(chosen)}", True


async def write_repo(workspace: Workspace, args: dict[str, Any]) -> tuple[str, bool]:
    """What `write_repo_file` with `args` tells in `workspace`, and whether the file was
    written."""
    path, content = args["path"], args["content"]
    try:
        await workspace.write_file(path, content)
    except OSError as error:
        return f"You could not write {path}: {error}", False
    return f"You wrote {path} ({counted(len(content), 'character')}).", True


async def edit_repo(workspace: Workspace, args: dict[str, Any]) -> tuple[str, bool]:
    """What `edit_repo_file` with `args` tells in `workspace`, and whether the file was
    changed: the passage `old_text`, which must appear exactly once, replaced by `new_text`,
    as the resident's own `edit_file` does."""
    path, old, new = args["path"], args["old_text"], args["new_text"]
    try:
        content = await workspace.read_file(path)
        count = content.count(old) if old else 0
        if count == 0:
            return f"The passage to replace does not appear in {path}.", False
        if count > 1:
            return (
                f"The passage to replace appears {count} times in {path}; include more of the "
                "text around it so that it appears once.",
                False,
            )
        await workspace.write_file(path, content.replace(old, new, 1))
    except OSError as error:
        return f"You could not change {path}: {error}", False
    return f"You changed {path}.", True


Handler = Callable[["World", "Resident", dict[str, Any]], Awaitable[ToolResult]]


def _now(world: World) -> str:
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


def _sit_down(world: World, r: Resident) -> str | ToolResult:
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
    return f"You sat down to work. {_now(world)}\n"


OPENED = {
    "store": "The counter is open.",
    "restaurant": "The kitchen is open.",
    "hospital": "The surgery is open.",
}
"""What sitting down to work at a place opens to others."""


async def _start_work(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    if r.place != r.occupation.workplace:
        return ToolResult(f"Your work is at {world.config.place(r.occupation.workplace).name}.")
    sat = _sit_down(world, r)
    if isinstance(sat, ToolResult):
        return sat
    then = OPENED.get(world.config.place(r.place).kind, "")
    return ToolResult(" ".join([sat.strip(), *([then] if then else []), *world.counter_told(r)]))


async def _view_board(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    office = world.config.workplace("office")
    if r.place != office.id:  # the board hangs there, for whoever is there to read
        return ToolResult(f"You are not at {office.name}.")
    start = world.config.start_date
    return ToolResult(world.board.text(r.name, lambda day: tell_date(day, start)))


async def _read_task(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    office, number, board = world.config.workplace("office"), args["task"], world.board
    if r.place != office.id:  # the board hangs there, for whoever is there to read
        return ToolResult(f"You are not at {office.name}.")
    if number not in board.open:
        return ToolResult(f"There is no task {number} on the board.")
    task = board.task(number)
    return ToolResult(f"The problem of task {number}, in {task.repo}:\n\n{task.problem_statement}")


async def _claim_task(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    office, number, board = world.config.workplace("office"), args["task"], world.board
    if r.place != office.id:
        return ToolResult(f"The board is at {office.name}; you can claim a task only there.")
    refusal = board.claim_refusal(r.name, number)
    if refusal:
        return ToolResult(refusal)
    sat = _sit_down(world, r)
    if isinstance(sat, ToolResult):
        return sat
    await board.claim(r.name, number)
    task = board.task(number)
    world.record(
        "claim",
        lambda w: f"{cap(you(r.name, w))} claimed task {number} ({task.repo}).",
        actor=r,
        payload={"task": number, "instance_id": task.instance_id},
    )
    sat = "sat down to work and " if sat else ""
    return ToolResult(
        f"You {sat}claimed task {number}, in {task.repo}; your workspace is ready. "
        f"{_now(world)} The problem:\n\n{task.problem_statement}"
    )


async def _assign(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    number, name, board = args["task"], args["to"], world.board
    sat = _working_at(world, r, "office")
    if isinstance(sat, ToolResult):
        return sat
    other = world.residents.get(name)
    if other is None or other.occupation.id != "programmer":
        return ToolResult(f"{sat}{name} is not one of the programmers.")
    if number not in board.open:
        return ToolResult(f"{sat}There is no task {number} on the board.")
    before = board.holder(number)
    if before == name:
        return ToolResult(f"{sat}{name} holds task {number} already.")
    if name in board.claims:
        return ToolResult(f"{sat}{name} holds task {board.claims[name].task} already.")
    board.give(name, number)
    task = board.task(number)
    moved = [world.residents[before]] if before is not None else []

    def told(w: str | None) -> str:
        held = "" if before is None else f", which {you(before, w)} held,"
        given = f"{cap(you(r.name, w))} gave task {number} ({task.repo}){held} to {you(name, w)}"
        gone = before is not None and w == before
        return f"{given}; your changes to it are gone." if gone else f"{given}."

    world.record(
        "assign",
        told,
        actor=r,
        audience=[other, *moved],
        payload={"task": number, "to": name, "from": before},
    )
    return ToolResult(f"{sat}{told(r.name)}")


NO_TASK = "You hold no task; claim one from the board first."


async def _workspace(world: World, r: Resident) -> tuple[Claim, Workspace, str] | ToolResult:
    """The task `r` holds and its workspace, reopened if the night closed it, with `r` sat down
    to work if it was not, and what it is told of sitting down, or nothing. The work is done
    at the office, where the machines are."""
    claim = world.board.claims.get(r.name)
    if claim is None:
        return ToolResult(NO_TASK)
    office = world.config.workplace("office")
    if r.place != office.id:
        return ToolResult(f"You can work on task {claim.task} only at {office.name}.")
    sat = _sit_down(world, r)
    if isinstance(sat, ToolResult):
        return sat
    workspace = await world.board.workspace(r.name, claim)
    if world.board.claims.get(r.name) is not claim:  # the claim ran out while it opened
        return ToolResult(f"{sat}{NO_TASK}")
    return claim, workspace, sat


async def _shell(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    held = await _workspace(world, r)
    if isinstance(held, ToolResult):
        return held
    claim, workspace, sat = held
    number = claim.task
    result = await workspace.exec(args["command"], world.config.work.shell_timeout_s)
    command = args["command"]
    world.record(
        "command",
        lambda w: (
            f"{cap(you(r.name, w))} ran a command for task {number}: "
            f"{command[:200]} (exit code {result.exit_code})."
        ),
        actor=r,
        payload={
            "task": number,
            "command": command,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "output_tail": (result.stdout + result.stderr)[-1000:],
        },
    )
    # The limit is of real time, which the town's clock outruns: told in the town's hours.
    return ToolResult(
        sat + told_command(result, f"The command ran too long and was stopped. {_now(world)}")
    )


async def _read_repo_file(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    held = await _workspace(world, r)
    if isinstance(held, ToolResult):
        return held
    claim, workspace, sat = held
    number, path = claim.task, args["path"]
    told, ok = await read_repo(workspace, args)
    world.record(
        "file_read",
        lambda w: f"{cap(you(r.name, w))} read {path} for task {number}.",
        actor=r,
        payload={"task": number, "path": path, "ok": ok},
    )
    return ToolResult(sat + told)


async def _write_repo_file(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    held = await _workspace(world, r)
    if isinstance(held, ToolResult):
        return held
    claim, workspace, sat = held
    number, path = claim.task, args["path"]
    told, ok = await write_repo(workspace, args)
    world.record(
        "file_write",
        lambda w: f"{cap(you(r.name, w))} wrote {path} for task {number}.",
        actor=r,
        payload={"task": number, "path": path, "characters": len(args["content"]), "ok": ok},
    )
    return ToolResult(sat + told)


async def _edit_repo_file(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    held = await _workspace(world, r)
    if isinstance(held, ToolResult):
        return held
    claim, workspace, sat = held
    number, path = claim.task, args["path"]
    told, ok = await edit_repo(workspace, args)
    world.record(
        "file_write",
        lambda w: f"{cap(you(r.name, w))} changed {path} for task {number}.",
        actor=r,
        payload={"task": number, "path": path, "edit": True, "ok": ok},
    )
    return ToolResult(sat + told)


async def _submit(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    held = await _workspace(world, r)
    if isinstance(held, ToolResult):
        return held
    claim, workspace, sat = held
    result = await _hand_in(world, r, claim, workspace)
    return ToolResult(sat + result.text, result.ends_turn)


async def _hand_in(world: World, r: Resident, claim: Claim, workspace: Workspace) -> ToolResult:
    """`r` hands in the task it holds, `claim`, from `workspace`: what `submit` tells."""
    board = world.board
    number = claim.task
    if board.runs_left(r.name, number) <= 0:
        return ToolResult(
            f"You have handed in task {number} {counted(world.config.work.acceptance_runs, 'time')}"
            " today, as often as a day allows; you can hand it in again tomorrow."
        )
    patch = await workspace.diff()
    if not patch.strip():
        return ToolResult("Your workspace has no changes to hand in.")
    task = board.task(number)
    world.record(
        "submission",
        lambda w: f"{cap(you(r.name, w))} handed in task {number}.",
        actor=r,
        payload={"task": number, "patch": patch},
    )
    verdict = await board.backend.accept(task, patch, world.config.work.acceptance_timeout_s)
    if verdict.status != "error":  # checks that could not be run use up no hand-in
        board.count_run(r.name, number)
    left = board.runs_left(r.name, number)
    holds = board.claims.get(r.name) is claim  # withdrawn or moved while the checks ran?
    world.record(
        "verdict",
        lambda w: (
            f"Task {number}, handed in by {you(r.name, w)}, was "
            + ("accepted." if verdict.resolved else f"not accepted: {failure(verdict)}.")
        ),
        actor=r,
        payload={
            "task": number,
            "status": verdict.status,
            "resolved": verdict.resolved,
            "fail_to_pass": list(verdict.fail_to_pass),
            "pass_to_pass": list(verdict.pass_to_pass),
            "held": holds,
        },
    )
    if not holds:  # withdrawn or given to another while the checks ran: nobody is paid for it
        told = "Accepted" if verdict.resolved else f"Not accepted: {failure(verdict)}"
        unpaid = ", so you are not paid for it" if verdict.resolved else ""
        return ToolResult(
            f"{told}. Task {number} was no longer yours by the time the checks finished"
            f"{unpaid}. {_now(world)}"
        )
    if not verdict.resolved:
        again = (
            f"You can hand in task {number} {counted(left, 'more time')} today."
            if left > 0
            else f"You cannot hand in task {number} again today."
        )
        if verdict.status == "error":
            told = f"{cap(failure(verdict))}, so this hand-in does not count."
        else:
            told = f"Not accepted: {failure(verdict)}."
        return ToolResult(f"{told} {again} {_now(world)}")
    finished = board.finish(r.name)
    if finished is not None:
        await finished.close()
    world.daybook.today["accepted"].append([r.name, number])
    world.fund.take("client", world.config.work.payment)
    sum_ = world.config.occupation("programmer").per_service  # the leader's own tasks too
    paid = world.pay_service(r, "task", f"task {number}", due=sum_, task=number)
    for leader in world.of_occupation("team-leader"):
        if leader is not r:
            about = f"task {number}, which {r.name} handed in"
            world.pay_service(leader, "team", about, task=number, tell=True)
    told = ("Accepted.", paid, world.purse(r), _now(world))
    return ToolResult(" ".join(part for part in told if part))


async def _abandon_task(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    board = world.board
    claim = board.claims.get(r.name)
    if claim is None:
        return ToolResult("You hold no task.")
    workspace = board.drop(r.name)
    if workspace is not None:
        await workspace.close()
    world.record(
        "abandon",
        lambda w: f"{cap(you(r.name, w))} gave up task {claim.task}.",
        actor=r,
        payload={"task": claim.task},
    )
    return ToolResult(f"You gave up task {claim.task}; its changes are gone. {_now(world)}")


async def _leave_work(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    world.stop_work(r)
    claim = world.board.claims.get(r.name)
    held = f" You still hold task {claim.task}." if claim else ""
    return ToolResult(f"You stopped work.{held} {_now(world)}")


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
            "conversation": conversation.room if conversation else None,
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
    kitchen's larder, and the price to the fund, from `r`'s purse or the fund's own for the
    kitchen; the shopkeeper is paid its sum."""
    thing, store = world.config.item(item), world.config.workplace("store")
    if r.place != store.id:
        return ToolResult(f"You can buy {thing.name} at {store.name}, not here.")
    seller = world.serving("store")
    if seller is None:
        return ToolResult(f"{cap(store.name)} is closed: nobody is at the counter.")
    if kitchen and thing.effect != "food":
        return ToolResult(f"{cap(thing.name)} is nothing the kitchen cooks with.")
    price = world.store.prices[thing.id]
    total = price * units
    if not kitchen and (refusal := world.cannot_pay(r, total)):
        return ToolResult(refusal)
    world.reckon(r)
    target = LARDER if kitchen else r.name
    refusal = world.move(thing.id, units, SHELVES, target, by=None if kitchen else r)
    if refusal:
        return ToolResult(refusal)
    bought = amount(thing, units)
    world.fund.take("sale", total)
    if kitchen:  # the fund pays itself: a sale, and the kitchen's purchase
        world.fund.pay("kitchen", total)
        tail = world.kitchen_told()
    else:
        r.inventory.money -= total
        r.inventory.moves.append(["bought", total, bought])
        world.take_in(r)
        tail = f"{world.things_told(r)} {world.purse(r)}"
    add(world.daybook.today["sales"], thing.id, units)
    for_whom = " for the kitchen" if kitchen else ""
    world.record_move(
        "buy",
        lambda w: f"{cap(you(r.name, w))} bought {bought}{for_whom} for {world.money(total)}.",
        by=r,
        audience=[seller] if seller is not r else [],
        item=thing.id,
        units=units,
        source=SHELVES,
        target=target,
        money=total,
        seller=seller.name,
    )
    if seller is not r:  # nobody is paid for serving itself
        world.pay_service(seller, "sale", "a sale", tell=True)
    paid = ", which the fund paid" if kitchen else ""
    return ToolResult(f"You bought {bought}{for_whom} for {world.money(total)}{paid}. {tail}")


def _buy_dish(world: World, r: Resident, item: str, units: int) -> ToolResult:
    """`r` buys a portion of the dish `item` in the Restaurant while its chef is at work there,
    and eats it at once: it goes from the kitchen's portions to `r` and is eaten, the price goes
    to the fund, and the chef is paid its sum."""
    dish, restaurant = world.config.item(item), world.config.workplace("restaurant")
    if r.place != restaurant.id:
        return ToolResult(f"You can have {dish.name} at {restaurant.name}, not here.")
    chef = world.serving("restaurant")
    if chef is None:
        return ToolResult("The kitchen is closed.")
    if r.occupation.workplace == restaurant.id:
        return ToolResult("You cook the dishes here; you cannot buy them.")
    if units != 1:
        return ToolResult("One dish at a time.")
    price = world.kitchen.menu[dish.id]
    if refusal := world.cannot_pay(r, price):
        return ToolResult(refusal)
    world.reckon(r)
    if refusal := world.move(dish.id, 1, PORTIONS, r.name, by=r):
        return ToolResult(refusal)
    r.inventory.money -= price
    r.inventory.moves.append(["bought", price, dish.name])
    world.fund.take("dish", price)
    add(world.daybook.today["dishes"], dish.id, 1)
    world.record_move(
        "buy",
        lambda w: (
            f"{cap(you(chef.name, w))} served {you(r.name, w)} {dish.name} for "
            f"{world.money(price)}."
        ),
        by=r,
        audience=[chef],
        item=dish.id,
        units=1,
        source=PORTIONS,
        target=r.name,
        money=price,
        seller=chef.name,
    )
    world.served(r, dish.id)
    world.pay_service(chef, "dish", "a dish served", tell=True)
    eaten = world.body.told("satiety", r.living.satiety)
    return ToolResult(f"You had {dish.name} for {world.money(price)}. {eaten} {world.purse(r)}")


def _working_at(world: World, r: Resident, kind: str) -> str | ToolResult:
    """`r`, whose work is at the town's `kind` of workplace, sits down to work there unless it
    is at work already: what it is told of it, or the refusal of one elsewhere or exhausted."""
    place = world.config.workplace(kind)
    if r.place != place.id:
        return ToolResult(f"You can do that only at {place.name}.")
    sat = _sit_down(world, r)
    if isinstance(sat, ToolResult) or not sat:
        return sat
    return f"{sat.strip()} "  # told on the line of what follows


async def _order(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    sat = _working_at(world, r, "store")
    if isinstance(sat, ToolResult):
        return sat
    thing, quantity = world.config.item(args["item"]), args["quantity"]
    assert thing.wholesale is not None
    cost = thing.wholesale * quantity
    ordered = amount(thing, quantity)
    if cost > world.fund.balance:
        return ToolResult(f"{sat}The fund cannot pay the supplier {world.money(cost)} now.")
    world.fund.pay("supplier", cost)
    now = world.clock.now()
    arrives = calendar_day(now) * DAY + parse_hour(world.config.day.delivery)
    world.store.pending.append([thing.id, quantity, arrives])
    world.record(
        "order",
        lambda w: (
            f"{cap(you(r.name, w))} ordered {ordered} from the supplier for {world.money(cost)}."
        ),
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
        f"{sat}You ordered {ordered} from the supplier for {world.money(cost)}, which the fund "
        f"paid; it arrives tomorrow at {clock_time(arrives)}."
    )


def _priced(world: World, item: str) -> str:
    """The item or the Hospital's service `item`, as a sentence names it."""
    return f"the {item}" if item in FEES else world.config.item(item).name


async def _set_price(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    item, price = args["item"], args["price"]
    kind = world.config.place(r.occupation.workplace).kind
    table = {"store": world.store.prices, "restaurant": world.kitchen.menu, "hospital": world.fees}
    prices, place, name = table[kind], world.config.workplace(kind), _priced(world, item)
    if item not in prices:
        sold = {"store": "sold at", "restaurant": "on the menu of", "hospital": "a service of"}
        return ToolResult(f"{cap(name)} is not {sold[kind]} {place.name}.")
    sat = _working_at(world, r, kind)
    if isinstance(sat, ToolResult):
        return sat
    before, prices[item] = prices[item], price
    world.record(
        "price",
        lambda w: (
            f"{cap(you(r.name, w))} set the price of {bare(name)} at {place.name} to "
            f"{world.money(price)}."
        ),
        actor=r,
        payload={"item": item, "name": name, "place": place.id, "price": price, "before": before},
    )
    return ToolResult(
        f"{sat}The price of {bare(name)} is now {world.money(price)}; it was {world.money(before)}."
    )


async def _cook(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    sat = _working_at(world, r, "restaurant")
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
    return ToolResult(f"{sat}You cooked {cooked}; {ready} ready to serve. {world.kitchen_told()}")


def _patient(world: World, r: Resident, name: str) -> tuple[Resident, str] | ToolResult:
    """The patient `name` the doctor `r` sees, with what `r` is told of sitting down to work:
    at the Hospital, where `r` sits down to work and the patient, awake, must be (`r` itself
    among them); or at the bedside of `name`, too ill to get up, where `r` sits down to nothing.
    Otherwise the refusal."""
    patient, hospital = world.residents.get(name), world.config.workplace("hospital")
    if patient is None:
        return ToolResult(f"There is nobody called {name} in the town.")
    if r.place != hospital.id:
        if patient in world.bedside(r):
            return patient, ""
        return ToolResult(
            f"You can do that at {hospital.name}, or at the bedside of one too ill to get up."
        )
    sat = _working_at(world, r, "hospital")
    if isinstance(sat, ToolResult):
        return sat
    if patient is not r and not world.visible(r, patient):
        return ToolResult(f"{sat}{name} is not here.")
    if not patient.awake:
        return ToolResult(f"{sat}{name} is asleep.")
    return patient, sat


def _charge(world: World, doctor: Resident, patient: Resident, service: str) -> str | int:
    """`patient` pays the fee of `service` (`examination` or `treatment`) to the fund, and is
    counted among the day's patients: the fee; or why it cannot pay, in its own words or, to the
    doctor, in the doctor's."""
    fee = world.fees[service]
    if fee > patient.inventory.money:
        if patient is doctor:
            return world.cannot_pay(patient, fee) or ""
        return f"{patient.name} does not have the {world.money(fee)} the {service} costs."
    patient.inventory.money -= fee
    patient.inventory.moves.append(
        ["paid", fee, f"an {service}" if service[0] in "aeiou" else f"a {service}"]
    )
    world.fund.take("fee", fee)
    world.daybook.today["patients"].append([patient.name, service])
    return fee


async def _examine(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    found = _patient(world, r, args["patient"])
    if isinstance(found, ToolResult):
        return found
    patient, sat = found
    fee = _charge(world, r, patient, "examination")
    if isinstance(fee, str):
        return ToolResult(f"{sat}{fee}")
    world.reckon(patient)
    living, cost = patient.living, world.money(fee)
    own, seen = world.body.examination(living), world.body.examination(living, patient.name)

    def told(w: str | None) -> str:
        if w == r.name:
            whom = "yourself" if patient is r else patient.name
            return f"You examined {whom} for {cost}. {own if patient is r else seen}"
        if w == patient.name:
            return f"{r.name} examined you for {cost}. {own}"
        return f"{r.name} examined {patient.name} for {cost}."

    world.record(
        "examination",
        told,
        actor=r,
        audience=[patient] if patient is not r else [],
        payload={
            "patient": patient.name,
            "fee": fee,
            "satiety": round(living.satiety, 1),
            "energy": round(living.energy, 1),
            "health": round(living.health, 1),
            "ill": living.ill,
            "night": dict(living.night),
        },
    )
    paid = "" if patient is r else world.pay_service(r, "patient", "a patient examined")
    return ToolResult(f"{sat}{told(r.name)} {paid}".strip())


async def _treat(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    found = _patient(world, r, args["patient"])
    if isinstance(found, ToolResult):
        return found
    patient, sat = found
    fee = _charge(world, r, patient, "treatment")
    if isinstance(fee, str):
        return ToolResult(f"{sat}{fee}")
    world.reckon(patient)
    living, cost, restores = patient.living, world.money(fee), world.config.hospital.restores

    def told(w: str | None) -> str:
        if w == r.name:
            return f"You treated {'yourself' if patient is r else patient.name} for {cost}."
        if w == patient.name:
            return f"{r.name} treated you for {cost}."
        return f"{r.name} treated {patient.name} for {cost}."

    world.record(
        "treatment",
        told,
        actor=r,
        audience=[patient] if patient is not r else [],
        payload={
            "patient": patient.name,
            "fee": fee,
            "restores": restores,
            "before": round(living.health, 1),
            "health": round(min(100.0, living.health + restores), 1),
            "ill": living.ill,
            "bedridden": living.bedridden,
        },
    )
    world.treat(patient, restores)
    paid = "" if patient is r else world.pay_service(r, "patient", "a patient treated")
    return ToolResult(f"{sat}{told(r.name)} {paid}".strip())


async def _report(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    sat = _working_at(world, r, "hall")
    if isinstance(sat, ToolResult):
        return sat
    world.record("report", lambda w: f"{cap(you(r.name, w))} read the town's report.", actor=r)
    return ToolResult(f"{sat}{world.report()}")


async def _announce(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    text = args["text"].strip()
    if not text:
        return ToolResult("You announced nothing.")
    sat = _working_at(world, r, "hall")
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
    other = world.residents.get(name)
    if other is None:
        return ToolResult(f"There is nobody called {name} in the town.")
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
    world.reckon(r)
    if refusal := world.move(thing.id, units, place, r.name, by=r):
        return ToolResult(refusal)
    got, where = amount(thing, units), world.config.place(place).name
    world.record_move(
        "get",
        lambda w: f"{cap(you(r.name, w))} took {got} that was left at {where}.",
        by=r,
        audience=world.addressable(r),
        item=thing.id,
        units=units,
        source=place,
        target=r.name,
    )
    world.take_in(r)
    return ToolResult(f"You took {got}. {world.things_told(r)}")


async def _put(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    assert r.place is not None
    thing, units, place = world.config.item(args["item"]), args.get("units", 1), r.place
    world.reckon(r)  # what it would have eaten by now is eaten first
    if refusal := world.move(thing.id, units, r.name, place, by=r):
        return ToolResult(refusal)
    left, where = amount(thing, units), world.config.place(place).name
    world.record_move(
        "put",
        lambda w: f"{cap(you(r.name, w))} left {left} at {where}, for anyone to take.",
        by=r,
        audience=world.addressable(r),
        item=thing.id,
        units=units,
        source=r.name,
        target=place,
    )
    return ToolResult(f"You left {left} here, for anyone to take. {world.things_told(r)}")


async def _pass(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    name, units = args["to"], args.get("units", 1)
    other = world.residents.get(name)
    if other is r:
        return ToolResult("You cannot pass anything to yourself.")
    if other is None:
        return ToolResult(f"There is nobody called {name} in the town.")
    if refusal := world.reach(r, name):
        return ToolResult(refusal)
    if args["item"] == MONEY:
        if refusal := world.cannot_pay(r, units):
            return ToolResult(refusal)
        r.inventory.money -= units
        other.inventory.money += units
        r.inventory.moves.append(["gave", units, name])
        other.inventory.moves.append(["received", units, r.name])
        given = world.money(units)
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
    thing = world.config.item(args["item"])
    serving = thing.dish and world.serving("restaurant") is r
    source = PORTIONS if serving else r.name
    world.reckon(r)  # what it would have eaten by now is eaten first
    world.reckon(other)
    if refusal := world.move(thing.id, units, source, name, by=r):
        return ToolResult(refusal)
    given = amount(thing, units)
    world.record_move(
        "pass",
        lambda w: (
            f"{cap(you(r.name, w))} served {you(name, w)} {given}, which nobody paid for."
            if serving
            else f"{cap(you(r.name, w))} passed {you(name, w)} {given}."
        ),
        by=r,
        audience=[other],
        item=thing.id,
        units=units,
        source=source,
        target=name,
    )
    if serving:  # a dish is eaten where it is served
        world.served(other, thing.id, units)
        return ToolResult(f"You served {name} {given}, which nobody paid for.")
    world.take_in(other, tell=True)  # food given is eaten at once by one who could eat
    return ToolResult(f"You passed {name} {given}. {world.things_told(r)}")


async def _eat(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    thing = world.config.item(args["item"])
    world.reckon(r)  # what it would have eaten by now is eaten first
    if not r.inventory.units(thing.id):
        return ToolResult(f"You have no {bare(thing.name)}.")
    before = world.body.bands(r.living)
    world.eat(r, thing.id)
    world.note_bands(r, before, tell=False)
    eaten = world.body.told("satiety", r.living.satiety)
    return ToolResult(f"You ate {amount(thing, 1)}. {eaten} {world.things_told(r)}")


async def _leave_conversation(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    world.leave_conversation(r)
    back = " You are back at work." if isinstance(r.base, Work) else ""
    return ToolResult(f"You left the conversation.{back}")


async def _review_day(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    return ToolResult(world.review(r))


HANDLERS: dict[str, Handler] = {
    "help": _help,
    "look_around": _look_around,
    "how_am_i": _how_am_i,
    "inventory": _inventory,
    "go": _go,
    "wait": _wait,
    "sleep": _sleep,
    "start_work": _start_work,
    "view_board": _view_board,
    "read_task": _read_task,
    "claim_task": _claim_task,
    "shell": _shell,
    "read_repo_file": _read_repo_file,
    "write_repo_file": _write_repo_file,
    "edit_repo_file": _edit_repo_file,
    "submit": _submit,
    "abandon_task": _abandon_task,
    "assign": _assign,
    "cook": _cook,
    "order": _order,
    "set_price": _set_price,
    "examine": _examine,
    "treat": _treat,
    "report": _report,
    "announce": _announce,
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
