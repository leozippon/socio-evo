"""The world log, `world.jsonl`: every event of the town, append-only, the run's ground truth.

Each entry has a sequence number (consecutive from 1 across the whole run, resumptions
included), its kind (one of `KINDS`), the simulated and the real time, the actor and the place
where there is one, the audience (the residents who perceived it), the text for nobody in
particular, the wording for each resident it concerns where that differs (naming the resident
"you"), and a payload of the facts for analysis; an entry about a task held by two names the
other holder in its payload as `with`. Residents never read the log.

A log is reopened on resumption and its sequence continues after the last line written. The
entries a lost day left after the last checkpoint stay in the file; the `resume` entry that
follows them names the checkpoint the world went back to, so an analysis can set them aside.
"""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from infrastructure.storage import append_jsonl, read_jsonl

KINDS = {
    "wake": "a resident woke up at home, at its hour or woken for the evening exchange",
    "depart": "a resident set off for another place",
    "arrive": "a resident arrived somewhere",
    "time": "a resident waiting was told the time, or that what it was just told ended its wait",
    "board_posted": "the day's board posted at the workplace in the morning; where the town has "
    "clients' projects, those formed on it (projects: repo and tasks of each)",
    "start_work": "a resident sat down to work, claiming a task or acting in its workspace",
    "leave_work": "a resident stopped work, or the exchange or the forced sleep stopped it",
    "claim": "a resident claimed a task and got a workspace; the first claim of a task for two "
    "(for_two) waits for a second, which joins it",
    "command": "a shell command run in a workspace, with its exit code and output tail",
    "file_read": "a file read in a workspace",
    "file_write": "a file written in a workspace",
    "submission": "a resident submitted its workspace's changes; a task for two goes to the "
    "checks at the second of its holders' submissions",
    "verdict": "the acceptance verdict on a submission",
    "payment": "a resident was paid for an accepted task",
    "bonus": "a resident paid for one of the tasks of a client's project received its bonus, all "
    "of them accepted in time (payload: tasks, the day it was posted, amount, purse)",
    "abandon": "a resident gave up its task",
    "expiry": "a claim ran out unpaid at midnight",
    "workspace_closed": "a workspace closed at the checkpoint, its changes kept",
    "speech": "something said, with its text and recipients",
    "leave_conversation": "a resident left a conversation",
    "conversation_end": "a conversation ended",
    "gift": "money, a thing or helpings of a stock handed from one resident to another, on "
    "their own terms (payload: to, and amount of money or item, name and quantity)",
    "skill_shared": "a copy of one of a resident's files, its journal excepted, handed to another",
    "message": "a written message from one resident to another, read wherever the other is",
    "purchase": "a good bought, with its price, and consumed at once if it is immediate",
    "move_in": "a resident moved into another home",
    "exchange_pairing": "the evening pairing of group B",
    "meeting": "a paired exchange began",
    "settlement": "the rent and fees charged at midnight, with the statement, the day's food and "
    "the body's numbers after the night's reckoning of health",
    "condition": "a need of a resident's body crossed into another band; told to it if awake",
    "death": "a resident's health ran out at midnight: its life ended, and the others were told",
    "sleep": "a resident went to bed, with the journal entry it gave, if any, and ratings read",
    "rating": "a rating given at night",
    "fell_asleep": "a resident in bed fell asleep",
    "forced_sleep": "a resident still up at the forced hour fell asleep without going to bed",
    "checkpoint": "the day's checkpoint",
    "resume": "the world went back to a checkpoint",
}


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
