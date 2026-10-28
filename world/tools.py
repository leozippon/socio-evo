"""The world's tools: the specs of every tool the town has, and their handlers.

`specs` builds the list once from the configuration (`message` only where something to write
with is sold); a resident's runtime declares, at each request, those of them its event offers
at its place (`World.usable`). `World.call` refuses a tool the resident's event does not offer
and arguments that do not fit the spec; the handlers here check the remaining conditions, each
refusal one line naming the condition, and act. Outputs of shell commands and repository files
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
from world.clock import calendar_day, clock_time, parse_hour
from world.config import IMMEDIATE_EFFECTS, TownConfig
from world.events import EXHAUSTED, Work
from world.rules import MAX_WAIT_MINUTES, TOPICS, bare
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


def specs(config: TownConfig) -> list[ToolSpec]:
    workplace = config.workplace.name
    for_sale = list(config.goods)
    counters = "; ".join(
        f"at {place.name}: {listed([f'{g.name} ({g.id})' for g in sold])}"
        for place in config.places
        if (sold := [g for g in for_sale if place.id in g.sold_at])
    )
    writing = listed([bare(g.name) for g in for_sale if g.effect == "messaging"], "or")
    kept = [g.id for g in for_sale if g.kind != "immediate"]  # what can be owned and given
    return [
        spec("help", f"Read how the town works, on one point: {listed(list(TOPICS))}.",
             topic={"type": "string", "enum": list(TOPICS)}),
        spec("look_around", "See where you are, who is here and what each of them is doing."),
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
        spec("view_board", f"Read the board at {workplace}: each task's number, repository, the "
             "first line of its problem and what the client pays, and whether it is held or "
             "already paid to you. If you hold a task, its whole problem is shown too."),
        spec("read_task", f"Read the whole problem of a task on the board at {workplace}, "
             "without claiming it.", ("task",), task=_number("the task's number on the board", 1)),
        spec("claim_task", f"Claim a task from the board at {workplace} and sit down to work on "
             "it there. You get a workspace with its repository and read the whole problem.",
             ("task",), task=_number("the task's number on the board", 1)),
        *WORKSPACE_SPECS,
        spec("submit", "Hand in your fix for the task you hold. The client's checks run on it "
             "in a clean copy of the repository; you are told whether it was accepted, and if "
             "so you are paid at once, and if not, what went wrong and how many checks failed. "
             "Each task can be handed in only a few times a day."),
        spec("abandon_task", "Give up the task you hold. Its changes are thrown away and you "
             "are not paid."),
        spec("leave_work", "Stop working for now. You stay where you are and keep your task and "
             "its changes."),
        spec("say", "Speak where you are. Without `to`, everyone awake here hears you; with "
             "`to`, only the people you name, and the others notice only that you said "
             "something to them.", ("text",), text=_text("what you say"),
             to={"type": "array", "items": {"type": "string"},
                 "description": "the names of the people you speak to"}),
        spec("buy", "Buy something where you are and pay for it in cash at once. Something "
             "eaten on the spot is eaten as you buy it; a stock is kept, and you eat from it a "
             "helping at a time whenever you could eat; a thing you keep is yours from then on. "
             f"For sale {counters}.",
             ("item",),
             item={"type": "string", "enum": [g.id for g in for_sale],
                   "description": "the good's short name, as given in brackets"},
             quantity=_number("how many: stocks or helpings; one thing you keep (1 if left "
                              "out)", 1)),
        spec("move_in", "Move into the home you are at, if it has a free room: you give up your "
             "old room and pay the new rent from the next midnight."),
        *([spec("message", f"Write to someone who also has a {writing}, wherever they are. "
                "They read it when they next look up from what they are doing; nobody else "
                "sees it.", ("to", "text"), to=_text("their name"), text=_text("what you write"))]
          if writing else []),
        spec("give", "Hand something of yours to someone here: money, a thing you own (with "
             "any daily charge on it) or helpings of a stock, as a gift or on terms you agree "
             "between you.", ("to", "what", "amount"), to=_text("their name"),
             what={"type": "string", "enum": ["money", *kept],
                   "description": "money, or the short name of the thing or stock, as given in "
                                  "brackets under buy"},
             amount=_number("how much money, or how many helpings; 1 for a thing", 1)),
        spec("leave_conversation", "Step out of the conversation and go back to what you "
             "were doing."),
        spec("review_day", "Look back over your day, hour by hour: where you went, what you "
             "did, what was said to you and by you, and the money you received and paid."),
    ]  # fmt: skip


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
    return ToolResult(world.rules.help(r.name, args.get("topic", ""), world.homes()))


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
    told = world.break_off(r)
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
        return ToolResult("You can sleep only at home.")
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
    told = world.break_off(r)
    went = world.go_to_bed(r, hour, journal, day)
    return ToolResult(f"{told}{went}", ends_turn=True)


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


async def _view_board(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    workplace = world.config.workplace
    if r.place != workplace.id:  # the board hangs there, for whoever is there to read
        return ToolResult(f"You are not at {workplace.name}.")
    return ToolResult(world.board.text(r.name, world.config.day.board_posted))


async def _read_task(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    workplace, number, board = world.config.workplace, args["task"], world.board
    if r.place != workplace.id:  # the board hangs there, for whoever is there to read
        return ToolResult(f"You are not at {workplace.name}.")
    if number not in board.posted:
        return ToolResult(f"There is no task {number} on the board.")
    task = board.task(number)
    return ToolResult(f"The problem of task {number}, in {task.repo}:\n\n{task.problem_statement}")


async def _claim_task(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    workplace, number, board = world.config.workplace, args["task"], world.board
    if r.place != workplace.id:
        return ToolResult(f"The board is at {workplace.name}; you can claim a task only there.")
    refusal = board.claim_refusal(r.name, number)
    if refusal:
        return ToolResult(refusal)
    sat = _sit_down(world, r)
    if isinstance(sat, ToolResult):
        return sat
    await board.claim(r.name, number, calendar_day(world.clock.now()))
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


NO_TASK = "You hold no task; claim one from the board first."


async def _workspace(world: World, r: Resident) -> tuple[Claim, Workspace, str] | ToolResult:
    """The task `r` holds and its workspace, reopened if the night closed it, with `r` sat down
    to work if it was not, and what it is told of sitting down, or nothing. The work is done
    at the workplace, where the machines are."""
    claim = world.board.claims.get(r.name)
    if claim is None:
        return ToolResult(NO_TASK)
    workplace = world.config.workplace
    if r.place != workplace.id:
        return ToolResult(f"You can work on task {claim.task} only at {workplace.name}.")
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
    holds = board.claims.get(r.name) is claim  # a claim can run out at midnight during the checks
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
    if not holds:  # the claim ran out at midnight while the checks ran: nobody is paid for it
        told = "Accepted" if verdict.resolved else f"Not accepted: {failure(verdict)}"
        unpaid = ", so you are not paid for it" if verdict.resolved else ""
        return ToolResult(
            f"{told}. Your claim on task {number} ran out at midnight while the checks ran"
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
    world.fund.take("client", world.config.work.payment)
    paid = world.pay_service(r, number)
    return ToolResult(f"Accepted. {paid} {world.purse(r)} {_now(world)}")


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
    good = world.config.good(args["item"])
    quantity = args.get("quantity", 1)
    if r.place not in good.sold_at:
        where = listed([world.config.place(place).name for place in good.sold_at], "or")
        return ToolResult(f"You can buy {good.name} at {where}, not here.")
    if good.kind == "durable":
        if r.inventory.units(good.id):
            return ToolResult(f"You already have {good.name}.")
        if quantity != 1:
            return ToolResult(f"One {bare(good.name)} is all you can have.")
    elif good.effect in IMMEDIATE_EFFECTS and quantity != 1:
        return ToolResult(f"One {bare(good.name)} at a time.")
    if good.effect == "treatment" and r.living.health >= 100:
        return ToolResult("The doctor finds nothing to treat.")
    total = good.price * quantity
    refusal = world.cannot_pay(r, total)
    if refusal:
        return ToolResult(refusal)
    bought = f"{quantity} × {good.name}" if quantity > 1 else good.name
    r.inventory.money -= total
    r.inventory.moves.append(["bought", total, bought])
    world.fund.take("sale", total)
    world.reckon(r)
    before = world.body.bands(r.living)
    findings = ""
    if good.kind == "durable":
        r.inventory.add(good.id, 1)
        tail = world.things_told(r)
    elif good.kind == "consumable":
        assert good.uses is not None
        r.inventory.add(good.id, good.uses * quantity)
        world.feed(r)
        tail = world.things_told(r)
    elif good.effect == "food":
        world.eat(r, good, quantity)
        tail = world.body.told("satiety", r.living.satiety)
    elif good.effect == "treatment":
        assert good.restores is not None
        world.treat(r, good.restores)
        tail = world.body.told("health", r.living.health)
    else:
        tail = findings = world.body.examination(r.living)
    world.note_bands(r, before, tell=False)
    world.record(
        "purchase",
        lambda w: (
            f"{cap(you(r.name, w))} bought {bought} for {world.money(total)}."
            + (f" {findings}" if findings and w == r.name else "")
        ),
        actor=r,
        payload={
            "item": good.id,
            "name": good.name,
            "kind": good.kind,
            "effect": good.effect,
            "quantity": quantity,
            "amount": total,
        },
    )
    return ToolResult(f"You bought {bought} for {world.money(total)}. {tail} {world.purse(r)}")


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
    writing = [good for good in world.config.goods if good.effect == "messaging"]
    names = listed([bare(good.name) for good in writing], "or")
    if not any(r.inventory.units(good.id) for good in writing):
        return ToolResult(f"You have no {names}.")
    other = world.residents.get(name)
    if other is None:
        return ToolResult(f"There is nobody called {name} in the town.")
    if other is r:
        return ToolResult("You cannot write to yourself.")
    if not any(other.inventory.units(good.id) for good in writing):
        return ToolResult(f"{name} has no {names}.")
    if not text:
        return ToolResult("You wrote nothing.")

    def tell(w: str | None) -> str:
        return f"{cap(you(r.name, w))} wrote to {you(name, w)}: “{text}”"

    world.record("message", tell, actor=r, audience=[other], payload={"to": name, "text": text})
    return ToolResult(tell(r.name))


async def _give(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    name, what, amount = args["to"], args["what"], args["amount"]
    other = world.residents.get(name)
    if other is r:
        return ToolResult("You cannot give to yourself.")
    if other is None or not world.visible(r, other):
        return ToolResult(f"{name} is not here.")
    if not other.awake:
        return ToolResult(f"{name} is asleep.")
    if what == "money":
        refusal = world.cannot_pay(r, amount)
        if refusal:
            return ToolResult(refusal)
        r.inventory.money -= amount
        other.inventory.money += amount
        r.inventory.moves.append(["gave", amount, name])
        other.inventory.moves.append(["received", amount, r.name])
        given, payload = world.money(amount), {"to": name, "amount": amount}
        left = world.purse(r)
    else:
        good = world.config.good(what)
        world.reckon(r)  # what it would have eaten by now is eaten first
        have = r.inventory.units(good.id)
        if not have:
            return ToolResult(f"You have no {bare(good.name)}.")
        if good.kind == "durable":
            if amount != 1:
                return ToolResult(f"You have one {bare(good.name)} to give.")
            if other.inventory.units(good.id):
                return ToolResult(f"{name} already has {good.name}.")
            given = good.name
        else:
            if amount > have:
                return ToolResult(f"You have only {counted(have, 'helping')} of {bare(good.name)}.")
            given = f"{counted(amount, 'helping')} of {bare(good.name)}"
        world.reckon(other)
        r.inventory.remove(good.id, amount)
        other.inventory.add(good.id, amount)
        payload = {"to": name, "item": good.id, "name": good.name, "quantity": amount}
        left = world.things_told(r)
    world.record(
        "gift",
        lambda w: f"{cap(you(r.name, w))} gave {you(name, w)} {given}.",
        actor=r,
        audience=[other],
        payload=payload,
    )
    world.reckon(other)  # food given is eaten at once by one who could eat
    return ToolResult(f"You gave {name} {given}. {left}")


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
    "view_board": _view_board,
    "read_task": _read_task,
    "claim_task": _claim_task,
    "shell": _shell,
    "read_repo_file": _read_repo_file,
    "write_repo_file": _write_repo_file,
    "edit_repo_file": _edit_repo_file,
    "submit": _submit,
    "abandon_task": _abandon_task,
    "leave_work": _leave_work,
    "say": _say,
    "buy": _buy,
    "move_in": _move_in,
    "message": _message,
    "give": _give,
    "leave_conversation": _leave_conversation,
    "review_day": _review_day,
}
