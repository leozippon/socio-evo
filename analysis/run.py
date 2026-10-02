"""A run directory as analysis reads it: manifest, frozen configuration, the complete events of
the log, and how far the latest checkpoint settles them.

A run may be in progress while it is read. The logs are appended one line at a time, so a
final line without its newline is a write under way and is left for the next reading; any
other line that is not a valid record is an error. Everything up to the latest checkpoint is
final, because a run resumes from that checkpoint and discards only what came after it.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from core.interaction import Event, day_of
from infrastructure.storage import Manifest, RunDirectory


@dataclass(frozen=True)
class RunData:
    """One reading of a run. `checkpoint` is the day of the latest checkpoint, None before
    the first; the days up to it are settled: their events, and the agent versions committed
    on them, never change again."""

    directory: RunDirectory
    manifest: Manifest
    config: dict[str, Any]
    events: tuple[Event, ...]
    checkpoint: int | None

    @property
    def settled_day(self) -> int:
        """The last settled day, 0 if none is."""
        return self.checkpoint or 0

    @property
    def last_day(self) -> int:
        """The day of the latest event, 0 before the first."""
        return day_of(self.events[-1].time) if self.events else 0

    @property
    def agents(self) -> list[str]:
        """The agent ids, in the order of the configuration."""
        return [agent["profile"]["name"] for agent in self.config["agents"]]


def read_run(root: Path) -> RunData:
    """Read the run at `root`. The manifest and the latest checkpoint are read before the
    events, so the events read reach at least as far as the checkpoint says.

    Raises ValueError if a complete line of the event log is not the next valid event in
    time order, or if the events of the settled days are not exactly those the checkpoint
    counts.
    """
    directory = RunDirectory(root)
    manifest = directory.read_manifest()
    config = yaml.safe_load(directory.config_path.read_text(encoding="utf-8"))
    latest = directory.latest_checkpoint()
    checkpoint = None if latest is None else json.loads(latest.read_text(encoding="utf-8"))
    events: list[Event] = []
    for number, line in enumerate(complete_lines(directory.events_path), start=1):
        try:
            event = Event.model_validate_json(line)
        except ValueError as error:
            raise ValueError(f"{directory.events_path}:{number}: {error}") from error
        if event.seq != len(events) or (events and event.time < events[-1].time):
            raise ValueError(f"{directory.events_path}:{number}: event out of sequence")
        events.append(event)
    run = RunData(
        directory,
        manifest,
        config,
        tuple(events),
        None if checkpoint is None else checkpoint["day"],
    )
    if checkpoint is not None:
        counted = checkpoint["environment"]["event_count"]
        settled = sum(1 for event in events if day_of(event.time) <= run.settled_day)
        if settled != counted:
            raise ValueError(
                f"{latest}: checkpoint of day {run.settled_day} counts {counted} events, "
                f"the log holds {settled} up to that day"
            )
    return run


def complete_lines(path: Path) -> Iterator[bytes]:
    """The newline-terminated lines of `path`, nothing if it does not exist; a final line
    without its newline is still being written and is left out."""
    if not path.exists():
        return iter(())
    return iter(path.read_bytes().split(b"\n")[:-1])


def read_records(path: Path) -> Iterator[dict[str, Any]]:
    """Each complete line of the JSONL file `path` as an object; raises ValueError naming the
    line for anything else."""
    for number, line in enumerate(complete_lines(path), start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{number}: {error}") from error
        if not isinstance(record, dict):
            raise ValueError(f"{path}:{number}: expected a JSON object")
        yield record
