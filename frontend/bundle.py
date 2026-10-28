"""The JSON documents of the data bundle, built from a run directory and its evaluation results.

Every document is a plain JSON value; `frontend/README.md` is its contract. The numbers come from
`frontend.timeline`, `frontend.progress`, `analysis.measures`, `analysis.tables` and
`analysis.compare`, which define them; this module only arranges them and adds what the viewer
needs of the run itself: the town laid out on a map, the world log cut into lived days, the
social graph, what each resident owns as its purchases and the checkpoints give it, and the
agents' files as their git repositories hold them. Agent files are read through git plumbing,
which never touches an index or a work tree.
"""

from __future__ import annotations

import json
from bisect import bisect_left
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from agent.directory import SESSION, TRACE
from analysis import compare as comparison
from analysis.measures import MEASURES
from analysis.tables import tables
from infrastructure.git import FileChange, Repository
from infrastructure.storage import RunDirectory, read_jsonl
from simulation.config import ExperimentConfig
from world.clock import DAY
from world.config import TownConfig
from world.rules import Rules

Entry = dict[str, Any]
Row = dict[str, Any]

OMITTED = frozenset({"patch", "diff"})
"""Payload fields left out of the published events: the code residents handed in or left in
their workspaces, which the bundle does not carry."""
UNPUBLISHED = frozenset({"session.jsonl", "trace.jsonl"})
"""Files of an agent's repository whose changes, diffs and contents the bundle leaves out."""
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
ROWS = {"home": 0.0, "workplace": 1.5, "social": 3.0, "shop": 3.0}
"""Where each kind of place stands on the map, in map units: the homes in a row at the top, the
workplace in the middle, the social places and the shops in a row below."""
COUNTED = (
    "claims",
    "submissions",
    "accepted",
    "rejected",
    "payments",
    "paid",
    "speeches",
    "messages",
    "gifts",
    "purchases",
    "skills_shared",
    "journals",
    "forced_sleeps",
    "deaths",
)
"""The counts of `frontend.progress` summed into a run's headline."""
GRAPH = ("minutes", "said", "said_private", "messages", "gifts", "money")
"""What one resident had to do with another on a day, by field."""
JOURNAL_FIELDS = (
    "resident",
    "day",
    "date",
    "journal",
    "record_lines",
    "claims",
    "supported",
    "contradicted",
    "unverifiable",
    "distortion",
)
"""The fields of a row of `evaluation.journals`' `days.json` the bundle publishes."""
DECLARED = {
    "capability": ("capability", "capability", "resolved rate on the held-out tasks"),
    "mask": ("mask", "mask", "share of truthful answers under pressure"),
    "distortion": ("journals", "distortion", "distortion rate of the journal"),
}
"""The declared outcomes compared across runs: the table of `evaluation.json` and the column
each is read from, and what it is called."""
EXPLORED = (
    "claimed",
    "accepted",
    "earned",
    "purse",
    "work_hours",
    "said_public",
    "said_private",
    "money_given",
    "journal",
    "forced_sleep",
    "health",
)
"""The town measures compared across runs, as exploration."""


# The world ------------------------------------------------------------------------------------


def layout(places: Sequence[Any]) -> dict[str, tuple[float, float]]:
    """Map positions of the places by id: each kind in its row (`ROWS`; kinds that share a row
    share it), the places of a row one unit apart and centred under one another."""
    rows = {
        y: [place for place in places if ROWS[place.kind] == y]
        for y in dict.fromkeys(ROWS.values())
    }
    width = max(len(found) for found in rows.values()) - 1
    found: dict[str, tuple[float, float]] = {}
    for y, row in rows.items():
        for index, place in enumerate(row):
            found[place.id] = (width / 2 + index - (len(row) - 1) / 2, y)
    return found


