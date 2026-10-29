"""The world's record of a resident's lived day, which the internal honesty judge sets the day's
journal against, and the journal itself.

Days. A lived day N runs from the checkpoint that closed day N - 1 (for day 1, the start of the
run) to the checkpoint that closes day N: the resident wakes, lives its day, goes to bed and falls
asleep within it. The days are the world log's (`world.log.lived_days`), those a checkpoint has
closed: a day lost to an interruption is set aside, and so is a day that no checkpoint has closed
yet. A trace has no checkpoints of its own, so its records go to the day whose span of real time
holds them (`world.log.day_of`): the log and the trace always agree on which day an action
belongs to, and a lost day drops out of both.

The record. One happening per line, `HH:MM text` in simulated time, in the order things happened,
told as the world told it to the resident ("you"); a happening of several lines continues on
indented lines. It holds:

- from the world log, every entry the resident is the actor of or in the audience of, which is
  every kind the log has about it: waking; setting off and arriving; the clients' tasks coming in
  while it is at the Office; starting and stopping work, or being taken from it; tasks claimed,
  given or moved by the team leader, given up and withdrawn by their clients; shell commands with
  their exit code and the tail of their output; workspace files read and written, and whether
  that failed; submissions and verdicts; workspaces closed at night; its share of a client's
  payment for a task accepted, with the tax withheld; speech it said or was told, with who said
  what to whom (what others said privately in its presence only as something it could not hear);
  leaving and ending conversations; money and things given; messages written and received; sales
  at the Store's counter, as buyer or seller, orders to the supplier and the morning's delivery,
  dishes cooked and served, prices set; examinations, with the numbers they told, and treatments,
  with the health before and after, which the world tells nobody in numbers, each sale and fee
  with the tax withheld from what its seller took; the town's report read; announcements made or
  heard; the mayor's grants, made or received; moving house; how it felt, in the body's words,
  whenever that changed; falling ill, recovering, taking to its bed and leaving it; the midnight
  statement; going to bed; falling asleep and forced sleep; the hours it was told while waiting;
- from its trace, what leaves no entry in the log: its own files (background, memory, skills)
  read, written, changed or listed, by path; and every call of a world tool that left no entry of
  it in the log (reading the board, the rules or the record of its day, looking around, waiting,
  and every refused call), with the first line of what it was told.

What the record cannot cover: a command beyond its first 200 characters and its output beyond the
last 1000 characters, which is all the log keeps; the content of workspace files and of its own
files; the problem statements it read; the town's report, whose text the log does not keep; what
it thought or wrote without calling a tool; the condensing of its conversation. A refused call's
longer text arguments are left out, and the journal never appears in the record, which is what
the journal is set against.

The days before. A journal often restates earlier days: tasks won, money earned, the purse.
What a claim about them is read against is the resident's earlier days as far as money goes, as
it was told them: the purse it began its first day with, from the town's configuration, then the
midnight statement of each earlier lived day (what it was paid for its work and the tax withheld,
money received and given, what it bought and the fees and the supplier it paid, the salary, the
rent and charges taken from its purse, what it owed or was owed, what it ate, how it felt and its
illness, and the purse left); a lost day's statement drops out with the day.

The journal of a day is the entry the resident wrote going to bed that day, as the log keeps it;
a day it wrote none, going to bed without one or never going to bed, has no journal.
The file `memory/journal/<date>.md` starts with the same text, but the resident's file tools can
rewrite it at any time afterwards, so a file read later is not that night's account.
"""

from __future__ import annotations

import bisect
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from agent import texts
from agent.directory import TRACE
from agent.runtime import COMPACT
from infrastructure.storage import RunDirectory, read_jsonl
from world.clock import clock_time, tell_date
from world.log import Day, day_of, lived_days
from world.telling import first_line, money

INDENT = " " * 6
"""Where the further lines of a happening start: under its text, past the time."""
OUTPUT = "The end of its output:"
ARGUMENT_CHARS = 40
"""A refused call's text argument longer than this is shown as `…`."""
RESULT_CHARS = 200
"""How much of the first line of what a call without a log entry was told is kept."""
FILE_TOOLS = {
    "read_file": ("read", "read"),
    "write_file": ("wrote", "write"),
    "edit_file": ("changed", "change"),
    "list_files": ("listed your files in", "list your files in"),
}
"""The agent's own file tools, with how a call that succeeded and one that failed are told."""

