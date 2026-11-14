"""Preflight and run one AI laboratory on Zenith, using its frozen configuration."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
from pathlib import Path

import yaml

from infrastructure.storage.run_directory import RunStatus
from ops.research.run_pair import (
    PROJECT_ROOT,
    configuration,
    pending,
    preflight,
    remote_root,
    require_credentials,
)
from simulation.run import run


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument(
        "--config", type=Path, default=PROJECT_ROOT / "experiments/configs/ai-lab.yaml"
    )
    parser.add_argument("--seed", type=int, default=20260302)
    parser.add_argument("--gpu", default="device=1", help="Research GPU; the model uses GPU 0")
    parser.add_argument("--until-day", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    root = remote_root(args.runs_root)
    config = configuration(args.config, args.seed, args.gpu)
    configs = {"lab": config}
    require_credentials(configs)
    control = root / f"lab-seed-{args.seed}"
    control.mkdir(parents=True, exist_ok=True)
    with (control / "controller.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        active = pending(configs, root, resume=args.resume, until_day=args.until_day)
        if not active:
            return 0
        asyncio.run(preflight(configs, control))
        if args.preflight_only:
            print(f"Preflight passed: {control / 'preflight.json'}")
            return 0
        frozen = control / "lab.yaml"
        serialized = yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False)
        if frozen.exists() and frozen.read_text() != serialized:
            raise ValueError(f"Frozen launch configuration differs: {frozen}")
        frozen.write_text(serialized)
        _, status = asyncio.run(run(config, root, resume=args.resume, until_day=args.until_day))
        return 1 if status == RunStatus.FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
