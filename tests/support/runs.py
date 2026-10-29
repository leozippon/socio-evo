"""A run directory written by a real world living a day in a small town of occupations, single log
entries written by hand, agent repositories committed as the simulation commits them, a
resident's trace and session, and a results root, for the frontend's tests; `make_run` puts them
together into the run the publisher's tests publish."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from infrastructure.git import Repository
from infrastructure.storage import RunDirectory, day_tag, read_jsonl
from simulation.config import ExperimentConfig
from tests.support.towns import (
    CARE,
    RESIDENTS,
    TRADES,
    Town,
    at,
    make_agent_dirs,
    opening,
    town_config,
)
from world.clock import DAY, ManualClock
from world.config import TownConfig
from world.testing import FakeBackend
from world.world import World

RUN = "data/runs/town"
"""Where the town's run is published in a site."""


def frontend_town() -> TownConfig:
    """The town of the frontend's tests: Mei and Aisha, programmers at the workshop (the office),
    with $20 to Aisha's name, and Tomas, their team leader; Olga the shopkeeper, Jonas the chef at
    the café (the restaurant), Lucia the doctor at the clinic (the hospital) and Vera the mayor
    at the hall, whose salary the treasury pays; a tenth of every payment for work is withheld
    into the treasury; a client withdraws a task at the midnight of the day it came in."""
    mei, tomas, aisha = RESIDENTS
    office = (mei, tomas | {"occupation": "team-leader"}, aisha | {"purse": 20})
    return town_config(residents=office + TRADES + CARE, tax=0.1, expiry_days=0)


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
    Store at 07:10 and sets the price of vegetables, of which Jonas buys some, and eggs, for the
    kitchen, paying her; she orders bread for the morning from her purse. Jonas cooks an omelette
    and two soups at the café at 07:30. Vera announces at the hall and grants Aisha $5 from the
    treasury. Mei works, talks, passes Tomas money and is paid her share of the client's payment; at
    10:30 she leaves for the clinic, where Lucia examines and treats her, has the omelette at the
    café, where Jonas serves her a soup unpaid, buys three helpings of bread at the Store, leaves
    one there, which Olga takes and eats, goes home, eats one and leaves the last there, where it
    lies. Tomas, the team leader, is paid his share of Mei's task, fails a task of his own and gives
    the third to Aisha at home; he works until 18:00, and both keep their tasks until the clients
    withdraw them at midnight. Every payment for work has a tenth withheld, none of them falling on
    a half. The four at the trades leave work at 18:00 for the flat, and are put to sleep at the
    forced hour with Aisha, who stays home and eats nothing; the soup nobody had is gone at
    midnight, when the treasury pays Vera her salary and takes everyone's rent, of which Aisha's
    purse spares only part, the rest owed."""
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
    await town.call("Olga", "set_price", item="vegetables", price=4)
    await town.call("Jonas", "buy", item="eggs", units=2, for_the_kitchen=True)
    await town.call("Jonas", "buy", item="vegetables", units=5, for_the_kitchen=True)
    await town.call("Jonas", "go", place="cafe")
    await town.call("Olga", "order", item="bread", quantity=5)
    await town.call("Lucia", "start_work")
    await town.call("Vera", "announce", text="The hall is open every day.")
    await town.call("Vera", "grant", amount=5, to="Aisha", reason="For the rent.")
    await town.until("07:30")
    await town.call("Jonas", "cook", dish="omelette", portions=1)
    await town.call("Jonas", "cook", dish="soup", portions=2)
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
    await town.call("Jonas", "pass", item="soup", to="Mei")
    await town.call("Mei", "go", place="store")
    await town.until("11:15")
    await town.call("Mei", "buy", item="bread", units=3)
    await town.call("Mei", "put", item="bread")
    await town.call("Olga", "get", item="bread")
    await town.call("Olga", "eat", item="bread")
    await town.call("Mei", "go", place="mill-street-house")
    await town.until("12:00")
    await town.call("Mei", "eat", item="bread")
    await town.until("12:05")
    await town.call("Mei", "put", item="bread")
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


def files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


async def make_run(root: Path) -> RunDirectory:
    """The town's run after a lived day: agents committed as created and at the first
    checkpoint, with Mei's trace and session."""
    run, town = new_town(root)
    config = frontend_town()
    commit_agents(run, config, 0)
    await live_a_day(town)
    await town.close()
    first, checkpoint = real_times(run)
    step = (checkpoint - first) / 10  # the manual clock lives a day in milliseconds
    tools = ["read_file", "go", "say"]
    records = [
        {
            "kind": "percept",
            "sim_time": at("07:00"),
            "real_time": first + 1 * step,
            "text": "You woke up.",
            "percept_kind": "wake",
            "event_id": 1,
            "percept_sim_time": at("07:00"),
            "percept_real_time": first,
        },
        {
            "kind": "prompt",
            "sim_time": at("07:00"),
            "real_time": first + 2 * step,
            "text": "You are Mei.",
        },
        {
            "kind": "request",
            "sim_time": at("07:00"),
            "real_time": first + 3 * step,
            "purpose": "step",
            "messages": [1],
            "tools": tools,
            "reasoning_effort": "low",
            "max_tokens": 100,
            "attempt": 1,
        },
        {
            "kind": "reply",
            "sim_time": at("07:01"),
            "real_time": first + 4 * step,
            "purpose": "step",
            "text": "",
            "truncated": False,
            "max_tokens": 100,
            "reasoning": "Off to work.",
            "tool_calls": [
                {"id": "c1", "name": "go", "arguments": {"place": "workshop"}, "unreadable": None}
            ],
            "finish_reason": "tool_calls",
            "usage": None,
            "latency": 0.1,
        },
        {
            "kind": "tool_call",
            "sim_time": at("07:01"),
            "real_time": first + 5 * step,
            "id": "c1",
            "name": "go",
            "arguments": {"place": "workshop"},
        },
        {
            "kind": "tool_result",
            "sim_time": at("07:01"),
            "real_time": first + 6 * step,
            "id": "c1",
            "name": "go",
            "text": "You set off.",
            "ends_turn": True,
        },
        {
            "kind": "request",
            "sim_time": at("07:30", day=2),
            "real_time": checkpoint + 1,
            "purpose": "step",
            "messages": [1, 2, 3, 4],
            "tools": tools,
            "reasoning_effort": "low",
            "max_tokens": 100,
            "attempt": 1,
        },
        {
            "kind": "lapse",
            "sim_time": at("07:31", day=2),
            "real_time": checkpoint + 2,
            "purpose": "step",
            "errors": ["timeout"],
        },
    ]
    session = [
        {
            "type": "message",
            "id": 1,
            "message": {"role": "user", "content": "You woke up. Now you can use: go."},
        },
        {
            "type": "message",
            "id": 2,
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "name": "go", "arguments": {"place": "workshop"}}],
            },
            "prompt_tokens": 10,
        },
        {
            "type": "message",
            "id": 3,
            "message": {"role": "tool", "content": "You set off.", "tool_call_id": "c1"},
        },
        {"type": "compaction", "id": 4, "replaced": [1], "summary": "I went to work."},
    ]
    write_trace(run, "Mei", records, session)
    commit_agents(run, config, 1)
    run.checkpoint_path(1).write_text(json.dumps(town.checkpoints[0][1]))
    return run
