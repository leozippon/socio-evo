"""Running untrusted model-written code against checks.

Each check runs in its own Python subprocess, all of a solution's checks concurrently. The
interpreter starts without site packages or the script directory on its import path, with a
fixed hash seed and an environment holding nothing else, in a fresh temporary working
directory. Before running the solution it limits its CPU time, address space, written file
size and process creation (the last does not bind root), and it is killed with its process
group after a wall-clock timeout. A crash, timeout, syntax error or any exception raised by
the solution or the check is a failed check, not an exception here.

This is process-level containment against accidents, not a security boundary: the code can
still read and write whatever the user running the simulation can, and reach the network.
Container isolation is future work.
"""

import asyncio
import json
import math
import os
import signal
import sys
import tempfile
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

from infrastructure.config import StrictModel

_HARNESS = Path(__file__).with_name("harness.py")
_MEMORY_BYTES = 1 << 30
_FILE_BYTES = 1 << 20
_ERROR_CHARS = 500


class CheckResult(StrictModel):
    """One check and, if it failed, why."""

    check: str
    passed: bool
    error: str | None = None


async def run_checks(
    source: str, checks: Sequence[str], *, timeout: float = 5.0
) -> list[CheckResult]:
    """Run each of `checks` after the solution `source`, each in a sandboxed process that may
    take `timeout` seconds; results are in the order of `checks`.

    Raises RuntimeError only if the harness itself fails before running the solution.
    """
    return list(await asyncio.gather(*(_run(source, check, timeout) for check in checks)))


async def _run(source: str, check: str, timeout: float) -> CheckResult:
    limits = {
        "RLIMIT_CPU": math.ceil(timeout) + 1,
        "RLIMIT_AS": _MEMORY_BYTES,
        "RLIMIT_FSIZE": _FILE_BYTES,
        "RLIMIT_NPROC": 0,
    }
    request = json.dumps({"source": source, "check": check, "limits": limits}).encode()
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
            stdout, stderr = await asyncio.wait_for(process.communicate(request), timeout)
        except TimeoutError:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
            return CheckResult(check=check, passed=False, error=f"timed out after {timeout:g} s")
    if stderr:
        raise RuntimeError(f"sandbox harness failed: {stderr.decode(errors='replace').strip()}")
    try:
        error = json.loads(stdout)["error"]
    except (ValueError, TypeError, KeyError):
        error = _ending(process.returncode)
    return CheckResult(
        check=check, passed=error is None, error=None if error is None else error[:_ERROR_CHARS]
    )


def _ending(returncode: int | None) -> str:
    if returncode is not None and returncode < 0:
        return f"the process was killed by {signal.Signals(-returncode).name}"
    return f"the process exited with status {returncode} and no result"
