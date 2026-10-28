"""The timeline of a run: every resident's events side by side, built from the world log.

`timeline(run_dir)` reads the town of the run's frozen configuration and the run's world log
and returns plain, JSON-serialisable data. Times are simulated seconds since 00:00 of day 1.

    {
      "start_date": "2001-01-01",   the date of day 1
      "currency": "$",
      "start": 9000,                when the world began: the checkpoint hour of day 1
      "now": 95400,                 the time of the last entry in the log
      "places": {"workshop": "the workshop", ...},
      "days": [{"day": 1, "start": 9000, "end": 95400,
                "real_start": 1792871249.7, "real_end": 1792880505.6}, ...],
          the lived days, from one checkpoint to the next; the day in progress ends at null.
          "real_start" and "real_end" are the real (Unix) times at which the day was begun and
          checkpointed: it was begun at the checkpoint before it, at the resumption that went
          back to that checkpoint, or, for day 1, at the first entry of the log, the board
          posted as the world began; null with no entries at all
      "residents": [{
          "name": "Mei",
          "home": "mill-street-house",
          "segments": [{"kind": "sleep", "start": 9000, "end": 25200,
                        "place": "mill-street-house", "task": null}, ...],
              the base event, contiguous from "start" to "now": "idle", "movement" (its place
              is the destination), "work" (its task is the task held, a new segment when that
              changes), "sleep" (in bed and asleep alike) or "dead" (at no place, to the end)
          "conversations": [{"start", "end", "place", "over": "work", "with": ["Tomas"]}, ...],
              the conversations layered over the base event they interrupted ("over" is its
              kind when the conversation began); "with" is whom the resident spoke to or heard
              from in it
          "markers": [{"seq", "t", "kind", "place", ...}, ...],
          "purse": [[9000, 120], [36000, 140], ...]   the purse after each change
      }, ...]
    }

The markers, each on the lane of the resident who acted, with their own fields:

    claim         task, instance_id
    submission    task; and once the verdict is in: resolved, status, fail_to_pass, pass_to_pass
                  (passed and total counts)
    payment       task, amount
    abandon       task                    the resident gave its task up
    expiry        task                    the claim ran out unpaid
    speech        text, to, private       "to" is everyone who heard it
    message       to, text                a written message, read by "to" alone
    gift          to, amount              money given; or to, item, name, quantity for a thing
                                          or helpings of a stock
    skill_shared  to, file                a copy of one of the resident's files passed on
    purchase      item, name, quantity, amount
    move_in       from, to                the resident moved house; its lane's home follows
    journal       text, day, wake         going to bed with the day's journal entry (a bedtime
                                          without one has no marker)
    forced_sleep  wake
    settlement    rent, fees, nourishment, satiety, energy, health, night
                  midnight: the rent and the daily charges taken, the day's food as a share of
                  a day's need, the body's numbers after the night's reckoning and how health
                  moved, by cause (the purse after the charges is a point of "purse")
    condition     need, band, value, lowest   a need of the body crossed into another band
    death                                the resident's health ran out; its lane is dead from here

The log is the only source. A running run's clock may be ahead of its last entry; the open
segment and conversation end at "now" all the same. When the world went back to a checkpoint,
the entries the lost day left between that checkpoint (or the start, for day 0) and the
`resume` entry are set aside.

The data of each run directory is cached with the size of its log; a call on a log that has
grown reads only the lines appended since (a line still being written waits for the next call)
and rebuilds the data from the kept entries.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from infrastructure.config import load_config
from infrastructure.storage import RunDirectory
from simulation.config import ExperimentConfig
from world.clock import parse_hour
from world.config import TownConfig

_FOLDED = frozenset(
    {
        "wake",
        "depart",
        "arrive",
        "board_posted",
        "start_work",
        "leave_work",
        "sleep",
        "forced_sleep",
        "claim",
        "submission",
        "verdict",
        "payment",
        "abandon",
        "expiry",
        "speech",
        "message",
        "leave_conversation",
        "conversation_end",
        "gift",
        "skill_shared",
        "purchase",
        "move_in",
        "settlement",
        "condition",
        "death",
        "checkpoint",
        "resume",
    }
)
"""The kinds of entry the timeline is built from; the rest (commands, file reads and writes,
the time told) add nothing to it. The board posted as the run starts is its first entry, kept
for the real time at which day 1 was begun; a `resume` is kept after it has set the lost day
aside, for the real time at which the day was begun again."""


@dataclass
class _Cache:
    """What a run's log has given so far: `offset` is the bytes read, `now` the time of the
    last entry read, `entries` those of the kinds folded."""

    town: TownConfig
    offset: int = 0
    now: int | None = None
    entries: list[dict[str, Any]] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


_caches: dict[Path, _Cache] = {}
_lock = threading.Lock()


def timeline(run_dir: Path) -> dict[str, Any]:
    """The timeline of the run in `run_dir`, as the module docstring describes it."""
    run = RunDirectory(run_dir)
    path = run.world_log_path
    key = run_dir.resolve()
    with _lock:
        size = path.stat().st_size if path.exists() else 0
        cache = _caches.get(key)
        if cache is None or size < cache.offset:  # new, or a log written afresh
            town = load_config(run.config_path, ExperimentConfig, record=True).town
            cache = _caches[key] = _Cache(town)
            cache.data = _build(cache.town, cache.entries, cache.now)
        try:
            if size > cache.offset and _read(cache, path):
                cache.data = _build(cache.town, cache.entries, cache.now)
        except ValueError:
            del _caches[key]  # read again from the start next time, and fail again
            raise
        return cache.data


def _read(cache: _Cache, path: Path) -> bool:
    """Read the whole lines appended since the last read; whether there were any."""
    with path.open("rb") as file:
        file.seek(cache.offset)
        chunk = file.read()
    whole = chunk[: chunk.rfind(b"\n") + 1]
    for line in whole.splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}: a malformed entry: {error}") from error
        cache.now = entry["sim_time"]
        kind = entry["kind"]
        if kind == "resume":
            _set_aside_lost_day(cache.entries, entry)
        if kind in _FOLDED:
            payload = entry["payload"]
            if kind == "submission":
                payload = {key: value for key, value in payload.items() if key != "patch"}
            cache.entries.append({key: entry[key] for key in _KEPT} | {"payload": payload})
    cache.offset += len(whole)
    return bool(whole)


_KEPT = ("seq", "kind", "sim_time", "real_time", "actor", "place", "audience")


def _set_aside_lost_day(entries: list[dict[str, Any]], resume: dict[str, Any]) -> None:
    """Drop what was kept after the checkpoint `resume` went back to; the checkpoint of day 0,
    taken before the first day, is the world's start."""
    day = resume["payload"]["day"]
    if day == 0:
        entries.clear()
        return
    for index in range(len(entries) - 1, -1, -1):
        entry = entries[index]
        if entry["kind"] == "checkpoint" and entry["payload"]["day"] == day:
            del entries[index + 1 :]
            return
    raise ValueError(f"entry {resume['seq']} resumes day {day}, which has no checkpoint")