def world(config: ExperimentConfig) -> dict[str, Any]:
    """The town and the rules of the run, from its frozen configuration."""
    town = config.town
    coords = layout(town.places)
    rules = Rules(town)
    return {
        "name": config.name,
        "days": config.days,
        "currency": town.currency,
        "start_date": town.start_date.isoformat(),
        "places": [
            {
                "id": place.id,
                "name": place.name,
                "kind": place.kind,
                "rent": place.rent,
                "rooms": place.rooms,
                "comfort": place.comfort,
                "x": coords[place.id][0],
                "y": coords[place.id][1],
            }
            for place in town.places
        ],
        "routes": [
            {"between": list(route.between), "minutes": route.minutes} for route in town.routes
        ],
        "travel_minutes": town.travel_minutes,
        "residents": [
            {"name": r.name, "home": r.home, "purse": r.purse, "rules": rules.text(r.name)}
            for r in town.residents
        ],
        "work": town.work.model_dump(mode="json"),
        "goods": [good.model_dump(mode="json") for good in town.goods],
        "needs": town.needs.model_dump(mode="json"),
        "social": town.social.model_dump(mode="json"),
        "day": town.day.model_dump(mode="json"),
        "model": {"backend": config.llm.backend, "name": config.llm.model},
    }


# The world log --------------------------------------------------------------------------------


def cut_days(entries: Iterable[Entry]) -> dict[int, list[Entry]]:
    """The entries by lived day, in log order: a closed day ends with its `checkpoint` entry, and
    the day in progress, if entries have been written since the last checkpoint, follows it. The
    entries a lost day left before a `resume` are set aside, and so is the `resume` itself."""
    days: dict[int, list[Entry]] = {}
    current: list[Entry] = []
    for entry in entries:
        if entry["kind"] == "resume":
            back = entry["payload"]["day"]
            days = {day: found for day, found in days.items() if day <= back}
            current = []
            continue
        current.append(entry)
        if entry["kind"] == "checkpoint":
            days[entry["payload"]["day"]] = current
            current = []
    if current:
        days[(max(days) if days else 0) + 1] = current
    return days


def closed(days: Mapping[int, Sequence[Entry]]) -> list[int]:
    """The days of `days` a checkpoint closed."""
    return [day for day, entries in days.items() if entries[-1]["kind"] == "checkpoint"]


def published_entry(entry: Entry) -> Entry:
    """The entry as the bundle carries it: as recorded, without the code (`OMITTED`)."""
    payload = {key: value for key, value in entry["payload"].items() if key not in OMITTED}
    return {**entry, "payload": payload}


def graph(timeline: Mapping[str, Any], days: Mapping[int, Sequence[Entry]]) -> list[Row]:
    """What one resident had to do with another on a day: one row per ordered pair and lived day
    with anything to count, by day, source and target. `minutes` are simulated minutes `source`
    spent in conversations `target` took part in (from the timeline's conversations, each on
    the day it began); the rest counts the day's entries: things `source` said that `target`
    heard (`said`, of which `said_private` to it by name), messages written to it and gifts
    (`gifts` times, `money` the money among them)."""
    ends = sorted((entries[-1]["sim_time"], day) for day, entries in days.items())
    times = [end for end, _ in ends]

    def day_of(t: int) -> int:
        return ends[min(bisect_left(times, t), len(ends) - 1)][1]

    totals: dict[tuple[int, str, str], dict[str, float]] = {}

    def add(day: int, source: str, target: str, field: str, amount: float) -> None:
        key = (day, source, target)
        row = totals.setdefault(key, dict.fromkeys(GRAPH, 0))
        row[field] += amount

    for lane in timeline["residents"]:
        for talk in lane["conversations"]:
            for other in talk["with"]:
                minutes = (talk["end"] - talk["start"]) / 60
                add(day_of(talk["start"]), lane["name"], other, "minutes", minutes)
    for day, entries in days.items():
        for entry in entries:
            kind, actor, payload = entry["kind"], entry["actor"], entry["payload"]
            if kind == "speech":
                for other in payload["to"]:
                    add(day, actor, other, "said", 1)
                    if payload["private"]:
                        add(day, actor, other, "said_private", 1)
            elif kind == "message":
                add(day, actor, payload["to"], "messages", 1)
            elif kind == "gift":
                add(day, actor, payload["to"], "gifts", 1)
                add(day, actor, payload["to"], "money", payload.get("amount", 0))  # 0: a thing
    return [
        {"day": day, "source": source, "target": target, **row}
        for (day, source, target), row in sorted(totals.items())
    ]


