"""Internal honesty of a run: each resident's journal of a day set against the world's record of
that day by the judge.

    python -m evaluation.journals RUN_DIR --days N [N ...] [--residents NAME ...]
        [--judge JUDGE.yaml] --out DIR

For each resident (every resident of the town by default) and each lived day given, the journal
entry it wrote going to bed is judged against its record of the day (`evaluation.records`) by
`evaluation.honesty.distortion`. DIR receives `days.json`, one row per resident-day: whether it
wrote a journal, the number of lines of its record, the count of claims of each label and the
distortion rate, null when it is undefined (no journal, or no claim the record could check);
`claims.json`, one row per claim: the passage, the claim restated, the label, the evidence
quoted from the record and the judge's reasoning; and `judge.jsonl`, every call of the judge.
None of these files may exist already.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.directory import TRACE
from evaluation.honesty import LABELS, HonestyResult, distortion
from evaluation.judge import CONFIG as JUDGE_CONFIG
from evaluation.judge import Judge
from evaluation.records import (
    agent_dir,
    day_date,
    journal_of,
    lived,
    lived_days,
    record,
    town,
    trace_days,
)
from infrastructure.storage import read_jsonl

OUTPUTS = ("days.json", "claims.json", "judge.jsonl")


@dataclass(frozen=True)
class ResidentDay:
    """What the judge is given for one resident-day: the record, and the journal if any."""

    resident: str
    day: int
    date: str
    record: str
    journal: str | None


def prepare(run_dir: Path, days: Sequence[int], residents: Sequence[str] = ()) -> list[ResidentDay]:
    """The record and journal of each of `residents` (all by default) on each of `days`;
    ValueError for a day the world log has not closed or a name that is no resident's."""
    config = town(run_dir)
    found = lived_days(run_dir)
    chosen = [lived(found, day) for day in dict.fromkeys(days)]
    items = []
    for name in residents or [r.name for r in config.residents]:
        traces = trace_days(agent_dir(run_dir, config, name) / TRACE, chosen)
        for day in chosen:
            items.append(
                ResidentDay(
                    name,
                    day.number,
                    day_date(config, day.number).isoformat(),
                    record(day.entries, traces[day.number], name),
                    journal_of(day.entries, name),
                )
            )
    return items


async def judge_all(
    items: Sequence[ResidentDay], judge: Judge
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The rows of `days.json` and of `claims.json` for `items`."""

    async def judged(item: ResidentDay) -> HonestyResult | None:
        if item.journal is None:
            return None
        return await distortion(item.record, item.journal, judge)

    results = await asyncio.gather(*(judged(item) for item in items))
    days, claims = [], []
    for item, result in zip(items, results, strict=True):
        key = {"resident": item.resident, "day": item.day, "date": item.date}
        counts = result.counts if result else dict.fromkeys(LABELS, 0)
        days.append(
            key
            | {
                "journal": item.journal is not None,
                "record_lines": len(item.record.splitlines()),
                "claims": sum(counts.values()),
                **counts,
                "distortion": result.distortion if result else None,
            }
        )
        for number, claim in enumerate(result.claims if result else (), start=1):
            verdict = claim.judgement.verdict
            claims.append(
                key
                | {
                    "claim": number,
                    "quote": claim.quote,
                    "statement": claim.statement,
                    "label": claim.label,
                    "evidence": list(verdict.evidence),
                    "reasoning": verdict.reasoning,
                }
            )
    return days, claims


def usage(log: Path) -> dict[str, int]:
    """The calls recorded in the judge's `log` and the tokens they used, as reported."""
    records = list(read_jsonl(log)) if log.exists() else []
    tokens = [r["response"]["usage"] for r in records if r["response"] and r["response"]["usage"]]
    return {
        "calls": len(records),
        "prompt_tokens": sum(t["prompt_tokens"] for t in tokens),
        "cached_prompt_tokens": sum(t.get("cached_prompt_tokens") or 0 for t in tokens),
        "completion_tokens": sum(t["completion_tokens"] for t in tokens),
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m evaluation.journals", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("run", type=Path, help="the run directory")
    parser.add_argument("--days", type=int, nargs="+", required=True, help="lived days, from 1")
    parser.add_argument("--residents", nargs="+", default=[], help="residents (default: all)")
    parser.add_argument("--judge", type=Path, default=JUDGE_CONFIG, help="judge LLMConfig YAML")
    parser.add_argument("--out", type=Path, required=True, help="directory of the results")
    args = parser.parse_args(argv)

    paths = {name: args.out / name for name in OUTPUTS}
    if existing := [str(path) for path in paths.values() if path.exists()]:
        parser.error(f"would overwrite {', '.join(existing)}")
    try:
        items = prepare(args.run, args.days, args.residents)
    except ValueError as error:
        parser.error(str(error))
    args.out.mkdir(parents=True, exist_ok=True)
    judge = Judge.from_config(paths["judge.jsonl"], args.judge)

    started = time.perf_counter()
    days, claims = asyncio.run(judge_all(items, judge))
    seconds = time.perf_counter() - started
    for name, rows in (("days.json", days), ("claims.json", claims)):
        paths[name].write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", "utf-8")
    judged = [row for row in days if row["journal"]]
    rates = [row["distortion"] for row in judged if row["distortion"] is not None]
    spent = usage(paths["judge.jsonl"])
    print(
        f"{len(days)} resident-days, {len(judged)} with a journal, {len(claims)} claims, "
        f"{len(rates)} with a distortion rate; {seconds:.1f} s; judge: {spent['calls']} calls, "
        f"{spent['prompt_tokens']} prompt tokens ({spent['cached_prompt_tokens']} cached), "
        f"{spent['completion_tokens']} completion tokens; written to {args.out}"
    )


if __name__ == "__main__":
    main()
