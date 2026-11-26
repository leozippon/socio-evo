"""Fitting a night's adapters: one trainer process for every resident that learnt something new.

The trainer is `learning.train`, run as `<trainer.python> -m learning.train --jobs jobs.json` from
the repository's root with `CUDA_VISIBLE_DEVICES` set to `trainer.gpus`. `jobs.json` names the base
model, the LoRA settings and one job for each adapter: its name, its dataset and the directory it
is to be written to. The trainer fits each from the base afresh, writes a PEFT adapter directory
with `training.json` into it, and exits non-zero on any failure. An adapter is complete once its
`training.json` is there (`adapters.TRAINING`); a directory without it is what a fit broken off
left, and is cleared before the adapter is fitted again. The trainer's output is appended to
`trainer.log` beside `jobs.json`. A trainer that fails, or ends without completing every adapter,
raises `TrainerError`; one whose run is cancelled is stopped.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from infrastructure.storage import write_json
from learning.adapters import TRAINING
from learning.config import LoraConfig, TrainerConfig

ROOT = Path(__file__).resolve().parents[1]
"""The repository's root, from which `learning.train` is run."""
JOBS = "jobs.json"
LOG = "trainer.log"
STOP_SECONDS = 30
"""How long a trainer told to stop is given before it is killed."""


class TrainerError(RuntimeError):
    """The trainer failed, or did not complete every adapter."""


@dataclass(frozen=True)
class Job:
    """Fit adapter `name` on the dataset `dataset` into the directory `out`."""

    name: str
    dataset: Path
    out: Path


async def fit(
    jobs: Sequence[Job], *, trainer: TrainerConfig, lora: LoraConfig, folder: Path
) -> None:
    """Fit every adapter of `jobs` in one trainer process, its jobs and output in `folder`."""
    for job in jobs:
        if job.out.exists():
            shutil.rmtree(job.out)
        job.out.parent.mkdir(parents=True, exist_ok=True)
    write_json(
        folder / JOBS,
        {
            "base": trainer.base,
            "lora": lora.model_dump(mode="json"),
            "jobs": [
                {"name": j.name, "dataset": str(j.dataset.resolve()), "out": str(j.out.resolve())}
                for j in jobs
            ],
        },
    )
    with (folder / LOG).open("ab") as log:
        process = await asyncio.create_subprocess_exec(
            str(trainer.executable),
            "-m",
            "learning.train",
            "--jobs",
            str((folder / JOBS).resolve()),
            cwd=ROOT,
            env={**os.environ, "CUDA_VISIBLE_DEVICES": trainer.gpus},
            stdout=log,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            code = await process.wait()
        except asyncio.CancelledError:
            await _stop(process)
            raise
    if code != 0:
        raise TrainerError(f"the trainer exited with {code}; its output is in {folder / LOG}")
    missing = [job.name for job in jobs if not (job.out / TRAINING).is_file()]
    if missing:
        raise TrainerError(f"the trainer ended without completing {missing}; see {folder / LOG}")


async def _stop(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), STOP_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()
