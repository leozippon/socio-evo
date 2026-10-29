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
    "wake": "a resident woke up at home",
    "depart": "a resident set off for another place",
    "arrive": "a resident arrived somewhere, at work if its duty runs anywhere (payload: place, "
    "working)",
    "time": "a resident waiting was told the time, or that what it was just told ended its wait",
    "task_arrived": "a client's task came in on the Office's board, told to those there "
    "(payload: task, instance_id, repo)",
    "task_withdrawn": "a client withdrew a task not accepted in time, at midnight, told to whoever "
    "held it (payload: task, holder or null)",
    "start_work": "a resident sat down to work: with start_work, or by doing its occupation's work "
    "where it works (claiming, assigning or acting in a task's workspace, cooking, ordering, "
    "setting a price, examining or treating, reading the report, announcing)",
    "leave_work": "a resident stopped work, or the forced sleep stopped it",
    "claim": "a resident claimed a task and got a workspace",
    "assign": "the team leader gave a task to a programmer, or moved it from the one who held it, "
    "told to both (payload: task, to, from or null)",
    "command": "a shell command run in a workspace, with its exit code and output tail",
    "file_read": "a file read in a workspace",
    "file_write": "a file written in a workspace",
    "submission": "a resident submitted its workspace's changes",
    "verdict": "the acceptance verdict on a submission",
    "service": "a resident was paid a sum for a service at once, as far as the fund had it: for a "
    "task of its own accepted, for one of the programmers' to the team leader, for a sale to the "
    "shopkeeper, for a dish served to the chef, for a patient examined or treated to the doctor "
    "(payload: for, task or null, amount, paid, owed, money)",
    "abandon": "a resident gave up its task",
    "workspace_closed": "a workspace closed at the checkpoint, its changes kept",
    "speech": "something said, with its text and recipients",
    "leave_conversation": "a resident left a conversation",
    "conversation_end": "a conversation ended",
    "move": "units of an item, or money, that a resident moved from one holder to another: a "
    "resident (by name), what is left at a place (by its id), the Store's shelves, the kitchen's "
    "larder or its portions, or nothing (null), with the money that went with them and why: get "
    "(taken from where it was left), put (left there), pass (handed to another, money alone "
    "without an item; from the portions, the chef serving a dish nobody pays for), eat (eaten, by "
    "choice or by the body as it grew hungry, into nothing) or buy (at the Store's counter, for "
    "oneself or by the chef for the kitchen's larder, which the fund pays, or a dish from the "
    "portions); seller is who served a purchase (payload: item, units, source, target, money, "
    "reason, seller)",
    "message": "a written message from one resident to another, read wherever the other is",
    "order": "what the shopkeeper ordered from the supplier, paid by the fund at once (payload: "
    "item, name, quantity, amount, arrives)",
    "delivery": "what the Store ordered came from the supplier onto its shelves in the morning "
    "(payload: items)",
    "cook": "portions of a dish the chef cooked from the kitchen's larder (payload: dish, name, "
    "portions, used)",
    "price": "a price the shopkeeper, the chef or the doctor set (payload: item, name, place, "
    "price, before)",
    "examination": "the doctor examined a patient, who paid the fee; the numbers it was told, "
    "told to both (payload: patient, fee, satiety, energy, health, ill, night)",
    "treatment": "the doctor treated a patient, who paid the fee (payload: patient, fee, restores, "
    "before, health, ill, bedridden)",
    "report": "the mayor read the town's report (its text is not kept)",
    "announcement": "the mayor announced something, told to every resident at once or on waking "
    "(payload: text)",
    "move_in": "a resident moved into another home",
    "wage": "a resident's wages paid at midnight for its hours at work, with its rent and daily "
    "charges taken out of them (payload: hours, wages, owed_before, rent, charges, "
    "arrears_before, remainder, paid, owed, arrears, money)",
    "settlement": "the midnight statement, with the day's food and the body's numbers after the "
    "night's reckoning of health (payload: nourishment, satiety, energy, health, night, ill)",
    "illness": "a resident fell ill at midnight (payload: chance, nights, health)",
    "condition": "a need of a resident's body crossed into another band; told to it if awake",
    "bedridden": "a resident's health ran out at midnight: it took to its bed at home, carried "
    "there if it was elsewhere, until treated",
    "recovered": "a resident's illness passed at midnight, or treatment ended it or let one "
    "bedridden leave its bed (payload: illness, bedridden, treated, health)",
    "sleep": "a resident went to bed, with the journal entry it gave, if any",
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
