"""The timeline of a run: every resident's events side by side, and the town's own state, built
from the world log.

`timeline(run_dir)` reads the town of the run's frozen configuration and the run's world log
and returns plain, JSON-serialisable data. Times are simulated seconds since 00:00 of day 1.

    {
      "start_date": "2001-01-01",   the date of day 1
      "currency": "$",
      "start": 16200,               when the world began: the checkpoint hour of day 1
      "now": 95400,                 the time of the last entry in the log
      "places": {"office": "the Office", ...},
      "days": [{"day": 1, "start": 16200, "end": 102600,
                "real_start": 1792871249.7, "real_end": 1792880505.6}, ...],
          the lived days, from one checkpoint to the next; the day in progress ends at null.
          "real_start" and "real_end" are the real (Unix) times at which the day was begun and
          checkpointed: it was begun at the checkpoint before it, at the resumption that went
          back to that checkpoint, or, for day 1, at the first entry of the log the timeline
          keeps; null with no entries at all
      "residents": [{
          "name": "Mei",
          "home": "mill-street-house",
          "segments": [{"kind": "sleep", "start": 16200, "end": 25200,
                        "place": "mill-street-house", "task": null}, ...],
              the base event, contiguous from "start" to "now": "idle", "movement" (its place
              is the destination), "work" (its task is the task held, a new segment when that
              changes), "sleep" (in bed and asleep alike) or "bedridden" (awake in bed at home,
              too ill to get up, until treated)
          "conversations": [{"start", "end", "place", "over": "work", "with": ["Tomas"]}, ...],
              the conversations layered over the base event they interrupted ("over" is its
              kind when the conversation began); "with" is whom the resident spoke to or heard
              from in it
          "markers": [{"seq", "t", "kind", "place", ...}, ...],
          "purse": [[16200, 240], [36000, 260], ...]   the money held after each change
      }, ...],
      "markers": [{"seq", "t", "kind", "place", ...}, ...],
          what happened to no resident in particular: task_arrived, task_withdrawn, delivery
      "tasks": [{"task": 170, "instance_id": "...", "repo": "...", "arrived": 36782,
                 "deadline": 345600, "holders": [[36859, "Aisha", null], [36887, null, null]],
                 "accepted": 36887, "by": "Aisha", "withdrawn": null}, ...],
          the Office's tasks in the order they came in: when the client withdraws one not
          accepted ("deadline", the midnight that ends the day `work.expiry_days` after its
          arrival), who held it from when (`[time, holder or null, the team leader who gave it
          or null]`: a claim, an assignment, and null when it was given up, accepted or
          withdrawn), when it was accepted and who handed it in, when it was withdrawn
      "store": {"prices": [[t, {item: price}]], "on_order": [[t, {item: units}]]},
      "kitchen": {"menu": [[t, {dish: price}]]},
      "fees": [[t, {"examination": 20, "treatment": 60}]]
          the Store's prices and what it has on order, the menu's prices and the Hospital's
          fees, from the start (the configuration's) and after each change: an order, a
          delivery, a price set; what the holders of items hold over time is the bundle's
          (`frontend.bundle.holdings`), from the checkpoints and the moves
    }

The markers, each on the lane of the resident who acted, with their own fields:

    claim         task, instance_id
    assign        task, to, from          the team leader gave a task to `to`, taking it from
                                          `from` (or null); the holders follow
    submission    task; and once the verdict is in: resolved, status, fail_to_pass, pass_to_pass
                  (passed and total counts)
    abandon       task                    the resident gave its task up
    service       for, task, amount, paid, owed   a sum paid at once for a service: for `task`
                                          (one's own task accepted), `team` (the team leader's
                                          for the programmers'), `sale`, `dish` or `patient`
    speech        text, to, private       "to" is the addressees, who heard the words: those
                                          named, or everyone there for a remark to all; the
                                          bystanders of a private remark are not among them
    message       to, text                a written message, read by "to" alone
    move          item, units, source, target, money, reason, seller   the log's `move` as
                                          recorded: units of an item, or money alone (item
                                          null), from one holder to another, by reason: get,
                                          put, pass, eat or buy
    order         item, name, quantity, amount, arrives   the shopkeeper's order, paid by the fund
    cook          dish, name, portions, used   portions the chef cooked from the kitchen's stock
    price         item, name, place, price, before   a price set at the Store, the restaurant
                                          or the Hospital
    examination   patient, fee, satiety, energy, health, ill, night   the doctor's examination
                                          and the numbers it told
    treatment     patient, fee, restores, before, health, ill, bedridden
    report                                the mayor read the town's report
    announcement  text                    the mayor's announcement, told to everyone
    illness       chance, nights, health  the resident fell ill at midnight
    recovered     illness, bedridden, treated, health   an illness passed or was treated, or a
                                          bed was left
    bedridden     day, home, from, carried, task   health ran out at midnight: in bed at home
    move_in       from, to                the resident moved house; its lane's home follows
    journal       text, day, wake         going to bed with the day's journal entry (a bedtime
                                          without one has no marker)
    forced_sleep  wake
    wage          hours, wages, tax, tax_from_purse, owed_before, rent, charges, arrears_before,
                  remainder, paid, owed, arrears   the midnight's wages for the day's hours at
                                          work, with the tax (what the wages did not cover of it
                                          from the purse), the rent and charges taken out of
                                          them (the money after them is a point of "purse")
    settlement    nourishment, satiety, energy, health, night, ill   the midnight statement:
                                          the day's food as a share of a day's need, the body's
                                          numbers after the night's reckoning, how health moved,
                                          by cause, and the nights of illness to come
    condition     need, band, value, lowest   a need of the body crossed into another band

and those of no resident, under "markers":

    task_arrived    task, instance_id, repo   a client's task came in at the Office
    task_withdrawn  task, holder              a client withdrew a task not accepted in time
    delivery        items                     what the Store ordered arrived ({item: units})

The purse moves with every sum of money the log records: the money after a service and after
the midnight's wages, money passed and received, what a resident paid for what it bought for
itself (at the Store's counter, or a dish), and the Hospital's fee a patient paid; what the chef
buys for the kitchen the fund pays.

The log is the only source, read by day as `world.log.Days` cuts it: the entries a lost day
left after the checkpoint a `resume` went back to (or the start, for day 0) are set aside. A
running run's clock may be ahead of its last entry; the open segment and conversation end at
"now" all the same.

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
from world.clock import DAY, calendar_day, parse_hour
from world.config import TownConfig
from world.economy import add, take
from world.log import KINDS, Day, Days

_FOLDED = frozenset(
    {
        "wake",
        "depart",
        "arrive",
        "start_work",
        "leave_work",
        "sleep",
        "forced_sleep",
        "task_arrived",
        "task_withdrawn",
        "claim",
        "assign",
        "submission",
        "verdict",
        "service",
        "abandon",
        "speech",
        "message",
        "leave_conversation",
        "conversation_end",
        "move",
        "order",
        "delivery",
        "cook",
        "price",
        "examination",
        "treatment",
        "report",
        "announcement",
        "illness",
        "recovered",
        "bedridden",
        "move_in",
        "wage",
        "settlement",
        "condition",
        "checkpoint",
        "resume",
    }
)
"""The kinds of entry the timeline is built from; the rest (commands, file reads and writes,
the time told, falling asleep) add nothing to it. The first of them is kept for the real time
at which day 1 was begun; the checkpoints and resumptions cut the days."""
_LEFT_OUT = {"service": "money", "wage": "money", "move_in": "rent"}
"""What a marker leaves out of its entry's payload: the money held after a sum or the wages,
which is a point of the purse, and the rent of a home moved into, which the town's places give."""
_COPIED = {
    kind: tuple(field for field in KINDS[kind].payload if field != _LEFT_OUT.get(kind))
    for kind in (
        "claim",
        "assign",
        "abandon",
        "service",
        "message",
        "order",
        "cook",
        "price",
        "examination",
        "treatment",
        "report",
        "announcement",
        "illness",
        "recovered",
        "bedridden",
        "move",
        "move_in",
        "wage",
        "settlement",
        "condition",
    )
}
"""The markers whose fields are the entry's payload as recorded (`world.log.KINDS`), and those
fields."""


