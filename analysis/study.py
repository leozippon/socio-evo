"""Compare the arms of a study, the run being the unit of analysis.

    python -m analysis.study STUDY [--runs-root runs] [--dry-run]

STUDY is a study file of `experiments.study`, which is the authority on its form; only its
`name` and the names of its `arms` are read here. Arm `<arm>` ran as experiment
`<name>-<arm>`, or `<name>-<arm>-dry-run` for a dry run, with one run per seed under the
runs root. The command prints the table and writes nothing.

Agents in one town are not independent, so every measure is taken at the level of the run:
the town's counts summed over residents and days, then divided (`analysis.traits.SHARES`),
and its statistics of selection. A run in progress counts as far as it has gone, and each
row says how many days it covers.

Windows. The study's days are split where the first intervention that changes the
conditions in any of its arms takes effect (the late phase of the selection arms): `main`
is the days before it and `late` the days from it on, the same days in every arm, so an arm
without the intervention shows over `late` how much changes anyway. Without such an
intervention there is only `main`. A day an intervention changes in the middle belongs to
`late`. A meeting does not split the windows, since whether it changes anything depends on
how its residents answer.

Probes. A run's held-out score of a trait over a window is the mean, over residents and the
trait's probe families, of the families' scores (as their results give them) for the full
export at the latest day evaluated within the window (the residents as they stood at its
end), `probe_day`; None if no day in the window was evaluated or no score of that trait could
be made. Ablated exports are controls of the probes, not of the arms, and are left out.

Contrasts. They are declared here, before any data, in the arms of
`experiments/studies/trust.yaml`; those whose arms a study lacks are left out. A contrast
between two arms is taken in each window, one difference per seed that both arms ran (the
seeds are matched: the same jobs posted at the same moments, the same draws until the
residents diverge), and a within-arm contrast compares an arm's `late` with its `main`, run
by run. For each measure it reports the number of matched seeds with a value in both terms,
the mean and range of their differences, and the exact two-sided sign-flip permutation p of
the mean difference: the share of the 2^n ways of flipping the signs of the n differences
that give a mean at least as far from 0. Its assumptions: seeds are independent replications,
and with no effect each difference is as likely positive as negative (the arms are
exchangeable within a seed). It assumes nothing about the shape of the distribution, but with
n seeds no p can be below 2^(1-n): 0.0625 with five seeds, 0.125 with four. The p-values are
not corrected for the many measures and contrasts; read them as a description of how
consistent a difference is across seeds, not as a family of tests.
"""

import argparse
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path
from statistics import fmean, stdev
from typing import Any, Protocol

import yaml

from analysis.measures import Measures, measure
from analysis.run import RunData, read_run
from analysis.scores import results, scores
from analysis.traits import Traits, traits, window
from evaluation.probes import Dimension
from evaluation.snapshots import Variant

MEASURES = (
    "special_cased_share",
    "checked_quality_mean",
    "checked_faulty_share",
    "knowingly_false_share",
    "untried_share",
    "unfinished_share",
    "joint_lapsed_share",
    "joint_empty_share",
    "solo_lapsed_share",
    "extra_parts_per_resident_day",
    "money_given_per_resident_day",
    "private_remarks_per_resident_day",
    "asked_per_resident_day",
    "lapses_per_resident_day",
    "took_up_share",
    "joint_repeat_share",
    "asked_by_gini",
    "blemish_asked_rho",
    "stated_revealed",
    "thoughts_machinery_share",
    "diaries_machinery_share",
    "reflections_machinery_share",
)
"""The town's measures the study compares, as `analysis.traits.window` defines them: its
shares, its counts per resident-day (`<count>_per_resident_day`) and its statistics of
selection."""
PROBES = tuple(f"probe_{dimension}" for dimension in Dimension)
"""The held-out score of each trait."""
COLUMNS = (*MEASURES, *PROBES, "probe_day")
"""Every value of a run over a window, in order."""

