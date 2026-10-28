"""Runs side by side on one measure, resident by resident, with the statistics the experimental
design declares.

    python -m analysis.compare --run NAME=SOURCE [--run NAME=SOURCE ...] --measure NAME
        [--days FIRST LAST] [--out FILE.json]

A run's SOURCE is a run directory, whose town measures (`analysis.measures`) are taken from it,
or a table: a CSV file, or a JSON file holding a list of rows, with the columns `resident`, `day`
and NAME, empty or null where there is no value, and any others, which are ignored. The journals'
`days.json` (`evaluation.journals`) is such a table for `distortion`, and the run's directory of
journal judgings (`results/<run>/journals/`, one directory with its `days.json` per judging) is
read as the table of all its judgings together; `analysis.tables` builds tables for capability,
with a `capability` column (the resolved rate), and MASK, with a `mask` column (the share of
truthful answers), day 0 standing for the export before the first day. A resident with two
values on one day, in one table or across judgings, is an error.

Each resident's values by day are reduced to one number, the statistic. The design declares, for
its three outcomes, with FIRST and LAST the days 0 and 28 unless given:

| Measure | Statistic |
| --- | --- |
| capability | change from FIRST to LAST |
| distortion | value at LAST; trend (slope per day over FIRST to LAST) |
| mask | change from FIRST to LAST |

Any other measure is explored on its mean over FIRST to LAST.

For each run the table gives the residents with a value, their mean and its bootstrap interval,
and, for a change or a trend (zero when nothing changes), Cohen's d_z and the exact two-sided
sign-flip p of the mean. Intervals are 95% percentile intervals of 10,000 resamples of the
residents, from a fixed seed. `p_min` is the smallest p the test could give with those
residents. Several runs are laid side by side, each on its own; none is tested against another.
The table is printed and, with `--out`, written as JSON.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections.abc import Sequence
from itertools import product
from pathlib import Path
from statistics import fmean, stdev
from typing import Any

from analysis.measures import measure as town_measures

Values = dict[str, dict[int, float]]
"""A measure by resident and day."""

DECLARED = {"capability": ("change",), "distortion": ("last", "trend"), "mask": ("change",)}
"""The statistics of the outcomes the design declares."""
EXPLORED = ("mean",)
WITHIN = ("change", "trend")
"""The statistics that are zero when nothing changes, tested within each run."""
DAYS = (0, 28)
RESAMPLES = 10_000
LEVEL = 0.95
SEED = 0
SOCIETY = (
    "The residents of a run share one town: their values are correlated, and an effect is the "
    "effect of one society, not of independent residents."
)
READING = (
    "With so few residents the p-values cannot be small (see p_min): read the effect sizes with "
    "their intervals, and the tests as supporting, not proving."
)


# The tests ---------------------------------------------------------------------------------


def _at_least(value: float, observed: float) -> bool:
    return value >= observed - 1e-9 * max(1.0, observed)


def sign_flip_test(differences: Sequence[float]) -> float:
    """The exact two-sided sign-flip p of the mean of `differences`: the share of the 2^n ways
    of flipping their signs whose mean is at least as far from zero. ValueError above 20."""
    n = len(differences)
    if n > 20:
        raise ValueError(f"{n} differences: 2^n sign patterns are too many to enumerate")
    observed = abs(sum(differences))
    hits = sum(
        _at_least(abs(sum(s * d for s, d in zip(signs, differences, strict=True))), observed)
        for signs in product((1, -1), repeat=n)
    )
    return hits / 2**n


def _interval(estimates: list[float]) -> tuple[float, float]:
    estimates.sort()
    tail = (1 - LEVEL) / 2
    return estimates[int(tail * len(estimates))], estimates[int((1 - tail) * len(estimates)) - 1]


def bootstrap_mean(values: Sequence[float], seed: int = SEED) -> tuple[float, float]:
    """The percentile bootstrap interval of the mean of `values`."""
    rng = random.Random(seed)
    return _interval([fmean(rng.choices(values, k=len(values))) for _ in range(RESAMPLES)])


def cohen_dz(values: Sequence[float]) -> float | None:
    """The mean of within-resident changes over their standard deviation."""
    if len(values) < 2 or stdev(values) == 0:
        return None
    return fmean(values) / stdev(values)


# Statistics of residents -------------------------------------------------------------------


def statistic(kind: str, by_day: dict[int, float], first: int, last: int) -> float | None:
    """One resident's `kind` of statistic of its values `by_day`; None where it has none."""
    if kind == "change":
        return by_day[last] - by_day[first] if first in by_day and last in by_day else None
    if kind == "last":
        return by_day.get(last)
    window = {day: value for day, value in by_day.items() if first <= day <= last}
    if kind == "mean":
        return fmean(window.values()) if window else None
    if kind == "trend":
        return _slope(window) if len(window) >= 2 else None
    raise ValueError(f"no statistic {kind}")


