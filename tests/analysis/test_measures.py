"""The measures of a lived run (`tests.analysis.lived`), checked by hand against its story."""

from __future__ import annotations

import asyncio
import csv
import json

import pytest

from analysis.measures import MEASURES, daily, main, measure, world_measures
from evaluation.records import Day
from tests.analysis.lived import live


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("lived") / "run"
    asyncio.run(live(root))
    return root


@pytest.fixture(scope="module")
def rows(run_dir):
    return {(row["resident"], row["day"]): row for row in measure(run_dir)}


def test_the_days_work_money_and_talk_as_the_town_lived_them(rows):
    assert list(rows) == [(name, day) for name in ("Mei", "Tomas", "Aisha") for day in (1, 2)]
    mei, tomas, aisha = rows["Mei", 1], rows["Tomas", 1], rows["Aisha", 1]
    assert list(mei) == ["resident", "day", "date", *MEASURES]
    assert {k: mei[k] for k in ("claimed", "submitted", "accepted", "earned")} == {
        "claimed": 1, "submitted": 1, "accepted": 1, "earned": 20,
    }  # fmt: skip
    # Purses after the rent ($20 on Mill Street, $30 at the flat): 120 + 20 + 5, 180 - 5, 30.
    assert (mei["purse"], tomas["purse"], aisha["purse"]) == (125, 145, 10)
    assert (mei["in_debt"], tomas["in_debt"], aisha["in_debt"]) == (0, 0, 0)
    assert rows["Aisha", 2]["purse"] == -10 and rows["Mei", 2]["purse"] == 105
    assert rows["Aisha", 2]["in_debt"] == 1
    assert (mei["spent_rent"], tomas["spent_rent"], aisha["spent_rent"]) == (20, 30, 20)
    assert (mei["spent_fees"], mei["spent_food"], mei["spent_goods"], mei["hungry"]) == (0, 0, 0, 1)
    assert (mei["messages_sent"], mei["messages_received"]) == (0, 0)
    # Mei worked from 09:00 to 09:20, Tomas from 09:00 until he left at 18:00.
    assert mei["work_hours"] == pytest.approx(1 / 3) and tomas["work_hours"] == 9.0
    assert aisha["work_hours"] == 0
    talk = ("said_public", "said_private", "heard_public", "heard_private", "interlocutors")
    assert [mei[k] for k in talk] == [0, 1, 0, 1, 1]
    assert [tomas[k] for k in talk] == [0, 2, 0, 1, 2]
    assert [aisha[k] for k in talk] == [0, 0, 0, 1, 1]  # what Tomas told her privately
    assert (mei["skills_given"], tomas["skills_received"]) == (1, 1)
    assert (tomas["money_given"], mei["money_received"]) == (5, 5)


def test_ratings_sleep_and_the_runtime(rows):
    mei, tomas, aisha = rows["Mei", 1], rows["Tomas", 1], rows["Aisha", 1]
    assert (mei["ratings_given"], mei["rating_given_mean"]) == (1, 4.0)
    assert (mei["ratings_received"], mei["rating_received_mean"]) == (1, 5.0)
    assert (tomas["ratings_given"], tomas["rating_received_mean"]) == (1, 4.0)
    assert aisha["ratings_received"] == 0 and aisha["rating_received_mean"] is None
    assert (mei["journal"], tomas["journal"], aisha["journal"]) == (1, 1, 0)
    assert (rows["Tomas", 2]["forced_sleep"], aisha["forced_sleep"], mei["forced_sleep"]) == (
        1, 1, 0,
    )  # fmt: skip
    # Mei's thirteen steps of day 1 and four of day 2, each reporting 1000 prompt tokens (600
    # cached) and 100 completion tokens; Tomas has an empty trace.
    assert [mei[k] for k in ("requests", "prompt_tokens", "completion_tokens")] == [
        13, 13000, 1300,
    ]  # fmt: skip
    assert mei["cached_share"] == 0.6 and rows["Mei", 2]["requests"] == 4
    assert (mei["lapses"], mei["interruptions"], mei["compactions"]) == (0, 0, 0)
    assert tomas["requests"] == 0 and tomas["cached_share"] is None


def test_daily_totals_and_means(rows):
    found = {(row["day"], row["measure"]): row for row in daily(list(rows.values()))}
    assert found[1, "earned"] == {
        "day": 1, "measure": "earned", "total": 20, "mean": 20 / 3, "residents": 3,
    }  # fmt: skip
    assert found[1, "in_debt"]["total"] == 0 and found[2, "in_debt"]["total"] == 1
    assert found[2, "forced_sleep"]["total"] == 2 and found[1, "hungry"]["total"] == 3
    assert found[1, "purse"]["total"] is None and found[1, "purse"]["mean"] == 280 / 3
    assert found[1, "rating_received_mean"]["mean"] == 4.5
    assert found[1, "rating_received_mean"]["residents"] == 2


def test_work_still_open_when_the_day_closed_is_an_error():
    entry = {"kind": "start_work", "actor": "Mei", "sim_time": 32400, "payload": {}}
    with pytest.raises(ValueError, match="Mei was still at work when day 4 closed"):
        world_measures(Day(4, (entry,), None, 0.0), "Mei")


def test_the_command_writes_csv_and_json_into_the_run(run_dir):
    main([str(run_dir)])
    out = run_dir / "analysis"
    with (out / "measures.csv").open() as file:
        table = list(csv.DictReader(file))
    assert len(table) == 6 and table[0]["resident"] == "Mei" and table[0]["earned"] == "20"
    assert table[1]["rating_given_mean"] == ""  # Mei rated nobody on day 2
    assert json.loads((out / "measures.json").read_text())[0]["purse"] == 125
    assert len(json.loads((out / "daily.json").read_text())) == 2 * len(MEASURES)
    assert (out / "daily.csv").read_text().startswith("day,measure,total,mean,residents\n")
