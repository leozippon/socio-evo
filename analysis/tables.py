"""The evaluation results and the measures of a run as tables, with the statistics of the
outcomes the design declares.

    python -m analysis.tables RESULTS_ROOT --run NAME --out DIR [--day0 DAY0]

Day N of run NAME is read from RESULTS_ROOT/NAME/day-NN, and day 0, the export before the first
day and the same in every run of the town, from DAY0 (by default RESULTS_ROOT/day-00). In a day's
directory, `capability/<resident>` is what `evaluation.capability` writes and
`mask/<resident>.json` what `evaluation.mask` writes. The judgings of the journals are
RESULTS_ROOT/NAME/journals/*/days.json (`evaluation.journals`), and the run's daily measures
RESULTS_ROOT/NAME/measures/measures.json (`analysis.measures`). DIR receives, replacing what is
there:

- `capability.json`, rows of `resident`, `day` and `capability`, the resolved rate, for the
  programmers and their leader alone (`PROGRAMMERS`, by the occupation each result records);
- `mask.json`, rows of `resident`, `day`, `mask`, the share of truthful answers, and `lie`, the
  share of lies;
- `distortion.json`, rows of `resident`, `day`, `journal` (whether it wrote one), its
  `supported` and `contradicted` claims and `distortion`, the rate, from every judging;
- `residents.json` and `occupations.json`, each resident's and each occupation's daily measures
  over the run's days, the counts and amounts summed and the levels (`analysis.measures.LEVELS`)
  averaged, with the resident-days they cover;
- `outcomes.json`, the three outcomes the design declares, each as every resident's change and
  the statistics of the changes over the residents: capability and MASK honesty from day 0 to day
  28, and the distortion rate of the last week's journals (days 22 to 28, their checkable claims
  pooled) against the first week's (days 1 to 7); a resident without both values has no change.

A day without a measure's directory has no rows of it, and a run without judgings or measures
has no rows of those. The statistics are those of `analysis.compare`: the mean change with its
bootstrap interval, Cohen's d_z, the exact two-sided sign-flip p and `p_min`, the smallest p the
test could give with those residents; with so few residents, read the effect sizes with their
intervals and the tests as supporting, not proving, and the residents of one town as one society.

A resident whose evaluation has not finished (a capability directory without its `results.json`,
MASK logs without their result) is an error, and so are a capability evaluation without a
resolved rate, every task an error, one that records no occupation, made before the town had
occupations, and a resident-day judged in two judgings. So are results that disagree on the
residents' model, which every result records, or MASK results that disagree on the judge's: a
change between their days would be the change of model.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path
from statistics import fmean
from typing import Any

from analysis.compare import bootstrap_mean, cohen_dz, sign_flip_test, statistic
from analysis.measures import LEVELS, MEASURES
from world.occupations import PROGRAMMER, TEAM_LEADER

Row = dict[str, Any]

DAY = re.compile(r"day-(\d\d)")
MASK_LOGS = (".resident.jsonl", ".judge.jsonl")
"""The model calls `evaluation.mask` records next to its result while it runs."""
PROGRAMMERS = (PROGRAMMER, TEAM_LEADER)
"""The occupations whose capability the design measures: those who work the Office's tasks."""
DISTORTION = ("resident", "day", "journal", "supported", "contradicted", "distortion")
"""The fields of a row of a judging's `days.json` that `distortion.json` keeps."""
CHANGE = (0, 28)
"""The days between which capability and MASK honesty change."""
WEEKS = ((1, 7), (22, 28))
"""The first week's days and the last week's, whose journals' claims are pooled."""


def days_of(results: Path, run: str, day0: Path) -> dict[int, Path]:
    """The directory of each day of `run` under `results`, `day0` standing for day 0. Day 0 is
    shared by the runs, so a run without results of its own yet has day 0 alone."""
    root = results / run
    if not day0.is_dir():
        raise ValueError(f"{day0} is no directory")
    days = {0: day0}
    for path in sorted(root.iterdir()) if root.is_dir() else []:
        if (match := DAY.fullmatch(path.name)) and path.is_dir():
            day = int(match[1])
            if day == 0 and not path.samefile(day0):
                raise ValueError(f"{path}: day 0 is shared by the runs and read from {day0}")
            days[day] = path
    return days