class _Lane:
    """One resident's timeline as it is built."""

    def __init__(self, name: str, home: str, purse: int, start: int) -> None:
        self.name, self.home = name, home
        self.segments: list[dict[str, Any]] = []
        self.conversations: list[dict[str, Any]] = []
        self.markers: list[dict[str, Any]] = []
        self.purse: list[list[int]] = [[start, purse]]
        self.task: int | None = None
        self.talk: dict[str, Any] | None = None
        self.submitted: dict[str, Any] | None = None
        self.segments.append(
            {"kind": "sleep", "start": start, "end": None, "place": home, "task": None}
        )

    def enter(self, t: int, kind: str, place: str | None) -> None:
        """Begin the base event `kind` at `t`; nothing changes if it is the current one. A
        segment that would last no time is replaced, and merges with the one before it if they
        are alike, so that the segments stay contiguous and distinct."""
        task = self.task if kind == "work" else None
        key = (kind, place, task)
        current = self.segments[-1]
        if (current["kind"], current["place"], current["task"]) == key:
            return
        if current["start"] == t and len(self.segments) > 1:
            self.segments.pop()
            previous = self.segments[-1]
            if (previous["kind"], previous["place"], previous["task"]) == key:
                previous["end"] = None
                return
        else:
            current["end"] = t
        self.segments.append({"kind": kind, "start": t, "end": None, "place": place, "task": task})

    def hold(self, t: int, task: int | None) -> None:
        """The task held is now `task`; a work segment in progress is split there."""
        self.task = task
        current = self.segments[-1]
        if current["kind"] == "work":
            self.enter(t, "work", current["place"])

    def join(self, t: int, place: str | None, others: list[str]) -> None:
        if self.talk is None:
            over = self.segments[-1]["kind"]
            self.talk = {"start": t, "end": None, "place": place, "over": over, "with": []}
            self.conversations.append(self.talk)
        self.talk["with"].extend(name for name in others if name not in self.talk["with"])

    def part(self, t: int, seq: int) -> None:
        if self.talk is None:
            raise ValueError(f"entry {seq}: {self.name} leaves a conversation it is not in")
        self.talk["end"] = t
        self.talk = None

    def mark(self, entry: dict[str, Any], kind: str, **fields: Any) -> dict[str, Any]:
        marker = {
            "seq": entry["seq"],
            "t": entry["sim_time"],
            "kind": kind,
            "place": entry["place"],
            **fields,
        }
        self.markers.append(marker)
        return marker

    def credit(self, t: int, amount: int) -> None:
        self.purse.append([t, self.purse[-1][1] + amount])

    def data(self, now: int) -> dict[str, Any]:
        for span in (self.segments[-1], self.talk):
            if span is not None:
                span["end"] = now
        return {
            "name": self.name,
            "home": self.home,
            "segments": self.segments,
            "conversations": self.conversations,
            "markers": self.markers,
            "purse": self.purse,
        }


