"""The world log, `world.jsonl`: every event of the town, append-only, the run's ground truth.

Each entry has a sequence number (consecutive from 1 across the whole run, resumptions
included), its kind (one of `KINDS`, which gives each kind's payload fields), the simulated and
the real time, the actor and the place where there is one, the audience (the residents who
perceived it), the text for nobody in particular, the wording for each resident it concerns
where that differs (naming the resident "you"), and a payload of the facts for analysis.
Residents never read the log.

A log is reopened on resumption and its sequence continues after the last line written. The
entries a lost day left after the last checkpoint stay in the file; the `resume` entry that
follows them names the checkpoint the world went back to, so an analysis can set them aside.

The log is read here too, by everything that reads it by day: `Days` cuts it into lived days
as its entries come, and `lived_days` reads a whole log so. A lived day runs from the checkpoint
that closed the day before (or the start of the run) to its own checkpoint, its last entry; the
entries a lost day left after the checkpoint a `resume` went back to are set aside, and so is
the `resume` itself. A day opens at the real time of the checkpoint before it, or of the
resumption that went back to that checkpoint, and closes at the real time of its own; a record
of real time, as a trace's, belongs to the day whose span holds it (`day_of`), so the log and a
trace always agree on which day an action belongs to. `counted_move` names what a move counts
as among a day's counts.
"""

from __future__ import annotations

import bisect
import math
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from infrastructure.storage import append_jsonl, read_jsonl
from world.economy import PORTIONS


@dataclass(frozen=True)
class Kind:
    """A kind of entry: what it records, and the fields of its payload in the order the world
    writes them; a field written only sometimes is said so."""

    what: str
    payload: tuple[str, ...] = ()


