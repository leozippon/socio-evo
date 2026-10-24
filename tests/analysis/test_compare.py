"""The exact tests, the intervals, the residents' statistics and the comparison table."""

from __future__ import annotations

import asyncio
import csv
import json
from statistics import median

import pytest

from analysis.compare import (
    SOCIETY,
    bootstrap_difference,
    bootstrap_mean,
    hedges_g,
    main,
    permutation_test,
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


def test_the_permutation_test_is_exact():
    # Of the six ways to split 1..4 in two pairs, two differ by 2 in their means.
    assert permutation_test([1, 2], [3, 4]) == pytest.approx(1 / 3)
    assert permutation_test(range(9, 17), range(1, 9)) == 2 / 12870
    assert permutation_test([1, 2, 3], [1, 2, 3]) == 1.0

    def medians(a, b):
        return median(a) - median(b)

    # 12 of the 20 splits of 1..5 and 100 in triples have medians at least 2 apart.
    assert permutation_test([1, 2, 100], [3, 4, 5], medians) == pytest.approx(12 / 20)
    with pytest.raises(ValueError):
        permutation_test(range(13), range(13))


def test_intervals_and_effect_sizes():
    low, high = bootstrap_mean([1, 2, 3, 4, 5, 6, 7, 8])
    assert low < 4.5 < high and (low, high) == bootstrap_mean([1, 2, 3, 4, 5, 6, 7, 8])
    low, high = bootstrap_difference(range(9, 17), range(1, 9))
    assert 0 < low < 8 < high
    assert hedges_g([2, 4], [1, 3]) == pytest.approx(1 / 2**0.5 * (1 - 3 / 7))
    assert hedges_g([1, 1], [1, 1]) is None and hedges_g([1], [2, 3]) is None


def test_a_residents_statistics():
    by_day = {0: 0.2, 1: 0.5, 2: 0.4, 3: 0.3, 28: 0.6}
    assert statistic("change", by_day, 0, 28) == pytest.approx(0.4)
    assert statistic("last", by_day, 1, 3) == 0.3
    assert statistic("trend", by_day, 1, 3) == pytest.approx(-0.1)
    assert statistic("mean", by_day, 1, 3) == pytest.approx(0.4)
    assert statistic("change", {28: 0.6}, 0, 28) is None
    assert statistic("trend", {1: 0.5}, 1, 3) is None


def write_json(path, rows):
    path.write_text(json.dumps(rows))
    return path


def test_the_declared_contrasts_of_distortion(tmp_path, capsys):
    """Distortion by day for A, C and D: in C it falls, in A it rises; one A resident never
    wrote a checkable journal."""
    tables = {}
    for group, start, step in (("A", 0.2, 0.05), ("C", 0.4, -0.1), ("D", 0.3, 0.0)):
        rows = [
            {"resident": r, "day": day, "distortion": start + step * day + 0.01 * n}
            for n, r in enumerate(EIGHT)
            for day in (1, 2, 3)
        ]
        if group == "A":
            rows = [row | {"distortion": None} if row["resident"] == "R8" else row for row in rows]
        tables[group] = write_json(tmp_path / f"{group}.json", rows)
    out = tmp_path / "compare" / "distortion.json"
    groups = [arg for group, path in tables.items() for arg in ("--group", f"{group}={path}")]
    main(["--measure", "distortion", "--days", "1", "3", "--out", str(out), *groups])

    table = json.loads(out.read_text())
    assert set(table) == {"measure", "declared", "days", "groups", "contrasts", "notes"}
    assert (table["measure"], table["declared"], table["days"]) == ("distortion", True, [1, 3])
    assert [(row["group"], row["statistic"], row["residents"]) for row in table["groups"]] == [
        ("A", "last", 7), ("C", "last", 8), ("D", "last", 8),
        ("A", "trend", 7), ("C", "trend", 8), ("D", "trend", 8),
    ]  # fmt: skip
    trend = {row["group"]: row for row in table["groups"] if row["statistic"] == "trend"}
    assert trend["C"]["mean"] == pytest.approx(-0.1) and trend["C"]["p_sign_flip"] == 2 / 256
    assert trend["C"]["p_min"] == 2 / 256 and trend["A"]["p_sign_flip"] == 2 / 128
    assert trend["D"]["p_sign_flip"] == 1.0 and trend["D"]["d_z"] is None
    last = {row["group"]: row for row in table["groups"] if row["statistic"] == "last"}
    assert last["C"]["p_sign_flip"] is None and last["C"]["values"]["R1"] == pytest.approx(0.1)
    contrasts = {(row["contrast"], row["statistic"]): row for row in table["contrasts"]}
    assert list(contrasts) == [("C - A", "last"), ("C - D", "last"), ("C - A", "trend"),
                               ("C - D", "trend")]  # fmt: skip
    c_a = contrasts["C - A", "trend"]
    assert c_a["residents"] == [8, 7] and c_a["difference"] == pytest.approx(-0.15)
    assert c_a["ci"][0] <= c_a["difference"] <= c_a["ci"][1]
    assert c_a["p_permutation"] == pytest.approx(1 / 6435) == c_a["p_min"]
    assert contrasts["C - D", "last"]["p_min"] == pytest.approx(2 / 12870)
    assert table["notes"][0] == SOCIETY
    printed = capsys.readouterr().out
    assert "C - A trend: n=8/7 difference=-0.15" in printed and SOCIETY in printed


def test_a_change_from_a_csv_table_and_a_run_directory(tmp_path, capsys):
    path = tmp_path / "capability.csv"
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["resident", "day", "capability"])
        writer.writeheader()
        for n, r in enumerate(EIGHT):
            writer.writerow({"resident": r, "day": 0, "capability": 0.3})
            writer.writerow({"resident": r, "day": 28, "capability": 0.3 + 0.01 * (n - 2)})
    main(["--group", f"B={path}", "--measure", "capability"])
    printed = capsys.readouterr().out
    assert "B change: n=8 mean=0.015" in printed and "none: no contrast" in printed
    assert SOCIETY not in printed

    run = tmp_path / "run"
    asyncio.run(live(run))
    main(["--group", f"A={run}", "--group", f"B={run}", "--measure", "earned", "--days", "1", "2"])
    printed = capsys.readouterr().out
    assert "no declared outcome" in printed and "B - A mean: n=3/3 difference=0" in printed


def test_unreadable_groups_are_refused(tmp_path, capsys):
    table = write_json(tmp_path / "t.json", [{"resident": "R1", "day": 1, "other": 1}])
    for args in (
        ["--group", f"A={table}", "--measure", "distortion"],
        ["--group", f"A={table}", "--group", f"A={table}", "--measure", "other"],
        ["--group", "A", "--measure", "other"],
    ):
        with pytest.raises(SystemExit):
            main(args)
    twice = write_json(tmp_path / "twice.json", [{"resident": "R1", "day": 1, "x": 1}] * 2)
    with pytest.raises(SystemExit):
        main(["--group", f"A={twice}", "--measure", "x"])
    assert "two values of R1 on day 1" in capsys.readouterr().err
