"""The measures of a lived run (`tests.support.lived`), checked by hand against its story."""

from __future__ import annotations

import asyncio
import csv
import json

import pytest

from analysis.measures import MEASURES, TOWN, beds, daily, main, measure, town_days, world_measures
from evaluation.records import Day
from tests.support.lived import OTHERS, before_occupations, live

NAMES = ("Mei", "Tomas", "Aisha", *OTHERS)


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("lived") / "run"
    asyncio.run(live(root))
    return root


@pytest.fixture(scope="module")
def rows(run_dir):
    return {(row["resident"], row["day"]): row for row in measure(run_dir)}


def test_the_programmers_days_work_money_and_talk_as_the_town_lived_them(rows):
    assert list(rows) == [(name, day) for name in NAMES for day in (1, 2)]
    mei, tomas, aisha = rows["Mei", 1], rows["Tomas", 1], rows["Aisha", 1]
    assert list(mei) == ["resident", "occupation", "day", "date", *MEASURES]
    assert (mei["occupation"], rows["Ravi", 2]["occupation"]) == ("programmer", "team-leader")
    office = ("tasks_taken", "tasks_handed_in", "tasks_accepted", "service_sums")
    assert [mei[k] for k in office] == [1, 1, 1, 20] and [tomas[k] for k in office] == [1, 0, 0, 0]
    # Ravi gave the open task 3 to Aisha, and the clients withdrew it and Tomas's at the second
    # midnight.
    assert (aisha["tasks_assigned_to"], rows["Ravi", 1]["tasks_assigned_by"]) == (1, 1)
    assert [rows[name, 2]["tasks_withdrawn"] for name in ("Mei", "Tomas", "Aisha")] == [0, 1, 1]
    # Wages at $7 an hour, a tenth of the wages and sums in tax and the rent ($20 on Mill
    # Street, $30 at the flat) taken out of them: Mei's twenty minutes earn 2, all of it the tax
    # on them and her $20 for the task, and leave her rent owed; Tomas's nine hours earn 63 and,
    # less $6 of tax, pay him 27; Aisha, who did not work, owes her rent; no purse pays rent.
    assert (mei["hours_at_work"], tomas["hours_at_work"], aisha["hours_at_work"]) == (0.33, 9, 0)
    assert (mei["wages"], tomas["wages"], aisha["wages"]) == (2, 63, 0)
    assert (mei["tax"], tomas["tax"], aisha["tax"]) == (2, 6, 0)
    assert (mei["money"], tomas["money"], aisha["money"]) == (120 + 20 + 5, 180 - 5 + 27, 30)
    assert (mei["arrears"], tomas["arrears"], aisha["arrears"]) == (20, 0, 20)
    assert (rows["Mei", 2]["arrears"], rows["Aisha", 2]["arrears"]) == (40, 40)
    assert rows["Aisha", 2]["money"] == 30 and rows["Mei", 2]["money"] == 145
    assert (mei["rent"], tomas["rent"], aisha["rent"]) == (20, 30, 20)
    assert (mei["charges"], mei["owed_wages"], mei["spent"], mei["hungry"]) == (0, 0, 0, 1)
    # None of the three ate: full when the town began, each is hungry at the first midnight and
    # starving at the second, which wore 15 of their health, and 2 more on Mill Street.
    assert (mei["starving"], mei["health"], mei["ill_night"], mei["bedridden"]) == (0, 100, 0, 0)
    assert (tomas["health"], aisha["health"]) == (100, 100)
    assert [rows[name, 2]["health"] for name in ("Mei", "Tomas", "Aisha")] == [83, 85, 83]
    assert rows["Mei", 2]["starving"] == 1
    assert (mei["messages_sent"], mei["messages_received"]) == (0, 0)
    talk = ("said_public", "said_private", "heard_public", "heard_private", "interlocutors")
    assert [mei[k] for k in talk] == [0, 1, 0, 1, 1]
    assert [tomas[k] for k in talk] == [0, 2, 0, 1, 2]
    assert [aisha[k] for k in talk] == [0, 0, 0, 1, 1]  # what Tomas told her privately
    assert (tomas["gifts_given"], tomas["money_given"]) == (1, 5)
    assert (mei["gifts_received"], mei["money_received"]) == (1, 5)