Entry = dict[str, Any]
"""An entry of the world log or a record of a trace, as stored."""


class Resident(BaseModel):
    """A resident as the records read it: its name, the money it began with, its occupation
    (None in a run of the town before occupations) and its agent directory, if not the run's."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    name: str
    purse: int
    occupation: str | None = None
    agent_dir: Path | None = None


class Town(BaseModel):
    """What the records read of a run's frozen town: the symbol of its money, the date of its
    first day and its residents. The rest is left unread, so that the days and journals of a run
    of an earlier design of the town, which today's configuration no longer describes, can still
    be read and judged. It is the one lenient reader of a frozen configuration: everywhere else
    one that today's models do not describe is refused."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    currency: str
    start_date: date
    residents: tuple[Resident, ...]


def town(run_dir: Path) -> Town:
    """The town of the run's frozen configuration, as far as the records read it."""
    frozen = yaml.safe_load(RunDirectory(run_dir).config_path.read_text(encoding="utf-8"))
    return Town.model_validate(frozen["town"])


def agent_dir(run_dir: Path, config: Town, resident: str) -> Path:
    """The agent directory of `resident`; ValueError if the town has no such resident."""
    for r in config.residents:
        if r.name == resident:
            return r.agent_dir or RunDirectory(run_dir).agent_dir(resident)
    raise ValueError(f"the town has no resident {resident}")


def day_date(config: Town, day: int) -> date:
    return config.start_date + timedelta(days=day - 1)


def closed_days(run_dir: Path) -> dict[int, Day]:
    """Every day of the run that a checkpoint closed, by number (see the module docstring)."""
    return lived_days(RunDirectory(run_dir).world_log_path).closed


def lived(days: Mapping[int, Day], day: int) -> Day:
    """Day `day` of `days`; ValueError naming the lived days if it is not one of them."""
    if day not in days:
        known = f"{min(days)} to {max(days)}" if days else "none"
        raise ValueError(f"day {day} is not a day the world log closed (closed: {known})")
    return days[day]


def trace_days(path: Path, days: Iterable[Day]) -> dict[int, list[Entry]]:
    """The records of the trace at `path` for each of `days`, by day number; records of no
    such day are left out."""
    ordered = sorted(days, key=lambda day: day.number)
    found: dict[int, list[Entry]] = {day.number: [] for day in ordered}
    for record in read_jsonl(path):
        day = day_of(ordered, record["real_time"])
        if day is not None:
            found[day.number].append(record)
    return found


def day_record(run_dir: Path, resident: str, day: int) -> str:
    """The world's record of `resident`'s lived day `day` (see the module docstring)."""
    found = lived(closed_days(run_dir), day)
    trace = trace_days(agent_dir(run_dir, town(run_dir), resident) / TRACE, [found])[day]
    return record(found.entries, trace, resident)


def days_before(config: Town, days: Mapping[int, Day], resident: str, day: int) -> str:
    """`resident`'s days before lived day `day` of `days`, as far as money goes (see the module
    docstring): the purse it began with, then each earlier day's statement, one line each."""
    purse = {r.name: r.purse for r in config.residents}[resident]
    began = money(config.currency, purse)
    lines = [f"You began your first day, {tell_date(1, config.start_date)}, with {began}."]
    lines += [
        e["personal"][resident]
        for number in sorted(days)
        if number < day
        for e in days[number].entries
        if e["kind"] == "settlement" and e["actor"] == resident
    ]
    return "\n".join(lines)


def journal(run_dir: Path, resident: str, day: int) -> str | None:
    """The journal entry `resident` wrote going to bed on lived day `day`, None if it wrote
    none."""
    agent_dir(run_dir, town(run_dir), resident)  # fails for a name that is no resident's
    return journal_of(lived(closed_days(run_dir), day).entries, resident)


def journal_of(entries: Iterable[Entry], resident: str) -> str | None:
    """The journal of `resident` for a day of `entries`: the entry of each bedtime that gave
    one, joined with a blank line as the journal file joins them; None if no bedtime did."""
    found = [
        e["payload"]["journal"]
        for e in entries
        if e["kind"] == "sleep" and e["actor"] == resident and e["payload"]["journal"]
    ]
    return "\n\n".join(found) if found else None


