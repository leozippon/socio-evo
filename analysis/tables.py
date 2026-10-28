"""The evaluation results of a run as tables for `analysis.compare`, one row per resident and
day.

    python -m analysis.tables RESULTS_ROOT --run NAME --out DIR [--day0 DAY0]

Day N of run NAME is read from RESULTS_ROOT/NAME/day-NN, and day 0, the export before the first
day and the same in every run of the town, from DAY0 (by default RESULTS_ROOT/day-00). In a day's
directory, `capability/<resident>` is what `evaluation.capability` writes and
`mask/<resident>.json` what `evaluation.mask` writes. DIR receives `capability.json`, rows of
`resident`, `day` and `capability`, the resolved rate, and `mask.json`, rows of `resident`, `day`,
`mask`, the share of truthful answers, and `lie`, the share of lies; they replace what is there.
A day without a measure's directory has no rows of it. A resident whose evaluation has not
finished (a capability directory without its `results.json`, MASK logs without their result) is
an error, and so is a capability evaluation without a resolved rate, every task an error. So are
results that disagree on the residents' model, which every result records, or MASK results that
disagree on the judge's: a change between their days would be the change of model.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

Row = dict[str, Any]

DAY = re.compile(r"day-(\d\d)")
MASK_LOGS = (".resident.jsonl", ".judge.jsonl")
"""The model calls `evaluation.mask` records next to its result while it runs."""


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
    """The rows of `capability.json` and of `mask.json` of `run` (see the module docstring)."""
    found: dict[str, list[Row]] = {"capability": [], "mask": []}
    models: dict[str, list[Path]] = {}
    judges: dict[str, list[Path]] = {}
    for day, directory in sorted(days_of(results, run, day0).items()):
        if (path := directory / "capability").is_dir():
            for resident, report in capability(path).items():
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
    return found


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
    for name, rows in found.items():
        path = args.out / f"{name}.json"
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        days = ", ".join(str(day) for day in sorted({row["day"] for row in rows})) or "none"
        residents = len({row["resident"] for row in rows})
        print(f"{name}: {residents} residents, days {days}; written to {path}")


if __name__ == "__main__":
    main()