KINDS = {
    "wake": Kind("a resident woke up at home"),
    "depart": Kind("a resident set off for another place", ("from", "to", "arrival")),
    "arrive": Kind(
        "a resident arrived somewhere, at work if its duty runs anywhere", ("place", "working")
    ),
    "time": Kind(
        "a resident waiting was told the time, or that what it was just told ended its wait "
        "after a minute or more (cut_short, then only)",
        ("waited_minutes", "cut_short"),
    ),
    "task_arrived": Kind(
        "a client's task came in on the Office's board, told to those there",
        ("task", "instance_id", "repo"),
    ),
    "task_withdrawn": Kind(
        "a client withdrew a task not accepted in time, at midnight, told to whoever held it "
        "(holder or null)",
        ("task", "holder"),
    ),
    "start_work": Kind(
        "a resident sat down to work: with start_work, or by doing its occupation's work where "
        "it works (claiming, assigning or acting in a task's workspace, cooking, ordering, "
        "setting a price, examining or treating, reading the report, announcing, granting)"
    ),
    "leave_work": Kind("a resident stopped work, or the forced sleep stopped it"),
    "claim": Kind("a resident claimed a task and got a workspace", ("task", "instance_id")),
    "assign": Kind(
        "the team leader gave a task to a programmer, or moved it from the one who held it "
        "(from, or null), told to both",
        ("task", "to", "from"),
    ),
    "command": Kind(
        "a shell command run in a workspace, with its exit code and output tail",
        ("task", "command", "exit_code", "timed_out", "output_tail"),
    ),
    "file_read": Kind("a file read in a workspace", ("task", "path", "ok")),
    "file_write": Kind(
        "a file written in a workspace: whole (characters) or a passage of it changed (edit)",
        ("task", "path", "characters", "edit", "ok"),
    ),
    "submission": Kind("a resident submitted its workspace's changes", ("task", "patch")),
    "verdict": Kind(
        "the acceptance verdict on a submission, and whether its task was still held",
        ("task", "status", "resolved", "fail_to_pass", "pass_to_pass", "held"),
    ),
    "service": Kind(
        "a resident was paid its share of a client's payment for a task accepted, the tax "
        "withheld into the treasury: for a task it handed in (task: the whole for the team "
        "leader's own, the rest after the leader's share for a programmer's), or the team "
        "leader's share of one a programmer handed in (team); money is its purse after",
        ("for", "task", "amount", "tax", "money"),
    ),
    "abandon": Kind("a resident gave up its task", ("task",)),
    "workspace_closed": Kind(
        "a workspace closed at the checkpoint, its changes kept", ("task", "diff")
    ),
    "speech": Kind(
        "something said, with its text and recipients",
        ("text", "to", "private", "bystanders", "conversation", "members"),
    ),
    "leave_conversation": Kind("a resident left a conversation"),
    "conversation_end": Kind("a conversation ended", ("room",)),
    "move": Kind(
        "units of an item, or money, that a resident moved from one holder to another: a "
        "resident (by name), what is left at a place (by its id), the Store's shelves, the "
        "kitchen's larder or its portions, or nothing (null), with the money that went with "
        "them and why: get (taken from where it was left), put (left there), pass (handed to "
        "another, money alone without an item; from the portions, the chef serving a dish "
        "nobody pays for), eat (eaten, by choice or by the body as it grew hungry, into nothing) "
        "or buy (at the Store's counter, for oneself or by the chef for the kitchen's larder, "
        "which the chef pays, or a dish from the portions); seller is who served a purchase, whose "
        "purse took the money less the tax withheld into the treasury (none when the seller "
        "served itself, which costs nothing)",
        ("item", "units", "source", "target", "money", "reason", "seller", "tax"),
    ),
    "message": Kind(
        "a written message from one resident to another, read wherever the other is",
        ("to", "text"),
    ),
    "order": Kind(
        "what the shopkeeper ordered from the supplier, paid from the shopkeeper's purse at once",
        ("item", "name", "quantity", "amount", "arrives"),
    ),
    "delivery": Kind(
        "what the Store ordered came from the supplier onto its shelves in the morning",
        ("items",),
    ),
    "cook": Kind(
        "portions of a dish the chef cooked from the kitchen's larder",
        ("dish", "name", "portions", "used"),
    ),
    "price": Kind(
        "a price the shopkeeper, the chef or the doctor set",
        ("item", "name", "place", "price", "before"),
    ),
    "examination": Kind(
        "the doctor examined a patient, who paid the fee into the doctor's purse less the tax "
        "withheld (none when the doctor is the patient); the numbers it was told, told to both",
        ("patient", "fee", "tax", "satiety", "energy", "health", "ill", "night"),
    ),
    "treatment": Kind(
        "the doctor treated a patient, who paid the fee as for an examination",
        ("patient", "fee", "tax", "restores", "before", "health", "ill", "bedridden"),
    ),
    "report": Kind("the mayor read the town's report (its text is not kept)"),
    "announcement": Kind(
        "the mayor announced something, told to every resident at once or on waking", ("text",)
    ),
    "grant": Kind(
        "the mayor granted money from the treasury to a resident, for a reason, told to the "
        "resident; treasury is its balance after",
        ("to", "amount", "reason", "treasury"),
    ),
    "move_in": Kind("a resident moved into another home", ("from", "to", "rent")),
    "settlement": Kind(
        "the midnight statement: the hours at work that calendar day; the salary due and what "
        "the treasury owed before, paid as far as it held the money and the rest owed; the rent, "
        "the daily charges and the arrears before, taken from the purse above what it spares and "
        "the rest in arrears; the purse after; the day's food and the body's numbers after the "
        "night's reckoning of health",
        (
            "hours",
            "salary",
            "owed_before",
            "salary_paid",
            "owed",
            "rent",
            "charges",
            "arrears_before",
            "rent_paid",
            "arrears",
            "money",
            "nourishment",
            "satiety",
            "energy",
            "health",
            "night",
            "ill",
        ),
    ),
    "illness": Kind("a resident fell ill at midnight", ("chance", "nights", "health")),
    "condition": Kind(
        "a need of a resident's body crossed into another band; told to it if awake",
        ("need", "band", "value", "lowest"),
    ),
    "bedridden": Kind(
        "a resident's health ran out at midnight: it took to its bed at home, carried there if "
        "it was elsewhere, until treated",
        ("day", "home", "from", "carried", "task"),
    ),
    "recovered": Kind(
        "a resident's illness passed at midnight, or treatment ended it or let one bedridden "
        "leave its bed",
        ("illness", "bedridden", "treated", "health"),
    ),
    "sleep": Kind(
        "a resident went to bed, with the journal entry it gave, if any", ("journal", "day", "wake")
    ),
    "fell_asleep": Kind("a resident in bed fell asleep", ("forced",)),
    "forced_sleep": Kind(
        "a resident still up at the forced hour fell asleep without going to bed", ("wake",)
    ),
    "checkpoint": Kind("the day's checkpoint", ("day",)),
    "resume": Kind("the world went back to a checkpoint", ("day", "time")),
}
"""Every kind of entry the log has, by name."""


@dataclass(frozen=True)
class Entry:
    seq: int
    kind: str
    sim_time: int
    real_time: float
    actor: str | None
    place: str | None
    audience: tuple[str, ...]
    text: str
    personal: Mapping[str, str]
    payload: Mapping[str, Any]


