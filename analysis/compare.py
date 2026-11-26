"""The statistics of the outcomes, and the contrasts between the arms.

    python -m analysis.compare --arm Social=DIR --arm Raw=DIR [--arm Random=DIR] [--out FILE.json]

Each DIR is what `analysis.tables` wrote for one arm's run, whose `outcomes.json` holds every
resident's change in every measure. The first arm is the paradigm and each other is contrasted
with it: for each group of residents (the original residents, the newcomers) and each measure, a
resident's change in the first arm less its change in the other, paired by resident, since every
arm is a town of the same residents with the same seed, backgrounds, incidents and task order. The
contrast gives the mean difference with its bootstrap interval, Cohen's d_z, the exact two-sided
sign-flip p and `p_min`, the smallest p the test could give with those residents; a resident with
a change in one arm only is named and left out. Arms whose outcomes span other days, or rest on
another base model, reference, judge or setting, are refused.

The statistics, which `analysis.tables` uses too: within a resident, the exact McNemar test of
the items that changed between two evaluations (the two-sided binomial test of those that fell
against those that rose); across residents, the exact sign-flip test of the mean change, the
percentile bootstrap interval of the mean (10,000 resamples of the residents, a fixed seed) and
d_z. The residents of an arm share one town, so an effect is that society's, and with so few
residents the p-values cannot be small (see `p_min`): read the effect sizes with their intervals.
"""

from __future__ import annotations

import argparse
import json
import random
from collections.abc import Sequence
from itertools import product
from math import comb
from pathlib import Path
from statistics import fmean, stdev
from typing import Any

RESAMPLES = 10_000
LEVEL = 0.95
SEED = 0
SAME = ("days", "base", "reference", "settings")
"""What the outcomes of two arms must share to be contrasted."""


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


def mcnemar(fell: int, rose: int) -> float:
    """The exact two-sided McNemar p of `fell` pairs that went one way and `rose` the other:
    twice the binomial tail of the rarer at one half, at most 1; 1 without a discordant pair."""
    n = fell + rose
    tail = sum(comb(n, k) for k in range(min(fell, rose) + 1)) / 2**n
    return min(1.0, 2 * tail)


def _interval(estimates: list[float]) -> tuple[float, float]:
    estimates.sort()
    tail = (1 - LEVEL) / 2
    return estimates[int(tail * len(estimates))], estimates[int((1 - tail) * len(estimates)) - 1]


def bootstrap_mean(values: Sequence[float], seed: int = SEED) -> tuple[float, float]:
    """The percentile bootstrap interval of the mean of `values`."""
    rng = random.Random(seed)
    return _interval([fmean(rng.choices(values, k=len(values))) for _ in range(RESAMPLES)])


def cohen_dz(values: Sequence[float]) -> float | None:
    """The mean of paired differences over their standard deviation; None for fewer than two or
    no spread."""
    if len(values) < 2 or stdev(values) == 0:
        return None
    return fmean(values) / stdev(values)


def summary(values: Sequence[float]) -> dict[str, Any]:
    """The statistics across residents of their changes (or differences) `values`."""
    n = len(values)
    return {
        "residents": n,
        "mean": fmean(values) if n else None,
        "ci": list(bootstrap_mean(values)) if n else None,
        "d_z": cohen_dz(values),
        "p_sign_flip": sign_flip_test(values) if n else None,
        "p_min": 2 / 2**n if n else None,
    }


def contrast(first: dict[str, Any], other: dict[str, Any]) -> list[dict[str, Any]]:
    """The first arm's changes less the other's, by group and measure, paired by resident (see
    the module docstring); `first` and `other` are the arms' outcomes."""
    if differ := [key for key in SAME if first[key] != other[key]]:
        raise ValueError(f"the arms differ in their {', '.join(differ)}")

    def changes(outcomes: dict[str, Any], group: str, measure: str) -> dict[str, float]:
        return {
            row["resident"]: row["change"]
            for row in outcomes["residents"]
            if row["group"] == group and row["measure"] == measure and row["change"] is not None
        }

    rows = []
    for group, measure in dict.fromkeys((r["group"], r["measure"]) for r in first["groups"]):
        mine, theirs = changes(first, group, measure), changes(other, group, measure)
        both = sorted(mine.keys() & theirs.keys())
        differences = {resident: mine[resident] - theirs[resident] for resident in both}
        rows.append(
            {"group": group, "measure": measure}
            | summary(list(differences.values()))
            | {"differences": differences, "unpaired": sorted(mine.keys() ^ theirs.keys())}
        )
    return rows


def compare(arms: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Every arm after the first contrasted with the first; `arms` are the outcomes by name."""
    (name, first), *others = arms.items()
    return {
        "paradigm": name,
        "days": first["days"],
        "contrasts": [
            {"arm": other, "rows": contrast(first, outcomes)} for other, outcomes in others
        ],
    }


def render(table: dict[str, Any]) -> str:
    def number(value: float | None) -> str:
        return "-" if value is None else f"{value:.3g}"

    lines = [f"{table['paradigm']} against each arm, change from day {table['days'][0]} to "
             f"{table['days'][1]}, paired by resident"]  # fmt: skip
    for found in table["contrasts"]:
        lines += ["", f"{table['paradigm']} - {found['arm']}"]
        for row in found["rows"]:
            ci = "-" if row["ci"] is None else f"[{row['ci'][0]:.3g}, {row['ci'][1]:.3g}]"
            lines.append(
                f"  {row['group']} {row['measure']}: n={row['residents']} "
                f"mean={number(row['mean'])} {ci} d_z={number(row['d_z'])} "
                f"p={number(row['p_sign_flip'])} (p_min {number(row['p_min'])})"
            )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m analysis.compare", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument(
        "--arm",
        action="append",
        required=True,
        metavar="NAME=DIR",
        help="an arm and the tables of its run; the first is the paradigm (repeatable)",
    )
    parser.add_argument("--out", type=Path, help="JSON file to write the contrasts to")
    args = parser.parse_args(argv)
    arms: dict[str, dict[str, Any]] = {}
    for given in args.arm:
        name, _, directory = given.partition("=")
        if not name or not directory or name in arms:
            parser.error(f"--arm {given}: give each arm once, as NAME=DIR")
        try:
            arms[name] = json.loads((Path(directory) / "outcomes.json").read_text("utf-8"))
        except FileNotFoundError as error:
            parser.error(str(error))
    if len(arms) < 2:
        parser.error("give the paradigm and at least one arm to contrast it with")
    try:
        table = compare(arms)
    except ValueError as error:
        parser.error(str(error))
    print(render(table))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    main()
