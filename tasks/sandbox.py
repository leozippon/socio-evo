"""Running a harness on untrusted input, in a process separated from the machine.

A harness is a script of the standard library that reads one JSON request from stdin, applies
the resource limits the request carries under `limits`, writes an empty line to stdout to say
that the untrusted input is about to run, then writes its report, one JSON object, and ends.
What the input should give never enters the process: the caller reaches the verdict from the
report. Each trade that runs what a worker delivers has its own harness and report.

The interpreter starts without site packages or the script directory on its import path, with
a fixed hash seed and an environment holding nothing else. Before running the input the harness
limits its CPU time, address space, written file size and process creation (the last does not
bind root), and it is killed with everything it started once the input has run for a
wall-clock timeout, once its report outgrows the caller's limit, or when the caller is
cancelled. The timeout starts when the harness is about to run the input, so time spent
starting a sandbox on a busy machine counts against nothing; a sandbox that has not started
after a minute is an error. At most 64 harnesses run at once in an event loop; the others wait
for their turn.

`Isolation` decides what else the process can reach. Under bubblewrap, the default, it runs in
new user, process, network, IPC, UTS and cgroup namespaces and may create no further ones. Its
file system holds only the system libraries, the interpreter with its standard library, the
harness and a minimal /dev, all read-only, and a private scratch directory of 16 MiB, its
working directory and the only place it can write, in which the files the caller names are
placed read-only. So it cannot see the project, the task banks, the run directory or any home
directory, reach the network, or see or signal any process outside its sandbox. If bubblewrap
is missing or cannot create the sandbox, running raises. Without isolation, a choice for
machines that lack bubblewrap, the limits are all there is: the input runs in a temporary
working directory, where the caller's files are linked, as the user running the simulation,
can read and write whatever that user can, and can reach the network.
"""

import asyncio
import json
import math
import os
import shutil
import signal
import sys
import sysconfig
import tempfile
import weakref
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from enum import StrEnum
from pathlib import Path
from typing import TypeVar

from pydantic import TypeAdapter, ValidationError

_MEMORY_BYTES = 1 << 30
_FILE_BYTES = 1 << 20
_SCRATCH_BYTES = 16 << 20
_FLAGS = ("-B", "-S", "-P")
_READY = b"\n"
_STARTUP = 60.0
_RUNNING = 64
_slots: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)

T = TypeVar("T")


class Isolation(StrEnum):
    """How the process running a worker's delivery is separated from the machine."""

    BUBBLEWRAP = "bubblewrap"
    NONE = "none"


class Sandbox:
    """Starts harnesses separated from the machine by `isolation`.

    Raises RuntimeError if bubblewrap isolation is asked for and bubblewrap is not installed.
    """

    def __init__(self, isolation: Isolation) -> None:
        self.isolation = isolation
        self._bwrap = _bwrap() if isolation is Isolation.BUBBLEWRAP else None

    async def run(
        self,
        harness: Path,
        request: Mapping[str, object],
        report: TypeAdapter[T],
        *,
        timeout: float,
        report_bytes: int,
        files: Mapping[str, Path] | None = None,
    ) -> T | str:
        """Run `harness` on `request`, with `files` in its scratch directory by name, letting
        the input run for `timeout` seconds; the report, validated by `report`, or why there
        is none, in words: a timeout, a report larger than `report_bytes`, or how the process
        ended without a readable one.

        Raises RuntimeError if the sandbox or the harness fails before running the input.
        """
        limits = {
            "RLIMIT_CPU": math.ceil(timeout) + 1,
            "RLIMIT_AS": _MEMORY_BYTES,
            "RLIMIT_FSIZE": _FILE_BYTES,
            "RLIMIT_NPROC": 0,
        }
        sent = json.dumps({**request, "limits": limits}).encode()
        async with _slot():
            with self._launch(harness, files or {}) as (command, workdir, env):
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
                    await _start(process, sent)
                    async with asyncio.timeout(timeout):
                        written = await _report(process, report_bytes)
                except TimeoutError:
                    return f"timed out after {timeout:g} s"
                finally:
                    await _stop(process, report_bytes)
        if written is None:
            return f"the result was larger than {report_bytes} bytes"
        try:
            return report.validate_json(written)
        except ValidationError:
            return _ending(process.returncode, self._bwrap is not None)

    @contextmanager
    def _launch(
        self, harness: Path, files: Mapping[str, Path]
    ) -> Iterator[tuple[list[str], str | None, dict[str, str]]]:
        """The command, working directory and environment that start `harness`: in its
        sandbox, or else in a fresh temporary directory where `files` are linked."""
        if self._bwrap is not None:
            yield _bubblewrap(self._bwrap, harness, files), None, {}
            return
        with tempfile.TemporaryDirectory(prefix="sandbox-", ignore_cleanup_errors=True) as work:
            for name, path in files.items():
                os.symlink(path.resolve(), Path(work) / name)
            yield [sys.executable, *_FLAGS, str(harness)], work, _environment(work)


def _bwrap() -> str:
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise RuntimeError(
            "delivered work cannot be isolated: bubblewrap (bwrap) is not installed; install "
            "it, or choose isolation 'none' to run delivered work without isolation"
        )
    return bwrap


def _bubblewrap(bwrap: str, harness: Path, files: Mapping[str, Path]) -> list[str]:
    """The bubblewrap command that runs `harness` in its sandbox, with `files` read-only in
    its scratch directory. The interpreter is mounted at /python with its site packages
    hidden; on a merged-/usr system /lib and /lib64 are symbolic links, which the sandbox
    repeats."""
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
    command += [
        *("--ro-bind", str(harness), "/harness.py"),
        *("--dev", "/dev", "--remount-ro", "/dev"),
        *("--size", str(_SCRATCH_BYTES), "--tmpfs", "/tmp"),
    ]
    for name, path in files.items():
        command += ["--ro-bind", str(path.resolve()), f"/tmp/{name}"]
    return [
        *command,
        *("--chdir", "/tmp", "--remount-ro", "/"),
        f"/python/bin/{python.name}",
        *_FLAGS,
        "/harness.py",
    ]


def _environment(scratch: str) -> dict[str, str]:
    """All the harness's environment holds: a fixed hash seed and the scratch directory."""
    return {"PYTHONHASHSEED": "0", "TMPDIR": scratch}


def _slot() -> asyncio.Semaphore:
    """The running event loop's semaphore of `_RUNNING` harnesses."""
    loop = asyncio.get_running_loop()
    if loop not in _slots:
        _slots[loop] = asyncio.Semaphore(_RUNNING)
    return _slots[loop]


async def _start(process: asyncio.subprocess.Process, request: bytes) -> None:
    """Send `request` and wait until the harness is about to run the input.

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


async def _report(process: asyncio.subprocess.Process, limit: int) -> bytes | None:
    """The report, read to its end, once the process has ended; None as soon as the report is
    larger than `limit` bytes."""
    try:
        await process.stdout.readexactly(limit + 1)
    except asyncio.IncompleteReadError as ended:
        await process.wait()
        return ended.partial
    return None


async def _stop(process: asyncio.subprocess.Process, chunk: int) -> None:
    """Kill the process with its group unless it has ended, then wait for it. What it left in
    its report pipe, at most the pipe's capacity, is read and dropped, because the wait ends
    only when the pipes have closed."""
    if process.returncode is None:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    while await process.stdout.read(chunk):
        pass
    await process.wait()


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
