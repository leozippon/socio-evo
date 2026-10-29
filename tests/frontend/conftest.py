"""A run directory written by a real world living a day in a small town of occupations, single log
entries written by hand, agent repositories committed as the simulation commits them, a
resident's trace and session, and a results root, for the frontend's tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from infrastructure.git import Repository
from infrastructure.storage import RunDirectory, day_tag, read_jsonl
from simulation.config import ExperimentConfig
from tests.world.conftest import (
    CARE,
    RESIDENTS,
    TRADES,
    Town,
    make_agent_dirs,
    opening,
    town_config,
)
from world.clock import DAY, ManualClock
from world.config import TownConfig
from world.testing import FakeBackend
from world.world import World


def frontend_town() -> TownConfig:
    """The town of the frontend's tests: Mei and Aisha, programmers at the workshop (the office),
    and Tomas, their team leader; Olga the shopkeeper, Jonas the chef at the café (the
    restaurant), Lucia the doctor at the clinic (the hospital) and Vera the mayor at the hall; a
    client withdraws a task at the midnight of the day it came in."""
    mei, tomas, aisha = RESIDENTS
    office = (mei, tomas | {"occupation": "team-leader"}, aisha)
    return town_config(residents=office + TRADES + CARE, expiry_days=0)


def new_town(root: Path, backend: FakeBackend | None = None) -> tuple[RunDirectory, Town]:
    config = frontend_town()
    run = RunDirectory(root / "town")
    if not run.root.exists():
        frozen = ExperimentConfig.model_validate(
            {
                "name": "town",
                "llm": {"backend": "scripted", "base_url": "-", "api_key_env": "-", "model": "-"},
                "runtime": {},
                "town": config.model_dump(mode="json"),
                "residents": [
                    {"name": r.name, "background": f"experiments/residents/{r.name.lower()}.md"}
                    for r in config.residents
                ],
                "days": 2,
            }
        )
        run = RunDirectory.create(root, "town", config=frozen, code_revision="test")
    make_agent_dirs(run.root, config)
    backend = backend or FakeBackend()
    world = World(config, run.root, backend, clock=ManualClock())
    opening(world)
    return run, Town(world, backend)


async def live_a_day(town: Town, midway: Callable[[], Any] = lambda: None) -> None:
    """Day 1 and day 2 until 18:05. The three tasks of the pool come in at 08:00. Olga opens the
    Store at 07:10, where Jonas buys eggs and vegetables for the kitchen; she orders bread for
    the morning and sets its price. Jonas cooks an omelette and a soup at the café at 07:30.
    Vera reads the report at the hall and announces. Mei works, talks, gives and is paid; at
    10:30 she leaves for the clinic, where Lucia examines and treats her, has the omelette at the
    café, buys bread at the Store and goes home. Tomas, the team leader, is paid his sum for
    Mei's task, fails a task of his own and gives the third to Aisha at home; he works until
    18:00, and both keep their tasks until the clients withdraw them at midnight. The
    four at the trades leave work at 18:00 for the flat, and are put to sleep at the forced
    hour with Aisha, who stays home."""
    skills = town.world.residents["Mei"].agent_dir / "skills"
    (skills / "triage.md").write_text("Read the traceback first.\n")
    town.start(until_day=3)
    await town.until("07:00")
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="workshop")
    for name, place in (
        ("Olga", "store"),
        ("Jonas", "store"),
        ("Lucia", "clinic"),
        ("Vera", "hall"),
    ):
        await town.call(name, "go", place=place)
    await town.until("07:10")
    await town.call("Olga", "start_work")
    await town.call("Jonas", "buy", item="eggs", units=2, for_the_kitchen=True)
    await town.call("Jonas", "buy", item="vegetables", units=3, for_the_kitchen=True)
    await town.call("Jonas", "go", place="cafe")
    await town.call("Olga", "order", item="bread", quantity=5)
    await town.call("Olga", "set_price", item="bread", price=5)
    await town.call("Lucia", "start_work")
    await town.call("Vera", "report")
    await town.call("Vera", "announce", text="The hall is open every day.")
    await town.until("07:30")
    await town.call("Jonas", "cook", dish="omelette", portions=1)
    await town.call("Jonas", "cook", dish="soup", portions=1)
    await town.until("09:00")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="fix.py", content="FIX\n")
    await town.until("09:30")
    await town.call("Tomas", "say", text="How is it going?")
    await town.until("09:32")
    await town.call("Mei", "say", text="Nearly done.", to=["Tomas"])
    await town.call("Mei", "pass", item="money", units=5, to="Tomas")
    await town.until("09:35")
    await town.call("Mei", "leave_conversation")
    midway()
    await town.until("10:00")
    await town.call("Mei", "submit")
    await town.call("Tomas", "claim_task", task=2)
    await town.call("Tomas", "write_repo_file", path="a.py", content="half\n")
    await town.call("Tomas", "submit")
    await town.call("Tomas", "assign", task=3, to="Aisha")
    await town.until("10:30")
    await town.call("Mei", "leave_work")
    await town.call("Mei", "go", place="clinic")
    await town.until("10:40")
    await town.call("Lucia", "examine", patient="Mei")
    await town.call("Lucia", "treat", patient="Mei")
    await town.call("Mei", "go", place="cafe")
    await town.until("11:00")
    await town.call("Mei", "buy", item="omelette")
    await town.call("Mei", "go", place="store")
    await town.until("11:15")
    await town.call("Mei", "buy", item="bread", units=2)
    await town.call("Mei", "go", place="mill-street-house")
    await town.until("18:00")
    for name in ("Tomas", "Olga", "Jonas", "Lucia", "Vera"):
        await town.call(name, "leave_work")
    for name in ("Olga", "Jonas", "Lucia", "Vera"):
        await town.call(name, "go", place="college-flat")
    await town.until("22:00")
    await town.call("Tomas", "go", place="college-flat")
    await town.call("Mei", "sleep", until="07:00", journal="I fixed task 1.")
    await town.until("23:00")
    await town.call("Tomas", "sleep", until="08:00", journal="Task 2 is hard.")
    town.rest()
    await town.until("18:05", day=2)


def entry(
    seq: int, kind: str, t: int, actor: str | None = None, *, real_time: float = 0.0, **payload: Any
) -> str:
    """A line of the world log."""
    return json.dumps(
        {
            "seq": seq,
            "kind": kind,
            "sim_time": t,
            "real_time": real_time,
            "actor": actor,
            "place": "mill-street-house",
            "audience": [],
            "text": "",
            "personal": {},
            "payload": payload,
        }
    )


def moment_of(config: TownConfig, t: int) -> datetime:
    """The wall-clock datetime the simulation gives simulated time `t`."""
    return datetime.combine(config.start_date, datetime.min.time(), UTC) + timedelta(seconds=t)


def commit_agents(run: RunDirectory, config: TownConfig, day: int) -> dict[str, str]:
    """Commit every resident's directory as the simulation does at the checkpoint of `day`
    (0 as created): a repository is made at day 0 with the resident's background, a note goes
    into its memory on later days, and a session and trace line of the day are written, as the
    runtime leaves them; returns the commit of each resident."""
    commits = {}
    for resident in config.residents:
        path = run.agent_dir(resident.name)
        if day == 0:
            (path / "background.md").write_text(f"You are {resident.name}.\n")
            (path / "memory" / "journal").mkdir(exist_ok=True)
            (path / "trace.jsonl").touch()  # every runtime writes one as it starts
            Repository.init(path, user_name=resident.name, user_email="r@town.invalid")
        else:
            with (path / "memory" / "notes.md").open("a") as file:
                file.write(f"Day {day}: a note on the work.\n")
        with (path / "session.jsonl").open("a") as file:
            file.write(
                json.dumps(
                    {
                        "type": "message",
                        "id": day + 100,
                        "message": {"role": "user", "content": f"day {day}"},
                    }
                )
                + "\n"
            )
        repository = Repository(path)
        t = day * DAY + 9000
        message = f"{day_tag(day)}: day {day} at 02:30"
        commits[resident.name] = repository.commit(
            message, date=moment_of(config, t), allow_empty=True
        )
        repository.tag(day_tag(day))
    return commits


def write_trace(
    run: RunDirectory, name: str, records: list[dict[str, Any]], session: list[dict[str, Any]]
) -> None:
    """Write `records` as the resident's trace and `session` as its session, as the runtime
    leaves them in its directory."""
    path = run.agent_dir(name)
    (path / "trace.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    (path / "session.jsonl").write_text("".join(json.dumps(r) + "\n" for r in session))


def real_times(run: RunDirectory) -> tuple[float, float]:
    """The real times of the log's first entry and of its first checkpoint."""
    entries = list(read_jsonl(run.world_log_path))
    first = entries[0]["real_time"]
    checkpoint = next(e["real_time"] for e in entries if e["kind"] == "checkpoint")
    return first, checkpoint


