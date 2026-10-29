"""The measures of a run: per resident and lived day, from the world log and the residents'
traces, with their daily totals and means; and per lived day for the town, from the world log
and the day's checkpoint.

    python -m analysis.measures RUN_DIR --out DIR

DIR receives `measures.csv` and `measures.json`, one row per resident and lived day with
`resident`, `occupation`, `day`, `date` and every measure of `MEASURES`; `daily.csv` and
`daily.json`, one row per day and measure with the total over the residents (for counts and
amounts) and the mean over the residents that have a value; and `town.csv` and `town.json`, one
row per day with `day`, `date` and every measure of `TOWN`. They are derived from the run alone
and replace what is there; DIR is given explicitly (by convention `results/<run>/measures`),
since analysis writes nothing under the run. The days are those the world log has closed
(`world.log.lived_days`), so a day lost to an interruption counts once, as it was lived again.
A run of the town before occupations, or from before the closed economy (with a fund and wages
instead of the treasury), is refused (`_measured`).

The midnight that ends a lived day settles the calendar day: the hours at work, the rent, the
salary and the treasury's takings and payments of a day are those of its calendar day, so work
after midnight counts on the next day; what was paid and sold, and the money at the checkpoint, are
the lived day's. Who lies bedridden is carried from day to day: a resident takes to its
bed at a midnight (`bedridden`) and leaves it when treated (`recovered`, for one bedridden), and a
visit to it is any other resident's arrival at the home where it lies, a housemate's coming home
included. A measure is None where it has no value: a cached share that no reply reported, or the
money and the health of a day without a midnight.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from statistics import fmean
from typing import Any

import yaml

from agent.directory import TRACE
from evaluation.records import Entry, Town, agent_dir, closed_days, day_date, town, trace_days
from infrastructure.storage import RunDirectory
from world.economy import LARDER, PAID, PORTIONS, SHELVES, TAKEN
from world.log import Day

MEASURES = {
    "tasks_taken": "tasks it claimed from the Office's board",
    "tasks_assigned_to": "tasks the team leader gave it, or moved to it from another",
    "tasks_assigned_by": "tasks it gave to a programmer, or moved, as the team leader",
    "tasks_handed_in": "hand-ins of its task (acceptance runs)",
    "tasks_accepted": "hand-ins accepted while it still held the task, which the client paid for",
    "tasks_given_up": "tasks it gave up",
    "tasks_withdrawn": "tasks the client withdrew at midnight while it held them",
    "hours_at_work": "hours at work at its workplace, as the midnight counted them",
    "client_shares": "its shares of the clients' payments for tasks accepted, before the tax",
    "takings": "what customers and patients paid it at its business, before the tax",
    "costs": "what its business bought: the shopkeeper's orders, the chef's for the kitchen",
    "tax": "the tax withheld into the treasury from what it was paid for its work",
    "rent": "the rent, daily charges and arrears the treasury took from its purse at midnight",
    "charges": "the daily charges on what it owns, due at midnight",
    "arrears": "the rent and charges its purse could not spare, owed to the treasury after it",
    "salary": "the salary the treasury paid it at midnight",
    "salary_owed": "the salary the treasury owes it after midnight",
    "granted": "money the mayor granted it from the treasury",
    "grants_made": "money it granted from the treasury as the mayor",
    "money": "its money after midnight",
    "spent": "money it paid at the Store's counter, for dishes and in the Hospital's fees",
    "sales_made": "sales at the Store's counter while it kept it",
    "bought": "purchases at the Store's counter for itself",
    "bought_for_kitchen": "purchases at the Store's counter for the kitchen",
    "orders": "orders it placed with the supplier",
    "portions_cooked": "portions of dishes it cooked",
    "dishes_served": "dishes it served as the chef, for which the diner paid",
    "dishes_eaten": "dishes it bought and ate at the Restaurant",
    "examinations_given": "examinations it made as the doctor",
    "examinations_received": "examinations of it, for which it paid",
    "treatments_given": "treatments it gave as the doctor",
    "treatments_received": "treatments of it, for which it paid",
    "hungry": "1 if it had nothing to eat that day",
    "starving": "1 if it was starving at midnight, which wore its health",
    "ill_night": "1 if illness cost it health at midnight",
    "health": "its health at midnight, after the night's reckoning, 0 to 100",
    "bedridden": "1 if it lay bedridden at some time of the day",
    "announcements": "announcements it made as the mayor",
    "reports_read": "times it read the town's report as the mayor",
    "said_public": "things said to everyone present",
    "said_private": "things said to named residents",
    "heard_public": "things said by others to everyone present, heard",
    "heard_private": "things said by others to it by name",
    "interlocutors": "distinct residents it spoke or wrote to, or was spoken or written to by",
    "messages_sent": "written messages it sent",
    "messages_received": "written messages it received",
    "gifts_given": "hand-overs of money or things to others, a dish the chef served unpaid among "
    "them",
    "gifts_received": "hand-overs of money or things from others",
    "money_given": "money handed to others",
    "money_received": "money received from others",
    "bedside_visits": "its arrivals at a home where another resident lay bedridden",
    "visited_in_bed": "others' arrivals at the home where it lay bedridden",
    "journal": "1 if it wrote a journal entry, going to bed",
    "forced_sleep": "1 if it was put to sleep at the forced hour",
    "requests": "model requests, retries and compactions included",
    "prompt_tokens": "prompt tokens reported",
    "completion_tokens": "completion tokens reported",
    "cached_share": "cached prompt tokens over prompt tokens, of the replies that report them",
    "lapses": "steps or compactions that found no usable reply",
    "compactions": "compactions of the context",
}
"""Every measure of a resident-day and what it counts."""
LEVELS = frozenset({"arrears", "salary_owed", "money", "health", "cached_share"})
"""The measures that are no count or amount, and so have no daily total."""
TOWN = {
    "tasks_arrived": "clients' tasks that came in on the Office's board",
    "tasks_accepted": "tasks accepted, which the clients paid for",
    "tasks_withdrawn": "tasks the clients withdrew at midnight, held or not",
    "clients": "what the clients paid for the tasks accepted, which came into the town",
    "supplier": "what the shopkeeper paid the supplier, the Store's costs, which left the town",
    "money": "the residents' money at the day's checkpoint",
    "treasury": "the treasury's balance at the day's checkpoint",
    "salary_owed": "the salary the treasury owed at the checkpoint",
    "arrears": "the rent and charges the residents owed the treasury at the checkpoint",
    **{
        f"taken_{kind}": f"what the treasury took {words} that day" for kind, words in TAKEN.items()
    },
    **{
        f"paid_{kind}": f"what the treasury paid out {words} that day"
        for kind, words in PAID.items()
    },
    "store_takings": "what customers paid at the Store's counter, the kitchen's purchases included",
    "kitchen_takings": "what diners paid for the kitchen's dishes",
    "kitchen_costs": "what the kitchen's ingredients cost at the Store's counter",
    "surgery_takings": "what patients paid in the Hospital's fees",
}
"""Every measure of the town's day and what it counts."""