def things(run: RunDirectory, town: TownConfig, data: Mapping[str, Any]) -> dict[str, list]:
    """What each resident owns over the run, by name: `[time, {good id: units}]` from the
    start and after each change, a durable counted 1 and a consumable by the units left of it.
    The purchases and the gifts of things are the timeline's markers: a durable is owned from
    then on, a consumable adds its units a purchase, an immediate good is used up as it is
    bought, and what is given goes from the giver to the receiver. What is eaten leaves no
    entry in the log, so at every checkpoint whose file the run has written the stock is read
    from the checkpoint instead, exact as of that moment; between checkpoints it is as last
    counted plus what was bought and given since."""
    goods = {good.id: good for good in town.goods}
    snapshots: dict[int, dict[str, dict[str, int]]] = {}
    for day in [{"day": 0, "end": data["start"]}, *data["days"]]:
        path = run.checkpoint_path(day["day"])
        if day["end"] is None or not path.is_file():
            continue
        state = json.loads(path.read_text(encoding="utf-8"))
        snapshots[day["end"]] = {
            name: dict(found["living"]["things"]) for name, found in state["residents"].items()
        }
    found = {}
    for lane in data["residents"]:
        changes: list[tuple[int, int, Any]] = [
            (t, 0, snapshot[lane["name"]])
            for t, snapshot in snapshots.items()
            if lane["name"] in snapshot
        ]
        changes += [(m["t"], 1, m) for m in lane["markers"] if m["kind"] == "purchase"]
        for other in data["residents"]:  # things given away and received
            for m in other["markers"]:
                if m["kind"] == "gift" and "item" in m and lane["name"] in (other["name"], m["to"]):
                    units = -m["quantity"] if other is lane else m["quantity"]
                    changes.append((m["t"], 1, m | {"units": units}))
        held: dict[str, int] = {}
        series: list[list[Any]] = [[data["start"], {}]]
        for t, kind, change in sorted(changes, key=lambda found: found[:2]):
            if kind == 0:
                held = dict(change)
            elif change["kind"] == "gift":
                held[change["item"]] = held.get(change["item"], 0) + change["units"]
                if not held[change["item"]]:
                    del held[change["item"]]
            else:
                good = goods[change["item"]]
                if good.kind == "durable":
                    held[good.id] = 1
                elif good.kind == "consumable":
                    assert good.uses is not None
                    held[good.id] = held.get(good.id, 0) + good.uses * change["quantity"]
            if t == series[-1][0]:
                series[-1][1] = dict(held)
            elif held != series[-1][1]:
                series.append([t, dict(held)])
        found[lane["name"]] = series
    return found


def headline(progress: Mapping[str, Any]) -> dict[str, Any]:
    """A few numbers for the home page: the day reached and the counts of `frontend.progress`
    summed over the lived days, with the purses at the end of the last of them."""
    daily = progress["daily"]
    return {
        "day": progress["day"],
        "clock": progress["clock"],
        "hours_per_day": progress["hours_per_day"],
        **{key: sum(row[key] for row in daily) for key in COUNTED},
        "purse": daily[-1]["purse"],
    }


# Evaluation -----------------------------------------------------------------------------------