def write_results(root: Path, run: str, *, finished: bool = True) -> None:
    """An evaluation results root for `run`: day 0 shared beside it, day 1 under it, journals
    of its first day; with `finished` false, Tomas's capability on day 1 is still running."""
    for day_dir in (root / "day-00", root / run / "day-01"):
        (day_dir / "capability" / "Mei").mkdir(parents=True)
        (day_dir / "capability" / "Mei" / "results.json").write_text(
            json.dumps(
                {
                    "model": {"model": "qwen"},
                    "occupation": "programmer",
                    "resolved_rate": 0.25 if day_dir.name == "day-00" else 0.5,
                    "evaluated": 4,
                    "resolved": 1,
                }
            )
        )
        (day_dir / "mask").mkdir()
        (day_dir / "mask" / "Mei.json").write_text(
            json.dumps(
                {
                    "model": {"model": "qwen"},
                    "judge": {"model": "deepseek"},
                    "shares": {"truthful": 0.4, "lie": 0.1, "evasive": 0.5},
                }
            )
        )
    if not finished:
        (root / run / "day-01" / "capability" / "Tomas").mkdir()
    journals = root / run / "journals" / "d01"
    journals.mkdir(parents=True)
    rows = [
        {
            "resident": "Mei",
            "day": 1,
            "date": "2001-01-01",
            "journal": True,
            "record_lines": 20,
            "claims": 4,
            "supported": 3,
            "contradicted": 1,
            "unverifiable": 0,
            "distortion": 0.25,
            "extra": "ignored",
        },
        {
            "resident": "Aisha",
            "day": 1,
            "date": "2001-01-01",
            "journal": False,
            "record_lines": 3,
            "claims": 0,
            "supported": 0,
            "contradicted": 0,
            "unverifiable": 0,
            "distortion": None,
        },
    ]
    (journals / "days.json").write_text(json.dumps(rows))
    (journals / "claims.json").write_text("[]")
