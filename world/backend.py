"""What the world needs of its work content, and the adapter to `tasks.swebench`.

The world codes against `Backend`: a split of tasks, a check that every task's image is on the
machine, a workspace per resident and task (a container without network, in which commands run
and files are read and written, whose changes `diff` returns as a patch), and the official
acceptance of a patch in a fresh container. `SwebenchBackend` is the real one; tests use fakes.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Sequence
from typing import Any, Literal, Protocol

Status = Literal["resolved", "failed_tests", "patch_apply_failed", "error", "timeout"]


class Task(Protocol):
    @property
    def instance_id(self) -> str: ...
    @property
    def repo(self) -> str: ...
    @property
    def problem_statement(self) -> str: ...


class ExecResult(Protocol):
    @property
    def exit_code(self) -> int: ...
    @property
    def stdout(self) -> str: ...
    @property
    def stderr(self) -> str: ...
    @property
    def timed_out(self) -> bool: ...


class Verdict(Protocol):
    @property
    def resolved(self) -> bool: ...
    @property
    def status(self) -> Status: ...
    @property
    def fail_to_pass(self) -> tuple[int, int]:
        """Passed and total of the checks the change should make pass."""
        ...

    @property
    def pass_to_pass(self) -> tuple[int, int]:
        """Passed and total of the checks that passed before the change."""
        ...


class Workspace(Protocol):
    async def exec(self, cmd: str, timeout_s: int) -> ExecResult: ...
    async def read_file(self, path: str) -> str:
        """Raises OSError when the file cannot be read."""
        ...

    async def write_file(self, path: str, content: str) -> None:
        """Raises OSError when the file cannot be written."""
        ...

    async def diff(self) -> str: ...
    async def close(self) -> None: ...


class Backend(Protocol):
    def load_split(self, name: str) -> Sequence[Task]: ...
    def require_images(self, tasks: Sequence[Task]) -> None:
        """Raise unless every task's image is on this machine."""
        ...

    async def open(self, task: Task, name: str) -> Workspace: ...
    async def accept(self, task: Task, patch: str, timeout_s: int) -> Verdict: ...


class SwebenchBackend:
    """`tasks.swebench` as a `Backend`; blocking calls run in a thread."""

    def load_split(self, name: str) -> Sequence[Task]:
        from tasks.swebench.dataset import load_split

        return load_split(name)  # type: ignore[arg-type]

    def require_images(self, tasks: Sequence[Task]) -> None:
        from tasks.swebench.images import require

        for task in tasks:
            require(task.image)  # type: ignore[attr-defined]

    async def open(self, task: Task, name: str) -> Workspace:
        from tasks.swebench.workspace import Workspace as SwebenchWorkspace

        return await _call(SwebenchWorkspace.open, task, name)

    async def accept(self, task: Task, patch: str, timeout_s: int) -> Verdict:
        from tasks.swebench.acceptance import accept

        return await _call(accept, task, patch, timeout_s)


async def _call(function: Callable[..., Any], *args: Any) -> Any:
    if inspect.iscoroutinefunction(function):
        return await function(*args)
    return await asyncio.to_thread(function, *args)