def evaluation(results_root: Path, name: str) -> dict[str, Any]:
    """The evaluation results of the run `name` under `results_root`, as tidy rows: capability
    and MASK from `analysis.tables` (day 0, the export before the first day, read from the
    `day-00` directory beside the run's), and journal honesty from every `days.json` under the
    run's `journals/`. A part that cannot be read is named in `problems` and left out."""
    doc: dict[str, Any] = {"capability": [], "mask": [], "journals": [], "problems": []}
    own, day0 = results_root / name, results_root / "day-00"
    if not (own.is_dir() or day0.is_dir()):
        return doc  # nothing has been evaluated yet
    try:
        found = tables(results_root, name, day0)
    except ValueError as error:
        doc["problems"].append(str(error))
    else:
        doc["capability"], doc["mask"] = found["capability"], found["mask"]
    seen: set[tuple[str, int]] = set()
    journals = own / "journals"
    for path in sorted(journals.glob("*/days.json")) if journals.is_dir() else []:
        for row in json.loads(path.read_text(encoding="utf-8")):
            key = (row["resident"], row["day"])
            if key in seen:
                doc["problems"].append(
                    f"{path}: {row['resident']}'s day {row['day']} is judged twice"
                )
                continue
            seen.add(key)
            doc["journals"].append({field: row[field] for field in JOURNAL_FIELDS})
    doc["journals"].sort(key=lambda row: (row["day"], row["resident"]))
    return doc


# Agents ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Version:
    """A commit of an agent's repository: the day whose checkpoint committed it (0 for the
    agent as created), its simulated time, and the files it changed."""

    commit: str
    parent: str | None
    day: int
    time: int
    subject: str
    changes: tuple[FileChange, ...]


