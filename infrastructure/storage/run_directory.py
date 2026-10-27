"""The on-disk layout of a run; the single source of every path inside it.

runs/<experiment>/
├── manifest.json               status, code revision, start and end, the running process
├── config.yaml                 the frozen configuration
├── world.jsonl                 the world log
├── checkpoints/day-NN.json     the world at each daily checkpoint; day-00 before day 1
├── agents/<name>/              agent directories, git repositories tagged day-NN
└── run.log                     the process log
"""

import os
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import AwareDatetime, BaseModel

from infrastructure.config import StrictModel


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    """Stopped before its last day without an error, on request or by a signal."""


class Manifest(StrictModel):
    """Run bookkeeping; times are wall-clock UTC; `code_revision` is the code the run was
    created with; `pid` is the id of the process running the run, None when none is (and in a
    manifest written before it was recorded)."""

    status: RunStatus
    code_revision: str
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    pid: int | None = None


def day_tag(day: int) -> str:
    """The name of day `day` in a run: its checkpoint file's stem and its agent directories'
    git tag (`day-00` is the state before the first day)."""
    return f"day-{day:02d}"


class RunDirectory:
    """Paths and manifest of the run at `root`, `runs/<experiment>/`.

    Obtain one through `create` (a new run) or `open` (an existing run); resuming is explicit.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def create(
        cls, runs_root: Path, experiment: str, *, config: BaseModel, code_revision: str
    ) -> "RunDirectory":
        """Create the run directory, freeze `config` into it and start a running manifest.

        Raises FileExistsError if the run directory already exists.
        """
        run = cls(runs_root / experiment)
        run.root.mkdir(parents=True)
        for directory in (run.checkpoints_dir, run.agents_dir):
            directory.mkdir()
        run.config_path.write_text(
            yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        run._write_manifest(
            Manifest(
                status=RunStatus.RUNNING,
                code_revision=code_revision,
                started_at=datetime.now(UTC),
            )
        )
        return run

    @classmethod
    def open(cls, root: Path) -> "RunDirectory":
        """Open an existing run; raises FileNotFoundError if `root` holds no manifest."""
        run = cls(root)
        run.read_manifest()
        return run

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @property
    def config_path(self) -> Path:
        return self.root / "config.yaml"

    @property
    def world_log_path(self) -> Path:
        return self.root / "world.jsonl"

    @property
    def run_log_path(self) -> Path:
        return self.root / "run.log"

    @property
    def checkpoints_dir(self) -> Path:
        return self.root / "checkpoints"

    @property
    def agents_dir(self) -> Path:
        return self.root / "agents"

    def checkpoint_path(self, day: int) -> Path:
        return self.checkpoints_dir / f"{day_tag(day)}.json"

    def latest_checkpoint(self) -> int | None:
        """The highest day with a checkpoint, or None if there is none."""
        return max(
            (
                int(path.stem.removeprefix("day-"))
                for path in self.checkpoints_dir.glob("day-*.json")
            ),
            default=None,
        )

    def agent_dir(self, name: str) -> Path:
        return self.agents_dir / name

    def read_manifest(self) -> Manifest:
        return Manifest.model_validate_json(self.manifest_path.read_text(encoding="utf-8"))

    def update_manifest(self, **changes: Any) -> Manifest:
        """Validate the manifest with `changes` applied, write it atomically and return it."""
        manifest = Manifest.model_validate({**self.read_manifest().model_dump(), **changes})
        self._write_manifest(manifest)
        return manifest

    def _write_manifest(self, manifest: Manifest) -> None:
        staging = self.manifest_path.with_suffix(".json.tmp")
        staging.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
        os.replace(staging, self.manifest_path)
