"""Fork a completed day-boundary run and continue it for more days.

Unlike partial-day resume, this preserves synchronized social/repository state.
The source run is never modified. Only the experiment name and duration change.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import shutil
import signal
from datetime import UTC, datetime
from pathlib import Path

import yaml

from experiments.config import ExperimentConfig
from experiments.run import close_providers, setup
from infrastructure.config import load_config
from infrastructure.storage import RunDirectory, RunStatus
from runtime.scheduler import Trigger, TriggerKind
from runtime.simulation import Simulation
from runtime.simulation.simulation import Checkpoint


def fork_completed(source: Path, name: str, days: int) -> tuple[RunDirectory, ExperimentConfig]:
    original = RunDirectory.open(source)
    config = load_config(original.config_path, ExperimentConfig)
    if original.read_manifest().status != RunStatus.COMPLETED:
        raise ValueError("only a completed run can be extended")
    if days <= config.simulation.days:
        raise ValueError("new duration must exceed the completed duration")
    path = original.latest_checkpoint()
    if path is None:
        raise ValueError("missing final checkpoint")
    checkpoint = Checkpoint.model_validate_json(path.read_text())
    if checkpoint.day != config.simulation.days or checkpoint.queue:
        raise ValueError("extension requires a final checkpoint with no pending triggers")
    events = original.events_path.read_bytes()
    if len(events.splitlines()) != checkpoint.environment["event_count"]:
        raise ValueError("events extend beyond the final checkpoint")
    data = config.model_dump(mode="json")
    data["name"] = name
    data["simulation"]["days"] = days
    extended = ExperimentConfig.model_validate(data)
    target = RunDirectory.root_of(source.parent.parent, name, original.read_manifest().seed)
    if target.exists():
        raise FileExistsError(target)
    shutil.copytree(source, target)
    directory = RunDirectory.open(target)
    directory.config_path.write_text(yaml.safe_dump(extended.model_dump(mode="json")))
    next_day = Trigger(
        time=config.simulation.calendar.start(checkpoint.day + 1), kind=TriggerKind.DAY_START
    )
    directory.checkpoint_path(checkpoint.day).write_text(
        checkpoint.model_copy(update={"queue": (next_day,)}).model_dump_json(indent=2) + "\n"
    )
    (target / "continuation.json").write_text(
        json.dumps(
            {
                "source": str(source.resolve()),
                "continued_at": datetime.now(UTC).isoformat(),
                "through_day": checkpoint.day,
                "target_day": days,
                "source_events_sha256": hashlib.sha256(events).hexdigest(),
                "source_checkpoint_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "note": "Same trajectory; daily task pool and all other settings preserved.",
            },
            indent=2,
        )
        + "\n"
    )
    directory.update_manifest(status=RunStatus.INTERRUPTED, ended_at=None)
    return directory, extended


async def extend(source: Path, name: str, days: int) -> RunStatus:
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)
    directory, config = fork_completed(source, name, days)
    parts = setup(config, directory.read_manifest().seed, directory.llm_calls_path)
    try:
        return await Simulation.resume(directory, parts).run()
    finally:
        await close_providers(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--days", type=int, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    print(asyncio.run(extend(args.source, args.name, args.days)))


if __name__ == "__main__":
    main()