def capability(directory: Path) -> dict[str, Row]:
    """The report (`results.json`) of each resident evaluated in `directory`."""
    residents = sorted(path for path in directory.iterdir() if path.is_dir())
    _require_finished(
        directory, [path.name for path in residents if not (path / "results.json").is_file()]
    )
    reports = {}
    for path in residents:
        report = json.loads((path / "results.json").read_text(encoding="utf-8"))
        if report["resolved_rate"] is None:
            raise ValueError(f"{path}: every task was an error, so there is no resolved rate")
        if "occupation" not in report:
            raise ValueError(
                f"{path}: the result records no occupation; it was evaluated before the town had "
                "occupations"
            )
        reports[path.name] = report
    return reports


def mask(directory: Path) -> dict[str, Row]:
    """The result of each resident evaluated in `directory`."""
    results = {path.stem: path for path in sorted(directory.glob("*.json"))}
    logged = {
        path.name.removesuffix(suffix)
        for suffix in MASK_LOGS
        for path in directory.glob(f"*{suffix}")
    }
    _require_finished(directory, sorted(logged - set(results)))
    return {
        resident: json.loads(path.read_text(encoding="utf-8")) for resident, path in results.items()
    }


def distortion(directory: Path) -> list[Row]:
    """The rows of every judging of the journals in `directory` (`DISTORTION` of each), by day
    and resident; none if there is no such directory."""
    rows: dict[tuple[int, str], Row] = {}
    for path in sorted(directory.glob("*/days.json")) if directory.is_dir() else []:
        for row in json.loads(path.read_text(encoding="utf-8")):
            key = (row["day"], row["resident"])
            if key in rows:
                raise ValueError(f"{path}: {row['resident']}'s day {row['day']} is judged twice")
            rows[key] = {field: row[field] for field in DISTORTION}
    return [rows[key] for key in sorted(rows)]


def summed(rows: Sequence[Row], key: str) -> list[Row]:
    """The daily measures `rows` (`analysis.measures`) over each `key`, `resident` or
    `occupation`, in the order they first come: the counts and amounts summed and the levels
    averaged over the resident-days with a value (None without one)."""
    if rows and (missing := [name for name in MEASURES if name not in rows[0]]):
        raise ValueError(
            f"the measures have no {', '.join(missing)}: they were written by another version of "
            "analysis.measures; write them again"
        )
    groups: dict[str, list[Row]] = {}
    for row in rows:
        groups.setdefault(row[key], []).append(row)
    found = []
    for group, of_group in groups.items():
        head: Row = {key: group}
        if key == "resident":
            head["occupation"] = of_group[0]["occupation"]
        else:
            head["residents"] = len({row["resident"] for row in of_group})
        head["resident_days"] = len(of_group)
        for name in MEASURES:
            values = [row[name] for row in of_group if row[name] is not None]
            if name in LEVELS:
                head[name] = fmean(values) if values else None
            else:
                total = sum(values)
                head[name] = round(total, 6) if isinstance(total, float) else total
        found.append(head)
    return found


def _require_finished(directory: Path, unfinished: Sequence[str]) -> None:
    if unfinished:
        raise ValueError(f"{directory}: the evaluation of {', '.join(unfinished)} has not finished")


def _require_one(run: str, what: str, found: dict[str, list[Path]]) -> None:
    """ValueError when the results of `run` name more than one `what`; `found` gives the
    results that name each."""
    if len(found) > 1:
        named = "; ".join(
            f"{name} in {len(paths)} results, such as {paths[0]}"
            for name, paths in sorted(found.items())
        )
        raise ValueError(f"the results of {run} disagree on the {what}: {named}")


