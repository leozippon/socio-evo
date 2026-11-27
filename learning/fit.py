"""Fitting a night's adapters: a trainer process on each GPU with room, the jobs shared among them.

The trainer is `learning.train`, run as `<trainer.python> -m learning.train --jobs jobs-<gpu>.json`
from the repository's root with `CUDA_VISIBLE_DEVICES` set to that one GPU. The jobs file names the
base model, the LoRA settings and one job for each adapter: its name, its dataset and the directory
it is to be written to. The trainer fits each from the base afresh, writes a PEFT adapter directory
with `training.json` into it, and exits non-zero on any failure. An adapter is complete once its
`training.json` is there (`adapters.TRAINING`); a directory without it is what a fit broken off
left, and is cleared before the adapter is fitted again.

The GPUs are the first `trainer.gpus_at_once` of `trainer.gpus`, in the order listed, that have
`trainer.free_gib` free when the fit begins, as nvidia-smi reports them (`free_memory`); while
none of those listed has, the fit looks again every minute, for up to `trainer.patience_minutes`,
and then raises `TrainerError`. The jobs are divided among the GPUs by `divide`, and the trainers
run until each has ended. On a machine others share, one of them may start a job on a GPU while a
trainer is fitting there and leave it too little memory, so a trainer that dies does not stop the
others: once all have ended, the jobs left without a complete adapter are fitted again in another
start, the GPUs found and the jobs divided anew, until a job has been left unfinished by
`ATTEMPTS` trainers, when the fit raises `TrainerError` naming it and its last trainer's output. A
fault of the job itself, as a malformed dataset or a missing base, thus fails as many times and
stops the night. Since a job's adapter depends only on the base, its dataset and the settings,
which GPU fits it, beside which others and in which start, changes nothing.

Start NN writes `jobs-NN-gpu<G>.json` for the trainer on GPU G and appends its output to
`trainer-NN-gpu<G>.log`; once its trainers have ended it appends a line to `fits.jsonl`: its number,
how long it waited, each listed GPU's free memory, why each GPU not used was passed over (`no room`,
or `not needed`, enough GPUs before it having room or no job being left for it), and for each
trainer its jobs, its exit status and the jobs it left unfinished. A start broken off, as when the
run is stopped, writes no line, and the next takes its number. A fit that is cancelled stops its
trainers.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from agent.session import estimate
from infrastructure.storage import append_jsonl, read_jsonl, write_json
from learning.adapters import TRAINING
from learning.config import LoraConfig, TrainerConfig

log = logging.getLogger("learning")

ROOT = Path(__file__).resolve().parents[1]
"""The repository's root, from which `learning.train` is run."""
FITS = "fits.jsonl"
STOP_SECONDS = 30
"""How long a trainer told to stop is given before it is killed."""
POLL_SECONDS = 60
"""How long a fit waiting for a GPU with room waits between looks."""
ATTEMPTS = 3
"""How many trainers may leave a job unfinished before the fit fails."""
STEP_COST = 350
"""What a step of a fit costs beside its own tokens, in tokens' worth: a step of 400 tokens takes
1.64 s and one of 800 tokens 2.52 s (ops/train/README.md, Memory and time)."""


class TrainerError(RuntimeError):
    """No GPU had room for the trainer, or a job was not fitted in `ATTEMPTS` trainers."""


@dataclass(frozen=True)
class Job:
    """Fit adapter `name` on the dataset `dataset` into the directory `out`."""

    name: str
    dataset: Path
    out: Path


async def fit(
    jobs: Sequence[Job], *, trainer: TrainerConfig, lora: LoraConfig, folder: Path
) -> None:
    """Fit every adapter of `jobs` on the first GPUs of `trainer` that have room, their jobs
    files, output and starts in `folder`, fitting again those a trainer left unfinished."""
    failures = dict.fromkeys((job.name for job in jobs), 0)
    last: dict[str, str] = {}
    left = list(jobs)
    while left:
        start = len(list(read_jsonl(folder / FITS))) + 1 if (folder / FITS).is_file() else 1
        for job in left:
            if job.out.exists():
                shutil.rmtree(job.out)
            job.out.parent.mkdir(parents=True, exist_ok=True)
        gpus, waited, free = await _gpus(trainer)
        shares = divide(left, gpus)
        passed_over = {
            gpu: "no room" if gib < trainer.free_gib else "not needed"
            for gpu, gib in free.items()
            if gpu not in shares
        }
        log.info(
            "fitting, start %d: %s%s",
            start,
            "; ".join(f"on GPU {gpu} {', '.join(j.name for j in s)}" for gpu, s in shares.items()),
            "".join(
                f"; GPU {gpu} passed over, {why}, {free[gpu]} GiB free"
                for gpu, why in passed_over.items()
            ),
        )
        outputs = {gpu: folder / f"trainer-{start:02d}-gpu{gpu}.log" for gpu in shares}
        tasks = {
            gpu: asyncio.create_task(
                _train(
                    gpu,
                    share,
                    spec=folder / f"jobs-{start:02d}-gpu{gpu}.json",
                    output=outputs[gpu],
                    trainer=trainer,
                    lora=lora,
                )
            )
            for gpu, share in shares.items()
        }
        try:
            await asyncio.gather(*tasks.values())
        finally:
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
        trainers = {}
        for gpu, share in shares.items():
            code = tasks[gpu].result()
            unfinished = [job.name for job in share if not (job.out / TRAINING).is_file()]
            trainers[gpu] = {
                "jobs": [j.name for j in share],
                "exit": code,
                "unfinished": unfinished,
            }
            for name in unfinished:
                failures[name] += 1
                last[name] = f"the trainer on GPU {gpu} exited with {code}; see {outputs[gpu]}"
            if unfinished:
                log.warning(
                    "start %d: the trainer on GPU %s exited with %d, leaving %s unfinished; see %s",
                    start,
                    gpu,
                    code,
                    ", ".join(unfinished),
                    outputs[gpu],
                )
        append_jsonl(
            folder / FITS,
            {
                "start": start,
                "waited_seconds": round(waited, 1),
                "free_gib": free,
                "passed_over": passed_over,
                "trainers": trainers,
            },
        )
        left = [job for job in left if not (job.out / TRAINING).is_file()]
        failed = [job.name for job in left if failures[job.name] >= ATTEMPTS]
        if failed:
            raise TrainerError(
                "; ".join(
                    f"{name} was not fitted by {ATTEMPTS} trainers: {last[name]}" for name in failed
                )
            )


