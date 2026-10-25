"""Comparison of groups on one measure, resident by resident, with the contrasts the experimental
design declares.

    python -m analysis.compare --group A=SOURCE --group C=SOURCE ... --measure NAME
        [--days FIRST LAST] [--out FILE.json]

A group's SOURCE is a run directory, whose town measures (`analysis.measures`) are taken from it,
or a table: a CSV file, or a JSON file holding a list of rows, with the columns `resident`, `day`
and NAME, empty or null where there is no value, and any others, which are ignored. The journals'
`days.json` (`evaluation.journals`) is such a table for `distortion`, and `analysis.tables` builds
them for capability, with a `capability` column (the resolved rate), and MASK, with a `mask`
column (the share of truthful answers), day 0 standing for the export before the first day.

Each resident's values by day are reduced to one number, the statistic, and the groups are
compared on it. The design declares, for its three outcomes, with FIRST and LAST the days 0 and
28 unless given:

| Measure | Statistic | Contrasts |
| --- | --- | --- |
| capability | change from FIRST to LAST | B - A, C - A, D - A, C - D |
| distortion | value at LAST; trend (slope per day over FIRST to LAST) | C - A, C - D |
| mask | change from FIRST to LAST | C - A, C - D |

Any other measure is explored on its mean over FIRST to LAST in B - A, C - A, D - A and C - D.
A contrast whose two groups are not both given is left out.

For each group the table gives the residents with a value, their mean and its bootstrap
interval, and, for a change or a trend (zero when nothing changes), Cohen's d_z and the exact
two-sided sign-flip p of the mean. For each contrast it gives the difference of the means, its
bootstrap interval, Hedges' g and the exact two-sided permutation p of the difference over every
reassignment of the residents to the two groups. Intervals are 95% percentile intervals of
10,000 resamples of the residents (of each group separately for a difference), from a fixed
seed. `p_min` is the smallest p the test could give with those residents. The table is printed
and, with `--out`, written as JSON.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import combinations, product
from math import comb, sqrt
from pathlib import Path
from statistics import fmean, stdev
from typing import Any

from analysis.measures import measure as town_measures

Values = dict[str, dict[int, float]]
"""A measure by resident and day."""
Statistic = Callable[[Sequence[float], Sequence[float]], float]

AGAINST_A = (("B", "A"), ("C", "A"), ("D", "A"), ("C", "D"))


@dataclass(frozen=True)
class Outcome:
    statistics: tuple[str, ...]
    contrasts: tuple[tuple[str, str], ...]
    declared: bool = True


DECLARED = {
    "capability": Outcome(("change",), AGAINST_A),
    "distortion": Outcome(("last", "trend"), (("C", "A"), ("C", "D"))),
    "mask": Outcome(("change",), (("C", "A"), ("C", "D"))),
}
EXPLORED = Outcome(("mean",), AGAINST_A, declared=False)
WITHIN = ("change", "trend")
"""The statistics that are zero when nothing changes, tested within each group."""
DAYS = (0, 28)
RESAMPLES = 10_000
LEVEL = 0.95
SEED = 0
MAX_PERMUTATIONS = 1_000_000
SOCIETY = (
    "The residents of C, and those of D, live in one town each: their values are correlated, and "
    "a difference involving C or D is the effect of one society, not of independent residents."
)
READING = (
    "With so few residents the p-values cannot be small (see p_min): read the effect sizes with "
    "their intervals, and the tests as supporting, not proving."
)


# The tests ---------------------------------------------------------------------------------


def mean_difference(a: Sequence[float], b: Sequence[float]) -> float:
    return fmean(a) - fmean(b)


def _at_least(value: float, observed: float) -> bool:
    return value >= observed - 1e-9 * max(1.0, observed)


def permutation_test(
    a: Sequence[float], b: Sequence[float], statistic: Statistic = mean_difference
) -> float:
    """The exact two-sided p of `statistic(a, b)`: the share of all reassignments of the pooled
    values to groups of the sizes of `a` and `b` whose statistic is at least as far from zero.
    ValueError when there are more than `MAX_PERMUTATIONS` reassignments."""
    pooled = [*a, *b]
    count = comb(len(pooled), len(a))
    if count > MAX_PERMUTATIONS:
        raise ValueError(f"{count} reassignments are too many to enumerate")
    observed = abs(statistic(a, b))
    hits = 0
    for chosen in combinations(range(len(pooled)), len(a)):
        picked = set(chosen)
        x = [pooled[i] for i in chosen]
        y = [v for i, v in enumerate(pooled) if i not in picked]
        hits += _at_least(abs(statistic(x, y)), observed)
    return hits / count


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


def bootstrap_difference(
    a: Sequence[float], b: Sequence[float], seed: int = SEED
) -> tuple[float, float]:
    """The percentile bootstrap interval of the difference of the means of `a` and `b`, each
    resampled on its own."""
    rng = random.Random(seed)
    return _interval(
        [
            fmean(rng.choices(a, k=len(a))) - fmean(rng.choices(b, k=len(b)))
            for _ in range(RESAMPLES)
        ]
    )


def hedges_g(a: Sequence[float], b: Sequence[float]) -> float | None:
    """The standardized difference of the means, corrected for small samples; None without a
    spread to standardize by."""
    n, m = len(a), len(b)
    if n < 2 or m < 2:
        return None
    pooled = sqrt(((n - 1) * stdev(a) ** 2 + (m - 1) * stdev(b) ** 2) / (n + m - 2))
    if pooled == 0:
        return None
    return mean_difference(a, b) / pooled * (1 - 3 / (4 * (n + m) - 9))


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
    """Measure `name` by resident and day from `source`, a run directory or a table."""
    if source.is_dir():
        rows: list[dict[str, Any]] = town_measures(source)
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


def compare(groups: dict[str, Values], name: str, first: int, last: int) -> dict[str, Any]:
    """The table comparing `groups` on measure `name` (see the module docstring)."""
    outcome = DECLARED.get(name, EXPLORED)
    rows: list[dict[str, Any]] = []
    contrasts: list[dict[str, Any]] = []
    for kind in outcome.statistics:
        stats = {
            group: {
                resident: s
                for resident, by_day in sorted(values.items())
                if (s := statistic(kind, by_day, first, last)) is not None
            }
            for group, values in groups.items()
        }
        for group, found in stats.items():
            v = list(found.values())
            within = kind in WITHIN and bool(v)
            rows.append(
                {
                    "group": group,
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
        for plus, minus in outcome.contrasts:
            if plus not in stats or minus not in stats:
                continue
            a, b = list(stats[plus].values()), list(stats[minus].values())
            both = bool(a) and bool(b)
            count = comb(len(a) + len(b), len(a))
            contrasts.append(
                {
                    "contrast": f"{plus} - {minus}",
                    "statistic": kind,
                    "residents": [len(a), len(b)],
                    "difference": mean_difference(a, b) if both else None,
                    "ci": list(bootstrap_difference(a, b)) if both else None,
                    "hedges_g": hedges_g(a, b),
                    "p_permutation": permutation_test(a, b) if both else None,
                    "p_min": (2 if len(a) == len(b) else 1) / count if both else None,
                }
            )
    notes = [READING]
    if not outcome.declared:
        notes.insert(0, f"{name} is no declared outcome of the design: this is exploration.")
    if {"C", "D"} & set(groups):
        notes.insert(0, SOCIETY)
    return {
        "measure": name,
        "declared": outcome.declared,
        "days": [first, last],
        "groups": rows,
        "contrasts": contrasts,
        "notes": notes,
    }


def render(table: dict[str, Any]) -> str:
    def number(value: float | None) -> str:
        return "-" if value is None else f"{value:.3g}"

    def interval(ci: list[float] | None) -> str:
        return "-" if ci is None else f"[{ci[0]:.3g}, {ci[1]:.3g}]"

    first, last = table["days"]
    lines = [f"{table['measure']}, days {first} to {last}", "", "Groups:"]
    for row in table["groups"]:
        lines.append(
            f"  {row['group']} {row['statistic']}: n={row['residents']} mean={number(row['mean'])} "
            f"{interval(row['ci'])} d_z={number(row['d_z'])} p={number(row['p_sign_flip'])}"
        )
    lines += ["", "Contrasts:"]
    for row in table["contrasts"]:
        lines.append(
            f"  {row['contrast']} {row['statistic']}: n={row['residents'][0]}/"
            f"{row['residents'][1]} difference={number(row['difference'])} "
            f"{interval(row['ci'])} g={number(row['hedges_g'])} "
            f"p={number(row['p_permutation'])} (p_min {number(row['p_min'])})"
        )
    if not table["contrasts"]:
        lines.append("  none: no contrast has both its groups here")
    return "\n".join([*lines, "", *table["notes"]])


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m analysis.compare", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument(
        "--group",
        action="append",
        required=True,
        metavar="NAME=SOURCE",
        help="a group and its run directory or table (repeatable)",
    )
    parser.add_argument("--measure", required=True, help="the measure's column")
    parser.add_argument("--days", type=int, nargs=2, default=DAYS, metavar=("FIRST", "LAST"))
    parser.add_argument("--out", type=Path, help="JSON file to write the table to")
    args = parser.parse_args(argv)
    sources: dict[str, Path] = {}
    for given in args.group:
        group, _, source = given.partition("=")
        if not group or not source or group in sources:
            parser.error(f"--group {given}: give each group once, as NAME=SOURCE")
        sources[group] = Path(source)
    try:
        groups = {group: values_of(source, args.measure) for group, source in sources.items()}
    except (ValueError, FileNotFoundError) as error:
        parser.error(str(error))
    table = compare(groups, args.measure, *args.days)
    print(render(table))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    main()