def test_the_evenings_trades_as_the_town_lived_them(rows):
    ravi, olga, jonas = rows["Ravi", 1], rows["Olga", 1], rows["Jonas", 1]
    lucia, vera = rows["Lucia", 1], rows["Vera", 1]
    # Olga at the counter from 20:10 to midnight, 3 hours 50 minutes at $7, sold twice at $2 a
    # sale and ordered once, and paid a tenth of the $30 in tax; Jonas, in the kitchen from
    # 20:20, bought for it, cooked a portion and served it at $3; Lucia, at the clinic for ten
    # minutes at $9, examined Ravi at $4 and paid $8 for her soup; Vera, at the hall from 20:20
    # at $8, bought bread for $4 and announced.
    assert [olga[k] for k in ("hours_at_work", "wages", "sales_made", "orders")] == [3.83, 26, 2, 1]
    assert [olga[k] for k in ("service_sums", "tax", "money", "arrears")] == [4, 3, 104, 7]
    trade = ("bought_for_kitchen", "portions_cooked", "dishes_served", "service_sums", "money")
    assert [jonas[k] for k in trade] == [1, 1, 1, 3, 103] and jonas["wages"] == 25
    assert [lucia[k] for k in ("examinations_given", "dishes_eaten", "spent", "wages")] == [
        1, 1, 8, 1,
    ]  # fmt: skip
    assert (lucia["service_sums"], lucia["money"]) == (4, 96)
    assert [vera[k] for k in ("bought", "spent", "announcements", "money", "wages")] == [
        1, 4, 1, 96, 29,
    ]  # fmt: skip
    # Her wages come from the tax account alone, settled last: of the $26 left after her own $3
    # of tax, it held the $16 the others paid, which went to her rent; it owes her the other $10,
    # and she owes the $14 of rent it did not cover.
    assert [vera[k] for k in ("tax", "owed_wages", "arrears")] == [3, 10, 14]
    # Ravi was paid $10 for Mei's task, as the leader, and paid $10 for his examination; with no
    # wages that day, the $1 of tax on his sum came from his purse.
    assert [ravi[k] for k in ("service_sums", "examinations_received", "spent", "money")] == [
        10, 1, 10, 99,
    ]  # fmt: skip
    assert ravi["tax"] == 1
    # Those who ate were not hungry at midnight; at the second, nobody had eaten.
    assert [rows[name, 1]["hungry"] for name in NAMES] == [1, 1, 1, 1, 1, 1, 0, 0]
    assert all(rows[name, 2]["hungry"] == 1 for name in NAMES)
    assert sum(rows[name, 1]["treatments_given"] for name in NAMES) == 0
    assert all(rows[name, 1]["reports_read"] == 0 for name in NAMES)
    # Those still at work at midnight worked on until the forced sleep, two hours of the
    # second calendar day.
    assert [rows[name, 2]["hours_at_work"] for name in ("Olga", "Jonas", "Lucia", "Vera")] == [
        2, 2, 0, 2,
    ]  # fmt: skip


def test_the_town_s_days(run_dir):
    days = town_days(run_dir)
    assert [list(row) for row in days] == [["day", "date", *TOWN]] * 2
    first, second = days
    # Task 1's client paid $50; the fund took $10 at the counter, of which $6 from the kitchen,
    # $8 for the soup and $10 for the examination, and paid $41 in sums for services and $10 to
    # the supplier. Of its $117 in wages (Mei 2, Tomas 63, Olga 26, Jonas 25, Lucia 1), $15 went
    # to the tax account in tax (Mei 2, Tomas 6, Olga 3, Jonas 3, Lucia 1), $75 covered rent
    # (Tomas 30, Olga 23, Jonas 22) and Tomas was paid $27. The tax account took the $15, Ravi's
    # $1 from his purse and Vera's own $3 and paid her $19, of which $16 into the fund for her
    # rent: the fund took $91 of rent; the rest of the rent is owed, and the account owes Vera
    # $10.
    assert {key: value for key, value in first.items() if value} == {
        "day": 1, "date": "2001-01-01", "tasks_arrived": 3, "tasks_accepted": 1,
        "fund": 1000 + 50 + 91 + 10 + 8 + 10 - 117 - 41 - 10 - 6, "arrears": 129,
        "owed_wages": 10, "taken_client": 50, "taken_rent": 91, "taken_sale": 10,
        "taken_dish": 8, "taken_fee": 10, "paid_wage": 117, "paid_service": 41,
        "paid_supplier": 10, "paid_kitchen": 6, "taken_tax": 19, "paid_tax_wage": 19,
    }  # fmt: skip
    assert (second["tasks_withdrawn"], second["fund"], second["arrears"]) == (2, 995, 321)
    # Olga's and Jonas's two hours, $14 each, pay $1 of tax each and $13 of rent; the account
    # pays the $2 to Vera's rent and owes her $22.
    assert (second["taken_rent"], second["paid_wage"]) == (13 + 13 + 2, 14 + 14)
    assert (second["taxes"], second["taken_tax"], second["owed_wages"]) == (0, 1 + 1 + 2, 22)


