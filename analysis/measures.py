"""Life in the town, measured: per resident and lived day, from the world log, the checkpoints and
the residents' traces, with their daily totals and means; per lived day for the town; and the
records the measures rest on, every take and every service received with whether it was paid,
every incident with what followed it, and what each resident chose at night.

    python -m analysis.measures RUN_DIR --out DIR

DIR receives, replacing what is there, each table as `.csv` and `.json` (`incidents` as `.json`
alone, its rows being nested); it is given explicitly (by convention `results/<run>/measures`),
since analysis writes nothing under the run.

| Table | A row per | From |
| --- | --- | --- |
| `measures` | resident and lived day: `HEAD`, then `MEASURES` | log, checkpoint before, trace |
| `daily` | day and measure: total (none for a level), mean, residents with a value | `measures` |
| `town` | lived day: `day`, `date`, then `TOWN` | log, the day's checkpoint |
| `takes` | take or service received, with its payment (`takes`) | log |
| `incidents` | incident, staged or not, and what followed it (`incidents`) | log |
| `nights` | resident and complete night: what it kept, learnt (`nights`) | `done.json` |

The days are those the world log has closed (`world.log.lived_days`), so a day lost to an
interruption counts once, as it was lived again. A resident may have no occupation. A run whose log
has a move of the town before the open actions (a purchase, `buy`, or a hand-over, `pass`) is
refused: these measures read takes, gifts and eating alone.

What was taken is told by where it was taken from (`world.log.taken_from`): the Store's shelves,
the kitchen's counter or its larder, what was left at a place, or another resident, awake (in
sight of the act) or asleep. Trade is a matter of honour, since nothing charges anyone and paying
is giving the keeper the money, and this is how it is measured. A priced act is a take, by one who
does not keep the business, of something priced where it stood (on the shelves or the counter),
or an examination or a treatment of a patient other than the doctor; what is due is the price
posted times the units, or the fee posted. It is paid soon if paid before leaving the place: the
money the one who got it gave a keeper of that business (for a service, the doctor), or left on
that business's shelves, counter or larder, in its stay at the place (from its departure before
the act to its departure after it, or the day's end) is set against the stay's priced acts at
that business in the order they were made, each covered as far as the money reaches. An act is
`paid` when covered in full, `underpaid` when in part and `unpaid` when not at all; a keeper's take
from its own business is `own`; a take of what is priced nowhere (from a person, from where it
was left, an ingredient in the larder) has no status. Money given to the keeper in the same stay
for anything else counts as paying, since nothing in the log says what money is for.

An incident's record is neutral: whether it was staged, and why not, who was told, and what each
of those told did after it until the day's end, as the log has it: what it took and gave, from
and to whom, what it said and wrote, and to whom. A resident's number (`liked_by`) is the one
everyone saw on it that day, which the checkpoint that opened the day holds, since the numbers
change only at the night's end. A night's record is its `done.json`: whether the choice ended
by itself, the moments marked and kept, the examples made and how many of them new, the moments
the generalising dropped and why, the dataset's size, whether an adapter was fitted and which one
the resident woke on; a night not complete has none.

The midnight that ends a lived day settles the calendar day: the hours at work, the rent, the
salary and the treasury's takings and payments of a day are those of its calendar day, so work
after midnight counts on the next day; what was taken and given, and the money at the checkpoint,
are the lived day's. Who lies bedridden is carried from day to day: a resident takes to its bed at
a midnight (`bedridden`) and leaves it when treated (`recovered`, for one bedridden), and a visit
to it is any other resident's arrival at the home where it lies, a housemate's coming home
included. A measure is None where it has no value: a cached share that no reply reported, the money
and the health of a day without a midnight, the names given of a day it did not go to bed.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from statistics import fmean
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from agent.directory import TRACE
from infrastructure.storage import RunDirectory, read_jsonl
from learning.adapters import DONE
from world.businesses import BUSINESSES, SURGERY, Business, keeping
from world.clock import clock_time
from world.economy import MONEY, PAID, TAKEN
from world.log import TAKEN_FROM, Day, day_of, lived_days, taken_from

Entry = dict[str, Any]
"""An entry of the world log or a record of a trace, as stored."""
Row = dict[str, Any]

HEAD = ("resident", "occupation", "newcomer", "day", "date")
"""What a resident-day row of the measures begins with."""
TOOK = {
    "shelves": "takes from the Store's shelves, the shopkeeper's own among them",
    "counter": "takes from the kitchen's counter, the chef's own among them",
    "larder": "takes from the kitchen's larder",
    "place": "takes of what was left at a place",
    "awake": "takes from another resident there and awake, in its sight",
    "asleep": "takes from another resident asleep",
}
"""Each place a take is from (`world.log.TAKEN_FROM`), as its measure counts it."""
assert tuple(TOOK) == TAKEN_FROM
STATUSES = ("paid", "underpaid", "unpaid")
"""The statuses of a priced act (see the module docstring)."""
TRADE = {
    "priced": "priced acts it got from another's business: takes of what was priced where it "
    "stood, examinations and treatments",
    "paid": "of them, those paid in full before it left the place",
    "underpaid": "of them, those paid in part",
    "unpaid": "of them, those paid nothing for",
    "due": "what they came to at the prices and fees posted",
    "covered": "how much of it the money given before leaving the place covered",
}
"""The measures of trade (see the module docstring), of a resident or of the town."""

MEASURES = {
    "tasks_taken": "tasks it claimed from the Office's board",
    "tasks_assigned_to": "tasks the team leader gave it, or moved to it from another",
    "tasks_assigned_by": "tasks it gave to a programmer, or moved, as the team leader",
    "tasks_handed_in": "hand-ins of its task (acceptance runs)",
    "tasks_accepted": "hand-ins accepted while it still held the task, which the client paid for",
    "tasks_given_up": "tasks it gave up",
    "tasks_withdrawn": "tasks the client withdrew at midnight while it held them",
    "hours_at_work": "hours at work at its workplace, as the midnight counted them",
    "client_shares": "its shares of the clients' payments for tasks accepted, before the tax",
    "tax": "the tax withheld into the treasury from its shares and from money given it at work",
    "rent": "the rent, daily charges and arrears the treasury took from its purse at midnight",
    "charges": "the daily charges on what it owns, due at midnight",
    "arrears": "the rent and charges its purse could not spare, owed to the treasury after it",
    "salary": "the salary the treasury paid it at midnight",
    "salary_owed": "the salary the treasury owes it after midnight",
    "granted": "money the mayor granted it from the treasury",
    "grants_made": "money it granted from the treasury as the mayor",
    "money": "its money after midnight",
    "orders": "orders it placed with the supplier",
    "portions_cooked": "portions of dishes it cooked",
    "examinations_given": "examinations it made as the doctor",
    "examinations_received": "examinations of it",
    "treatments_given": "treatments it gave as the doctor",
    "treatments_received": "treatments of it",
    **{f"took_from_{where}": told for where, told in TOOK.items()},
    "taken_from_it_awake": "takes by others from what it carried, in its sight",
    "taken_from_it_asleep": "takes by others from what it carried, while it slept",
    "money_taken": "money it took, from anyone or from anywhere",
    **TRADE,
    "money_given": "money it gave to others, payments among it",
    "things_given": "units of things it gave to others",
    "money_received": "money others gave it",
    "things_received": "units of things others gave it",
    "money_left": "money it left at a place or on a business's shelves, counter or larder",
    "things_left": "units of things it left so",
    "incidents_told": "incidents the world staged that reached it",
    "liked_by": "how many of the others liked it, the number everyone saw on it that day",
    "likes_named": "how many it named as the people it likes, going to bed",
    "searches": "web searches it made at the Office",
    "pages_read": "web pages it read at the Office",
    "hungry": "1 if it had nothing to eat that day",
    "starving": "1 if it was starving at midnight, which wore its health",
    "ill_night": "1 if illness cost it health at midnight",
    "health": "its health at midnight, after the night's reckoning, 0 to 100",
    "bedridden": "1 if it lay bedridden at some time of the day",
    "announcements": "announcements it made as the mayor",
    "said_public": "things said to everyone present",
    "said_private": "things said to named residents",
    "heard_public": "things said by others to everyone present, heard",
    "heard_private": "things said by others to it by name",
    "interlocutors": "distinct residents it spoke or wrote to, or was spoken or written to by",
    "messages_sent": "written messages it sent",
    "messages_received": "written messages it received",
    "bedside_visits": "its arrivals at a home where another resident lay bedridden",
    "visited_in_bed": "others' arrivals at the home where it lay bedridden",
    "journal": "1 if it wrote a journal entry, going to bed",
    "forced_sleep": "1 if it was put to sleep at the forced hour",
    "requests": "model requests, retries and compactions included",
    "prompt_tokens": "prompt tokens reported",
    "completion_tokens": "completion tokens reported",
    "cached_share": "cached prompt tokens over prompt tokens, of the replies that report them",
    "lapses": "steps or compactions that found no usable reply",
    "compactions": "compactions of the context",
}
"""Every measure of a resident-day and what it counts."""
LEVELS = frozenset({"arrears", "salary_owed", "money", "health", "cached_share", "liked_by"})
"""The measures that are no count or amount, and so have no daily total."""
TOWN = {
    "tasks_arrived": "clients' tasks that came in on the Office's board",
    "tasks_accepted": "tasks accepted, which the clients paid for",
    "tasks_withdrawn": "tasks the clients withdrew at midnight, held or not",
    "clients": "what the clients paid for the tasks accepted, which came into the town",
    "supplier": "what the shopkeeper paid the supplier for the orders, which left the town",
    "money": "the residents' money at the day's checkpoint",
    "money_left": "the money lying at the places and in the businesses' holders at the checkpoint",
    "treasury": "the treasury's balance at the day's checkpoint",
    "salary_owed": "the salary the treasury owed at the checkpoint",
    "arrears": "the rent and charges the residents owed the treasury at the checkpoint",
    **{
        f"taken_{kind}": f"what the treasury took {words} that day" for kind, words in TAKEN.items()
    },
    **{
        f"paid_{kind}": f"what the treasury paid out {words} that day"
        for kind, words in PAID.items()
    },
    **{f"took_from_{where}": told for where, told in TOOK.items()},
    **TRADE,
    "incidents": "incidents the world came to stage, staged or found impossible",
    "incidents_staged": "of them, those it staged",
    "searches": "web searches made at the Office",
    "pages_read": "web pages read at the Office",
}
"""Every measure of the town's day and what it counts."""
REASONS = ("take", "give", "eat")
"""Why a resident moves a thing or money, in the town of the open actions."""
FOLLOWED = ("move", "speech", "message")
"""What of a resident's acts an incident's record keeps after it: its takes and gifts (not what
it ate), what it said and what it wrote."""


