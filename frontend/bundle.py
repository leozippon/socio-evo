"""The JSON documents of the data bundle, built from a run directory and its evaluation results.

Every document is a plain JSON value; `frontend/README.md` is its contract. The numbers come from
`frontend.timeline`, `frontend.progress`, `analysis.measures`, `analysis.tables` and
`analysis.compare`, which define them; this module only arranges them and adds what the viewer
needs of the run itself: the town laid out on a map, the world log's lived days as published,
the social graph, what every holder of items held over time as the checkpoints and the moves
give it, and the agents' files as their git repositories hold them. Agent files are read through git
plumbing, which never touches an index or a work tree.
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
from frontend.progress import COUNTS
from infrastructure.git import FileChange, Repository
from infrastructure.storage import RunDirectory, read_jsonl
from simulation.config import ExperimentConfig
from world.clock import DAY
from world.config import TownConfig
from world.economy import LARDER, PORTIONS, SHELVES, add, take
from world.log import Day, counted_move, day_of
from world.rules import Rules

Entry = dict[str, Any]
Row = dict[str, Any]

OMITTED = frozenset({"patch", "diff"})
"""Payload fields left out of the published events: the code residents handed in or left in
their workspaces, which the bundle does not carry."""
UNPUBLISHED = frozenset({"session.jsonl", "trace.jsonl"})
"""Files of an agent's repository whose changes, diffs and contents the bundle leaves out."""
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
ROWS = {
    "home": 0.0,
    "office": 1.5,
    "hall": 1.5,
    "hospital": 1.5,
    "store": 3.0,
    "restaurant": 3.0,
    "social": 3.0,
}
"""Where each kind of place stands on the map, in map units: the homes in a row at the top, the
office, the hall and the hospital in the middle, the store, the restaurant and the social places
in a row below."""
GRAPH = ("minutes", "said", "said_private", "messages", "gifts", "money", "served")
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
    "tasks_accepted",
    "hours_at_work",
    "wages",
    "service_sums",
    "money",
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
            {
                "name": r.name,
                "home": r.home,
                "occupation": r.occupation,
                "purse": r.purse,
                "rules": rules.text(r.name),
            }
            for r in town.residents
        ],
        "occupations": [occupation.model_dump(mode="json") for occupation in town.occupations],
        "fund": town.fund.model_dump(mode="json"),
        "tax": town.tax,
        "work": town.work.model_dump(mode="json"),
        "goods": [item.model_dump(mode="json") for item in town.supplied],
        "store": town.store.model_dump(mode="json"),
        "dishes": [dish.model_dump(mode="json") for dish in town.dishes],
        "hospital": town.hospital.model_dump(mode="json"),
        "needs": town.needs.model_dump(mode="json"),
        "social": town.social.model_dump(mode="json"),
        "day": town.day.model_dump(mode="json"),
        "model": {"backend": config.llm.backend, "name": config.llm.model},
    }


# The world log --------------------------------------------------------------------------------


def published_entry(entry: Entry) -> Entry:
    """The entry as the bundle carries it: as recorded, without the code (`OMITTED`)."""
    payload = {key: value for key, value in entry["payload"].items() if key not in OMITTED}
    return {**entry, "payload": payload}


def graph(timeline: Mapping[str, Any], days: Sequence[Day]) -> list[Row]:
    """What one resident had to do with another on a day: one row per ordered pair and lived day
    of `days` (those with entries, in order) with anything to count, by day, source and target.
    `minutes` are simulated minutes `source` spent in conversations `target` took part in (from
    the timeline's conversations, each on the day it began); the rest counts the day's entries:
    things `source` said that `target` heard (`said`, of which `said_private` to it by name),
    messages written to it, gifts (`gifts` times, `money` the money among them) and the times
    `source` served `target` at its work (`served`: a sale at the Store's counter, a dish,
    bought or the chef's unpaid, an examination or a treatment; nobody serves itself)."""
    ends = [(day.entries[-1]["sim_time"], day.number) for day in days]
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
    for day in days:
        for entry in day.entries:
            kind, actor, payload = entry["kind"], entry["actor"], entry["payload"]
            moved = counted_move(payload) if kind == "move" else None
            if kind == "speech":
                for other in payload["to"]:
                    add(day.number, actor, other, "said", 1)
                    if payload["private"]:
                        add(day.number, actor, other, "said_private", 1)
            elif kind == "message":
                add(day.number, actor, payload["to"], "messages", 1)
            elif moved == "gift":
                add(day.number, actor, payload["target"], "gifts", 1)
                add(day.number, actor, payload["target"], "money", payload["money"])  # 0: a thing
            elif moved in ("sale", "dish"):
                buy = payload["reason"] == "buy"
                server, served = (payload["seller"], actor) if buy else (actor, payload["target"])
                if server != served:
                    add(day.number, server, served, "served", 1)
            elif kind in ("examination", "treatment") and payload["patient"] != actor:
                add(day.number, actor, payload["patient"], "served", 1)
    return [
        {"day": day, "source": source, "target": target, **row}
        for (day, source, target), row in sorted(totals.items())
    ]