Row = dict[str, Any]


def measure(run_dir: Path) -> list[Row]:
    """One row per resident and lived day of the run at `run_dir`, by resident and day."""
    config = _measured(run_dir)
    days = list(closed_days(run_dir).values())
    lying = beds(days)
    rows = []
    for resident in config.residents:
        traces = trace_days(agent_dir(run_dir, config, resident.name) / TRACE, days)
        for day in days:
            rows.append(
                {
                    "resident": resident.name,
                    "occupation": resident.occupation,
                    "day": day.number,
                    "date": day_date(config, day.number).isoformat(),
                    **world_measures(day, resident.name, lying[day.number]),
                    **trace_measures(traces[day.number]),
                }
            )
    return rows


def _measured(run_dir: Path) -> Town:
    """The town of the run at `run_dir`, which these measures read; ValueError for a run of the
    town before occupations, and for one from before the closed economy, whose frozen town has
    no treasury (it had the fund and the wages)."""
    config = town(run_dir)
    if any(resident.occupation is None for resident in config.residents):
        raise ValueError(f"{run_dir} is a run of the town before occupations, which these are not")
    frozen = yaml.safe_load(RunDirectory(run_dir).config_path.read_text(encoding="utf-8"))
    if "treasury" not in frozen["town"]:
        raise ValueError(
            f"{run_dir} predates the closed economy: its town has no treasury, which these read"
        )
    return config