class WorldLog:
    """`world.jsonl` at `path`, opened for appending; nothing is written until `append`."""

    def __init__(self, path: Path) -> None:
        self.path = path
        last = 0
        if path.exists():
            for record in read_jsonl(path):
                last = record["seq"]
        self._next = last + 1

    def append(
        self,
        kind: str,
        sim_time: int,
        text: str,
        *,
        actor: str | None = None,
        place: str | None = None,
        audience: Sequence[str] = (),
        personal: Mapping[str, str] | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> Entry:
        if kind not in KINDS:
            raise ValueError(f"unknown world event kind {kind!r}")
        entry = Entry(
            self._next,
            kind,
            sim_time,
            time.time(),
            actor,
            place,
            tuple(audience),
            text,
            dict(personal or {}),
            dict(payload or {}),
        )
        append_jsonl(
            self.path,
            {
                "seq": entry.seq,
                "kind": kind,
                "sim_time": sim_time,
                "real_time": entry.real_time,
                "actor": actor,
                "place": place,
                "audience": list(entry.audience),
                "text": text,
                "personal": entry.personal,
                "payload": entry.payload,
            },
        )
        self._next += 1
        return entry

    def entries(self) -> Iterator[dict[str, Any]]:
        """Every entry written so far, in order."""
        if self.path.exists():
            yield from read_jsonl(self.path)


@dataclass(frozen=True)
class Day:
    """A lived day: its number, its entries in log order (a closed day's last is the checkpoint
    that closed it), and the real times at which it opened (None for a run's first day) and
    closed (None for the day in progress)."""

    number: int
    entries: tuple[dict[str, Any], ...]
    opened: float | None
    closed: float | None

    def holds(self, real_time: float) -> bool:
        """Whether `real_time` falls in the day: after it opened and, once closed, not after."""
        return (self.opened is None or real_time > self.opened) and (
            self.closed is None or real_time <= self.closed
        )


class Days:
    """The lived days of a world log, cut as its entries are added in log order (see the module
    docstring). A `resume` to a day that no checkpoint closed is an error."""

    def __init__(self) -> None:
        self.closed: dict[int, Day] = {}
        """The days a checkpoint closed, by number, in order."""
        self._entries: list[dict[str, Any]] = []
        self._opened: float | None = None

    def add(self, entry: dict[str, Any]) -> None:
        kind = entry["kind"]
        if kind == "resume":
            back = entry["payload"]["day"]
            if back and back not in self.closed:
                raise ValueError(
                    f"entry {entry['seq']} resumes day {back}, which has no checkpoint"
                )
            self.closed = {number: day for number, day in self.closed.items() if number <= back}
            self._entries, self._opened = [], entry["real_time"]
            return
        self._entries.append(entry)
        if kind == "checkpoint":
            number, closed = entry["payload"]["day"], entry["real_time"]
            self.closed[number] = Day(number, tuple(self._entries), self._opened, closed)
            self._entries, self._opened = [], closed

    @property
    def open(self) -> Day:
        """The day in progress: the entries since the last checkpoint, perhaps none."""
        return Day(max(self.closed, default=0) + 1, tuple(self._entries), self._opened, None)

    def lived(self) -> list[Day]:
        """The days with entries, in order: the closed days, then the day in progress if
        anything has been logged since the last checkpoint."""
        closed = list(self.closed.values())
        return [*closed, self.open] if self._entries else closed


def lived_days(path: Path) -> Days:
    """The lived days of the world log at `path`; none before it is written."""
    days = Days()
    if path.exists():
        for entry in read_jsonl(path):
            days.add(entry)
    return days


def day_of(days: Sequence[Day], real_time: float) -> Day | None:
    """The day of `days`, given in order, whose span holds `real_time`, if any."""
    i = bisect.bisect_left(days, real_time, key=_closed)
    return days[i] if i < len(days) and days[i].holds(real_time) else None


def _closed(day: Day) -> float:
    return math.inf if day.closed is None else day.closed


def counted_move(payload: Mapping[str, Any]) -> str | None:
    """What a `move` counts as among a day's counts: `dish`, a portion from the kitchen, bought
    or handed over by the chef; `sale`, anything else bought, at the Store's counter; `gift`,
    anything else passed from one resident to another, money among it; None for what was taken,
    left or eaten."""
    if payload["source"] == PORTIONS:
        return "dish"
    return {"buy": "sale", "pass": "gift"}.get(payload["reason"])
