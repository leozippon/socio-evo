"""A work backend for tests and dry runs: tasks whose repositories are dictionaries of files.

A workspace's diff is its changed files as JSON; a patch is accepted when a changed file contains
FIX, unless verdicts are queued. Nothing runs in a container.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from world.board import KEPT_CHANGES


@dataclass(frozen=True)
class FakeTask:
    instance_id: str
    repo: str
    problem_statement: str


@dataclass(frozen=True)
class FakeExec:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass(frozen=True)
class FakeVerdict:
    status: str
    fail_to_pass: tuple[int, int]
    pass_to_pass: tuple[int, int]
    log_tail: str = "FAILED tests/test_secret.py::test_hidden_name"

    @property
    def resolved(self) -> bool:
        return self.status == "resolved"


class FakeWorkspace:
    """A repository as a dictionary of files; its diff is the changed files as JSON."""

    def __init__(self, task: FakeTask, name: str) -> None:
        self.task, self.name = task, name
        self.files = {"README": "read me\n"}
        self.changed: dict[str, str] = {}
        self.scratch: dict[str, str] = {}
        self.commands: list[str] = []
        self.closed = False

    async def exec(self, cmd: str, timeout_s: int) -> FakeExec:
        assert not self.closed
        self.commands.append(cmd)
        if cmd.startswith("git apply"):
            self.changed.update(json.loads(self.scratch.pop(KEPT_CHANGES)))
            return FakeExec(0, "", "")
        if cmd == "false":
            return FakeExec(1, "", "boom\n")
        if cmd == "sleep forever":
            return FakeExec(124, "", "", timed_out=True)
        return FakeExec(0, f"ran {cmd}\n", "")

    async def read_file(self, path: str) -> str:
        assert not self.closed
        if path in self.changed:
            return self.changed[path]
        if path in self.files:
            return self.files[path]
        raise OSError(f"cannot read {path}: No such file or directory")

    async def write_file(self, path: str, content: str) -> None:
        assert not self.closed
        if path.startswith("/"):
            self.scratch[path] = content
        else:
            self.changed[path] = content

    async def diff(self) -> str:
        assert not self.closed
        return json.dumps(self.changed, sort_keys=True) if self.changed else ""

    async def close(self) -> None:
        self.closed = True


class FakeBackend:
    """Three tasks; a patch is accepted when a changed file contains FIX, unless verdicts are
    queued in `verdicts`."""

    def __init__(self, tasks: int = 3, *, images: bool = True) -> None:
        self.tasks = [
            FakeTask(f"org__repo-{n}", f"org/repo{n}", f"Problem {n} goes wrong.\nDetails of {n}.")
            for n in range(1, tasks + 1)
        ]
        self.images = images
        self.opened: list[FakeWorkspace] = []
        self.accepted: list[tuple[str, str]] = []
        self.verdicts: list[FakeVerdict] = []

    def load_split(self, name: str) -> list[FakeTask]:
        if name != "train":
            raise KeyError(f"no split {name}")
        return list(self.tasks)

    def require_images(self, tasks: list[FakeTask]) -> None:
        if not self.images:
            raise RuntimeError("the image of org__repo-1 is not pulled")

    async def open(self, task: FakeTask, name: str) -> FakeWorkspace:
        workspace = FakeWorkspace(task, name)
        self.opened.append(workspace)
        return workspace

    async def accept(self, task: FakeTask, patch: str, timeout_s: int) -> FakeVerdict:
        self.accepted.append((task.instance_id, patch))
        if self.verdicts:
            return self.verdicts.pop(0)
        if "FIX" in patch:
            return FakeVerdict("resolved", (3, 3), (10, 10))
        return FakeVerdict("failed_tests", (1, 3), (9, 10))
