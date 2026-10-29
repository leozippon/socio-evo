"""The exact test, the intervals, the residents' statistics and the table of runs."""

from __future__ import annotations

import asyncio
import csv
import json

import pytest

from analysis.compare import (
    SOCIETY,
    bootstrap_mean,
    cohen_dz,
    main,
    sign_flip_test,
    statistic,
)
from tests.analysis.lived import live

EIGHT = [f"R{n}" for n in range(1, 9)]


def test_the_sign_flip_test_is_exact():
    assert sign_flip_test([0.1, 0.3, 0.2, 0.5, 0.4, 0.1, 0.2, 0.3]) == 2 / 256 == 0.0078125
    assert sign_flip_test([3, 1]) == 0.5  # sums 4, 2, -2, -4
    assert sign_flip_test([1, -1]) == 1.0
    assert sign_flip_test([0, 0, 0]) == 1.0
    with pytest.raises(ValueError):
        sign_flip_test([1] * 21)


def test_intervals_and_effect_sizes():
    low, high = bootstrap_mean([1, 2, 3, 4, 5, 6, 7, 8])
    assert low < 4.5 < high and (low, high) == bootstrap_mean([1, 2, 3, 4, 5, 6, 7, 8])
    assert cohen_dz([1, 2, 3]) == 2.0
    assert cohen_dz([1, 1]) is None and cohen_dz([1]) is None


def test_a_residents_statistics():
    by_day = {0: 0.2, 1: 0.5, 2: 0.4, 3: 0.3, 28: 0.6}
    assert statistic("change", by_day, 0, 28) == pytest.approx(0.4)
    assert statistic("last", by_day, 1, 3) == 0.3
    assert statistic("trend", by_day, 1, 3) == pytest.approx(-0.1)
    assert statistic("mean", by_day, 1, 3) == pytest.approx(0.4)
    assert statistic("change", {28: 0.6}, 0, 28) is None
    assert statistic("trend", {1: 0.5}, 1, 3) is None


def write_json(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))
    return path


def test_the_declared_statistics_of_distortion(tmp_path, capsys):
    """Distortion by day in three runs: it falls in one, rises in another, where one resident
    never wrote a checkable journal, and holds in the third. The falling run's days were judged
    in two judgings, read together from its journals directory."""
    tables = {}
    for run, start, step in (("rising", 0.2, 0.05), ("falling", 0.4, -0.1), ("flat", 0.3, 0.0)):
        rows = [
            {"resident": r, "day": day, "distortion": start + step * day + 0.01 * n}
            for n, r in enumerate(EIGHT)
            for day in (1, 2, 3)
        ]
        if run == "rising":
            rows = [row | {"distortion": None} if row["resident"] == "R8" else row for row in rows]
        tables[run] = write_json(tmp_path / f"{run}.json", rows)
    journals = tmp_path / "results" / "falling" / "journals"
    for judging, days in (("day-01-02", (1, 2)), ("day-03", (3,))):
        rows = json.loads(tables["falling"].read_text())
        write_json(journals / judging / "days.json", [row for row in rows if row["day"] in days])
    tables["falling"] = journals
    out = tmp_path / "compare" / "distortion.json"
    runs = [arg for run, path in tables.items() for arg in ("--run", f"{run}={path}")]
    main(["--measure", "distortion", "--days", "1", "3", "--out", str(out), *runs])

    table = json.loads(out.read_text())
    assert set(table) == {"measure", "declared", "days", "runs", "notes"}
    assert (table["measure"], table["declared"], table["days"]) == ("distortion", True, [1, 3])
    assert [(row["run"], row["statistic"], row["residents"]) for row in table["runs"]] == [
        ("rising", "last", 7), ("falling", "last", 8), ("flat", "last", 8),
        ("rising", "trend", 7), ("falling", "trend", 8), ("flat", "trend", 8),
    ]  # fmt: skip
    trend = {row["run"]: row for row in table["runs"] if row["statistic"] == "trend"}
    falling = trend["falling"]
    assert falling["mean"] == pytest.approx(-0.1) and falling["p_sign_flip"] == 2 / 256
    assert falling["ci"][0] <= falling["mean"] <= falling["ci"][1] < 0
    assert falling["p_min"] == 2 / 256 and trend["rising"]["p_sign_flip"] == 2 / 128
    assert trend["flat"]["p_sign_flip"] == 1.0 and trend["flat"]["d_z"] is None
    last = {row["run"]: row for row in table["runs"] if row["statistic"] == "last"}
    assert last["falling"]["p_sign_flip"] is None
    assert last["falling"]["values"]["R1"] == pytest.approx(0.1)
    assert table["notes"][0] == SOCIETY
    printed = capsys.readouterr().out
    assert "falling trend: n=8 mean=-0.1" in printed and SOCIETY in printed


def test_a_change_from_a_csv_table_and_runs_side_by_side(tmp_path, capsys):
    path = tmp_path / "capability.csv"
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["resident", "day", "capability"])
        writer.writeheader()
        for n, r in enumerate(EIGHT):
            writer.writerow({"resident": r, "day": 0, "capability": 0.3})
            writer.writerow({"resident": r, "day": 28, "capability": 0.3 + 0.01 * (n - 2)})
    main(["--run", f"town={path}", "--measure", "capability"])
    printed = capsys.readouterr().out
    assert "town change: n=8 mean=0.015" in printed and "(p_min 0.00781)" in printed

    run = tmp_path / "run"
    asyncio.run(live(run))
    main(
        ["--run", f"town={run}", "--run", f"again={run}", "--measure", "wages", "--days", "1", "2"]
    )
    printed = capsys.readouterr().out
    assert "no declared outcome" in printed
    assert "town mean: n=8" in printed and "again mean: n=8" in printed


def test_unreadable_runs_are_refused(tmp_path, capsys):
    table = write_json(tmp_path / "t.json", [{"resident": "R1", "day": 1, "other": 1}])
    for args in (
        ["--run", f"town={table}", "--measure", "distortion"],
        ["--run", f"town={table}", "--run", f"town={table}", "--measure", "other"],
        ["--run", "town", "--measure", "other"],
    ):
        with pytest.raises(SystemExit):
            main(args)
    twice = write_json(tmp_path / "twice.json", [{"resident": "R1", "day": 1, "x": 1}] * 2)
    with pytest.raises(SystemExit):
        main(["--run", f"town={twice}", "--measure", "x"])
    assert "two values of R1 on day 1" in capsys.readouterr().err
    for judging in ("day-01", "again"):  # a resident-day judged in two judgings
        write_json(
            tmp_path / "journals" / judging / "days.json", [{"resident": "R1", "day": 1, "x": 1}]
        )
    with pytest.raises(SystemExit):
        main(["--run", f"town={tmp_path / 'journals'}", "--measure", "x"])
    assert "two values of R1 on day 1" in capsys.readouterr().err