@dataclass
class _Cache:
    """What a run's log has given so far: `offset` is the bytes read, `now` the time of the
    last entry read, `days` the entries of the kinds folded, by lived day."""

    town: TownConfig
    offset: int = 0
    now: int | None = None
    days: Days = field(default_factory=Days)
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
            town = load_config(run.config_path, ExperimentConfig).town
            cache = _caches[key] = _Cache(town)
            cache.data = _build(cache.town, cache.days, cache.now)
        try:
            if size > cache.offset and _read(cache, path):
                cache.data = _build(cache.town, cache.days, cache.now)
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
        if kind in _FOLDED:
            payload = entry["payload"]
            if kind == "submission":
                payload = {key: value for key, value in payload.items() if key != "patch"}
            cache.days.add({key: entry[key] for key in _KEPT} | {"payload": payload})
    cache.offset += len(whole)
    return bool(whole)


_KEPT = ("seq", "kind", "sim_time", "real_time", "actor", "place", "audience")


def _marker(entry: dict[str, Any], kind: str, **fields: Any) -> dict[str, Any]:
    found = {"seq": entry["seq"], "t": entry["sim_time"], "kind": kind, "place": entry["place"]}
    return found | fields


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
        self.bedridden = False
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
        marker = _marker(entry, kind, **fields)
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