def divide(jobs: Sequence[Job], gpus: Sequence[str]) -> dict[str, list[Job]]:
    """`jobs` divided among `gpus`, each GPU's work as even as the greedy rule makes it: the jobs,
    the most work first and alike by name, each to the GPU with the least work so far, the first
    in `gpus` of those alike. A job's work is the estimated tokens of its conversations and
    `STEP_COST` for each. Each GPU's jobs keep their order in `jobs`, and a GPU given none is left
    out."""
    work = {
        job.name: sum(
            STEP_COST + estimate(line)
            for line in job.dataset.read_text(encoding="utf-8").splitlines()
        )
        for job in jobs
    }
    load = dict.fromkeys(gpus, 0)
    placed: dict[str, str] = {}
    for job in sorted(jobs, key=lambda j: (-work[j.name], j.name)):
        gpu = min(gpus, key=load.__getitem__)
        load[gpu] += work[job.name]
        placed[job.name] = gpu
    shares = {gpu: [job for job in jobs if placed[job.name] == gpu] for gpu in gpus}
    return {gpu: share for gpu, share in shares.items() if share}


def free_memory() -> dict[str, float]:
    """Every GPU's free memory in GiB, by its index, as nvidia-smi reports it."""
    listed = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout
    free = {}
    for line in listed.splitlines():
        index, used, total = (field.strip() for field in line.split(","))
        free[index] = (int(total) - int(used)) / 1024
    return free


async def _gpus(trainer: TrainerConfig) -> tuple[list[str], float, dict[str, float]]:
    """The first `gpus_at_once` GPUs of `trainer` that have room, once one has; how long that
    took, in seconds; and the free memory of every one listed then, in GiB."""
    gpus = [str(gpu) for gpu in trainer.gpus]
    started = time.monotonic()
    for look in range(trainer.patience_minutes + 1):
        if look:
            await asyncio.sleep(POLL_SECONDS)
        listed = free_memory()
        unknown = [gpu for gpu in gpus if gpu not in listed]
        if unknown:
            raise TrainerError(f"nvidia-smi lists no GPU {', '.join(unknown)} of {', '.join(gpus)}")
        free = {gpu: round(listed[gpu], 2) for gpu in gpus}
        room = [gpu for gpu in gpus if listed[gpu] >= trainer.free_gib][: trainer.gpus_at_once]
        if room:
            if look:
                log.info("GPU %s has room for a fit after %d minutes", ", ".join(room), look)
            return room, time.monotonic() - started, free
        if not look:
            log.info(
                "no GPU of %s has the %s GiB a fit needs free (%s); looking again every minute "
                "for up to %d minutes",
                ", ".join(gpus),
                trainer.free_gib,
                _free(free),
                trainer.patience_minutes,
            )
    raise TrainerError(
        f"no GPU of {', '.join(gpus)} had the {trainer.free_gib} GiB a fit needs free in "
        f"{trainer.patience_minutes} minutes ({_free(free)})"
    )


async def _train(
    gpu: str,
    jobs: Sequence[Job],
    *,
    spec: Path,
    output: Path,
    trainer: TrainerConfig,
    lora: LoraConfig,
) -> int:
    """The exit status of one trainer process fitting `jobs` on GPU `gpu`, its jobs file
    `spec` and its output appended to `output`."""
    write_json(
        spec,
        {
            "base": trainer.base,
            "lora": lora.model_dump(mode="json"),
            "jobs": [
                {"name": j.name, "dataset": str(j.dataset.resolve()), "out": str(j.out.resolve())}
                for j in jobs
            ],
        },
    )
    with output.open("ab") as out:
        process = await asyncio.create_subprocess_exec(
            str(trainer.executable),
            "-m",
            "learning.train",
            "--jobs",
            str(spec.resolve()),
            cwd=ROOT,
            # nvidia-smi numbers the GPUs by their PCI bus, CUDA by default by its guess of their
            # speed; the GPU found to have room is to be the GPU the trainer is given.
            env={**os.environ, "CUDA_DEVICE_ORDER": "PCI_BUS_ID", "CUDA_VISIBLE_DEVICES": gpu},
            stdout=out,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            return await process.wait()
        except asyncio.CancelledError:
            await _stop(process)
            raise


async def _stop(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), STOP_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()


def _free(free: Mapping[str, float]) -> str:
    return ", ".join(f"GPU {gpu} {gib} GiB" for gpu, gib in free.items())