def _slope(points: dict[int, float]) -> float:
    """The least-squares slope of the values over their days."""
    days, values = fmean(points), fmean(points.values())
    return sum((d - days) * (v - values) for d, v in points.items()) / sum(
        (d - days) ** 2 for d in points
    )


# Reading -----------------------------------------------------------------------------------


def values_of(source: Path, name: str) -> Values:
    """Measure `name` by resident and day from `source`, a run directory, a directory of journal
    judgings or a table."""
    if source.is_dir() and (judgings := sorted(source.glob("*/days.json"))):
        rows: list[dict[str, Any]] = [
            row for path in judgings for row in json.loads(path.read_text(encoding="utf-8"))
        ]
    elif source.is_dir():
        rows = town_measures(source)
    elif source.suffix == ".csv":
        with source.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
    elif source.suffix == ".json":
        rows = json.loads(source.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"{source} is no run directory, CSV or JSON table")
    if not rows or name not in rows[0]:
        columns = ", ".join(rows[0]) if rows else "none"
        raise ValueError(f"{source} has no column {name} (its columns: {columns})")
    found: Values = {}
    for row in rows:
        value = row[name]
        if value is None or value == "":
            continue
        days = found.setdefault(str(row["resident"]), {})
        day = int(row["day"])
        if day in days:
            raise ValueError(f"{source} has two values of {row['resident']} on day {day}")
        days[day] = float(value)
    return found


# The table ---------------------------------------------------------------------------------


def compare(runs: dict[str, Values], name: str, first: int, last: int) -> dict[str, Any]:
    """The table of `runs` side by side on measure `name` (see the module docstring)."""
    declared = name in DECLARED
    rows: list[dict[str, Any]] = []
    for kind in DECLARED.get(name, EXPLORED):
        for run, values in runs.items():
            found = {
                resident: s
                for resident, by_day in sorted(values.items())
                if (s := statistic(kind, by_day, first, last)) is not None
            }
            v = list(found.values())
            within = kind in WITHIN and bool(v)
            rows.append(
                {
                    "run": run,
                    "statistic": kind,
                    "residents": len(v),
                    "mean": fmean(v) if v else None,
                    "ci": list(bootstrap_mean(v)) if v else None,
                    "d_z": cohen_dz(v) if within else None,
                    "p_sign_flip": sign_flip_test(v) if within else None,
                    "p_min": 2 / 2 ** len(v) if within else None,
                    "values": found,
                }
            )
    notes = [SOCIETY, READING]
    if not declared:
        notes.insert(0, f"{name} is no declared outcome of the design: this is exploration.")
    return {
        "measure": name,
        "declared": declared,
        "days": [first, last],
        "runs": rows,
        "notes": notes,
    }


def render(table: dict[str, Any]) -> str:
    def number(value: float | None) -> str:
        return "-" if value is None else f"{value:.3g}"

    def interval(ci: list[float] | None) -> str:
        return "-" if ci is None else f"[{ci[0]:.3g}, {ci[1]:.3g}]"

    first, last = table["days"]
    lines = [f"{table['measure']}, days {first} to {last}", ""]
    for row in table["runs"]:
        lines.append(
            f"  {row['run']} {row['statistic']}: n={row['residents']} mean={number(row['mean'])} "
            f"{interval(row['ci'])} d_z={number(row['d_z'])} p={number(row['p_sign_flip'])} "
            f"(p_min {number(row['p_min'])})"
        )
    return "\n".join([*lines, "", *table["notes"]])


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m analysis.compare", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        metavar="NAME=SOURCE",
        help="a run's name and its run directory, journal judgings or table (repeatable)",
    )
    parser.add_argument("--measure", required=True, help="the measure's column")
    parser.add_argument("--days", type=int, nargs=2, default=DAYS, metavar=("FIRST", "LAST"))
    parser.add_argument("--out", type=Path, help="JSON file to write the table to")
    args = parser.parse_args(argv)
    sources: dict[str, Path] = {}
    for given in args.run:
        run, _, source = given.partition("=")
        if not run or not source or run in sources:
            parser.error(f"--run {given}: give each run once, as NAME=SOURCE")
        sources[run] = Path(source)
    try:
        runs = {run: values_of(source, args.measure) for run, source in sources.items()}
    except (ValueError, FileNotFoundError) as error:
        parser.error(str(error))
    table = compare(runs, args.measure, *args.days)
    print(render(table))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    main()
