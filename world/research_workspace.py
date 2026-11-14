"""Short-lived research commands over one persistent shared directory.

Research files and the optional separate runtime directory are writable. Evidence is read-only;
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


async def execute(
    image: str,
    files: Path,
    records: Path,
    command: str,
    timeout: int,
    *,
    network: bool = True,
    gpus: str | None = None,
    cpus: float = 2,
    memory: str = "2g",
    runtime_dir: Path | None = None,
) -> dict:
    name = "research-" + uuid.uuid4().hex
    args = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "bridge" if network else "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "128",
        "--cpus",
        str(cpus),
        "--memory",
        memory,
        "--memory-swap",
        memory,
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
    ]
    if gpus:
        args.extend(["--gpus", gpus])
    if runtime_dir is not None:
        for folder in ("python", "huggingface", "torch", "cache", "pip", "tmp", "home"):
            (runtime_dir / folder).mkdir(parents=True, exist_ok=True)
        args.extend(["--mount", f"type=bind,src={runtime_dir.resolve()},dst=/runtime"])
    args.extend(
        [
            image,
            "sh",
            "-c",
            command,
        ]
    )
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