def agent_versions(repository: Repository, start_date: Any) -> list[Version]:
    """The agent's versions, oldest first; none before the agent has a repository with a
    commit, which the first checkpoint gives it."""
    if not (repository.path / ".git").is_dir():
        return []
    log = repository.log()
    changes = repository.changes(log[0].id)
    origin = datetime.combine(start_date, datetime.min.time(), UTC)
    versions = []
    for commit in reversed(log):
        time = int((commit.date - origin).total_seconds())
        kept = tuple(change for change in changes[commit.id] if change.path not in UNPUBLISHED)
        versions.append(Version(commit.id, commit.parent, time // DAY, time, commit.subject, kept))
    return versions


def versions_index(resident: str, versions: Sequence[Version], urls: Mapping[int, str]) -> dict:
    """The agent's version history; `urls` gives the reference to each day's file."""
    return {
        "resident": resident,
        "versions": [
            {
                "commit": found.commit,
                "day": found.day,
                "time": found.time,
                "subject": found.subject,
                "changes": [asdict(change) for change in found.changes],
                "url": urls[found.day],
            }
            for found in versions
        ],
    }


def agent_day(repository: Repository, resident: str, day: int, versions: Sequence[Version]) -> dict:
    """The versions the agent committed on `day`, each with its diff against the version
    before and every file it then held, the session and the trace left out."""
    excluded = [f":(exclude){path}" for path in sorted(UNPUBLISHED)]
    trees = {found.commit: repository.tree(found.commit) for found in versions}
    blobs = {
        blob for tree in trees.values() for path, blob in tree.items() if path not in UNPUBLISHED
    }
    texts = {
        blob: data.decode("utf-8", errors="replace")
        for blob, data in repository.blobs(blobs).items()
    }
    return {
        "resident": resident,
        "day": day,
        "versions": [
            {
                "commit": found.commit,
                "diff": repository.diff(found.parent or EMPTY_TREE, found.commit, ".", *excluded),
                "files": {
                    path: texts[blob]
                    for path, blob in sorted(trees[found.commit].items())
                    if path not in UNPUBLISHED
                },
            }
            for found in versions
        ],
    }


# The trace -----------------------------------------------------------------------------------


def spans(days: Mapping[int, Sequence[Entry]]) -> list[tuple[int, float | None, float | None]]:
    """The real-time span of each lived day of `days`, as (day, opened, closed): a day opens at
    the real time of the checkpoint that closed the day before (None for the first) and closes
    at its own (None for the day in progress). After a closed last day a span for the next day
    follows, open, for what the runtimes have done since."""
    found = []
    opened: float | None = None
    for day, entries in sorted(days.items()):
        closed = entries[-1]["real_time"] if entries[-1]["kind"] == "checkpoint" else None
        found.append((day, opened, closed))
        opened = closed
    if found and found[-1][2] is not None:
        found.append((found[-1][0] + 1, found[-1][2], None))
    return found


def trace_days(
    agent_dir: Path, resident: str, days: Sequence[tuple[int, float | None, float | None]]
) -> dict[int, dict[str, Any]]:
    """The records of the resident's trace by lived day (the day whose span holds a record's
    real time), each record as the runtime wrote it. A `request` record carries besides the ids
    of its messages the messages themselves that it named for the first time (`new_messages`),
    from the resident's own session file: what the resident was told since its last request,
    a compaction's summary among them. A day's `prompt` is the system prompt in force as the
    day began: the last one assembled before its first record. Nothing comes from outside the
    resident's directory. Empty before the runtime has written a trace."""
    trace = agent_dir / TRACE
    if not trace.exists():
        return {}
    messages: dict[int, Any] = {}
    session = agent_dir / SESSION
    if session.exists():
        for record in read_jsonl(session):
            if record["type"] == "message":
                messages[record["id"]] = record["message"]
            elif record["type"] == "compaction":
                messages[record["id"]] = {
                    "role": "user",
                    "content": record["summary"],
                    "compaction": True,
                }
    found = {
        day: {"resident": resident, "day": day, "prompt": None, "records": []} for day, _, _ in days
    }
    seen: set[int] = set()
    prompt: str | None = None
    for record in read_jsonl(trace):
        day = next(
            (
                d
                for d, opened, closed in days
                if (opened is None or record["real_time"] > opened)
                and (closed is None or record["real_time"] <= closed)
            ),
            None,
        )
        if record["kind"] == "request":
            new = [messages[i] for i in record["messages"] if i not in seen and i in messages]
            seen.update(record["messages"])
            record = {**record, "new_messages": new}
        if day is not None:
            doc = found[day]
            if not doc["records"]:
                doc["prompt"] = prompt
            doc["records"].append(record)
        if record["kind"] == "prompt":
            prompt = record["text"]
    return {day: doc for day, doc in found.items() if doc["records"]}


# Runs compared --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Analysed:
    """A published run as the comparison of runs reads it."""

    name: str
    measures: Sequence[Row]
    evaluation: Mapping[str, Any]


def compared(name: str, runs: Sequence[Analysed]) -> dict[str, Any]:
    """The `runs` compared, by name, on the declared outcomes and the explored town measures
    that any of them has values for (`analysis.compare`), each from day 0 (day 1 for a town
    measure) to the latest day with a value."""
    by_name = {run.name: run for run in runs}
    measures = []
    for measure, (table, column, label) in DECLARED.items():
        values = {found: _values(run.evaluation[table], column) for found, run in by_name.items()}
        measures.append(_compared(measure, label, True, values, 0))
    for measure in EXPLORED:
        values = {found: _values(run.measures, measure) for found, run in by_name.items()}
        measures.append(_compared(measure, MEASURES[measure], False, values, 1))
    return {
        "name": name,
        "runs": sorted(by_name),
        "measures": [found for found in measures if found is not None],
    }


def _values(rows: Iterable[Row], column: str) -> comparison.Values:
    found: comparison.Values = {}
    for row in rows:
        if row[column] is not None:
            found.setdefault(row["resident"], {})[int(row["day"])] = float(row[column])
    return found


def _compared(
    measure: str, label: str, declared: bool, values: Mapping[str, comparison.Values], first: int
) -> dict[str, Any] | None:
    days = sorted({day for found in values.values() for by_day in found.values() for day in by_day})
    if not days:
        return None
    table = comparison.compare(dict(values), measure, first, days[-1])
    daily = {}
    for group, found in values.items():
        means = []
        for day in days:
            values_of_day = [by_day[day] for by_day in found.values() if day in by_day]
            if values_of_day:
                means.append([day, fmean(values_of_day)])
        daily[group] = means
    return {"label": label, **table, "declared": declared, "daily": daily}
