"""A trainer that honours the jobs contract of `learning.train` without a GPU or a model.

Run as `<python> -m learning.train --jobs JOBS.json` through the interpreter `fake_trainer`
writes, it reads the jobs, and for each writes an adapter directory (`adapter_config.json`, empty
weights and `training.json`) to the job's `out`, which must not exist; `training.json` records,
as the real trainer's does, the job's name, the base, the dataset with its SHA-256 and the
settings, the number of examples, and the steps with the loss of each, one step an example an
epoch, the loss falling. It appends what it was asked, with
`CUDA_VISIBLE_DEVICES`, to the file named by `FAKE_TRAINER_RECORD` if that is set; with
`FAKE_TRAINER_FAIL` set it fits the first job only and exits with status 3, as a trainer does that
fails part of the way through.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path


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
    if record := os.environ.get("FAKE_TRAINER_RECORD"):
        with open(record, "a", encoding="utf-8") as file:
            asked = {"spec": spec, "cuda": os.environ.get("CUDA_VISIBLE_DEVICES")}
            file.write(json.dumps(asked) + "\n")
    for number, job in enumerate(spec["jobs"]):
        if number == 1 and os.environ.get("FAKE_TRAINER_FAIL"):
            print(f"{job['name']}: out of memory", file=sys.stderr)
            return 3
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
        }
        (out / "training.json").write_text(json.dumps(record))
        print(f"{job['name']}: fitted on {len(examples)} examples")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
