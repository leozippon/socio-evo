"""Running untrusted model-written code against checks.

A check is a call, a Python expression evaluated with the names a solution defines, and the
outcome expected of it: a returned value, written as a Python literal, or a raised exception,
named by its built-in class. Written out, in a task bank or a specification, a check reads
`roman_to_int("IX") == 9` or `parse_duration("") raises ValueError`.

Each check runs in its own Python subprocess, all of a solution's checks concurrently. The child
process receives the solution and the call, never the expected outcome, and reports what the
call did: the value it returned, rebuilt from the built-in types of plain data (None, bool, int,
float, str, bytes, and lists, tuples, dicts and sets of them) and written as a Python literal,
or the classes of the exception it raised. The verdict is reached here, in the parent. A
returned value matches only the same plain data with the same types: `1`, `1.0` and `True`
differ, and so do a tuple and a list, while dicts and sets compare regardless of order. A raised
exception matches if its class or one of its bases has the expected name. Anything else fails
the check: an exception while loading the solution, a value that is not plain data, a crash, a
timeout, or a report that is malformed, repeated or larger than 64 KiB.

The interpreter starts without site packages or the script directory on its import path, with a
fixed hash seed and an environment holding nothing else. Before running the solution it limits
its CPU time, address space, written file size and process creation (the last does not bind
root), and it is killed with everything it started once the solution has run for a wall-clock
timeout, once its report outgrows the limit, or when the caller is cancelled. The timeout
starts when the harness is about to run the solution, so time spent starting a sandbox on a
busy machine counts against no solution; a sandbox that has not started after a minute is an
error. At most 64 checks run at once in an event loop; the others wait for their turn.

`Isolation` decides what else the process can reach. Under bubblewrap, the default, it runs in
new user, process, network, IPC, UTS and cgroup namespaces and may create no further ones. Its
file system holds only the system libraries, the interpreter with its standard library, the
harness and a minimal /dev, all read-only, and a private scratch directory of 16 MiB, its
working directory and the only place it can write. So it cannot see the project, the task
banks, the run directory or any home directory, reach the network, or see or signal any process
outside its sandbox. If bubblewrap is missing or cannot create the sandbox, running checks
raises. Without isolation, a choice for machines that lack bubblewrap, the limits are all
there is: the code runs in a temporary working directory as the user running the simulation,
can read and write whatever that user can, and can reach the network.
"""

import ast
import asyncio
import builtins
import json
import math
import os
import shutil
import signal
import sys
import sysconfig
import tempfile
import weakref
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError, model_validator

from infrastructure.config import StrictModel

_HARNESS = Path(__file__).with_name("harness.py")
_MEMORY_BYTES = 1 << 30
_FILE_BYTES = 1 << 20
_SCRATCH_BYTES = 16 << 20
_REPORT_BYTES = 1 << 16
_OUTCOME_CHARS = 500
_RAISES = " raises "
_FLAGS = ("-B", "-S", "-P")
_READY = b"\n"
_STARTUP = 60.0
_RUNNING = 64
_slots: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


class Isolation(StrEnum):
    """How the process running a check is separated from the machine."""

    BUBBLEWRAP = "bubblewrap"
    NONE = "none"


class Check(StrictModel):
    """A call and its expected outcome: the returned value `expected`, a Python literal, or the
    built-in exception class named `raises`. A check may be given as its text."""

    call: str
    expected: str | None = None
    raises: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _parse(cls, data: Any) -> Any:
        if not isinstance(data, str):
            return data
        text = data.strip()
        call, raises, name = text.rpartition(_RAISES)
        if raises and name.isidentifier():
            return {"call": call.strip(), "raises": name}
        tree = _expression(text).body
        if not (isinstance(tree, ast.Compare) and [type(op) for op in tree.ops] == [ast.Eq]):
            raise ValueError(f"not `<call> == <literal>` or `<call> raises <exception>`: {text!r}")
        return {
            "call": ast.get_source_segment(text, tree.left),
            "expected": ast.get_source_segment(text, tree.comparators[0]),
        }

    @model_validator(mode="after")
    def _valid(self) -> "Check":
        _expression(self.call)
        if (self.expected is None) == (self.raises is None):
            raise ValueError("a check expects either a returned value or a raised exception")
        if self.expected is not None:
            ast.literal_eval(_expression(self.expected))
        elif not (
            isinstance(kind := getattr(builtins, self.raises, None), type)
            and issubclass(kind, BaseException)
        ):
            raise ValueError(f"{self.raises} is not a built-in exception class")
        return self

    @property
    def text(self) -> str:
        """The check written out."""
        if self.raises is None:
            return f"{self.call} == {self.expected}"
        return f"{self.call}{_RAISES}{self.raises}"