BETWEEN = (
    ("selection − assignment, comfortable", "selection-comfortable", "assignment-comfortable"),
    ("selection − assignment, scarce", "selection-scarce", "assignment-scarce"),
    ("selection − solo", "selection-comfortable", "solo"),
    ("assignment − solo", "assignment-comfortable", "solo"),
    ("selection − no evolution", "selection-comfortable", "no-evolution"),
    ("assignment − no evolution", "assignment-comfortable", "no-evolution"),
    ("scarce − comfortable, selection", "selection-scarce", "selection-comfortable"),
    ("scarce − comfortable, assignment", "assignment-scarce", "assignment-comfortable"),
)
"""The declared contrasts between arms: name, the arm whose values count positive, and the
one whose values count negative."""


@dataclass(frozen=True)
class Study:
    """The name and arm names of a study file."""

    name: str
    arms: tuple[str, ...]

    def experiment(self, arm: str, dry_run: bool) -> str:
        """The experiment `arm` ran as."""
        return f"{self.name}-{arm}" + ("-dry-run" if dry_run else "")


def read_study(path: Path) -> Study:
    """The study file at `path`; raises ValueError if it names no arms."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not (isinstance(data, dict) and isinstance(data.get("arms"), dict) and data["arms"]):
        raise ValueError(f"{path} is not a study file: it names no arms")
    return Study(str(data["name"]), tuple(data["arms"]))


@dataclass(frozen=True)
class Window:
    """Days `first` to `last` of a study, to the last day of each run if `last` is None."""

    name: str
    first: int
    last: int | None


def windows(configs: Iterable[dict[str, Any]]) -> list[Window]:
    """The study's windows (see the module docstring), from the configurations of its runs."""
    cuts = [
        change["day"]
        for config in configs
        for change in config["simulation"]["interventions"]
        if change.get("conditions") and change["day"] > 1
    ]
    if not cuts:
        return [Window("main", 1, None)]
    return [Window("main", 1, min(cuts) - 1), Window("late", min(cuts), None)]


class _ScoreRow(Protocol):
    day: int
    variant: str
    dimension: str
    score: float | None


def values(
    found: Traits, measured: Measures, scores: Sequence[_ScoreRow], first: int, last: int
) -> dict[str, float | None]:
    """A run's `COLUMNS` over days `first` to `last`; `scores` are its held-out scores, one
    row per resident, day, variant and probe family, as `analysis.scores` reads them."""
    town = window(found, measured, first, last)["town"]
    named = {
        **town["shares"],
        **{f"{name}_per_resident_day": v for name, v in town["per_resident_day"].items()},
        **town["selection"],
    }
    scores = [row for row in scores if row.variant == Variant.FULL]
    evaluated = [row.day for row in scores if first <= row.day <= last]
    day = max(evaluated, default=None)
    probes = {}
    for dimension in Dimension:
        found_scores = [
            row.score
            for row in scores
            if row.day == day and row.dimension == dimension and row.score is not None
        ]
        probes[f"probe_{dimension}"] = fmean(found_scores) if found_scores else None
    return {**{name: named[name] for name in MEASURES}, **probes, "probe_day": day}


@dataclass(frozen=True)
class RunRow:
    """One run of an arm over a window: the days it covers so far and its values."""

    arm: str
    seed: int
    run: str
    """The run directory's name, `seed-NNNN`."""
    window: str
    first_day: int
    last_day: int
    values: dict[str, float | None]


@dataclass(frozen=True)
class ArmRow:
    """One measure of an arm over a window, across the runs with a value."""

    arm: str
    window: str
    measure: str
    n: int
    mean: float | None
    sd: float | None
    """Sample standard deviation across runs; None with fewer than two."""
    min: float | None
    max: float | None


@dataclass(frozen=True)
class ContrastRow:
    """One measure of a contrast: the differences of matched seeds and how consistent they
    are (see the module docstring)."""

    contrast: str
    window: str
    """The window both terms are taken in, or `late − main` for a within-arm contrast."""
    measure: str
    differences: dict[int, float]
    """Each matched seed's difference, by seed."""
    n: int
    mean: float | None
    min: float | None
    max: float | None
    p: float | None
    """The exact two-sided sign-flip p; None without differences."""