class _Series:
    """A state of the town (prices, orders) as it is built: `[time, state]` from the start and
    after each change, a change at the same moment replacing the point before."""

    def __init__(self, start: int, state: dict[str, int]) -> None:
        self.state = dict(state)
        self.points: list[list[Any]] = [[start, dict(state)]]

    def changed(self, t: int) -> None:
        if t == self.points[-1][0]:
            self.points[-1][1] = dict(self.state)
        elif self.state != self.points[-1][1]:
            self.points.append([t, dict(self.state)])


def _begun(day: Day) -> float | None:
    """The real time at which `day` was begun: when it opened or, for the first day, at its first
    entry; None with no entries at all."""
    if day.opened is not None:
        return day.opened
    return day.entries[0]["real_time"] if day.entries else None


def _build(town: TownConfig, lived: Days, now: int | None) -> dict[str, Any]:
    start = parse_hour(town.day.checkpoint)
    lanes = {r.name: _Lane(r.name, r.home, r.purse, start) for r in town.residents}
    kinds = {place.id: place.kind for place in town.places}
    markers: list[dict[str, Any]] = []
    tasks: dict[int, dict[str, Any]] = {}
    prices = _Series(start, {item.id: item.price for item in town.supplied})
    on_order = _Series(start, {})
    menu = _Series(start, {dish.id: dish.price for dish in town.dishes})
    hospital = town.hospital
    fees = _Series(start, {"examination": hospital.examination, "treatment": hospital.treatment})
    priced = {"store": prices, "restaurant": menu, "hospital": fees}
    days: list[dict[str, Any]] = []
    for day in lived.closed.values():
        days.append(
            {
                "day": day.number,
                "start": days[-1]["end"] if days else start,
                "end": day.entries[-1]["sim_time"],
                "real_start": _begun(day),
                "real_end": day.closed,
            }
        )
    entries = [e for day in [*lived.closed.values(), lived.open] for e in day.entries]

    def task(number: int, seq: int) -> dict[str, Any]:
        if number not in tasks:
            raise ValueError(f"entry {seq}: task {number} never came in")
        return tasks[number]

    for entry in entries:
        kind, t, payload = entry["kind"], entry["sim_time"], entry["payload"]
        place = entry["place"]
        lane = lanes.get(entry["actor"])  # the actor's, where there is one
        if kind in _COPIED:
            lane.mark(entry, kind, **{key: payload[key] for key in _COPIED[kind]})
        if kind == "wake":
            lane.enter(t, "bedridden" if lane.bedridden else "idle", place)
        elif kind in ("start_work", "leave_work"):
            lane.enter(t, "work" if kind == "start_work" else "idle", place)
        elif kind == "depart":
            lane.enter(t, "movement", payload["to"])
        elif kind == "arrive":
            lane.enter(t, "work" if payload["working"] else "idle", payload["place"])
        elif kind == "sleep":
            lane.enter(t, "sleep", place)
            if payload["journal"]:
                journal = payload["journal"]
                lane.mark(entry, "journal", text=journal, day=payload["day"], wake=payload["wake"])
        elif kind == "forced_sleep":
            lane.enter(t, "sleep", lane.home)
            lane.mark(entry, "forced_sleep", wake=payload["wake"])
        elif kind == "task_arrived":
            number = payload["task"]
            fields = {key: payload[key] for key in ("task", "instance_id", "repo")}
            markers.append(_marker(entry, kind, **fields))
            deadline = (calendar_day(t) + town.work.expiry_days) * DAY
            tasks[number] = fields | {
                "arrived": t,
                "deadline": deadline,
                "holders": [],
                "accepted": None,
                "by": None,
                "withdrawn": None,
            }
        elif kind == "task_withdrawn":
            holder, found = payload["holder"], task(payload["task"], entry["seq"])
            markers.append(_marker(entry, kind, task=payload["task"], holder=holder))
            found["withdrawn"] = t
            if holder is not None:
                lanes[holder].hold(t, None)
                found["holders"].append([t, None, None])
        elif kind == "claim":
            lane.hold(t, payload["task"])
            task(payload["task"], entry["seq"])["holders"].append([t, lane.name, None])
        elif kind == "assign":
            if payload["from"] is not None:
                lanes[payload["from"]].hold(t, None)
            lanes[payload["to"]].hold(t, payload["task"])
            given = [t, payload["to"], lane.name]
            task(payload["task"], entry["seq"])["holders"].append(given)
        elif kind == "abandon":
            lane.hold(t, None)
            task(payload["task"], entry["seq"])["holders"].append([t, None, None])
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
            if payload["resolved"] and payload["held"]:  # accepted, and paid for
                lane.hold(t, None)
                found = task(payload["task"], entry["seq"])
                found.update(accepted=t, by=lane.name)
                found["holders"].append([t, None, None])
        elif kind in ("service", "wage"):
            lane.purse.append([t, payload["money"]])
        elif kind == "speech":
            heard, members = payload["to"], payload["members"]  # no members: nobody drawn in
            for name in members:
                lanes[name].join(t, place, [other for other in members if other != name])
            lane.mark(entry, "speech", text=payload["text"], to=heard, private=payload["private"])
        elif kind == "leave_conversation":
            lane.part(t, entry["seq"])
        elif kind == "conversation_end":
            for name in entry["audience"]:
                lanes[name].part(t, entry["seq"])
        elif kind == "move":
            paid, target = payload["money"], payload["target"]
            if payload["reason"] == "pass" and payload["item"] is None:  # money handed over
                lane.credit(t, -paid)
                lanes[target].credit(t, paid)
            elif payload["reason"] == "buy" and target == lane.name:  # paid from its own money
                lane.credit(t, -paid)
        elif kind == "order":
            add(on_order.state, payload["item"], payload["quantity"])
            on_order.changed(t)
        elif kind == "delivery":
            markers.append(_marker(entry, kind, items=payload["items"]))
            for item, units in payload["items"].items():
                take(on_order.state, item, units)
            on_order.changed(t)
        elif kind == "price":
            series = priced[kinds[payload["place"]]]
            series.state[payload["item"]] = payload["price"]
            series.changed(t)
        elif kind in ("examination", "treatment"):
            lanes[payload["patient"]].credit(t, -payload["fee"])
        elif kind == "bedridden":
            lane.bedridden = True
            if lane.segments[-1]["kind"] != "sleep":  # one asleep is bedridden on waking
                lane.enter(t, "bedridden", payload["home"])
        elif kind == "recovered" and payload["bedridden"]:
            lane.bedridden = False
            if lane.segments[-1]["kind"] == "bedridden":
                lane.enter(t, "idle", lane.segments[-1]["place"])
        elif kind == "move_in":
            lane.home = payload["to"]
    end = start if now is None else now
    if not days or end > days[-1]["end"]:
        days.append(
            {
                "day": lived.open.number,
                "start": days[-1]["end"] if days else start,
                "end": None,
                "real_start": _begun(lived.open),
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
        "markers": markers,
        "tasks": list(tasks.values()),
        "store": {"prices": prices.points, "on_order": on_order.points},
        "kitchen": {"menu": menu.points},
        "fees": fees.points,
    }
