"""Export every resident's directory of a run as it stood at a day's checkpoint.

    python -m experiments.export RUN --day N --out DIR

Each resident's directory at its tag `day-NN` is written, without history, to `DIR/<name>`,
without the session and the trace, and `DIR/export.json` records the run, the day, each
resident's commit and occupation and the run's frozen model and runtime settings
(`evaluation.exports`). Day 0 is the residents as they started. Evaluation runs on such exports,
never on the run itself.

A DIR that holds the same export already is kept as it is, so the command can be run before
every evaluation; one that holds an export of other commits or settings (a run created again
under the same name, say) is replaced, and anything else in DIR's place is refused.
"""

from __future__ import annotations

import argparse
import shutil
from collections.abc import Sequence
from pathlib import Path

import yaml

from evaluation.exports import MANIFEST, Export
from infrastructure.config import RECORD
from infrastructure.git import Repository
from infrastructure.storage import RunDirectory, day_tag


def manifest(run_dir: Path, day: int) -> Export:
    """What an export of day `day` of the run at `run_dir` records; ValueError when the run has
    no checkpoint of that day."""
    run = RunDirectory.open(run_dir)
    if not run.checkpoint_path(day).is_file():
        raise ValueError(f"{run_dir} has no checkpoint of day {day}")
    frozen = yaml.safe_load(run.config_path.read_text(encoding="utf-8"))
    commits = {
        agent.name: Repository(agent).log(day_tag(day))[0].id
        for agent in sorted(path for path in run.agents_dir.iterdir() if path.is_dir())
    }
    return Export.model_validate(
        {
            "run": str(run.root.resolve()),
            "day": day,
            "commits": commits,
            "occupations": {r["name"]: r["occupation"] for r in frozen["town"]["residents"]},
            "llm": frozen["llm"],
            "runtime": frozen["runtime"],
        },
        context=RECORD,
    )


def export_day(run_dir: Path, day: int, out: Path) -> dict[str, Path]:
    """Every resident's directory of the run at `run_dir` as of day `day`, exported into
    `out/<name>`, which must not exist, and the export's manifest into `out`; the exports by
    name. The session and the trace are left out, so that a runtime started on an export begins
    a session of its own rather than continuing the town's."""
    found = manifest(run_dir, day)
    run = RunDirectory.open(run_dir)
    exports = {}
    for name in found.commits:
        Repository(run.agent_dir(name)).export(day_tag(day), out / name)
        exports[name] = out / name
        for kept in ("session.jsonl", "trace.jsonl"):
            (out / name / kept).unlink(missing_ok=True)
    (out / MANIFEST).write_text(found.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return exports


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m experiments.export", description=__doc__.splitlines()[0]
    )
    parser.add_argument("run", type=Path, help="the run directory")
    parser.add_argument("--day", type=int, required=True, help="the day's checkpoint")
    parser.add_argument("--out", type=Path, required=True, help="where the exports go")
    args = parser.parse_args(argv)
    try:
        expected = manifest(args.run, args.day)
    except ValueError as error:
        parser.error(str(error))
    if (args.out / MANIFEST).is_file():
        try:
            held: Export | None = Export.read(args.out / MANIFEST)
        except ValueError:  # a manifest the code cannot read is of other settings
            held = None
        if held == expected:
            print(f"{args.out} holds this export already")
            return
        shutil.rmtree(args.out)
        print(f"{args.out} held an export of other commits or settings: exporting again")
    elif args.out.exists():
        parser.error(f"{args.out} exists and holds no {MANIFEST}: it is no export to replace")
    for name, path in export_day(args.run, args.day, args.out).items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
