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
fixed hash seed and an environment holding nothing else, in a fresh temporary working directory.
Before running the solution it limits its CPU time, address space, written file size and
process creation (the last does not bind root), and it is killed with its process group after a
wall-clock timeout, once its report outgrows the limit, or when the caller is cancelled.

This is process-level containment against accidents, not a security boundary: the code can
still read and write whatever the user running the simulation can, the task banks with their
expected values included, inspect and signal that user's other processes, and reach the
network. Container isolation is future work.
"""

import ast
import asyncio
import builtins
import json
import math
import os
import signal
import sys
import tempfile
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError, model_validator

from infrastructure.config import StrictModel

_HARNESS = Path(__file__).with_name("harness.py")
_MEMORY_BYTES = 1 << 30
_FILE_BYTES = 1 << 20
_REPORT_BYTES = 1 << 16
_OUTCOME_CHARS = 500
_RAISES = " raises "


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
    source: str, checks: Sequence[Check], *, timeout: float = 5.0
) -> list[CheckResult]:
    """Run each of `checks` on the solution `source`, each in a sandboxed process that may take
    `timeout` seconds; results are in the order of `checks`.

    Raises an ExceptionGroup of RuntimeError only if the harness itself fails before running
    the solution, cancelling the other checks.
    """
    async with asyncio.TaskGroup() as group:
        running = [group.create_task(_run(source, check, timeout)) for check in checks]
    return [task.result() for task in running]


async def _run(source: str, check: Check, timeout: float) -> CheckResult:
    limits = {
        "RLIMIT_CPU": math.ceil(timeout) + 1,
        "RLIMIT_AS": _MEMORY_BYTES,
        "RLIMIT_FSIZE": _FILE_BYTES,
        "RLIMIT_NPROC": 0,
    }
    request = json.dumps({"source": source, "call": check.call, "limits": limits}).encode()
    with tempfile.TemporaryDirectory(prefix="sandbox-", ignore_cleanup_errors=True) as workdir:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-B",
            "-S",
            "-P",
            str(_HARNESS),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workdir,
            env={"PYTHONHASHSEED": "0", "TMPDIR": workdir},
            start_new_session=True,
        )
        try:
            async with asyncio.timeout(timeout):
                exchanged = await _exchange(process, request)
        except TimeoutError:
            return _result(check, False, f"timed out after {timeout:g} s")
        finally:
            await _stop(process)
    if exchanged is None:
        return _result(check, False, f"the result was larger than {_REPORT_BYTES} bytes")
    report, errors = exchanged
    if errors:
        raise RuntimeError(f"sandbox harness failed: {errors.decode(errors='replace').strip()}")
    try:
        verdict = _REPORT.validate_json(report)
    except ValidationError:
        return _result(check, False, _ending(process.returncode))
    match verdict:
        case _Returned(returned=value):
            passed = check.expected is not None and _same(value, check.expected)
            return _result(check, passed, f"returned {value}")
        case _Raised(raised=classes, error=error):
            return _result(check, check.raises in classes, f"raised {error}")
        case _Failed(error=error):
            return _result(check, False, error)


async def _exchange(
    process: asyncio.subprocess.Process, request: bytes
) -> tuple[bytes, bytes] | None:
    """Send `request`, then read the report to its end, the harness's own errors and the exit;
    None as soon as the report is larger than the limit."""
    process.stdin.write(request)
    process.stdin.close()
    try:
        await process.stdout.readexactly(_REPORT_BYTES + 1)
    except asyncio.IncompleteReadError as ended:
        errors = await process.stderr.read()
        await process.wait()
        return ended.partial, errors
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


def _ending(returncode: int | None) -> str:
    if returncode is not None and returncode < 0:
        return f"the process was killed by {signal.Signals(-returncode).name}"
    return f"the process exited with status {returncode} without a readable result"
