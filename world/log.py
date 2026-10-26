"""The world log, `world.jsonl`: every event of the town, append-only, the run's ground truth.

Each entry has a sequence number (consecutive from 1 across the whole run, resumptions
included), its kind (one of `KINDS`), the simulated and the real time, the actor and the place
where there is one, the audience (the residents who perceived it), the text for nobody in
particular, the wording for each resident it concerns where that differs (naming the resident
"you"), and a payload of the facts for analysis. Residents never read the log.

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
    "time": "a resident waiting idle was told the time",
    "board_posted": "the day's board posted, at midnight and as a new world starts",
    "start_work": "a resident started work",
    "leave_work": "a resident stopped work, or the exchange or the forced sleep stopped it",
    "claim": "a resident claimed a task and got a workspace",
    "command": "a shell command run in a workspace, with its exit code and output tail",
    "file_read": "a file read in a workspace",
    "file_write": "a file written in a workspace",
    "submission": "a resident submitted its workspace's changes",
    "verdict": "the acceptance verdict on a submission",
    "payment": "a resident was paid for an accepted task",
    "abandon": "a resident gave up its task",
    "expiry": "a claim ran out unpaid at midnight",
    "workspace_closed": "a workspace closed at the checkpoint, its changes kept",
    "speech": "something said, with its text and recipients",
    "leave_conversation": "a resident left a conversation",
    "conversation_end": "a conversation ended",
    "gift": "money handed from one resident to another, a gift or a loan on their own terms",
    "skill_shared": "a skill file's text handed to another resident",
    "message": "a written message from one resident to another, read wherever the other is",
    "purchase": "a good bought, with its price, and consumed at once if it is immediate",
    "move_in": "a resident moved into another home",
    "exchange_pairing": "the evening pairing of group B",
    "meeting": "a paired exchange began",
    "settlement": "the rent and fees charged at midnight, with the statement and the day's food",
    "hungry": "a resident took no food in the day and cannot sit down to work until it eats",
    "sleep": "a resident went to bed, with its journal entry and the ratings it read",
    "rating": "a rating given at night",
    "fell_asleep": "a resident in bed fell asleep",
    "forced_sleep": "a resident still up at the forced hour fell asleep without a journal entry",
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
