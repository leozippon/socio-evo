"""The world's tools: the declared list, constant for the run, and their handlers.

`specs` builds the list once from the configuration; every resident's runtime declares it at
every step. `World.call` refuses a tool the resident's event does not offer and arguments that
do not fit the spec; the handlers here check the remaining conditions, each refusal one line
naming the condition, and act. Outputs of shell commands and repository files are passed
through whole (a file in part when the resident asks for some of its lines); the runtime
truncates what enters its context.

The tools that act in a task's workspace (`WORKSPACE_SPECS`) are declared and answered here
for the town and for the work-only port of `world.solo` alike: what they do in a workspace and
tell of it is `told_command`, `read_repo`, `write_repo` and `edit_repo`, and the town's handlers
add the claim they need and the log entry.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from agent.port import ToolResult, ToolSpec
from world.backend import ExecResult, Workspace
from world.board import Claim, failure
from world.clock import DAY, clock_time, parse_hour
from world.config import TownConfig
from world.events import Idle, Work
from world.rules import TOPICS
from world.telling import cap, counted, listed, you

if TYPE_CHECKING:
    from world.world import Resident, World

MAX_WAIT_MINUTES = 600
_SKILL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


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
    spec("shell", "Run a shell command in your workspace, in the repository's folder, without "
         "internet. You get its whole output and its exit code.", ("command",),
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
"""The tools that act in a task's workspace, in their declared order."""


