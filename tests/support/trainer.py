"""A trainer that honours the jobs contract of `learning.train` without a GPU or a model.

Run as `<python> -m learning.train --jobs JOBS.json` through the interpreter `fake_trainer`
writes, it reads the jobs, and for each writes an adapter directory (`adapter_config.json`, empty
weights and `training.json`) to the job's `out`, which must not exist; `training.json` records,
as the real trainer's does, the job's name, the base, the dataset with its SHA-256 and the
settings, the number of examples, the steps with the loss of each, one step an example an epoch,
the loss falling, and the seconds the job took. It appends what it was asked, with
`CUDA_VISIBLE_DEVICES` and its process id, to the file named by `FAKE_TRAINER_RECORD` if that is
set. These make it behave as the tests need:

- `FAKE_TRAINER_FAIL=<job>`: on coming to that job it says it is out of memory and exits with
  status 3, as a trainer does that fails part of the way through;
- `FAKE_TRAINER_TOGETHER=<n>:<dir>`: the trainers meet in `<dir>`: each waits to begin until `n`
  have begun, and fails with status 4 if they do not within 30 s, so that trainers run one after
  another fail; one that fails, as above, first waits until the `n - 1` others have done their
  jobs;
- `FAKE_TRAINER_HANG`: a trainer that has done its jobs waits to be stopped instead of exiting;
- `FAKE_TRAINER_SECONDS=<s>`: it takes that long before its first job, as a real fit takes time.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import time
from pathlib import Path

MEET_SECONDS = 30


def fake_trainer(folder: Path) -> Path:
    """An executable in `folder` that stands for the training environment's interpreter."""
    path = folder / "trainer-python"
    path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{Path(__file__).resolve()}" "$@"\n')
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def main(argv: list[str]) -> int:
    if argv[:3] != ["-m", "learning.train", "--jobs"] or len(argv) != 4:
        print(f"unexpected arguments {argv}", file=sys.stderr)
        return 2
    spec = json.loads(Path(argv[3]).read_text(encoding="utf-8"))
    gpu = os.environ.get("CUDA_VISIBLE_DEVICES")
    if record := os.environ.get("FAKE_TRAINER_RECORD"):
        with open(record, "a", encoding="utf-8") as file:
            file.write(json.dumps({"spec": spec, "cuda": gpu, "pid": os.getpid()}) + "\n")
    together = os.environ.get("FAKE_TRAINER_TOGETHER")
    if together:
        count, meeting = together.split(":", 1)
        (Path(meeting) / f"{gpu}.begun").touch()
        if not _meet(Path(meeting), "begun", int(count)):
            print(f"the trainer on GPU {gpu} began alone", file=sys.stderr)
            return 4
    time.sleep(float(os.environ.get("FAKE_TRAINER_SECONDS", "0")))
    for job in spec["jobs"]:
        if job["name"] == os.environ.get("FAKE_TRAINER_FAIL"):
            if together:
                _meet(Path(meeting), "done", int(count) - 1)
            print(f"{job['name']}: out of memory", file=sys.stderr)
            return 3
        started = time.monotonic()
        out, dataset = Path(job["out"]), Path(job["dataset"])
        examples = dataset.read_text(encoding="utf-8").splitlines()
        out.mkdir(parents=False)
        (out / "adapter_config.json").write_text(json.dumps({"r": spec["lora"]["rank"]}))
        (out / "adapter_model.safetensors").write_bytes(b"")
        steps = len(examples) * spec["lora"]["epochs"]
        record = {
            "name": job["name"],
            "base": spec["base"],
            "dataset": str(dataset),
            "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
            "lora": spec["lora"],
            "examples": len(examples),
            "steps": steps,
            "loss": [round(2.0 / (1 + step / 2), 4) for step in range(steps)],
            "wall_seconds": round(time.monotonic() - started, 3),
        }
        (out / "training.json").write_text(json.dumps(record))
        print(f"{job['name']}: fitted on {len(examples)} examples")
    if together:
        (Path(meeting) / f"{gpu}.done").touch()
    if os.environ.get("FAKE_TRAINER_HANG"):
        time.sleep(600)
    return 0


def _meet(meeting: Path, what: str, count: int) -> bool:
    """Whether `count` trainers are `what` in `meeting` within `MEET_SECONDS`."""
    deadline = time.monotonic() + MEET_SECONDS
    while len(list(meeting.glob(f"*.{what}"))) < count:
        if time.monotonic() > deadline:
            return False
        time.sleep(0.02)
    return True


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
