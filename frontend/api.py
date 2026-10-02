"""The read-only JSON view of a runs root: run lists, worlds, events, agent history, scores.

Nothing here writes: events and config are plain reads, and agent repositories are read
through git commands that touch neither the index nor the work tree.
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from core.agent.evolution import History
from infrastructure.git import Repository
from infrastructure.storage import RunDirectory

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SEED = re.compile(r"seed-\d+")
_COMMIT = re.compile(r"[0-9a-f]{4,40}")
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


class NotFound(LookupError):
    """The named run, agent, commit or file does not exist (or is not a valid name)."""


class Api:
    """JSON-ready answers about the runs under `runs_root`."""

    def __init__(self, runs_root: Path) -> None:
        self.runs_root = runs_root.resolve()

    def runs(self) -> list[dict[str, Any]]:
        """Every run with a manifest, with its manifest fields and day progress."""
        listing = []
        for manifest in sorted(self.runs_root.glob("*/seed-*/manifest.json")):
            if not (
                _NAME.fullmatch(manifest.parent.parent.name)
                and _SEED.fullmatch(manifest.parent.name)
            ):
                continue
            run = RunDirectory(manifest.parent)
            checkpoint = run.latest_checkpoint()
            listing.append(
                {
                    "experiment": run.root.parent.name,
                    "directory": run.root.name,
                    **run.read_manifest().model_dump(mode="json"),
                    "days": _config(run)["simulation"]["days"],
                    "days_done": int(checkpoint.stem.removeprefix("day-")) if checkpoint else 0,
                }
            )
        return listing

    def world(self, experiment: str, seed: str) -> dict[str, Any]:
        """Places, agent profiles, calendar and starting conditions from the frozen config."""
        run = self._run(experiment, seed)
        config = _config(run)
        environment = config["environment"]
        return {
            "manifest": run.read_manifest().model_dump(mode="json"),
            "places": environment["places"],
            "agents": [agent["profile"] for agent in config["agents"]],
            "calendar": config["simulation"]["calendar"],
            "days": config["simulation"]["days"],
            "conditions": environment["conditions"],
            "initial_balance": environment["initial_balance"],
        }

    def events(self, experiment: str, seed: str, after: int = -1) -> dict[str, Any]:
        """Events with `seq` greater than `after`, the run status and the last `seq` seen.

        A final line still being appended is left for the next call.
        """
        run = self._run(experiment, seed)
        chunk = run.events_path.read_bytes() if run.events_path.exists() else b""
        lines = chunk.split(b"\n")[:-1]
        events = [event for event in map(json.loads, lines) if event["seq"] > after]
        return {
            "status": run.read_manifest().status.value,
            "events": events,
            "last": events[-1]["seq"] if events else after,
        }

    def history(self, experiment: str, seed: str, agent: str) -> list[dict[str, Any]]:
        """The agent's versions, oldest first."""
        history = History(self._agent_dir(self._run(experiment, seed), agent))
        return [
            {
                "commit": version.commit,
                "time": version.time,
                "level": version.level,
                "trigger": version.trigger,
                "subject": version.subject,
                "body": version.body,
            }
            for version in reversed(history.log())
        ]

    def diff(self, experiment: str, seed: str, agent: str, commit: str) -> dict[str, str]:
        """The unified diff a commit made against its parent."""
        repository = self._repository(experiment, seed, agent)
        found = self._commit(repository, commit)
        return {"commit": found.id, "diff": repository.diff(found.parent or _EMPTY_TREE, found.id)}

    def files(self, experiment: str, seed: str, agent: str, commit: str) -> dict[str, Any]:
        """Policy, skills, insights and latest diary of the agent as of `commit`."""
        repository = self._repository(experiment, seed, agent)
        found = self._commit(repository, commit)
        names = _tree(repository, found.id)

        def read(name: str) -> str:
            return repository.read_file(found.id, name)

        insights = "memory/insights.jsonl"
        diaries = sorted(name for name in names if re.fullmatch(r"memory/diary/[^/]+\.md", name))
        return {
            "commit": found.id,
            "policy": read("parameters/policy.md") if "parameters/policy.md" in names else "",
            "skills": {
                Path(name).stem: read(name)
                for name in sorted(names)
                if re.fullmatch(r"memory/skills/[^/]+\.md", name)
            },
            "insights": (
                [json.loads(line) for line in read(insights).splitlines() if line.strip()]
                if insights in names
                else []
            ),
            "diary": {"name": Path(diaries[-1]).stem, "text": read(diaries[-1])}
            if diaries
            else None,
        }

    def evaluation(self, experiment: str, seed: str) -> list[dict[str, Any]]:
        """Every evaluation result file as `label`, `agent` and its parsed content."""
        run = self._run(experiment, seed)
        return [
            {
                "label": path.parent.name,
                "agent": path.stem,
                "result": json.loads(path.read_text("utf-8")),
            }
            for path in sorted(run.evaluation_dir.glob("*/*.json"))
        ]

    def _run(self, experiment: str, seed: str) -> RunDirectory:
        if not (_NAME.fullmatch(experiment) and _SEED.fullmatch(seed)):
            raise NotFound(f"no run {experiment}/{seed}")
        root = (self.runs_root / experiment / seed).resolve()
        if root.parent.parent != self.runs_root or not (root / "manifest.json").is_file():
            raise NotFound(f"no run {experiment}/{seed}")
        return RunDirectory(root)

    @staticmethod
    def _agent_dir(run: RunDirectory, agent: str) -> Path:
        known = [path.name for path in run.agents_dir.iterdir() if (path / ".git").exists()]
        if agent not in known:
            raise NotFound(
                f"no agent {agent!r} in this run; known agents: {', '.join(sorted(known))}"
            )
        return run.agent_dir(agent)

    def _repository(self, experiment: str, seed: str, agent: str) -> Repository:
        return Repository(self._agent_dir(self._run(experiment, seed), agent))

    @staticmethod
    def _commit(repository: Repository, commit: str):
        if not _COMMIT.fullmatch(commit):
            raise NotFound(f"no commit {commit!r}")
        matches = [found for found in repository.log() if found.id.startswith(commit)]
        if len(matches) != 1:
            raise NotFound(f"no commit {commit!r}")
        return matches[0]


def _config(run: RunDirectory) -> dict[str, Any]:
    return yaml.safe_load(run.config_path.read_text(encoding="utf-8"))


def _tree(repository: Repository, commit: str) -> set[str]:
    """Paths of every file in `commit`."""
    result = subprocess.run(
        [
            "git",
            f"--git-dir={repository.path / '.git'}",
            "ls-tree",
            "-r",
            "--name-only",
            "-z",
            commit,
        ],
        capture_output=True,
        check=True,
    )
    return set(result.stdout.decode().split("\0")) - {""}
