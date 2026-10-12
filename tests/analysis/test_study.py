"""The comparison of a study's arms, on a dry-run study of two arms and two seeds."""

from itertools import product
from pathlib import Path
from statistics import fmean, stdev
from types import SimpleNamespace

import pytest
import yaml

from analysis import read_run
from analysis.study import (
    COLUMNS,
    Window,
    main,
    read,
    read_study,
    sign_flip_p,
    table,
    values,
)
from core.interaction import day_of
from experiments.study import main as run_study

TOWN = Path(__file__).parents[2] / "experiments" / "configs" / "town.yaml"
ARMS = ("selection-comfortable", "assignment-comfortable")


@pytest.fixture(scope="module")
def study(tmp_path_factory) -> tuple[Path, Path]:
    """A study file and its runs root: the town for three days, under selection with a late
    phase from day 3, and under assignment, each over seeds 0 and 1, answered by the dry run."""
    root = tmp_path_factory.mktemp("study")
    late = {"partner_choice": False, "defect_discovery_prob": 0.0}
    data = {
        "name": "mini",
        "base": str(TOWN),
        "seeds": [0, 1],
        "overlays": {
            "short": {"simulation": {"days": 3, "interventions": []}},
            "late-phase": {"simulation": {"interventions": [{"day": 3, "conditions": late}]}},
            "assignment": {"environment": {"conditions": {"partner_choice": False}}},
        },
        "arms": {ARMS[0]: ["short", "late-phase"], ARMS[1]: ["short", "assignment"]},
    }
    path = root / "mini.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    runs = root / "runs"
    run_study([str(path), "--dry-run", "--workers", "4", "--runs-root", str(runs)])
    return path, runs


def events(root: Path, kind: str, first: int, last: int) -> list[dict]:
    run = read_run(root)
    return [
        event.payload | {"actor": event.actor}
        for event in run.events
        if event.kind == kind and first <= day_of(event.time) <= last
    ]


def test_each_run_is_measured_on_its_own_over_the_same_windows(study):
    path, runs = study
    found = table(read_study(path), True, read(read_study(path), runs, True))
    assert found.windows == [Window("main", 1, 2), Window("late", 3, None)]
    assert sorted((row.arm, row.seed, row.window) for row in found.runs) == sorted(
        product(ARMS, (0, 1), ("main", "late"))
    )
    for row in found.runs:
        assert (row.first_day, row.last_day) == ((1, 2) if row.window == "main" else (3, 3))
        assert list(row.values) == list(COLUMNS)
        root = runs / f"mini-{row.arm}-dry-run" / row.run
        span = (row.first_day, row.last_day)
        asked = events(root, "task_proposed", *span)
        residents = len(read_run(root).agents)
        days = row.last_day - row.first_day + 1
        assert row.values["asked_per_resident_day"] == len(asked) / (residents * days)
        handed = events(root, "work_submitted", *span)
        unfinished = [e for e in handed if e["declaration"] == "incomplete"]
        share = row.values["unfinished_share"]
        assert share == (len(unfinished) / len(handed) if handed else None)
        if row.arm == "assignment-comfortable":  # nobody asks anybody: undefined, not zero
            assert not asked and row.values["took_up_share"] is None
            assert row.values["asked_by_gini"] is None
        assert row.values["probe_day"] is None and row.values["probe_honesty"] is None
    assert any(row.values["asked_per_resident_day"] for row in found.runs)

    for arm_row in found.arms:
        known = [
            row.values[arm_row.measure]
            for row in found.runs
            if (row.arm, row.window) == (arm_row.arm, arm_row.window)
            and row.values[arm_row.measure] is not None
        ]
        assert arm_row.n == len(known)
        if known:
            assert arm_row.mean == pytest.approx(fmean(known))
            assert (arm_row.min, arm_row.max) == (min(known), max(known))
            assert arm_row.sd == (pytest.approx(stdev(known)) if len(known) > 1 else None)

    by = {(row.arm, row.window, row.seed): row.values for row in found.runs}
    contrasts = {(row.contrast, row.window, row.measure): row for row in found.contrasts}
    assert {(c, w) for c, w, _ in contrasts} == {
        ("selection − assignment, comfortable", "main"),
        ("selection − assignment, comfortable", "late"),
        ("late − main, selection-comfortable", "late − main"),
        ("late − main, assignment-comfortable", "late − main"),
    }
    for (name, window, measure), row in contrasts.items():
        if name.startswith("selection"):
            terms = [((ARMS[0], window), 1), ((ARMS[1], window), -1)]
        else:
            arm = name.removeprefix("late − main, ")
            terms = [((arm, "late"), 1), ((arm, "main"), -1)]
        expected = {}
        for seed in (0, 1):
            found_values = [by[(*term, seed)][measure] for term, _ in terms]
            if None not in found_values:
                expected[seed] = sum(w * v for (_, w), v in zip(terms, found_values, strict=True))
        assert row.differences == pytest.approx(expected)
        assert row.n == len(expected)
        if expected:
            assert row.mean == pytest.approx(fmean(expected.values()))
            assert row.p == sign_flip_p(list(expected.values()))


def test_the_sign_flip_p_counts_the_sign_patterns_at_least_as_extreme():
    assert sign_flip_p([1.0, 2.0, 3.0]) == 2 / 8  # only all plus and all minus
    assert sign_flip_p([1.0, -1.0]) == 1.0
    assert sign_flip_p([0.0, 0.0]) == 1.0
    assert sign_flip_p([1.0, 1.0, 1.0, 1.0, 1.0]) == 2 / 32  # the least five seeds can give
    assert sign_flip_p([3.0, -1.0, 1.0]) == 6 / 8  # all but 3-1-1 and its mirror reach 3
    with pytest.raises(ValueError):
        sign_flip_p([1.0] * 21)


def test_a_window_takes_the_scores_of_its_last_evaluated_day():
    def row(day: int, dimension: str, score: float | None, variant="full") -> SimpleNamespace:
        return SimpleNamespace(day=day, variant=variant, dimension=dimension, score=score)

    scores = [
        row(0, "honesty", 0.0),
        row(2, "honesty", 0.5),
        row(2, "honesty", 1.0),
        row(2, "honesty", 0.0, "no-policy"),
        row(2, "reliability", None),
        row(3, "honesty", 0.25),
        row(4, "honesty", 0.75, "no-insights"),
    ]
    found = SimpleNamespace(agents=[], pairs=[])
    measured = SimpleNamespace(agents=[], graph=[])
    main_values = values(found, measured, scores, 1, 2)
    assert main_values["probe_day"] == 2 and main_values["probe_honesty"] == 0.75
    assert main_values["probe_reliability"] is None
    assert values(found, measured, scores, 3, 3)["probe_honesty"] == 0.25
    assert values(found, measured, scores, 4, 5)["probe_day"] is None


def test_the_command_prints_the_table_and_writes_nothing(study, capsys):
    path, runs = study

    def stamps(root: Path) -> dict[str, tuple[int, int]]:
        return {
            str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()
        }

    before = stamps(path.parent)
    main([str(path), "--dry-run", "--runs-root", str(runs)])
    out = capsys.readouterr().out
    assert stamps(path.parent) == before
    assert out.startswith("Study mini (dry run); windows: main days 1–2, late days 3–.")
    for title in ("Runs, window main", "Arms, window late", "Contrasts"):
        assert title in out
    with pytest.raises(SystemExit):
        main([str(path), "--runs-root", str(runs)])  # no runs that are not dry