class Resident(BaseModel):
    """A resident as the measures read it: its name, its occupation (none for one without),
    whether it is a newcomer, and its agent directory, if not the run's."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    name: str
    occupation: str | None = None
    newcomer: bool = False
    agent_dir: Path | None = None


class Town(BaseModel):
    """What the measures read of a run's frozen town: the date of its first day and its
    residents. The rest is left unread, so that a run is measured without what loading its whole
    configuration would ask (the web's search key, for one)."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    start_date: date
    residents: tuple[Resident, ...]

    @property
    def names(self) -> set[str]:
        return {r.name for r in self.residents}

    def keepers(self, business: Business) -> set[str]:
        """The residents who keep `business`."""
        return {r.name for r in self.residents if business.keeps(r.occupation)}


def town(run_dir: Path) -> Town:
    """The town of the run's frozen configuration, as far as the measures read it."""
    frozen = yaml.safe_load(RunDirectory(run_dir).config_path.read_text(encoding="utf-8"))
    return Town.model_validate(frozen["town"])


def day_date(config: Town, day: int) -> date:
    return config.start_date + timedelta(days=day - 1)


def trace_days(path: Path, days: Iterable[Day]) -> dict[int, list[Entry]]:
    """The records of the trace at `path` for each of `days`, by day number: each record goes to
    the day whose span of real time holds it (`world.log.day_of`); records of no such day are
    left out."""
    ordered = sorted(days, key=lambda day: day.number)
    found: dict[int, list[Entry]] = {day.number: [] for day in ordered}
    for record in read_jsonl(path):
        day = day_of(ordered, record["real_time"])
        if day is not None:
            found[day.number].append(record)
    return found


def lived(run_dir: Path) -> tuple[Town, list[Day]]:
    """The town of the run at `run_dir` and its closed days; ValueError for a run of the town
    before the open actions, whose moves these measures do not read."""
    config = town(run_dir)
    days = list(lived_days(RunDirectory(run_dir).world_log_path).closed.values())
    for day in days:
        for e in day.entries:
            if e["kind"] == "move" and (reason := e["payload"]["reason"]) not in REASONS:
                raise ValueError(
                    f"{run_dir} is a run of the town before the open actions (its log has a "
                    f"{reason!r} move), which these measures do not read"
                )
    return config, days


def measure(run_dir: Path) -> list[Row]:
    """One row per resident and lived day of the run at `run_dir`, by resident and day."""
    config, days = lived(run_dir)
    lying, shown = beds(days), numbers(run_dir, days)
    acts = {day.number: takes_of(day, config) for day in days}
    rows = []
    for resident in config.residents:
        directory = resident.agent_dir or RunDirectory(run_dir).agent_dir(resident.name)
        traces = trace_days(directory / TRACE, days)
        for day in days:
            found = {
                "resident": resident.name,
                "occupation": resident.occupation,
                "newcomer": resident.newcomer,
                "day": day.number,
                "date": day_date(config, day.number).isoformat(),
                "liked_by": shown[day.number][resident.name],
                **world_measures(day, resident.name, config, lying[day.number], acts[day.number]),
                **trace_measures(traces[day.number]),
            }
            rows.append({key: found[key] for key in (*HEAD, *MEASURES)})
    return rows


def numbers(run_dir: Path, days: Sequence[Day]) -> dict[int, dict[str, int]]:
    """Every resident's number on each of `days`: what the checkpoint that opened the day
    shows, the numbers changing only at the night's end."""
    run = RunDirectory(run_dir)
    return {
        day.number: json.loads(run.checkpoint_path(day.number - 1).read_text(encoding="utf-8"))[
            "regard"
        ]["shown"]
        for day in days
    }


def beds(days: Sequence[Day]) -> dict[int, dict[str, str]]:
    """Who lay bedridden at the start of each of `days`, given in order, and at which home."""
    lying: dict[str, str] = {}
    found = {}
    for day in days:
        found[day.number] = dict(lying)
        for e in day.entries:
            _turn(lying, e)
    return found


def _turn(lying: dict[str, str], e: Entry) -> None:
    """`lying` after the entry `e`: one taken to its bed, or let up from it."""
    if e["kind"] == "bedridden":
        lying[e["actor"]] = e["payload"]["home"]
    elif e["kind"] == "recovered" and e["payload"]["bedridden"]:
        del lying[e["actor"]]


def takes_of(day: Day, config: Town) -> list[Row]:
    """Every take and every service received of `day`, in the log's order, with what was due and
    how much of it was paid soon (see the module docstring)."""
    names = config.names
    keepers = {kind: config.keepers(business) for kind, business in BUSINESSES.items()}
    keeps = {name: kind for kind, found in keepers.items() for name in found}
    stays: Counter[str] = Counter()
    rows: list[Row] = []
    stayed: list[tuple[str, int, str] | None] = []
    paid: Counter[tuple[str, int, str]] = Counter()
    for e in day.entries:
        kind, actor, payload = e["kind"], e["actor"], e["payload"]
        when = {"day": day.number, "time": clock_time(e["sim_time"])}
        if kind == "depart":
            stays[actor] += 1
        elif kind == "move" and payload["reason"] == "take":
            business = keeping(payload["source"])
            own = business is not None and actor in keepers[business.kind]
            stay = None
            if business is not None and payload["price"] is not None and not own:
                stay = (actor, stays[actor], business.kind)
            rows.append(
                when
                | {"resident": actor, "act": "take", "what": payload["what"]}
                | {"amount": payload["amount"], "source": payload["source"]}
                | {"from": taken_from(e, names), "price": payload["price"]}
                | {"due": payload["price"] * payload["amount"] if stay else None}
                | {"covered": None, "status": "own" if own else None}
            )
            stayed.append(stay)
        elif kind in ("examination", "treatment") and payload["patient"] != actor:
            patient = payload["patient"]
            rows.append(
                when
                | {"resident": patient, "act": kind, "what": kind, "amount": 1, "source": actor}
                | {"from": None, "price": payload["fee"], "due": payload["fee"]}
                | {"covered": None, "status": None}
            )
            stayed.append((patient, stays[patient], SURGERY.kind))
        elif kind == "move" and payload["reason"] == "give" and payload["what"] == MONEY:
            target = payload["target"]
            business = keeping(target) if target not in names else None
            to = keeps.get(target) if business is None else business.kind
            if to is not None:
                paid[actor, stays[actor], to] += payload["amount"]
    for row, stay in zip(rows, stayed, strict=True):
        if stay is not None:
            row["covered"] = covered = min(row["due"], paid[stay])
            paid[stay] -= covered
            row["status"] = STATUSES[0 if covered == row["due"] else 1 if covered else 2]
    return rows


def trade(acts: Iterable[Row]) -> Row:
    """The measures of trade (`TRADE`) of `acts`, rows of `takes_of`."""
    priced = [act for act in acts if act["status"] in STATUSES]
    counted = Counter(act["status"] for act in priced)
    return {
        "priced": len(priced),
        **{status: counted[status] for status in STATUSES},
        "due": sum(act["due"] for act in priced),
        "covered": sum(act["covered"] for act in priced),
    }


def world_measures(
    day: Day, name: str, config: Town, lying: Mapping[str, str], acts: Sequence[Row]
) -> Row:
    """The measures of `name`'s lived `day` that the world log gives, with `lying` those
    bedridden when it began and where, and `acts` the day's takes and services (`takes_of`)."""

    def mine(kind: str) -> list[Entry]:
        return [e for e in day.entries if e["kind"] == kind and e["actor"] == name]

    def to_me(kind: str, key: str) -> list[Entry]:
        return [e for e in day.entries if e["kind"] == kind and e["payload"][key] == name]

    settled, shares = mine("settlement"), mine("service")
    last = settled[-1]["payload"] if settled else None
    moves = [e for e in day.entries if e["kind"] == "move"]
    took = [e for e in moves if e["actor"] == name and e["payload"]["reason"] == "take"]
    where = Counter(taken_from(e, config.names) for e in took)
    lost = [e for e in moves if e["payload"]["reason"] == "take" and e["payload"]["source"] == name]
    gave = [e["payload"] for e in mine("move") if e["payload"]["reason"] == "give"]
    given = [p for p in gave if p["target"] in config.names]
    left = [p for p in gave if p["target"] not in config.names]
    got = [e["payload"] for e in to_me("move", "target") if e["payload"]["reason"] == "give"]
    examined, treated = to_me("examination", "patient"), to_me("treatment", "patient")
    speech = [e for e in day.entries if e["kind"] == "speech"]
    said = [e for e in speech if e["actor"] == name]
    heard = [e for e in speech if e["actor"] != name and name in e["payload"]["to"]]
    sent, written = mine("message"), to_me("message", "to")
    named = mine("likes")
    visits, visited = _visits(day, name, lying)
    return {
        "tasks_taken": len(mine("claim")),
        "tasks_assigned_to": len(to_me("assign", "to")),
        "tasks_assigned_by": len(mine("assign")),
        "tasks_handed_in": len(mine("submission")),
        "tasks_accepted": sum(
            e["payload"]["resolved"] and e["payload"]["held"] for e in mine("verdict")
        ),
        "tasks_given_up": len(mine("abandon")),
        "tasks_withdrawn": len(to_me("task_withdrawn", "holder")),
        "hours_at_work": sum(e["payload"]["hours"] for e in settled),
        "client_shares": sum(e["payload"]["amount"] for e in shares),
        "tax": sum(e["payload"]["tax"] for e in shares) + sum(p["tax"] for p in got),
        "rent": sum(e["payload"]["rent_paid"] for e in settled),
        "charges": sum(e["payload"]["charges"] for e in settled),
        "arrears": last["arrears"] if last else None,
        "salary": sum(e["payload"]["salary_paid"] for e in settled),
        "salary_owed": last["owed"] if last else None,
        "granted": sum(e["payload"]["amount"] for e in to_me("grant", "to")),
        "grants_made": sum(e["payload"]["amount"] for e in mine("grant")),
        "money": last["money"] if last else None,
        "orders": len(mine("order")),
        "portions_cooked": sum(e["payload"]["portions"] for e in mine("cook")),
        "examinations_given": len(mine("examination")),
        "examinations_received": len(examined),
        "treatments_given": len(mine("treatment")),
        "treatments_received": len(treated),
        **{f"took_from_{place}": where[place] for place in TAKEN_FROM},
        "taken_from_it_awake": sum(name in e["audience"] for e in lost),
        "taken_from_it_asleep": sum(name not in e["audience"] for e in lost),
        "money_taken": _amount(e["payload"] for e in took),
        **trade(act for act in acts if act["resident"] == name),
        "money_given": _amount(given),
        "things_given": _amount(given, things=True),
        "money_received": _amount(got),
        "things_received": _amount(got, things=True),
        "money_left": _amount(left),
        "things_left": _amount(left, things=True),
        "incidents_told": sum(
            e["payload"]["staged"] and name in e["payload"]["told"]
            for e in day.entries
            if e["kind"] == "incident"
        ),
        "likes_named": len(named[-1]["payload"]["names"]) if named else None,
        "searches": sum(e["payload"]["ok"] for e in mine("web_search")),
        "pages_read": sum(e["payload"]["ok"] for e in mine("web_page")),
        "hungry": int(bool(last) and last["nourishment"] == 0),
        "starving": int(bool(last) and "starving" in last["night"]),
        "ill_night": int(bool(last) and "illness" in last["night"]),
        "health": last["health"] if last else None,
        "bedridden": int(name in lying or bool(mine("bedridden"))),
        "announcements": len(mine("announcement")),
        "said_public": sum(not e["payload"]["private"] for e in said),
        "said_private": sum(e["payload"]["private"] for e in said),
        "heard_public": sum(not e["payload"]["private"] for e in heard),
        "heard_private": sum(e["payload"]["private"] for e in heard),
        "interlocutors": len(
            {other for e in said for other in e["payload"]["to"]}
            | {e["actor"] for e in heard}
            | {e["payload"]["to"] for e in sent}
            | {e["actor"] for e in written}
        ),
        "messages_sent": len(sent),
        "messages_received": len(written),
        "bedside_visits": visits,
        "visited_in_bed": visited,
        "journal": int(any(e["payload"]["journal"] for e in mine("sleep"))),
        "forced_sleep": len(mine("forced_sleep")),
    }


def _amount(moved: Iterable[Mapping[str, Any]], *, things: bool = False) -> int:
    """The money moved, or the units of things, of the move payloads `moved`."""
    return sum(p["amount"] for p in moved if (p["what"] != MONEY) == things)


def _visits(day: Day, name: str, lying: Mapping[str, str]) -> tuple[int, int]:
    """`name`'s arrivals on `day` at a home where another lay bedridden, and others' arrivals
    at the home where it lay, with `lying` those bedridden when the day began."""
    lying, visits, visited = dict(lying), 0, 0
    for e in day.entries:
        _turn(lying, e)
        if e["kind"] != "arrive":
            continue
        place = e["payload"]["place"]
        if e["actor"] == name:
            visits += any(home == place for other, home in lying.items() if other != name)
        elif lying.get(name) == place:
            visited += 1
    return visits, visited


def trace_measures(trace: Sequence[Entry]) -> Row:
    """The measures of a resident-day that its trace gives."""
    usage = [r["usage"] for r in trace if r["kind"] == "reply" and r["usage"] is not None]
    reported = [u for u in usage if u.get("cached_prompt_tokens") is not None]
    prompt = sum(u["prompt_tokens"] for u in reported)
    return {
        "requests": sum(r["kind"] == "request" for r in trace),
        "prompt_tokens": sum(u["prompt_tokens"] for u in usage),
        "completion_tokens": sum(u["completion_tokens"] for u in usage),
        "cached_share": sum(u["cached_prompt_tokens"] for u in reported) / prompt
        if prompt
        else None,
        "lapses": sum(r["kind"] == "lapse" for r in trace),
        "compactions": sum(r["kind"] == "compaction" for r in trace),
    }


def town_days(run_dir: Path) -> list[Row]:
    """One row per lived day of the run at `run_dir`, by day: the measures of `TOWN`, from the
    world log and, for the money and what the treasury owes, is owed and took and paid on the
    calendar day its midnight closed, from the day's checkpoint."""
    config, days = lived(run_dir)
    run = RunDirectory(run_dir)
    rows = []
    for day in days:
        state = json.loads(run.checkpoint_path(day.number).read_text(encoding="utf-8"))
        treasury = state["treasury"]
        kinds = Counter(e["kind"] for e in day.entries)
        where = Counter(taken_from(e, config.names) for e in day.entries if e["kind"] == "move")
        rows.append(
            {
                "day": day.number,
                "date": day_date(config, day.number).isoformat(),
                "tasks_arrived": kinds["task_arrived"],
                "tasks_accepted": sum(
                    e["kind"] == "verdict" and e["payload"]["resolved"] and e["payload"]["held"]
                    for e in day.entries
                ),
                "tasks_withdrawn": kinds["task_withdrawn"],
                "clients": _summed(day, "service", "amount"),
                "supplier": _summed(day, "order", "amount"),
                "money": sum(r["inventory"]["money"] for r in state["residents"].values()),
                "money_left": sum(held["money"] for held in state["holders"].values()),
                "treasury": treasury["balance"],
                "salary_owed": sum(treasury["owed"].values()),
                "arrears": sum(treasury["arrears"].values()),
                **{f"taken_{kind}": treasury["yesterday"].get(kind, 0) for kind in TAKEN},
                **{f"paid_{kind}": treasury["yesterday"].get(kind, 0) for kind in PAID},
                **{f"took_from_{place}": where[place] for place in TAKEN_FROM},
                **trade(takes_of(day, config)),
                "incidents": kinds["incident"],
                "incidents_staged": _summed(day, "incident", "staged"),
                "searches": _summed(day, "web_search", "ok"),
                "pages_read": _summed(day, "web_page", "ok"),
            }
        )
    return rows


def _summed(day: Day, kind: str, field: str) -> int:
    """The payloads' `field` summed over the entries of `kind` of `day`."""
    return sum(e["payload"][field] for e in day.entries if e["kind"] == kind)


def takes(run_dir: Path) -> list[Row]:
    """Every take and every service received in the run at `run_dir`, by day, in the log's order
    (`takes_of`): when, who, what and how much, from where or whom, the price or fee posted,
    what was due, how much was paid soon, and the status."""
    config, days = lived(run_dir)
    return [row for day in days for row in takes_of(day, config)]


def incidents(run_dir: Path) -> list[Row]:
    """Every incident of the run at `run_dir` as the log has it, with what each resident told
    of it did after it until the day's end (see the module docstring)."""
    _, days = lived(run_dir)
    rows = []
    for day in days:
        for i, e in enumerate(day.entries):
            if e["kind"] != "incident":
                continue
            payload = e["payload"]
            after = day.entries[i + 1 :]
            rows.append(
                {"day": day.number, "time": clock_time(e["sim_time"])}
                | {key: payload[key] for key in ("id", "kind", "category", "staged", "why")}
                | {"effects": payload["effects"], "told": payload["told"]}
                | {"followed": {name: _acts(after, name) for name in payload["told"]}}
            )
    return rows


def _acts(entries: Iterable[Entry], name: str) -> list[Row]:
    """What `name` took, gave, said and wrote in `entries`, each when, what and with whom."""
    found = []
    for e in entries:
        if e["actor"] != name or e["kind"] not in FOLLOWED:
            continue
        p, when = e["payload"], clock_time(e["sim_time"])
        if e["kind"] == "move" and p["reason"] != "eat":
            other = p["source"] if p["reason"] == "take" else p["target"]
            found.append(
                {"time": when, "act": p["reason"], "what": p["what"]}
                | {"amount": p["amount"], "with": other}
            )
        elif e["kind"] == "speech":
            found.append({"time": when, "act": "said", "text": p["text"], "to": p["to"]})
        elif e["kind"] == "message":
            found.append({"time": when, "act": "wrote", "text": p["text"], "to": [p["to"]]})
    return found


def nights(run_dir: Path) -> list[Row]:
    """One row per resident and complete night of the run at `run_dir`, by night, from the
    night's `done.json` (`learning.night`): how its choice ended and after how many replies, the
    moments it marked and those kept, the examples made of them and how many were new, those the
    generalising dropped (`dropped`) and why (`dropped_why`, a count by reason), the dataset's
    size, whether an adapter was fitted, and the adapter it woke on (None: the base model)."""
    run = RunDirectory(run_dir)
    rows = []
    for folder in sorted(run.learning_dir.glob("night-*")):
        if not (folder / DONE).is_file():
            continue
        done = json.loads((folder / DONE).read_text(encoding="utf-8"))
        for name, s in done["residents"].items():
            rows.append(
                {"resident": name, "night": done["night"]}
                | {key: s[key] for key in ("ended", "replies", "marked", "kept", "examples", "new")}
                | {"dropped": sum(s["dropped"].values()), "dropped_why": s["dropped"]}
                | {key: s[key] for key in ("dataset", "fitted", "adapter")}
            )
    return rows


def daily(rows: Sequence[Row]) -> list[Row]:
    """One row per day and measure: the total over residents (None for `LEVELS`), the mean
    over the residents with a value, and how many have one."""
    found = []
    for day in sorted({row["day"] for row in rows}):
        of_day = [row for row in rows if row["day"] == day]
        for name in MEASURES:
            values = [row[name] for row in of_day if row[name] is not None]
            found.append(
                {
                    "day": day,
                    "measure": name,
                    "total": None if name in LEVELS else sum(values),
                    "mean": _mean(values),
                    "residents": len(values),
                }
            )
    return found


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return fmean(values) if values else None


def write(rows: Sequence[Row], stem: Path, *, csv_too: bool = True) -> None:
    """`rows` as `<stem>.json` and, unless not `csv_too`, `<stem>.csv` (None as an empty cell,
    a list or a mapping as its JSON)."""
    stem.with_suffix(".json").write_text(
        json.dumps(list(rows), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not csv_too:
        return
    with stem.with_suffix(".csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]) if rows else [])
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False)
                    if isinstance(value, list | dict)
                    else value
                    for key, value in row.items()
                }
            )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m analysis.measures", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("run", type=Path, help="the run directory")
    parser.add_argument("--out", type=Path, required=True, help="where to write")
    args = parser.parse_args(argv)
    try:
        rows = measure(args.run)
    except ValueError as error:
        parser.error(str(error))
    if not rows:
        parser.error(f"{args.run} has no lived day closed by a checkpoint")
    args.out.mkdir(parents=True, exist_ok=True)
    write(rows, args.out / "measures")
    write(daily(rows), args.out / "daily")
    write(town_days(args.run), args.out / "town")
    write(takes(args.run), args.out / "takes")
    write(incidents(args.run), args.out / "incidents", csv_too=False)
    write(nights(args.run), args.out / "nights")
    days = sorted({row["day"] for row in rows})
    residents = len({row["resident"] for row in rows})
    print(f"{residents} residents, days {days[0]} to {days[-1]}: written to {args.out}")


if __name__ == "__main__":
    main()