def beds(days: Sequence[Day]) -> dict[int, dict[str, str]]:
    """Who lay bedridden at the start of each of `days`, given in order, and at which home."""
    lying: dict[str, str] = {}
    found = {}
    for day in days:
        found[day.number] = dict(lying)
        for e in day.entries:
            _turn(lying, e)
    return found


def _turn(lying: dict[str, str], e: Entry) -> None:
    """`lying` after the entry `e`: one taken to its bed, or let up from it."""
    if e["kind"] == "bedridden":
        lying[e["actor"]] = e["payload"]["home"]
    elif e["kind"] == "recovered" and e["payload"]["bedridden"]:
        del lying[e["actor"]]


def world_measures(day: Day, name: str, lying: Mapping[str, str]) -> Row:
    """The measures of `name`'s lived `day` that the world log gives, with `lying` those
    bedridden when it began and where."""

    def mine(kind: str) -> list[Entry]:
        return [e for e in day.entries if e["kind"] == kind and e["actor"] == name]

    def to_me(kind: str, key: str) -> list[Entry]:
        return [e for e in day.entries if e["kind"] == kind and e["payload"][key] == name]

    settled, shares = mine("settlement"), mine("service")
    last = settled[-1]["payload"] if settled else None
    moves = [e["payload"] | {"actor": e["actor"]} for e in day.entries if e["kind"] == "move"]
    bought = [m for m in moves if m["reason"] == "buy"]
    sales = [m for m in bought if m["source"] == SHELVES]  # at the Store's counter
    dishes = [m for m in bought if m["source"] == PORTIONS]
    sold = [m for m in bought if m["seller"] == name]  # and the seller's, as their keeper
    own = [m for m in sales if m["actor"] == name and m["target"] == name]
    eaten = [m for m in dishes if m["actor"] == name]
    kitchen = [m for m in sales if m["actor"] == name and m["target"] == LARDER]
    examined, treated = to_me("examination", "patient"), to_me("treatment", "patient")
    seen = mine("examination") + mine("treatment")
    speech = [e for e in day.entries if e["kind"] == "speech"]
    said = [e for e in speech if e["actor"] == name]
    heard = [e for e in speech if e["actor"] != name and name in e["payload"]["to"]]
    sent, got = mine("message"), to_me("message", "to")
    passed = [m for m in moves if m["reason"] == "pass" and m["actor"] != m["target"]]
    given = [m for m in passed if m["actor"] == name]  # not the chef's own dish
    received = [m for m in passed if m["target"] == name]
    visits, visited = _visits(day, name, lying)
    return {
        "tasks_taken": len(mine("claim")),
        "tasks_assigned_to": len(to_me("assign", "to")),
        "tasks_assigned_by": len(mine("assign")),
        "tasks_handed_in": len(mine("submission")),
        "tasks_accepted": sum(
            e["payload"]["resolved"] and e["payload"]["held"] for e in mine("verdict")
        ),
        "tasks_given_up": len(mine("abandon")),
        "tasks_withdrawn": len(to_me("task_withdrawn", "holder")),
        "hours_at_work": sum(e["payload"]["hours"] for e in settled),
        "client_shares": sum(e["payload"]["amount"] for e in shares),
        "takings": sum(m["money"] for m in sold) + sum(e["payload"]["fee"] for e in seen),
        "costs": sum(e["payload"]["amount"] for e in mine("order"))
        + sum(m["money"] for m in kitchen),
        "tax": sum(e["payload"]["tax"] for e in shares + seen) + sum(m["tax"] for m in sold),
        "rent": sum(e["payload"]["rent_paid"] for e in settled),
        "charges": sum(e["payload"]["charges"] for e in settled),
        "arrears": last["arrears"] if last else None,
        "salary": sum(e["payload"]["salary_paid"] for e in settled),
        "salary_owed": last["owed"] if last else None,
        "granted": sum(e["payload"]["amount"] for e in to_me("grant", "to")),
        "grants_made": sum(e["payload"]["amount"] for e in mine("grant")),
        "money": last["money"] if last else None,
        "spent": sum(m["money"] for m in own + eaten + kitchen)
        + sum(e["payload"]["fee"] for e in examined + treated),
        "sales_made": sum(m["seller"] == name for m in sales),
        "bought": len(own),
        "bought_for_kitchen": len(kitchen),
        "orders": len(mine("order")),
        "portions_cooked": sum(e["payload"]["portions"] for e in mine("cook")),
        "dishes_served": sum(m["seller"] == name for m in dishes),
        "dishes_eaten": len(eaten),
        "examinations_given": len(mine("examination")),
        "examinations_received": len(examined),
        "treatments_given": len(mine("treatment")),
        "treatments_received": len(treated),
        "hungry": int(bool(last) and last["nourishment"] == 0),
        "starving": int(bool(last) and "starving" in last["night"]),
        "ill_night": int(bool(last) and "illness" in last["night"]),
        "health": last["health"] if last else None,
        "bedridden": int(name in lying or bool(mine("bedridden"))),
        "announcements": len(mine("announcement")),
        "reports_read": len(mine("report")),
        "said_public": sum(not e["payload"]["private"] for e in said),
        "said_private": sum(e["payload"]["private"] for e in said),
        "heard_public": sum(not e["payload"]["private"] for e in heard),
        "heard_private": sum(e["payload"]["private"] for e in heard),
        "interlocutors": len(
            {other for e in said for other in e["payload"]["to"]}
            | {e["actor"] for e in heard}
            | {e["payload"]["to"] for e in sent}
            | {e["actor"] for e in got}
        ),
        "messages_sent": len(sent),
        "messages_received": len(got),
        "gifts_given": len(given),
        "gifts_received": len(received),
        "money_given": sum(m["money"] for m in given),  # 0: a thing
        "money_received": sum(m["money"] for m in received),
        "bedside_visits": visits,
        "visited_in_bed": visited,
        "journal": int(any(e["payload"]["journal"] for e in mine("sleep"))),
        "forced_sleep": len(mine("forced_sleep")),
    }