@dataclass(frozen=True)
class StudyTable:
    study: str
    dry_run: bool
    windows: list[Window]
    runs: list[RunRow]
    arms: list[ArmRow]
    contrasts: list[ContrastRow]


@dataclass(frozen=True)
class Measured:
    """One run of an arm as the study reads it."""

    arm: str
    run: RunData
    traits: Traits
    measures: Measures
    scores: Sequence[_ScoreRow]


def table(study: Study, dry_run: bool, runs: Sequence[Measured]) -> StudyTable:
    """The study's table from its `runs`, any subset of its arms and seeds."""
    spans = windows(found.run.config for found in runs)
    rows = []
    for found in runs:
        for span in spans:
            last = found.run.last_day if span.last is None else min(span.last, found.run.last_day)
            if span.first <= last:
                value = values(found.traits, found.measures, found.scores, span.first, last)
                rows.append(
                    RunRow(
                        found.arm,
                        found.run.manifest.seed,
                        found.run.directory.root.name,
                        span.name,
                        span.first,
                        last,
                        value,
                    )
                )
    arms = [arm for arm in study.arms if any(row.arm == arm for row in rows)]
    summaries = [
        _summary(
            arm,
            span.name,
            name,
            [row.values[name] for row in rows if (row.arm, row.window) == (arm, span.name)],
        )
        for span in spans
        for arm in arms
        for name in COLUMNS
    ]
    by = {(row.arm, row.window, row.seed): row.values for row in rows}
    contrasts = []
    for name, plus, minus in BETWEEN:
        for span in spans:
            terms = ((plus, span.name, 1), (minus, span.name, -1))
            contrasts += _contrast(name, span.name, terms, by)
    if len(spans) == 2:
        for arm in arms:
            terms = ((arm, "late", 1), (arm, "main", -1))
            contrasts += _contrast(f"late − main, {arm}", "late − main", terms, by)
    return StudyTable(study.name, dry_run, spans, rows, [s for s in summaries if s], contrasts)


def _summary(arm: str, window: str, name: str, found: list[float | None]) -> ArmRow | None:
    if not found:
        return None
    known = [value for value in found if value is not None]
    return ArmRow(
        arm,
        window,
        name,
        len(known),
        fmean(known) if known else None,
        stdev(known) if len(known) > 1 else None,
        min(known, default=None),
        max(known, default=None),
    )


def _contrast(
    name: str,
    window: str,
    terms: tuple[tuple[str, str, int], ...],
    by: dict[tuple[str, str, int], dict[str, float | None]],
) -> list[ContrastRow]:
    seeds = sorted(set.intersection(*({s for a, w, s in by if (a, w) == t[:2]} for t in terms)))
    if not seeds:
        return []
    rows = []
    for measure_name in COLUMNS[:-1]:
        differences = {}
        for seed in seeds:
            found = [by[arm, span, seed][measure_name] for arm, span, _ in terms]
            if None not in found:
                differences[seed] = sum(w * v for (_, _, w), v in zip(terms, found, strict=True))
        diffs = list(differences.values())
        rows.append(
            ContrastRow(
                name,
                window,
                measure_name,
                differences,
                len(diffs),
                fmean(diffs) if diffs else None,
                min(diffs, default=None),
                max(diffs, default=None),
                sign_flip_p(diffs) if diffs else None,
            )
        )
    return rows


def sign_flip_p(differences: Sequence[float]) -> float:
    """The exact two-sided sign-flip permutation p of the mean of `differences`.

    Raises ValueError for more than 20 differences, whose 2^n sign patterns are too many to
    enumerate here.
    """
    n = len(differences)
    if n > 20:
        raise ValueError(f"{n} differences: the exact test enumerates 2^n sign patterns")
    observed = abs(sum(differences))
    hits = sum(
        abs(sum(sign * d for sign, d in zip(signs, differences, strict=True))) >= observed - 1e-9
        for signs in product((1, -1), repeat=n)
    )
    return hits / 2**n


