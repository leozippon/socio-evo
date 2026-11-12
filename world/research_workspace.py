"""Short-lived isolated CPU commands over one persistent shared directory.

Only the files directory is writable in the container. Evidence is mounted read-only;
Git history, private memories, simulation files and Docker sockets are never mounted.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from pathlib import Path


def require_image(image: str) -> None:
    subprocess.run(["docker", "image", "inspect", image], check=True, capture_output=True)


async def execute(image: str, files: Path, records: Path, command: str, timeout: int) -> dict:
    name = "research-" + uuid.uuid4().hex
    args = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "128",
        "--cpus",
        "2",
        "--memory",
        "2g",
        "--memory-swap",
        "2g",
        # Bind-mounted files use the simulation process's host UID, even on remapped daemons.
        "--userns",
        "host",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--tmpfs",
        "/tmp:rw,nosuid,size=256m,mode=1777",
        "--mount",
        f"type=bind,src={files.resolve()},dst=/research",
        "--mount",
        f"type=bind,src={records.resolve()},dst=/records,readonly",
        "--workdir",
        "/research",
        image,
        "sh",
        "-c",
        command,
    ]
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    communication = asyncio.create_task(proc.communicate())
    timed_out = False
    try:
        try:
            stdout, stderr = await asyncio.wait_for(asyncio.shield(communication), timeout)
        except TimeoutError:
            timed_out = True
            await _remove(name)
            stdout, stderr = await communication
        return {
            "exit_code": proc.returncode,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
            "timed_out": timed_out,
        }
    finally:
        # Also stop orphaned/background processes on cancellation or successful shell exit.
        await asyncio.shield(_remove(name))
        if proc.returncode is None:
            proc.kill()
        await communication


async def _remove(name: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "rm",
        "-f",
        name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