class CheckResult(StrictModel):
    """A check, whether it passed, and what its call did, in words."""

    check: Check
    passed: bool
    outcome: str


class _Returned(StrictModel):
    returned: str


class _Raised(StrictModel):
    raised: tuple[str, ...]
    error: str


class _Failed(StrictModel):
    error: str


_REPORT = TypeAdapter(_Returned | _Raised | _Failed)
"""The report of the harness: exactly one JSON object of one of these forms."""


async def run_checks(
    source: str,
    checks: Sequence[Check],
    *,
    timeout: float = 5.0,
    isolation: Isolation = Isolation.BUBBLEWRAP,
) -> list[CheckResult]:
    """Run each of `checks` on the solution `source`, each in a process separated from the
    machine by `isolation` that may take `timeout` seconds; results are in the order of
    `checks`.

    Raises RuntimeError if bubblewrap isolation is asked for and bubblewrap is not installed,
    and an ExceptionGroup of RuntimeError if the sandbox or the harness fails before running
    the solution, cancelling the other checks.
    """
    sandbox = _bubblewrap() if isolation is Isolation.BUBBLEWRAP else None
    async with asyncio.TaskGroup() as group:
        running = [group.create_task(_run(source, check, timeout, sandbox)) for check in checks]
    return [task.result() for task in running]


def _bubblewrap() -> list[str]:
    """The bubblewrap command that runs the harness in its sandbox. The interpreter is mounted
    at /python with its site packages hidden; on a merged-/usr system /lib and /lib64 are
    symbolic links, which the sandbox repeats."""
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise RuntimeError(
            "delivered code cannot be isolated: bubblewrap (bwrap) is not installed; install "
            "it, or choose isolation 'none' to run delivered code without isolation"
        )
    prefix, python = Path(sys.base_prefix).resolve(), Path(sys.executable).resolve()
    if python.parent != prefix / "bin":
        raise RuntimeError(f"the interpreter {python} is not in {prefix / 'bin'}")
    command = [
        bwrap,
        *("--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-ipc"),
        *("--unshare-uts", "--unshare-cgroup", "--disable-userns"),
        *("--die-with-parent", "--new-session"),
        *("--ro-bind", "/usr/lib", "/usr/lib"),
    ]
    for name, value in _environment("/tmp").items():
        command += ["--setenv", name, value]
    for system in ("/usr/lib64", "/lib", "/lib64"):
        path = Path(system)
        if path.is_symlink():
            command += ["--symlink", os.readlink(path), system]
        elif path.is_dir():
            command += ["--ro-bind", system, system]
    command += ["--ro-bind", str(python), f"/python/bin/{python.name}"]
    command += ["--ro-bind", str(prefix / "lib"), "/python/lib"]
    for key in ("purelib", "platlib"):
        packages = Path(sysconfig.get_path(key)).resolve()
        if packages.is_relative_to(prefix / "lib"):
            hidden = f"/python/{packages.relative_to(prefix)}"
            command += ["--tmpfs", hidden, "--remount-ro", hidden]
    return [
        *command,
        *("--ro-bind", str(_HARNESS), "/harness.py"),
        *("--dev", "/dev", "--remount-ro", "/dev"),
        *("--size", str(_SCRATCH_BYTES), "--tmpfs", "/tmp", "--chdir", "/tmp"),
        *("--remount-ro", "/"),
        f"/python/bin/{python.name}",
        *_FLAGS,
        "/harness.py",
    ]


@contextmanager
def _launch(
    sandbox: list[str] | None,
) -> Iterator[tuple[list[str], str | None, dict[str, str]]]:
    """The command, working directory and environment that start the harness: in `sandbox`,
    or else in a fresh temporary directory."""
    if sandbox is not None:
        yield sandbox, None, {}
        return
    with tempfile.TemporaryDirectory(prefix="sandbox-", ignore_cleanup_errors=True) as workdir:
        yield [sys.executable, *_FLAGS, str(_HARNESS)], workdir, _environment(workdir)


def _environment(scratch: str) -> dict[str, str]:
    """All the harness's environment holds: a fixed hash seed and the scratch directory."""
    return {"PYTHONHASHSEED": "0", "TMPDIR": scratch}


def _slot() -> asyncio.Semaphore:
    """The running event loop's semaphore of `_RUNNING` checks."""
    loop = asyncio.get_running_loop()
    if loop not in _slots:
        _slots[loop] = asyncio.Semaphore(_RUNNING)
    return _slots[loop]