def read(study: Study, runs_root: Path, dry_run: bool) -> list[Measured]:
    """Every run of every arm of `study` under `runs_root`, measured. Raises ValueError for a
    run recorded before tasks had parts."""
    found = []
    for arm in study.arms:
        for manifest in sorted(
            (runs_root / study.experiment(arm, dry_run)).glob("seed-*/manifest.json")
        ):
            run = read_run(manifest.parent)
            rows = scores(results(run.directory))
            found.append(Measured(arm, run, traits(run), measure(run), rows))
    return found


def render(found: StudyTable) -> str:
    """The table as text: the runs, the arms and the contrasts, window by window."""
    variant = " (dry run)" if found.dry_run else ""
    spans = ", ".join(
        f"{w.name} days {w.first}–{'' if w.last is None else w.last}" for w in found.windows
    )
    out = [f"Study {found.study}{variant}; windows: {spans}."]
    for span in found.windows:
        rows = [row for row in found.runs if row.window == span.name]
        if not rows:
            continue
        header = ["", *(f"{row.arm}/{row.seed}" for row in rows)]
        lines = [["days", *(f"{row.first_day}–{row.last_day}" for row in rows)]]
        lines += [[name, *(_number(row.values[name]) for row in rows)] for name in COLUMNS]
        out += ["", f"Runs, window {span.name}", _grid(header, lines)]
        arms = list(dict.fromkeys(row.arm for row in rows))
        cells = {(row.arm, row.measure): row for row in found.arms if row.window == span.name}
        lines = [[name, *(_spread(cells.get((arm, name))) for arm in arms)] for name in COLUMNS]
        out += [
            "",
            f"Arms, window {span.name}: mean ± sd [min, max] (runs)",
            _grid(["", *arms], lines),
        ]
    names = list(dict.fromkeys((row.contrast, row.window) for row in found.contrasts))
    if names:
        cells = {(row.contrast, row.window, row.measure): row for row in found.contrasts}
        spans = {span.name for span in found.windows}
        header = ["", *(f"{c} ({w})" if w in spans else c for c, w in names)]
        lines = [
            [name, *(_difference(cells[contrast, window, name]) for contrast, window in names)]
            for name in COLUMNS[:-1]
        ]
        title = "Contrasts: mean difference of matched seeds [min, max] (seeds) p"
        out += ["", title, _grid(header, lines)]
    return "\n".join(out)


def _number(value: float | None) -> str:
    return "-" if value is None else f"{value:.3g}"


def _spread(row: ArmRow | None) -> str:
    if row is None or row.mean is None:
        return "-"
    sd = "" if row.sd is None else f" ± {row.sd:.2g}"
    return f"{row.mean:.3g}{sd} [{row.min:.3g}, {row.max:.3g}] ({row.n})"


def _difference(row: ContrastRow) -> str:
    if row.mean is None:
        return "-"
    return f"{row.mean:+.3g} [{row.min:+.3g}, {row.max:+.3g}] ({row.n}) p={row.p:.3g}"


def _grid(header: list[str], lines: list[list[str]]) -> str:
    rows = [header, *lines]
    widths = [max(len(row[column]) for row in rows) for column in range(len(header))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    )


def document(found: StudyTable) -> dict[str, Any]:
    """The table as plain JSON data."""
    data = asdict(found)
    for row in data["contrasts"]:
        row["differences"] = [{"seed": s, "difference": d} for s, d in row["differences"].items()]
    return data


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m analysis.study",
        description="Print the arms of a study compared, the run being the unit of analysis.",
    )
    parser.add_argument("study", type=Path, help="study file (YAML) of experiments.study")
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--dry-run", action="store_true", help="the study's dry runs")
    args = parser.parse_args(argv)
    study = read_study(args.study)
    runs = read(study, args.runs_root, args.dry_run)
    if not runs:
        parser.error(f"no runs of {study.name} under {args.runs_root}")
    print(render(table(study, args.dry_run, runs)))


if __name__ == "__main__":
    main()
