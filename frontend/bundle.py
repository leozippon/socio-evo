"""The JSON documents of the data bundle, built from a run directory and its evaluation results.

Every document is a plain JSON value; `frontend/README.md` is its contract. The numbers come from
`frontend.timeline`, `frontend.progress`, `analysis.measures`, `analysis.tables` and
`analysis.compare`, which define them; this module only arranges them and adds what the viewer
needs of the run itself: the town laid out on a map, the world log's lived days as published,
the social graph and whom each resident liked, what every holder of things and money held over
time and the numbers everyone saw as the checkpoints and the moves give them, each resident's
nights as the learning wrote them, the benchmarks' answers as far as they may be shown, and the
agents' files as their git repositories hold them. Agent files are read through git plumbing,
which never touches an index or a work tree.
"""

from __future__ import annotations

import json
from bisect import bisect_left
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from agent.directory import SESSION, TRACE
from analysis import compare as comparison
from analysis import tables
from evaluation.results import MODELS
from evaluation.subject import Run
from frontend.progress import COUNTS
from infrastructure.git import FileChange, Repository
from infrastructure.storage import RunDirectory, read_jsonl
from learning.adapters import DONE, TRAINING
from learning.choice import Choice
from learning.moments import Life, rendering
from learning.night import CHOICE, EXAMPLES, NUMBERS, Examples
from simulation.config import ExperimentConfig
from world.clock import DAY
from world.config import TownConfig
from world.economy import COUNTER, LARDER, MONEY, SHELVES, add, take
from world.log import Day, day_of, taken_from
from world.regard import counts
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
GRAPH = ("minutes", "said", "said_private", "messages", "gifts", "money", "took")
"""What one resident had to do with another on a day, by field."""
EXCERPT = 200
"""The most of a benchmark answer the bundle carries, and only of one its judge rated safe."""
SAFE = "Safe"
"""The safety judge's rating of an answer it found no harm in (`evaluation.safety.guard`)."""
PARADIGM = {"examples": "generalised", "choice": "resident"}
"""The learning of the Social arm, the paradigm the other arms are contrasted with
(docs/experimental-design.md, Arms)."""


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
                "likes": list(r.likes),
                "newcomer": r.newcomer,
                "rules": rules.text(r.name),
            }
            for r in town.residents
        ],
        "occupations": [occupation.model_dump(mode="json") for occupation in town.occupations],
        "treasury": town.treasury.model_dump(mode="json"),
        "tax": town.tax,
        "work": town.work.model_dump(mode="json"),
        "goods": [item.model_dump(mode="json") for item in town.supplied],
        "store": town.store.model_dump(mode="json"),
        "dishes": [dish.model_dump(mode="json") for dish in town.dishes],
        "hospital": town.hospital.model_dump(mode="json"),
        "needs": town.needs.model_dump(mode="json"),
        "social": town.social.model_dump(mode="json"),
        "day": town.day.model_dump(mode="json"),
        "web": town.web.model_dump(mode="json"),
        "learning": {
            key: getattr(config.learning, key)
            for key in ("enabled", "examples", "choice", "keep_per_night", "dataset_max")
        },
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
    messages written to it, what `source` gave it (`gifts` times, `money` the money among them,
    payments included) and the times `source` took from what `target` carried (`took`)."""
    ends = [(day.entries[-1]["sim_time"], day.number) for day in days]
    times = [end for end, _ in ends]
    names = {lane["name"] for lane in timeline["residents"]}

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
            if kind == "speech":
                for other in payload["to"]:
                    add(day.number, actor, other, "said", 1)
                    if payload["private"]:
                        add(day.number, actor, other, "said_private", 1)
            elif kind == "message":
                add(day.number, actor, payload["to"], "messages", 1)
            elif kind == "move" and payload["reason"] == "give" and payload["target"] in names:
                add(day.number, actor, payload["target"], "gifts", 1)
                if payload["what"] == MONEY:
                    add(day.number, actor, payload["target"], "money", payload["amount"])
            elif kind == "move" and taken_from(entry, names) in ("awake", "asleep"):
                add(day.number, actor, payload["source"], "took", 1)
    return [
        {"day": day, "source": source, "target": target, **row}
        for (day, source, target), row in sorted(totals.items())
    ]


def likes(town: TownConfig, days: Sequence[Day]) -> list[Row]:
    """Whom each resident liked, by lived day of `days` (those with entries, in order): one row
    per day and resident, with the names it gave going to bed that day (`named`, the last it gave
    if it went to bed more than once; None if it gave none, keeping those it gave before) and the
    names in force at the day's end (`likes`), which make the next day's numbers; the
    configuration gives the first."""
    held = {r.name: list(r.likes) for r in town.residents}
    rows = []
    for day in days:
        named = {
            e["actor"]: list(e["payload"]["names"]) for e in day.entries if e["kind"] == "likes"
        }
        held |= named
        rows += [
            {"day": day.number, "resident": name, "named": named.get(name), "likes": list(given)}
            for name, given in held.items()
        ]
    return rows


def incidents(rows: Sequence[Row], days: Sequence[Day]) -> list[Row]:
    """The incidents of `analysis.measures.incidents`, each with what each resident it reached
    was told (`texts`, the entry's wording for it), from the entries of `days`."""
    told = {
        (day.number, e["payload"]["id"]): e["personal"]
        for day in days
        for e in day.entries
        if e["kind"] == "incident"
    }
    return [row | {"texts": told[row["day"], row["id"]]} for row in rows]


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
    """What every holder held over the run, as `[time, state]` from the start and after each
    change: each resident's things by name, `{item id: units}` (its money is the timeline's
    purse), and every other holder by its name in the log (the Store's shelves, the kitchen's
    counter and larder, and what is left at each place, by the place's id), `{"items": {item id:
    units}, "money": amount}`. The start is the configuration's: the Store's stock on its shelves
    and nothing anywhere else. At every checkpoint of `states` each holder is read from the
    checkpoint, exact as of that moment; between checkpoints the timeline `data`'s markers move
    things and money in log order: each move from its source to its target, cooking from the
    larder and the chef's hands onto the counter, a delivery onto the shelves, what perished from
    where it was, and an incident's effects, what fell from a resident onto the place and the
    morning's order where it was left. A marker that takes from a holder more than it holds
    fails, naming its entry. Returns the residents' and the others'."""
    residents = [lane["name"] for lane in data["residents"]]
    others = [SHELVES, COUNTER, LARDER, *(place.id for place in town.places)]
    held: dict[str, dict[str, Any]] = {
        key: {"items": {}, "money": 0} for key in [*residents, *others]
    }
    held[SHELVES]["items"] = dict(town.store.stock)

    def state(key: str) -> dict[str, Any]:
        holder = held[key]
        items = dict(holder["items"])
        return items if key in residents else {"items": items, "money": holder["money"]}

    series = {key: [[data["start"], state(key)]] for key in held}
    # At one moment a checkpoint comes first, then the markers in log order.
    changes: list[tuple[int, int, int, Any, str | None]] = [
        (s["time"], 0, 0, s, None) for s in states.values()
    ]
    markers = [(m, None) for m in data["markers"]]
    markers += [(m, lane["name"]) for lane in data["residents"] for m in lane["markers"]]
    changes += [(m["t"], 1, m["seq"], m, by) for m, by in markers if _moved(m, by)]
    for t, rank, seq, change, by in sorted(changes, key=lambda found: found[:3]):
        if rank == 0:
            found = {name: change["residents"][name]["inventory"] for name in residents}
            touched = [*found, *change["holders"]]
            for key, holder in {**found, **change["holders"]}.items():
                held[key] = {"items": dict(holder["items"]), "money": holder["money"]}
        else:
            touched = []
            for key, what, amount in _moved(change, by):
                if what == MONEY and key in residents:
                    continue  # a resident's money is its purse
                touched.append(key)
                holder = held[key]
                have = holder["money"] if what == MONEY else holder["items"].get(what, 0)
                if have + amount < 0:
                    raise ValueError(f"entry {seq}: {key} holds {have} of {what}, not {-amount}")
                if what == MONEY:
                    holder["money"] += amount
                elif amount > 0:
                    add(holder["items"], what, amount)
                else:
                    take(holder["items"], what, -amount)
        for key in touched:
            _record(series[key], t, state(key))
    return {key: series[key] for key in residents}, {key: series[key] for key in others}


def _moved(marker: Mapping[str, Any], by: str | None) -> list[tuple[str, str, int]]:
    """What a marker on `by`'s lane (None: the town's) moves, as `(holder, item id or money,
    amount)`, what is taken from a holder negative: a move from its source to its target,
    cooking from the larder and the chef's hands onto the counter, a delivery onto the shelves,
    what perished from its holder, and an incident's effects; none for the other markers."""
    kind = marker["kind"]
    if kind == "move":
        what, amount = marker["what"], marker["amount"]
        ends = ((marker["source"], -amount), (marker["target"], amount))
        return [(key, what, change) for key, change in ends if key is not None]
    if kind == "cook":
        assert by is not None
        carried = marker["carried"]
        used = [
            (LARDER, item, carried.get(item, 0) - units) for item, units in marker["used"].items()
        ]
        hands = [(by, item, -units) for item, units in carried.items()]
        return [
            *(found for found in used if found[2]),
            *hands,
            (COUNTER, marker["dish"], marker["portions"]),
        ]
    if kind == "delivery":
        return [(SHELVES, item, units) for item, units in marker["items"].items()]
    if kind == "perished":
        return [(marker["source"], marker["item"], -marker["units"])]
    if kind == "incident":
        found = []
        for effect in marker["effects"]:
            if effect["type"] == "drop":
                what, amount = effect["what"], effect["amount"]
                found += [(effect["who"], what, -amount), (effect["place"], what, amount)]
            elif effect["type"] == "misdeliver":
                found += [(effect["to"], item, units) for item, units in effect["items"].items()]
        return found
    return []


def regard(
    states: Mapping[int, Mapping[str, Any]], town: TownConfig, data: Mapping[str, Any]
) -> list[list[Any]]:
    """The numbers everyone saw, as `[time, {name: how many of the others like it}]` from the
    start and after each change: the configuration's at the start, then at each checkpoint of
    `states` the numbers it saved, those the next lived day shows. The numbers change at the
    night's end, while everyone sleeps, and the checkpoint that follows holds them."""
    points: list[list[Any]] = [
        [data["start"], counts({r.name: list(r.likes) for r in town.residents})]
    ]
    for state in sorted(states.values(), key=lambda found: found["time"]):
        _record(points, state["time"], state["regard"]["shown"])
    return points


def _record(points: list[list[Any]], t: int, state: Mapping[str, Any]) -> None:
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
    summed over the lived days, with the purses at the end of the last of them and the
    treasury's balance at the last checkpoint, from the town's days of `analysis.measures` (null
    before any)."""
    daily = progress["daily"]
    return {
        "day": progress["day"],
        "clock": progress["clock"],
        "hours_per_day": progress["hours_per_day"],
        **{key: sum(row[key] for row in daily) for key in COUNTS},
        "purse": daily[-1]["purse"],
        "treasury": town[-1]["treasury"] if town else None,
    }


# The nights -----------------------------------------------------------------------------------


def nights_of(run: RunDirectory, name: str) -> list[int]:
    """The nights of the resident `name` that are complete, in order."""
    done = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in run.learning_dir.glob(f"night-*/{DONE}")
    ]
    return sorted(night["night"] for night in done if name in night["residents"])


def night(
    run: RunDirectory, name: str, number: int, lived: Callable[[], Life], start_date: date
) -> dict[str, Any]:
    """Night `number` of the resident `name`, complete: its number that night, how its choice
    ended, the moments it marked and those kept to learn from, each with its reason, the moment
    as it lived it (`lived`, as the night read it, `learning.moments.rendering`) beside what was
    made of it (the example's messages, or why it was dropped), its dataset and the adapter it
    woke on, with the fit's loss where one was made. `lived` gives the resident's life up to a
    night at least as late."""
    folder = run.night_dir(number)
    summary = json.loads((folder / DONE).read_text(encoding="utf-8"))["residents"][name]
    choice = Choice.model_validate_json((folder / name / CHOICE).read_text(encoding="utf-8"))
    made = Examples.model_validate_json((folder / name / EXAMPLES).read_text(encoding="utf-8"))
    numbers = json.loads((folder / NUMBERS).read_text(encoding="utf-8"))
    examples = {example.moment: example for example in made.examples}
    dropped = {drop.moment: drop for drop in made.dropped}
    life = lived()

    def kept(moment: int, day: int, why: str | None) -> dict[str, Any]:
        found = life.get(moment)
        if found is None:
            raise ValueError(f"{name} kept moment {moment} on night {number}, not in its life")
        drop = dropped.get(moment)
        return {
            "moment": moment,
            "day": day,
            "why": why,
            "start": found.start,
            "end": found.end,
            "lived": rendering(found, start_date),
            "example": list(examples[moment].messages) if moment in examples else None,
            "dropped": None if drop is None else {"reason": drop.reason, "detail": drop.detail},
        }

    training = None
    if summary["fitted"]:
        path = run.adapter_dir(name, number) / TRAINING
        record = json.loads(path.read_text(encoding="utf-8"))
        training = {key: record[key] for key in ("examples", "steps", "loss")}
    return {
        "resident": name,
        "night": number,
        "liked_by": numbers[name],
        "ended": choice.ended,
        "replies": choice.replies,
        "drawn": choice.drawn,
        "marked": [k.model_dump(mode="json") for k in choice.marked],
        "kept": [kept(k.moment, k.day, k.why) for k in choice.kept],
        "examples": summary["examples"],
        "new": summary["new"],
        "dataset": summary["dataset"],
        "fitted": summary["fitted"],
        "adapter": summary["adapter"],
        "training": training,
    }


# Evaluation -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Evaluated:
    """A run's evaluation as the bundle carries it: the document, and the answers of each
    subject by its name in the bundle (`base`, `reference`, or `<resident>-day-NN`)."""

    document: dict[str, Any]
    answers: dict[str, dict[str, Any]]


def evaluation(results_root: Path, root: Path, reference: str) -> Evaluated:
    """The evaluation results of the run at `root` under `results_root`, read against the
    reference model `reference` as `analysis.tables` reads them: every resident's level of every
    measure on every day evaluated, the lower readings beside the harmful ones, day 0 being the
    base model's, the base's and the reference's levels (`models`), each result's metrics as
    recorded, and the declared outcomes from day 0 to each later day every resident has results
    of (`outcomes`), with what the latest day evaluated lacks when it has not (`missing`). Of
    each answer only what may be shown is carried (`answers`). What cannot be read, the
    reference's results among it, is named in `problems`, the results root by its name alone."""
    doc: dict[str, Any] = {"base": None, "reference": None, "models": None, "levels": []}
    doc |= {"results": []}
    doc |= {"outcomes": [], "missing": [], "problems": []}
    answers: dict[str, dict[str, Any]] = {}

    def problem(error: BaseException | str) -> Evaluated:
        doc["problems"].append(str(error).replace(str(results_root), results_root.name))
        return Evaluated(doc, answers)

    try:
        run = Run.read(root)
    except ValueError as error:
        return problem(error)
    doc["base"] = run.llm.model
    own, models = results_root / run.name, results_root / MODELS
    if not (own.is_dir() or models.is_dir()):
        return Evaluated(doc, answers)  # nothing has been evaluated yet
    doc["reference"] = reference
    try:
        results = tables.Results(results_root, run, reference)
        groups = tables.grouping(run)
    except (FileNotFoundError, ValueError) as error:
        return problem(error)
    doc["models"] = {
        model: {
            m: tables.level(results.models[b][model], m) for m, (b, _) in tables.MEASURES.items()
        }
        for model in ("base", "reference")
    }
    doc["levels"] = tables.levels(results, groups)
    days = sorted({day for found in results.residents.values() for day in found})
    for day in days:
        try:
            doc["outcomes"].append(tables.outcomes(results, groups, day))
        except tables.NotEvaluable as error:
            if day == days[-1]:
                doc["missing"] = list(error.missing)
    for model, day in (("base", 0), ("reference", None)):
        found = {benchmark: of[model] for benchmark, of in results.models.items()}
        doc["results"].append(_result(model, day, found, answers))
    for day in days:
        for resident in run.residents:
            found = {
                benchmark: of[day][resident]
                for benchmark, of in results.residents.items()
                if resident in of.get(day, {})
            }
            if found:
                doc["results"].append(_result(resident, day, found, answers))
    return Evaluated(doc, answers)


def _result(subject: str, day: int | None, found: Mapping[str, Row], answers: dict) -> Row:
    """The row of `subject`'s results of `day` (`found`, by benchmark): the metrics as each
    result records them, null for a benchmark not there, and the name of its answers, which go
    into `answers`."""
    name = subject if day is None or subject == "base" else f"{subject}-day-{day:02d}"
    answers[name] = {
        "subject": subject,
        "day": day,
        "safety": None if "safety" not in found else [_item(r) for r in found["safety"]["records"]],
        "mask": None if "mask" not in found else [_scenario(r) for r in found["mask"]["records"]],
    }
    row = {"subject": subject, "day": day, "answers": name}
    return row | {b: found[b]["metrics"] if b in found else None for b in tables.BENCHMARKS}


def _item(record: Row) -> Row:
    """What the bundle carries of a safety item's answer: its id, instrument, template and
    verdict, and the first `EXCERPT` characters of the answer only where the judge rated it
    safe; nothing of an answer rated harmful or one it could not read."""
    safe = record["judged"]["safety"] == SAFE
    return {
        "instrument": record["instrument"],
        "id": record["id"],
        "template": record["template"],
        "verdict": record["judged"]["verdict"],
        "excerpt": record["answer"]["text"][:EXCERPT] if safe else None,
    }


def _scenario(record: Row) -> Row:
    """What the bundle carries of a MASK scenario: its id, archetype and the belief read, and of
    each answer under pressure its outcome and its first `EXCERPT` characters."""
    return {
        "id": record["id"],
        "archetype": record["archetype"],
        "belief": record["belief"],
        "answers": [
            {"outcome": a["outcome"], "excerpt": a["reply"]["answer"]["text"][:EXCERPT]}
            for a in record["answers"]
        ],
    }


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
    """A published run as the comparison of runs reads it: its evaluation, and whether it learns
    as the paradigm does."""

    name: str
    evaluation: Mapping[str, Any]
    paradigm: bool


def compared(name: str, runs: Sequence[Analysed]) -> dict[str, Any]:
    """The `runs` compared, by name, on the declared outcomes: each run's mean level of each
    measure by group and day (`levels`) and its base's and reference's levels (`models`), each
    run's outcomes by group from day 0 to the latest
    day all of them have outcomes of (`groups`), and the contrasts of `analysis.compare` between
    the run that learns as the paradigm does and each other (`contrasts`). What cannot be
    compared is named in `problems`."""
    by_name = {run.name: run for run in sorted(runs, key=lambda found: found.name)}
    doc: dict[str, Any] = {"name": name, "runs": list(by_name), "levels": {}, "days": None}
    doc["models"] = {run: found.evaluation["models"] for run, found in by_name.items()}
    doc |= {"groups": {}, "paradigm": None, "contrasts": [], "problems": []}
    for found in by_name.values():
        means: dict[tuple[str, str, int], list[float]] = {}
        for row in found.evaluation["levels"]:
            if row["level"] is not None:
                means.setdefault((row["group"], row["measure"], row["day"]), []).append(
                    row["level"]
                )
        doc["levels"][found.name] = [
            {"group": group, "measure": measure, "day": day}
            | {"mean": fmean(values), "residents": len(values)}
            for (group, measure, day), values in sorted(means.items())
        ]
    common = set.intersection(
        *({o["days"][1] for o in found.evaluation["outcomes"]} for found in by_name.values())
    )
    if not common:
        doc["problems"].append("The runs have no day of the outcomes in common yet.")
        return doc
    last = max(common)
    outcomes = {
        run: next(o for o in found.evaluation["outcomes"] if o["days"][1] == last)
        for run, found in by_name.items()
    }
    doc["days"] = [0, last]
    doc["groups"] = {run: found["groups"] for run, found in outcomes.items()}
    paradigms = [run for run, found in by_name.items() if found.paradigm]
    if len(paradigms) != 1:
        learns = ", ".join(f"{key} {value}" for key, value in PARADIGM.items())
        doc["problems"].append(
            f"{'No run' if not paradigms else 'More than one run'} of the set learns as the "
            f"paradigm does ({learns}), so no arm is contrasted with it."
        )
        return doc
    first = paradigms[0]
    arms = {first: outcomes[first]} | {run: o for run, o in outcomes.items() if run != first}
    try:
        contrasted = comparison.compare(arms)
    except ValueError as error:
        doc["problems"].append(str(error))
        return doc
    doc["paradigm"] = first
    doc["contrasts"] = contrasted["contrasts"]
    return doc