def _visits(day: Day, name: str, lying: Mapping[str, str]) -> tuple[int, int]:
    """`name`'s arrivals on `day` at a home where another lay bedridden, and others' arrivals
    at the home where it lay, with `lying` those bedridden when the day began."""
    lying, visits, visited = dict(lying), 0, 0
    for e in day.entries:
        _turn(lying, e)
        if e["kind"] != "arrive":
            continue
        place = e["payload"]["place"]
        if e["actor"] == name:
            visits += any(home == place for other, home in lying.items() if other != name)
        elif lying.get(name) == place:
            visited += 1
    return visits, visited


def trace_measures(trace: Sequence[Entry]) -> Row:
    """The measures of a resident-day that its trace gives."""
    usage = [r["usage"] for r in trace if r["kind"] == "reply" and r["usage"] is not None]
    reported = [u for u in usage if u.get("cached_prompt_tokens") is not None]
    prompt = sum(u["prompt_tokens"] for u in reported)
    return {
        "requests": sum(r["kind"] == "request" for r in trace),
        "prompt_tokens": sum(u["prompt_tokens"] for u in usage),
        "completion_tokens": sum(u["completion_tokens"] for u in usage),
        "cached_share": sum(u["cached_prompt_tokens"] for u in reported) / prompt
        if prompt
        else None,
        "lapses": sum(r["kind"] == "lapse" for r in trace),
        "compactions": sum(r["kind"] == "compaction" for r in trace),
    }