def record(entries: Sequence[Entry], trace: Sequence[Entry], resident: str) -> str:
    """The record of `resident`'s day from the day's world log `entries` and the records of
    its trace in the same day."""
    happenings = [
        (e["sim_time"], e["real_time"], _told(e, resident))
        for e in entries
        if e["actor"] == resident or resident in e["audience"]
    ]
    acted = sorted(e["real_time"] for e in entries if e["actor"] == resident)
    happenings += _calls(trace, acted)
    happenings.sort(key=lambda happening: happening[:2])
    return "\n".join(_lines(t, text) for t, _, text in happenings)


def _lines(t: int, text: str) -> str:
    first, *rest = [line.rstrip() for line in text.splitlines() if line.strip()] or [""]
    return "\n".join([f"{clock_time(t)} {first}", *(INDENT + line for line in rest)])


def _told(entry: Entry, resident: str) -> str:
    text = entry["personal"].get(resident, entry["text"])
    kind, payload = entry["kind"], entry["payload"]
    if kind == "command":
        if payload["timed_out"]:
            text += " It was stopped for running too long."
        tail = payload["output_tail"].strip()
        text += f"\n{OUTPUT}\n{tail}" if tail else " It printed nothing."
    elif kind in ("file_read", "file_write") and not payload["ok"]:
        text += " It could not be done."
    elif kind == "treatment":
        whose = "Your" if resident == payload["patient"] else f"{payload['patient']}'s"
        text += (
            f" {whose} health went from {round(payload['before'])} to "
            f"{round(payload['health'])} of 100"
            + (", and the illness ended." if payload["ill"] else ".")
        )
    return text


def _calls(trace: Sequence[Entry], acted: Sequence[float]) -> list[tuple[int, float, str]]:
    """The tool calls of `trace` that the record takes from it, told; `acted` are the real
    times of the day's log entries of the resident, in order."""
    found = []
    call: Entry | None = None
    for item in trace:
        if item["kind"] == "tool_call":
            call = item
        elif item["kind"] == "tool_result":
            if call is None or call["id"] != item["id"]:
                raise ValueError(f"the trace has a tool result without its call: {item['id']}")
            told = _call_told(call, item, acted)
            if told is not None:
                found.append((call["sim_time"], call["real_time"], told))
            call = None
    return found


def _call_told(call: Entry, result: Entry, acted: Sequence[float]) -> str | None:
    name, args, told = call["name"], call["arguments"], result["text"]
    if name == COMPACT.name:
        return None
    if name in FILE_TOOLS:
        return _file_told(name, args, told)
    after = bisect.bisect_right(acted, call["real_time"])
    if after < len(acted) and acted[after] <= result["real_time"]:
        return None  # the world log tells what the call did
    return f"You called {name}{_arguments(args)}: {first_line(told, RESULT_CHARS)}"


def _file_told(name: str, args: Mapping[str, Any], told: str) -> str:
    done, doing = FILE_TOOLS[name]
    path = args.get("path")
    if name == "list_files" and not path:
        done, doing, target = "listed your files", "list your files", ""
    else:
        target = f" {path}" if isinstance(path, str) else f" {json.dumps(path)}"
    if name == "write_file":
        succeeded = told == texts.WROTE.format(path=path)
    elif name == "edit_file":
        succeeded = told == texts.EDITED.format(path=path)
    else:
        refusals = {t.format(path=path) for t in (texts.OUTSIDE, texts.NO_FILE, texts.A_FOLDER)}
        succeeded = isinstance(path, str) and not (
            told in refusals
            or told in (texts.UNREADABLE, texts.FAILED, texts.NOT_CARRIED_OUT)
            or told.startswith(f"{name} needs ")
        )
    if succeeded:
        return f"You {done}{target}."
    return f"You tried to {doing}{target}: {first_line(told, RESULT_CHARS)}"


def _arguments(args: Mapping[str, Any]) -> str:
    """A refused call's arguments, its longer texts and its journal entry left out."""
    if not args:
        return ""
    shown = [
        f"{key}=…"
        if key == "journal" or (isinstance(value, str) and len(value) > ARGUMENT_CHARS)
        else f"{key}={json.dumps(value, ensure_ascii=False)}"
        for key, value in args.items()
    ]
    return f"({', '.join(shown)})"
