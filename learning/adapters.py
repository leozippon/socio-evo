"""Where each resident's adapters are, and which one it runs on.

The adapter fitted for a resident on night N is the directory `learning/adapters/<name>/night-NN/`
of the run, complete once the trainer has written `training.json` into it. It is the resident's
from the morning after, once night N is complete (`learning/night-NN/done.json`), until a later
night fits it another; a resident no night has fitted runs on the base model. On the model server
an adapter is named for the run, the resident and the night (the trainer's job, `job_name`), and
for what it was fitted from: a digest of the base, the dataset and the settings `training.json`
records. A run made again under the same name, while the server keeps the adapters it loaded
before, thus has adapters of names of their own, unless it fitted them from the same.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from infrastructure.storage import RunDirectory, night_tag

TRAINING = "training.json"
"""What the trainer writes into an adapter's directory, last: the adapter is complete."""
DONE = "done.json"
"""What a night writes into its directory, last: the night is complete."""
DIGEST = 8
"""The hexadecimal digits of the digest in a served name."""


@dataclass(frozen=True)
class Adapter:
    """An adapter: its name on the model server and its directory."""

    name: str
    path: Path


def adapter_for(run_dir: Path, name: str, day: int) -> Path | None:
    """The directory of the adapter resident `name` of the run at `run_dir` ran on after day `day`:
    the latest fitted for it on a complete night at or before that day; None for the base model."""
    adapter = current(run_dir, name, day)
    return None if adapter is None else adapter.path


def current(run_dir: Path, name: str, day: int) -> Adapter | None:
    """The adapter resident `name` runs on after day `day`, as `adapter_for` finds it."""
    run = RunDirectory(run_dir)
    for night in range(day, 0, -1):
        adapter = fitted(run_dir, name, night)
        if adapter is not None and (run.night_dir(night) / DONE).is_file():
            return adapter
    return None


def fitted(run_dir: Path, name: str, night: int) -> Adapter | None:
    """The adapter fitted for resident `name` on night `night`, if it is complete. A
    `training.json` without the base, the dataset's digest or the settings raises KeyError."""
    path = RunDirectory(run_dir).adapter_dir(name, night)
    if not (path / TRAINING).is_file():
        return None
    record = json.loads((path / TRAINING).read_text(encoding="utf-8"))
    fitted_from = [record["base"], record["dataset_sha256"], record["lora"]]
    digest = hashlib.sha256(json.dumps(fitted_from, sort_keys=True).encode()).hexdigest()
    return Adapter(f"{job_name(run_dir, name, night)}-{digest[:DIGEST]}", path.resolve())


def job_name(run_dir: Path, name: str, night: int) -> str:
    """The name of the trainer's job that fits resident `name`'s adapter on night `night` of the
    run at `run_dir`, which its name on the model server begins with."""
    return f"{run_dir.resolve().name}-{name}-{night_tag(night)}"
