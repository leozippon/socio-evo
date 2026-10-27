"""The measures of a run, per resident and lived day, from the world log and the residents'
traces, with their daily totals and means.

    python -m analysis.measures RUN_DIR --out DIR

DIR receives `measures.csv` and `measures.json`, one row per resident and lived day with
`resident`, `day`, `date` and every measure of `MEASURES`, and `daily.csv` and `daily.json`, one
row per day and measure with the total over the residents (for counts and amounts) and the mean
over the residents that have a value. They are derived from the run alone and replace what is
there; DIR is given explicitly (by convention `results/<run>/measures`), since analysis writes
nothing under the run. The days are those the world log has closed (`evaluation.records`), so a
day lost to an interruption counts once, as it was lived again.

A measure is None where it has no value: the mean of no ratings, or a cached share that no
reply reported.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from statistics import fmean
from typing import Any

from agent.directory import TRACE
from evaluation.records import Day, Entry, agent_dir, day_date, lived_days, town, trace_days

MEASURES = {
    "claimed": "tasks claimed",
    "submitted": "tasks handed in (acceptance runs)",
    "accepted": "hand-ins accepted",
    "earned": "money paid for accepted tasks",
    "spent_rent": "rent charged at midnight",
    "spent_fees": "the daily charges on what it owns, at midnight",
    "spent_food": "money spent on food",
    "spent_goods": "money spent on other goods",
    "hungry": "1 if it had nothing to eat that day",
    "starving": "1 if it was starving at midnight, which wore its health",
    "health": "its health at midnight, after the night's reckoning, 0 to 100",
    "died": "1 if its health ran out that midnight",
    "purse": "the purse after the midnight charges",
    "in_debt": "1 if that purse is below zero",
    "work_hours": "simulated hours at work, from starting work to stopping it or being taken away",
    "said_public": "things said to everyone present",
    "said_private": "things said to named residents",
    "heard_public": "things said by others to everyone present, heard",
    "heard_private": "things said by others to it by name",
    "interlocutors": "distinct residents it spoke or wrote to, or was spoken or written to by",
    "messages_sent": "written messages it sent",
    "messages_received": "written messages it received",
    "skills_given": "skills passed to others",
    "skills_received": "skills received",
    "money_given": "money handed to others",
    "money_received": "money received from others",
    "ratings_given": "ratings it gave that night",
    "rating_given_mean": "the mean score of those ratings",
    "ratings_received": "ratings others gave it that night",
    "rating_received_mean": "the mean score of those ratings",
    "journal": "1 if it wrote a journal entry, going to bed",
    "forced_sleep": "1 if it was put to sleep at the forced hour",
    "requests": "model requests, retries and compactions included",
    "prompt_tokens": "prompt tokens reported",
    "completion_tokens": "completion tokens reported",
    "cached_share": "cached prompt tokens over prompt tokens, of the replies that report them",
    "lapses": "steps or compactions that found no usable reply",
    "interruptions": "replies aborted by speech",
    "compactions": "compactions of the context",
}
"""Every measure of a resident-day and what it counts."""
LEVELS = frozenset({"health", "purse", "rating_given_mean", "rating_received_mean", "cached_share"})
"""The measures that are no count or amount, and so have no daily total."""

Row = dict[str, Any]


def measure(run_dir: Path) -> list[Row]:
    """One row per resident and lived day of the run at `run_dir`, by resident and day."""
    config = town(run_dir)
    days = sorted(lived_days(run_dir).values(), key=lambda day: day.number)
    rows = []
    for resident in config.residents:
        traces = trace_days(agent_dir(run_dir, config, resident.name) / TRACE, days)
        for day in days:
            rows.append(
                {
                    "resident": resident.name,
                    "day": day.number,
                    "date": day_date(config, day.number).isoformat(),
                    **world_measures(day, resident.name),
                    **trace_measures(traces[day.number]),
                }
            )
    return rows


def world_measures(day: Day, name: str) -> Row:
    """The measures of `name`'s lived `day` that the world log gives."""

    def mine(kind: str) -> list[Entry]:
        return [e for e in day.entries if e["kind"] == kind and e["actor"] == name]

    def to_me(kind: str, key: str) -> list[Entry]:
        return [e for e in day.entries if e["kind"] == kind and e["payload"][key] == name]

    settled = mine("settlement")
    purse = settled[-1]["payload"]["purse"] if settled else None
    bought = mine("purchase")
    speech = [e for e in day.entries if e["kind"] == "speech"]
    said = [e for e in speech if e["actor"] == name]
    heard = [e for e in speech if e["actor"] != name and name in e["payload"]["to"]]
    sent, got = mine("message"), to_me("message", "to")
    given, received = mine("rating"), to_me("rating", "rated")
    return {
        "claimed": len(mine("claim")),
        "submitted": len(mine("submission")),
        "accepted": sum(e["payload"]["resolved"] for e in mine("verdict")),
        "earned": sum(e["payload"]["amount"] for e in mine("payment")),
        "spent_rent": sum(e["payload"]["rent"] for e in settled),
        "spent_fees": sum(e["payload"]["fees"] for e in settled),
        "spent_food": sum(
            e["payload"]["amount"] for e in bought if e["payload"]["effect"] == "food"
        ),
        "spent_goods": sum(
            e["payload"]["amount"] for e in bought if e["payload"]["effect"] != "food"
        ),
        "hungry": int(bool(settled) and settled[-1]["payload"]["nourishment"] == 0),
        "starving": int(bool(settled) and "starving" in settled[-1]["payload"]["night"]),
        "health": settled[-1]["payload"]["health"] if settled else None,
        "died": int(bool(mine("death"))),
        "purse": purse,
        "in_debt": None if purse is None else int(purse < 0),
        "work_hours": _work_seconds(day, name) / 3600,
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
        "skills_given": len(mine("skill_shared")),
        "skills_received": len(to_me("skill_shared", "to")),
        "money_given": sum(e["payload"].get("amount", 0) for e in mine("gift")),  # 0: a thing
        "money_received": sum(e["payload"].get("amount", 0) for e in to_me("gift", "to")),
        "ratings_given": len(given),
        "rating_given_mean": _mean(e["payload"]["score"] for e in given),
        "ratings_received": len(received),
        "rating_received_mean": _mean(e["payload"]["score"] for e in received),
        "journal": int(any(e["payload"]["journal"] for e in mine("sleep"))),
        "forced_sleep": len(mine("forced_sleep")),
    }


def _work_seconds(day: Day, name: str) -> int:
    """Simulated seconds `name` spent in Work on `day`: from each start of work to its leaving
    work, by its own choice or the world's."""
    seconds, started = 0, None
    for e in day.entries:
        if e["kind"] == "start_work" and e["actor"] == name:
            started = e["sim_time"]
        elif started is not None and e["kind"] == "leave_work" and e["actor"] == name:
            seconds += e["sim_time"] - started
            started = None
    if started is not None:
        raise ValueError(f"{name} was still at work when day {day.number} closed")
    return seconds


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
        "interruptions": sum(r["kind"] == "interruption" for r in trace),
        "compactions": sum(r["kind"] == "compaction" for r in trace),
    }


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
    rows = measure(args.run)
    if not rows:
        parser.error(f"{args.run} has no lived day closed by a checkpoint")
    args.out.mkdir(parents=True, exist_ok=True)
    write(rows, args.out / "measures")
    write(daily(rows), args.out / "daily")
    days = sorted({row["day"] for row in rows})
    residents = len({row["resident"] for row in rows})
    print(f"{residents} residents, days {days[0]} to {days[-1]}: written to {args.out}")


if __name__ == "__main__":
    main()
