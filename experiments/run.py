"""Run a town.

    python -m experiments.run CONFIG [--runs-root runs] [--until-day N] [--resume] [--dry-run]

The run lives in `<runs-root>/<name>`. Creating a run that exists fails; `--resume` continues it
from its latest checkpoint and requires the configuration frozen in it. `--until-day N` stops
after the checkpoint of day N, leaving the run interrupted and resumable. `--dry-run` runs
`<name>-dry-run` on the scripted dry-run model and a fake board, with a clock that lives a day
in seconds, so it needs neither the model server nor Docker. Credentials come from the
environment: `set -a; . ./.env; set +a` first.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path

from experiments.config import load_experiment
from simulation.run import run


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m experiments.run", description="Run a town.")
    parser.add_argument("config", type=Path, help="experiment configuration (YAML)")
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--until-day", type=int, help="stop after the checkpoint of this day")
    parser.add_argument("--resume", action="store_true", help="continue the existing run")
    parser.add_argument("--dry-run", action="store_true", help="scripted model, fake board")
    args = parser.parse_args(argv)
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
    config = load_experiment(args.config)
    root, status = asyncio.run(
        run(
            config,
            args.runs_root,
            resume=args.resume,
            until_day=args.until_day,
            dry_run=args.dry_run,
        )
    )
    print(f"{root}: {status.value}")


if __name__ == "__main__":
    main()
