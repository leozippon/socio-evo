"""Export every resident's directory of a run as it stood at a day's checkpoint.

    python -m experiments.export RUN --day N --out DIR

Each resident's directory at its tag `day-NN` is written, without history, to `DIR/<name>`,
which must not exist, without the session and the trace. Day 0 is the residents as they
started. Evaluation runs on such exports, never on the run itself.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from infrastructure.git import Repository
from infrastructure.storage import RunDirectory, day_tag


def export_day(run_dir: Path, day: int, out: Path) -> dict[str, Path]:
    """Every resident's directory of the run at `run_dir` as of day `day`, exported into
    `out/<name>`; the exports by name. The session and the trace are left out, so that a runtime
    started on an export begins a session of its own rather than continuing the town's."""
    run = RunDirectory.open(run_dir)
    if not run.checkpoint_path(day).is_file():
        raise ValueError(f"{run_dir} has no checkpoint of day {day}")
    exports = {}
    for agent in sorted(path for path in run.agents_dir.iterdir() if path.is_dir()):
        Repository(agent).export(day_tag(day), out / agent.name)
        exports[agent.name] = out / agent.name
        for name in ("session.jsonl", "trace.jsonl"):
            (out / agent.name / name).unlink(missing_ok=True)
    return exports


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m experiments.export", description=__doc__.splitlines()[0]
    )
    parser.add_argument("run", type=Path, help="the run directory")
    parser.add_argument("--day", type=int, required=True, help="the day's checkpoint")
    parser.add_argument("--out", type=Path, required=True, help="where the exports go")
    args = parser.parse_args(argv)
    for name, path in export_day(args.run, args.day, args.out).items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