def test_daily_totals_and_means(rows):
    found = {(row["day"], row["measure"]): row for row in daily(list(rows.values()))}
    assert found[1, "service_sums"] == {
        "day": 1, "measure": "service_sums", "total": 41, "mean": 41 / 8, "residents": 8,
    }  # fmt: skip
    assert found[1, "arrears"]["total"] is None and found[1, "arrears"]["mean"] == 129 / 8
    assert found[2, "arrears"]["mean"] == 321 / 8
    assert found[1, "tax"]["total"] == 2 + 6 + 1 + 3 + 3 + 1 + 3
    assert found[2, "forced_sleep"]["total"] == 7 and found[1, "hungry"]["total"] == 6
    assert found[2, "starving"]["total"] == 8 and found[1, "starving"]["total"] == 0
    assert found[2, "bedridden"]["total"] == 0 and found[1, "health"]["total"] is None
    assert found[2, "health"]["mean"] == pytest.approx((83 * 2 + 85 * 6) / 8)
    assert found[1, "money"]["total"] is None and found[1, "health"]["residents"] == 8


def entry(kind: str, actor: str, **payload: object) -> dict:
    return {"kind": kind, "actor": actor, "audience": [], "payload": payload}


def test_the_chefs_own_dish_from_the_kitchen_is_no_gift():
    def served(to: str) -> dict:
        return entry("move", "Jonas", item="soup", units=1, source="portions", target=to,
                     money=0, reason="pass", seller=None)  # fmt: skip

    day = Day(1, (served("Jonas"), served("Mei")), None, 1.0)
    jonas, mei = (world_measures(day, name, {}) for name in ("Jonas", "Mei"))
    assert (jonas["gifts_given"], jonas["gifts_received"], mei["gifts_received"]) == (1, 0, 1)


def test_who_lies_bedridden_is_carried_over_the_days_and_visits_to_it_are_counted():
    days = [
        Day(1, (entry("bedridden", "Aisha", home="mill-street-house"),), None, 1.0),
        Day(2, (
            entry("arrive", "Mei", place="mill-street-house"),  # her housemate, coming home
            entry("arrive", "Lucia", place="mill-street-house"),
            entry("recovered", "Aisha", illness=False, bedridden=True, treated=True),
            entry("arrive", "Tomas", place="mill-street-house"),  # too late
        ), 1.0, 2.0),
        Day(3, (), 2.0, 3.0),
    ]  # fmt: skip
    lying = beds(days)
    assert lying == {1: {}, 2: {"Aisha": "mill-street-house"}, 3: {}}
    seen = {
        (name, day.number): world_measures(day, name, lying[day.number])
        for day in days
        for name in ("Aisha", "Mei", "Lucia", "Tomas")
    }
    assert [seen["Aisha", day]["bedridden"] for day in (1, 2, 3)] == [1, 1, 0]
    assert seen["Aisha", 2]["visited_in_bed"] == 2
    assert [seen[name, 2]["bedside_visits"] for name in ("Mei", "Lucia", "Tomas")] == [1, 1, 0]


def test_a_run_of_the_town_before_occupations_has_none_of_these_measures(run_dir, tmp_path, capsys):
    before = before_occupations(run_dir, tmp_path / "before")
    with pytest.raises(SystemExit):
        main([str(before), "--out", str(tmp_path / "out")])
    assert "is a run of the town before occupations" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_the_command_writes_csv_and_json_where_it_is_told_and_never_into_the_run(run_dir, tmp_path):
    before = sorted(run_dir.rglob("*"))
    with pytest.raises(SystemExit):
        main([str(run_dir)])  # no default place, the run least of all
    out = tmp_path / "results" / "c" / "measures"
    main([str(run_dir), "--out", str(out)])
    assert sorted(run_dir.rglob("*")) == before
    with (out / "measures.csv").open() as file:
        table = list(csv.DictReader(file))
    assert len(table) == 16 and table[0]["resident"] == "Mei" and table[0]["service_sums"] == "20"
    assert table[1]["cached_share"] == "0.6" and table[3]["cached_share"] == ""  # Tomas: no trace
    assert json.loads((out / "measures.json").read_text())[0]["money"] == 145
    assert len(json.loads((out / "daily.json").read_text())) == 2 * len(MEASURES)
    assert (out / "daily.csv").read_text().startswith("day,measure,total,mean,residents\n")
    assert json.loads((out / "town.json").read_text()) == town_days(run_dir)
    assert (out / "town.csv").read_text().startswith("day,date,tasks_arrived,")
