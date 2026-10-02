"""The on-disk layout of a run; the single source of every path inside it."""

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


class Manifest(StrictModel):
    """Run bookkeeping; times are wall-clock UTC."""

    seed: int
    status: RunStatus
    code_revision: str
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None


class RunDirectory:
    """Paths and manifest of one run at `runs/<experiment>/seed-<NNNN>/`.

    Obtain one through `create` (a new run) or `open` (an existing run); resuming is explicit.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def create(
        cls,
        runs_root: Path,
        experiment: str,
        seed: int,
        *,
        config: BaseModel,
        code_revision: str,
    ) -> "RunDirectory":
        """Create the run directory, freeze `config` into it and start a running manifest.

        Raises FileExistsError if the run directory already exists.
        """
        run = cls(runs_root / experiment / f"seed-{seed:04d}")
        run.root.mkdir(parents=True)
        for directory in (run.checkpoints_dir, run.agents_dir, run.evaluation_dir):
            directory.mkdir()
        run.config_path.write_text(
            yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        run._write_manifest(
            Manifest(
                seed=seed,
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
    def events_path(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def llm_calls_path(self) -> Path:
        return self.root / "llm_calls.jsonl"

    @property
    def checkpoints_dir(self) -> Path:
        return self.root / "checkpoints"

    @property
    def agents_dir(self) -> Path:
        return self.root / "agents"

    @property
    def evaluation_dir(self) -> Path:
        return self.root / "evaluation"

    def checkpoint_path(self, day: int) -> Path:
        return self.checkpoints_dir / f"day-{day:04d}.json"

    def latest_checkpoint(self) -> Path | None:
        """The checkpoint with the highest day number, or None if there is none."""
        return max(
            self.checkpoints_dir.glob("day-*.json"),
            key=lambda path: int(path.stem.removeprefix("day-")),
            default=None,
        )

    def agent_dir(self, agent_id: str) -> Path:
        return self.agents_dir / agent_id

    def evaluation_path(self, label: str, agent_id: str) -> Path:
        return self.evaluation_dir / label / f"{agent_id}.json"

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