def saved(run: RunDirectory, data: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    """The state of the world at every checkpoint whose file the run has written, by day: day
    0, the world before the first day, and each lived day the timeline `data` has closed."""
    states = {}
    for day in [{"day": 0, "end": data["start"]}, *data["days"]]:
        path = run.checkpoint_path(day["day"])
        if day["end"] is not None and path.is_file():
            states[day["day"]] = json.loads(path.read_text(encoding="utf-8"))
    return states


def holdings(
    states: Mapping[int, Mapping[str, Any]], town: TownConfig, data: Mapping[str, Any]
) -> tuple[dict[str, list], dict[str, list]]:
    """What every holder of items held over the run, as `[time, {item id: units}]` from the
    start and after each change: each resident's inventory by name, and every other holder by
    its name in the log (the Store's shelves, the kitchen's larder and its portions, and what is
    left at each place, by the place's id). The start is the configuration's: the Store's stock
    on its shelves and nothing anywhere else. At every checkpoint of `states` each holder is read
    from the checkpoint, exact as of that moment; between checkpoints the timeline `data`'s
    markers move the units in log order: each move from its source to its target (money alone
    moves none), cooking from the larder into portions, and a delivery onto the shelves; and what
    perishes is gone at every midnight, wherever it is, as the world takes it unlogged. A marker
    that takes from a holder more than it holds fails, naming its entry. Returns the residents'
    and the others'."""
    perishes = [item.id for item in town.items if item.perishes]
    residents = [lane["name"] for lane in data["residents"]]
    others = [SHELVES, LARDER, PORTIONS, *(place.id for place in town.places)]
    held: dict[str, dict[str, int]] = {key: {} for key in [*residents, *others]}
    held[SHELVES] = dict(town.store.stock)
    series = {key: [[data["start"], dict(items)]] for key, items in held.items()}
    # At one moment a checkpoint comes first, then a midnight, then the markers in log order.
    changes: list[tuple[int, int, int, Any]] = [(s["time"], 0, 0, s) for s in states.values()]
    midnights = range(data["start"] // DAY * DAY + DAY, data["now"] + 1, DAY)
    changes += [(t, 1, 0, None) for t in midnights]
    markers = [*data["markers"], *(m for lane in data["residents"] for m in lane["markers"])]
    changes += [(m["t"], 2, m["seq"], m) for m in markers if _moved(m)]
    for t, rank, seq, change in sorted(changes, key=lambda found: found[:3]):
        if rank == 0:
            found = {name: change["residents"][name]["inventory"]["items"] for name in residents}
            touched = [*found, *change["holders"]]
            for key, items in {**found, **change["holders"]}.items():
                held[key] = dict(items)
        elif rank == 1:
            touched = list(held)
            for items in held.values():
                for item in perishes:
                    items.pop(item, None)
        else:
            touched = []
            for key, item, units in _moved(change):
                touched.append(key)
                if units > 0:
                    add(held[key], item, units)
                elif held[key].get(item, 0) >= -units:
                    take(held[key], item, -units)
                else:
                    have = held[key].get(item, 0)
                    raise ValueError(f"entry {seq}: {key} holds {have} of {item}, not {-units}")
        for key in touched:
            _record(series[key], t, held[key])
    return {key: series[key] for key in residents}, {key: series[key] for key in others}


def _moved(marker: Mapping[str, Any]) -> list[tuple[str, str, int]]:
    """The units a marker moves, as `(holder, item, units)`, those taken first and negative: a
    move's from its source to its target, cooking's from the larder into portions, a delivery's
    onto the shelves; none for the other markers and for money alone."""
    kind = marker["kind"]
    if kind == "move" and marker["item"] is not None:
        item, units = marker["item"], marker["units"]
        ends = ((marker["source"], -units), (marker["target"], units))
        return [(key, item, change) for key, change in ends if key is not None]
    if kind == "cook":
        used = [(LARDER, item, -units) for item, units in marker["used"].items()]
        return [*used, (PORTIONS, marker["dish"], marker["portions"])]
    if kind == "delivery":
        return [(SHELVES, item, units) for item, units in marker["items"].items()]
    return []


def _record(points: list[list[Any]], t: int, state: Mapping[str, int]) -> None:
    """Add the state at `t` to a series of points: a point at the same moment is replaced, and
    a state no different from the point before it is no change."""
    if points[-1][0] == t:
        points[-1][1] = dict(state)
        if len(points) > 1 and points[-2][1] == state:
            points.pop()
    elif points[-1][1] != state:
        points.append([t, dict(state)])


def headline(progress: Mapping[str, Any], town: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """A few numbers for the home page: the day reached and the counts of `frontend.progress`
    summed over the lived days, with the purses at the end of the last of them and the fund's
    balance at the last checkpoint, from the town's days of `analysis.measures` (null before
    any)."""
    daily = progress["daily"]
    return {
        "day": progress["day"],
        "clock": progress["clock"],
        "hours_per_day": progress["hours_per_day"],
        **{key: sum(row[key] for row in daily) for key in COUNTS},
        "purse": daily[-1]["purse"],
        "fund": town[-1]["fund"] if town else None,
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


def trace_days(agent_dir: Path, resident: str, days: Sequence[Day]) -> dict[int, dict[str, Any]]:
    """The records of the resident's trace by lived day of `days`, given in order (the day whose
    span of real time holds a record, `world.log.day_of`), each record as the runtime wrote it.
    A `request` record carries besides the ids of its messages the messages themselves that it named
    for the first time (`new_messages`), from the resident's own session file: what the resident was
    told since its last request, a compaction's summary among them. A day's `prompt` is the system
    prompt in force as the day began: the last one assembled before its first record. Nothing comes
    from outside the resident's directory. Empty before the runtime has written a trace."""
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
        day.number: {"resident": resident, "day": day.number, "prompt": None, "records": []}
        for day in days
    }
    seen: set[int] = set()
    prompt: str | None = None
    for record in read_jsonl(trace):
        day = day_of(days, record["real_time"])
        if record["kind"] == "request":
            new = [messages[i] for i in record["messages"] if i not in seen and i in messages]
            seen.update(record["messages"])
            record = {**record, "new_messages": new}
        if day is not None:
            doc = found[day.number]
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