def town_days(run_dir: Path) -> list[Row]:
    """One row per lived day of the run at `run_dir`, by day: the measures of `TOWN`, the tasks,
    the clients' payments, the supplier's bills and the businesses' takings and costs from the
    world log, and from the day's checkpoint the residents' money and the treasury's, what it owes
    and is owed, and its takings and payments of the calendar day its midnight closed."""
    config, run = _measured(run_dir), RunDirectory(run_dir)
    rows = []
    for day in closed_days(run_dir).values():
        state = json.loads(run.checkpoint_path(day.number).read_text(encoding="utf-8"))
        treasury = state["treasury"]
        kinds = Counter(e["kind"] for e in day.entries)
        bought = [e["payload"] for e in day.entries if e["kind"] == "move"]
        bought = [m for m in bought if m["reason"] == "buy"]
        rows.append(
            {
                "day": day.number,
                "date": day_date(config, day.number).isoformat(),
                "tasks_arrived": kinds["task_arrived"],
                "tasks_accepted": sum(
                    e["kind"] == "verdict" and e["payload"]["resolved"] and e["payload"]["held"]
                    for e in day.entries
                ),
                "tasks_withdrawn": kinds["task_withdrawn"],
                "clients": _summed(day, "service", "amount"),
                "supplier": _summed(day, "order", "amount"),
                "money": sum(r["inventory"]["money"] for r in state["residents"].values()),
                "treasury": treasury["balance"],
                "salary_owed": sum(treasury["owed"].values()),
                "arrears": sum(treasury["arrears"].values()),
                **{f"taken_{kind}": treasury["yesterday"].get(kind, 0) for kind in TAKEN},
                **{f"paid_{kind}": treasury["yesterday"].get(kind, 0) for kind in PAID},
                "store_takings": sum(m["money"] for m in bought if m["source"] == SHELVES),
                "kitchen_takings": sum(m["money"] for m in bought if m["source"] == PORTIONS),
                "kitchen_costs": sum(m["money"] for m in bought if m["target"] == LARDER),
                "surgery_takings": _summed(day, "examination", "fee")
                + _summed(day, "treatment", "fee"),
            }
        )
    return rows


def _summed(day: Day, kind: str, field: str) -> int:
    """The payloads' `field` summed over the entries of `kind` of `day`."""
    return sum(e["payload"][field] for e in day.entries if e["kind"] == kind)


def daily(rows: Sequence[Row]) -> list[Row]:
    """One row per day and measure: the total over residents (None for `LEVELS`), the mean
    over the residents with a value, and how many have one."""
    found = []
    for day in sorted({row["day"] for row in rows}):
        of_day = [row for row in rows if row["day"] == day]
        for name in MEASURES:
            values = [row[name] for row in of_day if row[name] is not None]
            found.append(
                {
                    "day": day,
                    "measure": name,
                    "total": None if name in LEVELS else sum(values),
                    "mean": _mean(values),
                    "residents": len(values),
                }
            )
    return found


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return fmean(values) if values else None


def write(rows: Sequence[Row], stem: Path) -> None:
    """`rows` as `<stem>.csv` (None as an empty cell) and `<stem>.json`."""
    stem.with_suffix(".json").write_text(
        json.dumps(list(rows), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with stem.with_suffix(".csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]) if rows else [])
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m analysis.measures", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("run", type=Path, help="the run directory")
    parser.add_argument("--out", type=Path, required=True, help="where to write")
    args = parser.parse_args(argv)
    try:
        rows = measure(args.run)
    except ValueError as error:
        parser.error(str(error))
    if not rows:
        parser.error(f"{args.run} has no lived day closed by a checkpoint")
    args.out.mkdir(parents=True, exist_ok=True)
    write(rows, args.out / "measures")
    write(daily(rows), args.out / "daily")
    write(town_days(args.run), args.out / "town")
    days = sorted({row["day"] for row in rows})
    residents = len({row["resident"] for row in rows})
    print(f"{residents} residents, days {days[0]} to {days[-1]}: written to {args.out}")


if __name__ == "__main__":
    main()