async def _run(source: str, check: Check, timeout: float, sandbox: list[str] | None) -> CheckResult:
    limits = {
        "RLIMIT_CPU": math.ceil(timeout) + 1,
        "RLIMIT_AS": _MEMORY_BYTES,
        "RLIMIT_FSIZE": _FILE_BYTES,
        "RLIMIT_NPROC": 0,
    }
    request = json.dumps({"source": source, "call": check.call, "limits": limits}).encode()
    async with _slot():
        with _launch(sandbox) as (command, workdir, env):
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
                env=env,
                start_new_session=True,
            )
            try:
                await _start(process, request)
                async with asyncio.timeout(timeout):
                    report = await _report(process)
            except TimeoutError:
                return _result(check, False, f"timed out after {timeout:g} s")
            finally:
                await _stop(process)
    if report is None:
        return _result(check, False, f"the result was larger than {_REPORT_BYTES} bytes")
    try:
        verdict = _REPORT.validate_json(report)
    except ValidationError:
        return _result(check, False, _ending(process.returncode, sandbox is not None))
    match verdict:
        case _Returned(returned=value):
            passed = check.expected is not None and _same(value, check.expected)
            return _result(check, passed, f"returned {value}")
        case _Raised(raised=classes, error=error):
            return _result(check, check.raises in classes, f"raised {error}")
        case _Failed(error=error):
            return _result(check, False, error)


async def _start(process: asyncio.subprocess.Process, request: bytes) -> None:
    """Send `request` and wait until the harness is about to run the solution.

    Raises RuntimeError, with what the harness wrote to stderr, if it ends first, and if it
    does not get there within `_STARTUP` seconds.
    """
    process.stdin.write(request)
    process.stdin.close()
    try:
        async with asyncio.timeout(_STARTUP):
            ready = await process.stdout.read(len(_READY))
    except TimeoutError:
        raise RuntimeError(f"the sandbox did not start within {_STARTUP:g} s") from None
    if ready != _READY:
        errors = (await process.stderr.read()).decode(errors="replace").strip()
        raise RuntimeError(f"sandbox harness failed: {errors or 'it ended without a message'}")


async def _report(process: asyncio.subprocess.Process) -> bytes | None:
    """The report, read to its end, once the process has ended; None as soon as the report is
    larger than the limit."""
    try:
        await process.stdout.readexactly(_REPORT_BYTES + 1)
    except asyncio.IncompleteReadError as ended:
        await process.wait()
        return ended.partial
    return None


async def _stop(process: asyncio.subprocess.Process) -> None:
    """Kill the process with its group unless it has ended, then wait for it. What it left in
    its report pipe, at most the pipe's capacity, is read and dropped, because the wait ends
    only when the pipes have closed."""
    if process.returncode is None:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    while await process.stdout.read(_REPORT_BYTES):
        pass
    await process.wait()


def _same(returned: str, expected: str) -> bool:
    """Whether the literal `returned` is the plain data that `expected` is, types included."""
    try:
        value = ast.literal_eval(returned)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False
    return _typed(value) == _typed(ast.literal_eval(expected))


def _typed(value: object) -> object:
    """`value` as a hashable structure in which every part carries its type, so that equality
    is type-strict and ignores the order of dicts and sets."""
    if isinstance(value, list | tuple):
        return type(value), tuple(map(_typed, value))
    if isinstance(value, set):
        return set, frozenset(map(_typed, value))
    if isinstance(value, dict):
        return dict, frozenset((_typed(key), _typed(item)) for key, item in value.items())
    return type(value), value


def _expression(text: str) -> ast.Expression:
    try:
        return ast.parse(text, mode="eval")
    except SyntaxError as error:
        raise ValueError(f"not a Python expression: {text!r}") from error


def _result(check: Check, passed: bool, outcome: str) -> CheckResult:
    if len(outcome) > _OUTCOME_CHARS:
        outcome = outcome[: _OUTCOME_CHARS - 4] + " ..."
    return CheckResult(check=check, passed=passed, outcome=outcome)


def _ending(returncode: int | None, sandboxed: bool) -> str:
    """Why a process ended without a report; bubblewrap exits with 128 plus the number of the
    signal that killed what it ran."""
    killer = None
    if returncode is not None and returncode < 0:
        killer = -returncode
    elif sandboxed and returncode is not None and returncode > 128:
        killer = returncode - 128
    if killer is not None:
        with suppress(ValueError):
            return f"the process was killed by {signal.Signals(killer).name}"
    return f"the process exited with status {returncode} without a readable result"
