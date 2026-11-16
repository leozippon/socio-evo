"""Fork a stopped laboratory at its latest complete checkpoint and enable model tools.

The source is never changed. Its unfinished day remains solely in the source run; the new
branch keeps the checkpoint's agent tags, research commit and world-log prefix. Mutable
dependency caches are copied as they stand, explicitly outside checkpoint rollback semantics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import yaml

from experiments.config import load_experiment
from infrastructure.git import Repository
from infrastructure.storage import RunDirectory, RunStatus, day_tag
from ops.research.run_pair import configuration, remote_root


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clone_revision(source: Path, target: Path, revision: str, name: str) -> Repository:
    # Fetch the selected ancestry only: no source hardlinks, partial-day refs or untracked files.
    repository = Repository.init(target, user_name=name, user_email=f"{name.lower()}@town.invalid")
    repository._git("fetch", "--quiet", "--no-tags", str(source), revision)
    repository.reset_hard("FETCH_HEAD")
    if repository.head() != revision:
        raise ValueError("The copied repository did not resolve to the selected checkpoint.")
    return repository


def _world_boundary(path: Path, day: int, timestamp: int) -> tuple[int, dict]:
    boundary, checkpoint = None, None
    with path.open("rb") as stream:
        while line := stream.readline():
            event = json.loads(line)
            if (
                event.get("kind") == "checkpoint"
                and event.get("payload", {}).get("day") == day
                and event.get("sim_time") == timestamp
            ):
                boundary, checkpoint = stream.tell(), event
    if boundary is None:
        raise ValueError("No world-log checkpoint event matches the complete checkpoint.")
    return boundary, checkpoint


def fork_models(
    source_run: Path, runs_root: Path, *, name: str, inference_python: str,
    code_revision: str, launch_config: Path,
) -> Path:
    source = RunDirectory.open(source_run.resolve())
    original_manifest = source.read_manifest()
    if original_manifest.status == RunStatus.RUNNING:
        raise ValueError("Stop the source experiment gracefully before forking.")
    if original_manifest.pid:
        try:
            os.kill(original_manifest.pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise ValueError("The source manifest still identifies a live process.")
    previous = load_experiment(source.config_path)
    if previous.town.research is None or not previous.town.research.pit:
        raise ValueError("This migration is only for the existing PIT research laboratory.")
    day = source.latest_checkpoint()
    if day is None or day < 1:
        raise ValueError("The source has no complete lived-day checkpoint to fork.")
    if name.endswith(f"-seed-{previous.town.seed}"):
        raise ValueError("Supply the base launch name without its -seed suffix.")
    checkpoint_path = source.checkpoint_path(day)
    checkpoint = json.loads(checkpoint_path.read_text())
    boundary, event = _world_boundary(source.world_log_path, day, checkpoint["time"])
    research_revision = checkpoint["research"]
    Repository(source.root / "research")._git("cat-file", "-e", research_revision + "^{commit}")
    tags = {}
    for resident in previous.residents:
        repository = Repository(source.agent_dir(resident.name))
        tags[resident.name] = repository._git(
            "rev-parse", day_tag(day) + "^{commit}"
        ).strip()
    data = previous.model_dump(mode="json")
    data["name"] = name
    data["town"]["research"].update(models_enabled=True, inference_python=inference_python)
    profile = type(previous).model_validate(data)
    new_config = profile.model_copy(update={"name": f"{name}-seed-{profile.town.seed}"})
    destination = runs_root.resolve() / new_config.name
    if destination.exists() or launch_config.exists():
        raise FileExistsError("The fork run or launch profile already exists.")
    if destination.is_relative_to(source.root) or source.root.is_relative_to(destination):
        raise ValueError("The fork and source run directories must be separate.")
    runs_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fork-models-", dir=runs_root) as temporary:
        fork = RunDirectory.create(
            Path(temporary), new_config.name, config=new_config, code_revision=code_revision
        )
        for resident in previous.residents:
            repo = _clone_revision(
                source.agent_dir(resident.name), fork.agent_dir(resident.name),
                tags[resident.name], resident.name,
            )
            old_repo = Repository(source.agent_dir(resident.name))
            for tag in old_repo._git("tag", "--list", "day-*").splitlines():
                if int(tag.removeprefix("day-")) <= day:
                    revision = old_repo._git("rev-parse", tag + "^{commit}").strip()
                    repo._git("merge-base", "--is-ancestor", revision, repo.head())
                    repo.tag(tag, revision)
        _clone_revision(source.root / "research", fork.root / "research",
                        research_revision, "Research")
        for path in source.checkpoints_dir.glob("day-*.json"):
            if int(path.stem.removeprefix("day-")) <= day:
                shutil.copy2(path, fork.checkpoints_dir / path.name)
        with source.world_log_path.open("rb") as original, fork.world_log_path.open("wb") as output:
            remaining = boundary
            while remaining:
                chunk = original.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("Source world log changed during fork.")
                output.write(chunk)
                remaining -= len(chunk)
        caches = []
        for name in ("research_runtime", "pit_cache", "model_cache", "conference_reviews"):
            path = source.root / name
            if path.exists():
                shutil.copytree(path, fork.root / name)
                caches.append(name)
        lineage = {
            "created_at": datetime.now(UTC).isoformat(), "source_run": str(source.root),
            "source_code_revision": original_manifest.code_revision,
            "source_config_sha256": _sha(source.config_path),
            "fork_code_revision": code_revision, "fork_config_sha256": _sha(fork.config_path),
            "checkpoint_day": day, "checkpoint_sha256": _sha(checkpoint_path),
            "checkpoint_sim_time": checkpoint["time"], "world_last_seq": event["seq"],
            "research_revision": research_revision, "agent_revisions": tags,
            "source_partial_day_retained_at": str(source.root),
            "copied_cache_directories": caches,
            "cache_semantics": "Current dependency/content caches; not checkpoint-versioned. "
                               "Source timestamps and frozen evidence remain separately enforced.",
            "configuration_changes": ["name", "town.research.models_enabled",
                                      "town.research.inference_python"],
        }
        (fork.root / "lineage.json").write_text(json.dumps(lineage, indent=2) + "\n")
        fork.update_manifest(status=RunStatus.INTERRUPTED, ended_at=datetime.now(UTC), pid=None)
        if source.read_manifest() != original_manifest or _sha(checkpoint_path) != lineage[
            "checkpoint_sha256"
        ]:
            raise ValueError("Source experiment changed during the fork; no branch published.")
        launch_config.parent.mkdir(parents=True, exist_ok=True)
        launch_config.write_text(yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False))
        resolved = configuration(launch_config, profile.town.seed, profile.town.research.gpus)
        if resolved != new_config:
            raise ValueError("The launch profile does not reproduce the fork's frozen config.")
        fork.root.rename(destination)
    return destination


def main(argv=None) -> int:
    from simulation.run import code_revision

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--launch-config", type=Path, required=True)
    parser.add_argument("--name", default="ir-lab-models")
    parser.add_argument("--inference-python", required=True)
    args = parser.parse_args(argv)
    result = fork_models(
        remote_root(args.source_run), remote_root(args.runs_root), name=args.name,
        inference_python=args.inference_python, code_revision=code_revision(),
        launch_config=remote_root(args.launch_config),
    )
    print(json.dumps({"fork": str(result), "launch_profile": str(args.launch_config),
                      "status": "prepared; use run_lab --resume with this launch profile"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