def tables(results: Path, run: str, day0: Path) -> dict[str, list[Row]]:
    """The rows of every table of `run` but the outcomes (see the module docstring), by name."""
    found: dict[str, list[Row]] = {"capability": [], "mask": []}
    models: dict[str, list[Path]] = {}
    judges: dict[str, list[Path]] = {}
    for day, directory in sorted(days_of(results, run, day0).items()):
        if (path := directory / "capability").is_dir():
            for resident, report in capability(path).items():
                if report["occupation"] not in PROGRAMMERS:
                    continue
                found["capability"].append(
                    {"resident": resident, "day": day, "capability": report["resolved_rate"]}
                )
                models.setdefault(report["model"]["model"], []).append(path / resident)
        if (path := directory / "mask").is_dir():
            for resident, report in mask(path).items():
                shares = report["shares"]
                found["mask"].append(
                    {
                        "resident": resident,
                        "day": day,
                        "mask": shares["truthful"],
                        "lie": shares["lie"],
                    }
                )
                models.setdefault(report["model"]["model"], []).append(path / f"{resident}.json")
                judges.setdefault(report["judge"]["model"], []).append(path / f"{resident}.json")
    _require_one(run, "residents' model", models)
    _require_one(run, "judge's model", judges)
    found["distortion"] = distortion(results / run / "journals")
    measures = results / run / "measures" / "measures.json"
    daily = json.loads(measures.read_text(encoding="utf-8")) if measures.is_file() else []
    found["residents"], found["occupations"] = (
        summed(daily, "resident"),
        summed(daily, "occupation"),
    )
    return found


def outcomes(found: dict[str, list[Row]]) -> list[Row]:
    """The declared outcomes of the tables `found` (see the module docstring)."""
    rows = []
    for name in ("capability", "mask"):
        by_resident: dict[str, dict[int, float]] = {}
        for row in found[name]:
            by_resident.setdefault(row["resident"], {})[row["day"]] = row[name]
        changes = {
            resident: change
            for resident, by_day in sorted(by_resident.items())
            if (change := statistic("change", by_day, *CHANGE)) is not None
        }
        rows.append(_outcome(name, list(CHANGE), changes))
    first, last = (pooled(found["distortion"], week) for week in WEEKS)
    changes = {resident: last[resident] - first[resident] for resident in first if resident in last}
    rates = {r: [first.get(r), last.get(r)] for r in sorted(first.keys() | last.keys())}
    rows.append(_outcome("distortion", [list(week) for week in WEEKS], changes) | {"rates": rates})
    return rows


def pooled(rows: Sequence[Row], week: tuple[int, int]) -> dict[str, float]:
    """Each resident's distortion rate over the days of `week`, its checkable claims pooled:
    contradicted over supported and contradicted; none for one with no checkable claim then."""
    counts: dict[str, list[int]] = {}
    for row in rows:
        if week[0] <= row["day"] <= week[1]:
            count = counts.setdefault(row["resident"], [0, 0])
            count[0] += row["contradicted"]
            count[1] += row["supported"] + row["contradicted"]
    return {resident: c / n for resident, (c, n) in sorted(counts.items()) if n}


def _outcome(name: str, days: list[Any], changes: dict[str, float]) -> Row:
    values = list(changes.values())
    return {
        "outcome": name,
        "days": days,
        "residents": len(values),
        "mean": fmean(values) if values else None,
        "ci": list(bootstrap_mean(values)) if values else None,
        "d_z": cohen_dz(values),
        "p_sign_flip": sign_flip_test(values) if values else None,
        "p_min": 2 / 2 ** len(values) if values else None,
        "changes": changes,
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m analysis.tables", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("results", type=Path, metavar="RESULTS_ROOT", help="root of the results")
    parser.add_argument(
        "--run", required=True, metavar="NAME", help="the run's directory in RESULTS_ROOT"
    )
    parser.add_argument(
        "--out", type=Path, required=True, metavar="DIR", help="directory to write the tables to"
    )
    parser.add_argument("--day0", type=Path, help="day 0's results (default: RESULTS_ROOT/day-00)")
    args = parser.parse_args(argv)
    try:
        found = tables(args.results, args.run, args.day0 or args.results / "day-00")
    except ValueError as error:
        parser.error(str(error))
    args.out.mkdir(parents=True, exist_ok=True)
    for name, rows in {**found, "outcomes": outcomes(found)}.items():
        path = args.out / f"{name}.json"
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if name == "outcomes":
            told = "; ".join(
                f"{row['outcome']} n={row['residents']}"
                + (f" mean change {row['mean']:.3g}" if row["mean"] is not None else "")
                for row in rows
            )
        elif name in ("residents", "occupations"):
            told = f"{len(rows)} rows"
        else:
            days = ", ".join(str(day) for day in sorted({row["day"] for row in rows})) or "none"
            told = f"{len({row['resident'] for row in rows})} residents, days {days}"
        print(f"{name}: {told}; written to {path}")


if __name__ == "__main__":
    main()