def specs(config: TownConfig) -> list[ToolSpec]:
    workplace = config.workplace.name
    return [
        spec("help", f"Read the town's rules on one topic: {listed(list(TOPICS))}.",
             topic={"type": "string", "enum": list(TOPICS)}),
        spec("look_around", "See where you are, who is here and what each of them is doing."),
        spec("go", "Walk to another place in town. You arrive after the walk; on the way you "
             "can do nothing and nobody can speak to you.", ("place",),
             place={"type": "string", "enum": [place.id for place in config.places],
                    "description": "the place's name as the rules give it in brackets"}),
        spec("wait", "Let time pass where you are. You are told when something happens, or "
             "when the minutes are up.", ("minutes",),
             minutes=_number("how many minutes to wait", 1, MAX_WAIT_MINUTES)),
        spec("sleep", "Go to bed at home, ending your day. You can then look over your day, "
             "rate people and see to your files before you fall asleep.", ("until", "journal"),
             until=_text(f"the hour to wake, HH:MM, no earlier than {config.day.wake_earliest}"),
             journal=_text("your account of the day in your own words: what work you did and "
                           "with what result, what methods you used and where they came from, "
                           "what you concluded, and what remains open")),
        spec("start_work", f"Start work at {workplace} while it is open. If you hold a task, "
             "its workspace is set up again as you left it."),
        spec("view_board", "Read the board: each task's number, repository, first line and "
             "pay, and whether it is held or already paid to you. If you hold a task, its "
             "whole problem is shown too."),
        spec("claim_task", "Claim a task from the board. You get a workspace with the task's "
             "repository and are shown its whole problem.", ("task",),
             task=_number("the task's number on the board", 1)),
        *WORKSPACE_SPECS,
        spec("submit", "Hand in your changes to the repository for checking. You are told "
             "whether they were accepted, and if so you are paid at once; if not, what kind of "
             "failure it was and how many checks failed. Each task can be handed in only a few "
             "times a day."),
        spec("abandon_task", "Give up the task you hold. Its changes are thrown away and you "
             "are not paid."),
        spec("leave_work", f"Stop working and step out of {workplace}. You keep your task and "
             "its changes."),
        spec("say", "Speak where you are. Without `to`, everyone awake here hears you; with "
             "`to`, only the people you name, and the others notice only that you said "
             "something to them.", ("text",), text=_text("what you say"),
             to={"type": "array", "items": {"type": "string"},
                 "description": "the names of the people you speak to"}),
        spec("give_money", "Hand some of your money to someone you are talking with.",
             ("to", "amount"), to=_text("their name"), amount=_number("how much", 1)),
        spec("share_skill", "Pass one of your skills to someone you are talking with: they "
             "receive the text of its file.", ("to", "skill"), to=_text("their name"),
             skill=_text("the skill's file name in your skills folder")),
        spec("leave_conversation", "Step out of the conversation and go back to what you "
             "were doing."),
        spec("review_day", "Read the town's record of your day: where you went, what you did, "
             "what was said to you and by you, and the money you received and paid."),
        spec("rate", "Rate someone you spent time with today, from 1 to 5, with your reason. "
             "They read it the next night, without your name.", ("resident", "score", "reason"),
             resident=_text("their name"), score=_number("from 1 to 5", 1, 5),
             reason=_text("why")),
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


def told_command(result: ExecResult, timeout: int) -> str:
    """What `shell` tells of a command's outcome: its outputs whole, then its exit code, or that
    it was stopped after `timeout` seconds."""
    parts = [result.stdout.rstrip("\n")] if result.stdout else []
    if result.stderr:
        parts.append("stderr:\n" + result.stderr.rstrip("\n"))
    if result.timed_out:
        parts.append(f"The command was stopped after {timeout} seconds.")
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


async def _help(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    return ToolResult(world.rules.help(r.name, args.get("topic", "")))


async def _look_around(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    return ToolResult(world.look(r))


async def _go(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    place = world.config.place(args["place"])
    if place.id == r.place:
        return ToolResult(f"You are already at {place.name}.")
    arrival = world.depart(r, place.id)
    return ToolResult(
        f"You set off for {place.name} and will arrive at {clock_time(arrival)}.", ends_turn=True
    )


async def _wait(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    r.wait_minutes = args["minutes"]
    return ToolResult(f"You wait for up to {counted(args['minutes'], 'minute')}.", ends_turn=True)


async def _sleep(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    hours, day = world.config.day, world.lived_day()
    if world.clock.now() - (day - 1) * DAY < hours.of_day(hours.earliest_sleep):
        return ToolResult(f"Not yet: nobody goes to bed before {hours.earliest_sleep}.")
    if r.place != r.home:
        return ToolResult("You can sleep only at home.")
    try:
        hour = parse_hour(args["until"].strip())
    except ValueError:
        return ToolResult("Give the hour to wake as HH:MM, for example 07:30.")
    if hour < parse_hour(hours.wake_earliest):
        return ToolResult(f"You can sleep until {hours.wake_earliest} at the earliest.")
    journal = args["journal"].strip()
    if not journal:
        return ToolResult("Write your journal entry for the day before you go to bed.")
    date = world.config.start_date + timedelta(days=day - 1)
    path = r.agent_dir / "memory" / "journal" / f"{date.isoformat()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(journal + "\n", encoding="utf-8")
    wake = day * DAY + hour
    world.go_to_bed(r, wake, journal, day)
    return ToolResult("You went to bed.", ends_turn=True)


async def _start_work(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    workplace = world.config.workplace
    if r.place != workplace.id:
        return ToolResult(f"You are not at {workplace.name}.")
    if not world.workplace_open:
        return ToolResult(
            f"{cap(workplace.name)} is closed; it is open from {workplace.opens} to "
            f"{workplace.closes}."
        )
    r.base = Work()
    world.record("start_work", lambda w: f"{cap(you(r.name, w))} started work.", actor=r)
    claim = world.board.claims.get(r.name)
    if claim is None:
        return ToolResult("You started work. You hold no task; the board shows what there is.")
    if r.name not in world.board.workspaces:
        await world.board.reopen(r.name)
        return ToolResult(
            f"You started work. The workspace of task {claim.task}, which you hold, is set up "
            "again with your changes."
        )
    return ToolResult(f"You started work. You hold task {claim.task}.")


async def _view_board(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    return ToolResult(world.board.text(r.name))


async def _claim_task(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    number = args["task"]
    refusal = world.board.claim_refusal(r.name, number)
    if refusal:
        return ToolResult(refusal)
    await world.board.claim(r.name, number, world.lived_day())
    task = world.board.task(number)
    world.record(
        "claim",
        lambda w: f"{cap(you(r.name, w))} claimed task {number} ({task.repo}).",
        actor=r,
        payload={"task": number, "instance_id": task.instance_id},
    )
    return ToolResult(
        f"You claimed task {number}, in {task.repo}; your workspace is ready. The problem:\n\n"
        f"{task.problem_statement}"
    )


async def _workspace(world: World, r: Resident) -> tuple[Claim, Workspace] | ToolResult:
    """The task `r` holds and its workspace, reopened if the night closed it."""
    claim = world.board.claims.get(r.name)
    if claim is not None and r.name not in world.board.workspaces:
        await world.board.reopen(r.name)
    if claim is None or world.board.claims.get(r.name) is not claim:
        return ToolResult("You hold no task; claim one from the board first.")
    return claim, world.board.workspaces[r.name]


async def _shell(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    held = await _workspace(world, r)
    if isinstance(held, ToolResult):
        return held
    claim, workspace = held
    number = claim.task
    timeout = world.config.work.shell_timeout_s
    result = await workspace.exec(args["command"], timeout)
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
    return ToolResult(told_command(result, timeout))


async def _read_repo_file(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    held = await _workspace(world, r)
    if isinstance(held, ToolResult):
        return held
    claim, workspace = held
    number, path = claim.task, args["path"]
    told, ok = await read_repo(workspace, args)
    world.record(
        "file_read",
        lambda w: f"{cap(you(r.name, w))} read {path} for task {number}.",
        actor=r,
        payload={"task": number, "path": path, "ok": ok},
    )
    return ToolResult(told)


async def _write_repo_file(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    held = await _workspace(world, r)
    if isinstance(held, ToolResult):
        return held
    claim, workspace = held
    number, path = claim.task, args["path"]
    told, ok = await write_repo(workspace, args)
    world.record(
        "file_write",
        lambda w: f"{cap(you(r.name, w))} wrote {path} for task {number}.",
        actor=r,
        payload={"task": number, "path": path, "characters": len(args["content"]), "ok": ok},
    )
    return ToolResult(told)


async def _edit_repo_file(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    held = await _workspace(world, r)
    if isinstance(held, ToolResult):
        return held
    claim, workspace = held
    number, path = claim.task, args["path"]
    told, ok = await edit_repo(workspace, args)
    world.record(
        "file_write",
        lambda w: f"{cap(you(r.name, w))} changed {path} for task {number}.",
        actor=r,
        payload={"task": number, "path": path, "edit": True, "ok": ok},
    )
    return ToolResult(told)


async def _submit(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    board = world.board
    held = await _workspace(world, r)
    if isinstance(held, ToolResult):
        return held
    claim, workspace = held
    number = claim.task
    if board.runs_left(r.name, number) <= 0:
        return ToolResult(
            f"You have handed in task {number} {counted(world.config.work.acceptance_runs, 'time')}"
            " today, as often as a day allows; you can hand it in again tomorrow."
        )
    patch = await workspace.diff()
    if not patch.strip():
        return ToolResult("Your workspace has no changes to hand in.")
    board.count_run(r.name, number)
    task = board.task(number)
    world.record(
        "submission",
        lambda w: f"{cap(you(r.name, w))} handed in task {number}.",
        actor=r,
        payload={"task": number, "patch": patch},
    )
    verdict = await board.backend.accept(task, patch, world.config.work.acceptance_timeout_s)
    left = board.runs_left(r.name, number)
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
        },
    )
    if not verdict.resolved:
        again = (
            f"You can hand in task {number} {counted(left, 'more time')} today."
            if left > 0
            else f"You cannot hand in task {number} again today."
        )
        return ToolResult(f"Not accepted: {failure(verdict)}. {again}")
    finished = board.finish(r.name, claim)
    if finished is not None:
        await finished.close()
    payment = world.config.work.payment
    world.economy.pay(r.name, payment, number)
    world.record(
        "payment",
        lambda w: (
            f"{cap(you(r.name, w))} received {world.economy.money(payment)} for task {number}."
        ),
        actor=r,
        payload={"task": number, "amount": payment, "purse": world.economy.purses[r.name]},
    )
    return ToolResult(
        f"Accepted. You were paid {world.economy.money(payment)}. {world.economy.purse(r.name)}"
    )


async def _abandon_task(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    claim = world.board.claims.get(r.name)
    if claim is None:
        return ToolResult("You hold no task.")
    workspace = world.board.drop(r.name)
    if workspace is not None:
        await workspace.close()
    world.record(
        "abandon",
        lambda w: f"{cap(you(r.name, w))} gave up task {claim.task}.",
        actor=r,
        payload={"task": claim.task},
    )
    return ToolResult(f"You gave up task {claim.task}; its changes are gone.")


async def _leave_work(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    r.base = Idle()
    world.record("leave_work", lambda w: f"{cap(you(r.name, w))} stopped work.", actor=r)
    claim = world.board.claims.get(r.name)
    held = f" You still hold task {claim.task}." if claim else ""
    return ToolResult(f"You stopped work and stepped out of {world.config.workplace.name}.{held}")


async def _say(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    text = args["text"].strip()
    if not text:
        return ToolResult("You said nothing.")
    conversation = r.conversation
    budget = conversation.budget if conversation else None
    if budget is not None and budget[r.name] <= 0:
        return ToolResult("You have used all your messages for this meeting.")
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
    conversation = world.converse(r, recipients)
    if conversation.budget is not None:
        conversation.budget[r.name] -= 1

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
        interrupt=recipients,
        payload={
            "text": text,
            "to": heard,
            "private": private,
            "bystanders": sorted(unheard),
            "conversation": conversation.room,
        },
    )
    left = conversation.budget[r.name] if conversation.budget is not None else None
    tail = "" if left is None else f" You have {counted(left, 'message')} left."
    return ToolResult(tell(r.name) + tail)


def _partner_refusal(world: World, r: Resident, name: str) -> str | None:
    other = world.residents.get(name)
    if other is None or other is r or other.conversation is not r.conversation:
        return f"{name} is not in your conversation."
    return None


async def _give_money(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    name, amount = args["to"], args["amount"]
    refusal = _partner_refusal(world, r, name)
    if refusal:
        return ToolResult(refusal)
    economy = world.economy
    if amount > economy.purses[r.name]:
        return ToolResult(f"You do not have {economy.money(amount)}. {economy.purse(r.name)}")
    economy.give(r.name, name, amount)
    world.record(
        "gift",
        lambda w: f"{cap(you(r.name, w))} gave {you(name, w)} {economy.money(amount)}.",
        actor=r,
        audience=[world.residents[name]],
        payload={"to": name, "amount": amount},
    )
    return ToolResult(f"You gave {name} {economy.money(amount)}. {economy.purse(r.name)}")


async def _share_skill(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    if not world.config.social.skills_shareable:
        return ToolResult("Skills cannot be passed on here.")
    name, skill = args["to"], args["skill"].strip().removesuffix(".md")
    refusal = _partner_refusal(world, r, name)
    if refusal:
        return ToolResult(refusal)
    path = r.agent_dir / "skills" / f"{skill}.md"
    if not _SKILL.fullmatch(skill) or not path.is_file():
        return ToolResult(f"You have no skill called {args['skill']}.")
    content = path.read_text(encoding="utf-8")

    def tell(w: str | None) -> str:
        told = f"{cap(you(r.name, w))} passed the skill “{skill}” to {you(name, w)}"
        return f"{told}. It reads:\n\n{content}" if w == name else f"{told}."

    world.record(
        "skill_shared",
        tell,
        actor=r,
        audience=[world.residents[name]],
        payload={"to": name, "skill": skill, "text": content},
    )
    return ToolResult(f"You passed the skill “{skill}” to {name}.")


async def _leave_conversation(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    world.leave_conversation(r)
    back = " You are back at work." if isinstance(r.base, Work) else ""
    return ToolResult(f"You left the conversation.{back}")


async def _review_day(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    return ToolResult(world.review(r))


async def _rate(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    rated, score, reason = args["resident"], args["score"], args["reason"].strip()
    refusal = world.ratings.refusal(r.name, rated)
    if refusal:
        return ToolResult(refusal)
    if not reason:
        return ToolResult("Give a reason with your rating.")
    world.ratings.rate(r.name, rated, score, reason)
    world.record(
        "rating",
        lambda w: f"{cap(you(r.name, w))} rated {rated} {score} of 5: “{reason}”",
        actor=r,
        payload={"rated": rated, "score": score, "reason": reason},
    )
    return ToolResult(f"You rated {rated} {score} of 5.")


HANDLERS: dict[str, Handler] = {
    "help": _help,
    "look_around": _look_around,
    "go": _go,
    "wait": _wait,
    "sleep": _sleep,
    "start_work": _start_work,
    "view_board": _view_board,
    "claim_task": _claim_task,
    "shell": _shell,
    "read_repo_file": _read_repo_file,
    "write_repo_file": _write_repo_file,
    "edit_repo_file": _edit_repo_file,
    "submit": _submit,
    "abandon_task": _abandon_task,
    "leave_work": _leave_work,
    "say": _say,
    "give_money": _give_money,
    "share_skill": _share_skill,
    "leave_conversation": _leave_conversation,
    "review_day": _review_day,
    "rate": _rate,
}