def _build(town: TownConfig, entries: list[dict[str, Any]], now: int | None) -> dict[str, Any]:
    start = parse_hour(town.day.checkpoint)
    lanes = {r.name: _Lane(r.name, r.home, r.purse, start) for r in town.residents}
    days: list[dict[str, Any]] = []
    begun = entries[0]["real_time"] if entries else None  # the real time the day was begun
    for entry in entries:
        kind, t, payload = entry["kind"], entry["sim_time"], entry["payload"]
        place = entry["place"]
        lane = lanes.get(entry["actor"])  # the actor's, where there is one
        if kind in ("wake", "start_work", "leave_work"):
            lane.enter(t, "work" if kind == "start_work" else "idle", place)
        elif kind == "depart":
            lane.enter(t, "movement", payload["to"])
        elif kind == "arrive":
            lane.enter(t, "idle", payload["place"])
        elif kind == "sleep":
            lane.enter(t, "sleep", place)
            if payload["journal"]:
                journal = payload["journal"]
                lane.mark(entry, "journal", text=journal, day=payload["day"], wake=payload["wake"])
        elif kind == "forced_sleep":
            lane.enter(t, "sleep", lane.home)
            lane.mark(entry, "forced_sleep", wake=payload["wake"])
        elif kind == "claim":
            lane.hold(t, payload["task"])
            instance = payload["instance_id"]
            lane.mark(entry, "claim", task=payload["task"], instance_id=instance)
        elif kind == "submission":
            lane.submitted = lane.mark(entry, "submission", task=payload["task"])
        elif kind == "verdict":
            if lane.submitted is None or lane.submitted["task"] != payload["task"]:
                raise ValueError(f"entry {entry['seq']}: a verdict on no submission")
            lane.submitted.update(
                resolved=payload["resolved"],
                status=payload["status"],
                fail_to_pass=payload["fail_to_pass"],
                pass_to_pass=payload["pass_to_pass"],
            )
            lane.submitted = None
        elif kind == "payment":
            lane.hold(t, None)
            lane.mark(entry, "payment", task=payload["task"], amount=payload["amount"])
            lane.purse.append([t, payload["purse"]])
        elif kind in ("abandon", "expiry"):
            lane.hold(t, None)
            lane.mark(entry, kind, task=payload["task"])
        elif kind == "speech":
            heard = payload["to"]
            # Those in the conversation: the log says who since a remark stopped drawing in
            # everyone who heard it; older logs leave it to the audience.
            people = payload["members"] if "members" in payload else [lane.name, *heard]
            for name in people:
                lanes[name].join(t, place, [other for other in people if other != name])
            lane.mark(entry, "speech", text=payload["text"], to=heard, private=payload["private"])
        elif kind == "leave_conversation":
            lane.part(t, entry["seq"])
        elif kind == "conversation_end":
            for name in entry["audience"]:
                lanes[name].part(t, entry["seq"])
        elif kind == "message":
            lane.mark(entry, "message", to=payload["to"], text=payload["text"])
        elif kind == "gift" and "amount" in payload:  # money
            lane.mark(entry, "gift", to=payload["to"], amount=payload["amount"])
            lane.credit(t, -payload["amount"])
            lanes[payload["to"]].credit(t, payload["amount"])
        elif kind == "gift":  # a thing, or helpings of a stock
            lane.mark(
                entry,
                "gift",
                to=payload["to"],
                item=payload["item"],
                name=payload["name"],
                quantity=payload["quantity"],
            )
        elif kind == "purchase":
            lane.mark(
                entry,
                "purchase",
                item=payload["item"],
                name=payload["name"],
                quantity=payload["quantity"],
                amount=payload["amount"],
            )
            lane.credit(t, -payload["amount"])
        elif kind == "move_in":
            lane.home = payload["to"]
            lane.mark(entry, "move_in", **{"from": payload["from"], "to": payload["to"]})
        elif kind == "skill_shared":  # a log from before any file was shared names a skill
            file = payload["file"] if "file" in payload else f"skills/{payload['skill']}.md"
            lane.mark(entry, "skill_shared", to=payload["to"], file=file)
        elif kind == "settlement":
            lane.purse.append([t, payload["purse"]])
            lane.mark(
                entry,
                "settlement",
                rent=payload["rent"],
                fees=payload["fees"],
                nourishment=payload["nourishment"],
                satiety=payload["satiety"],
                energy=payload["energy"],
                health=payload["health"],
                night=payload["night"],
            )
        elif kind == "condition":
            lane.mark(
                entry,
                "condition",
                need=payload["need"],
                band=payload["band"],
                value=payload["value"],
                lowest=payload["lowest"],
            )
        elif kind == "death":
            lane.hold(t, None)
            lane.enter(t, "dead", None)
            lane.mark(entry, "death")
        elif kind == "checkpoint":
            days.append(
                {
                    "day": payload["day"],
                    "start": days[-1]["end"] if days else start,
                    "end": t,
                    "real_start": begun,
                    "real_end": entry["real_time"],
                }
            )
            begun = entry["real_time"]
        elif kind == "resume":
            begun = entry["real_time"]
    end = start if now is None else now
    if not days or end > days[-1]["end"]:
        days.append(
            {
                "day": days[-1]["day"] + 1 if days else 1,
                "start": days[-1]["end"] if days else start,
                "end": None,
                "real_start": begun,
                "real_end": None,
            }
        )
    return {
        "start_date": town.start_date.isoformat(),
        "currency": town.currency,
        "start": start,
        "now": end,
        "places": {place.id: place.name for place in town.places},
        "days": days,
        "residents": [lane.data(end) for lane in lanes.values()],
    }
