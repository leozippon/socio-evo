"""Short-lived research commands over one persistent shared directory.

Research files and the optional separate runtime directory are writable unless readonly is set.
Evidence is read-only; Git history, private memories, simulation files and Docker sockets are
never mounted. A selected Git snapshot can replace the live files for an isolated command.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path, PurePosixPath


def require_image(image: str) -> None:
    subprocess.run(["docker", "image", "inspect", image], check=True, capture_output=True)


def snapshot_path(value: str) -> str:
    """Normalize one admitted path for both snapshot selection and dependency comparison."""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("Snapshot paths must be nonempty repository-relative paths.")
    path = PurePosixPath(value)
    if (path.is_absolute() or not path.parts or path.parts[0] not in {"files", "records"}
            or any(part in {"..", ".git"} for part in path.parts)):
        raise ValueError("Snapshot paths must stay within files/ or records/, outside Git metadata")
    return path.as_posix()


def _git(root: Path, *args: str, stdout=subprocess.PIPE):
    try:
        return subprocess.run(
            ["git", "--literal-pathspecs", "-C", str(root), *args],
            stdout=stdout, stderr=subprocess.PIPE, check=True,
        ).stdout
    except subprocess.CalledProcessError as error:
        raise ValueError("Cannot read the requested research Git revision or files.") from error


@contextmanager
def snapshot(
    files: Path,
    records: Path,
    revision: str,
    paths: Sequence[str],
    *,
    optional_paths: Sequence[str] = (),
) -> Iterator[tuple[Path, Path]]:
    """Export selected tracked files from one commit, without a checkout or Git history.

    Required paths can name files or directories. Optional paths name exact output files:
    existing files are copied from this revision, while missing files get only their parent
    directories. The caller decides whether to mount the snapshot read-only or publish outputs.
    Temporary files are removed on every exit, including command failure and cancellation.
    """
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
        raise ValueError("A snapshot requires a full Git commit SHA.")
    if files.name != "files" or records.name != "records" or files.parent != records.parent:
        raise ValueError("Snapshot files and records must belong to one research repository.")
    if isinstance(paths, str) or isinstance(optional_paths, str):
        raise ValueError("Snapshot paths must be lists of repository-relative paths.")
    required = {snapshot_path(path) for path in paths}
    optional = {snapshot_path(path) for path in optional_paths}
    if not required | optional:
        raise ValueError("Select at least one snapshot path.")
    if optional & {"files", "records"}:
        raise ValueError("Optional snapshot paths must name exact files.")
    root = files.parent
    _git(root, "rev-parse", "--verify", f"{revision}^{{commit}}")
    listing = _git(root, "ls-tree", "-rlz", "--full-tree", revision, "--",
                   *sorted(required | optional))
    entries = {}
    total_bytes = 0
    for row in listing.split(b"\0"):
        if not row:
            continue
        metadata, raw_path = row.split(b"\t", 1)
        mode, kind, oid, size = metadata.decode().split()
        path = snapshot_path(os.fsdecode(raw_path))
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError(f"Snapshot paths must contain only regular tracked files: {path}")
        entries[path] = (mode, oid)
        total_bytes += int(size)
    for path in required:
        if not any(name == path or name.startswith(path + "/") for name in entries):
            raise ValueError(f"Snapshot path does not exist at this revision: {path}")
    for path in optional:
        if any(name.startswith(path + "/") for name in entries):
            raise ValueError(f"Optional snapshot path is a directory, not an exact file: {path}")
    free = shutil.disk_usage(root.parent).free
    if total_bytes > free:
        raise ValueError(f"Insufficient snapshot disk space: need {total_bytes} bytes; {free} free")
    with tempfile.TemporaryDirectory(prefix="research-snapshot-", dir=root.parent) as temporary:
        destination = Path(temporary)
        for name in ("files", "records"):
            (destination / name).mkdir()
        for path in optional:
            (destination / path).parent.mkdir(parents=True, exist_ok=True)
        for path, (mode, oid) in entries.items():
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as output:
                _git(root, "cat-file", "blob", oid, stdout=output)
            target.chmod(0o755 if mode == "100755" else 0o644)
        yield destination / "files", destination / "records"


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
    models: dict[str, Path] | None = None,
    readonly: bool = False,
    runtime_readonly: bool = False,
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
        f"type=bind,src={files.resolve()},dst=/research" + (",readonly" if readonly else ""),
        "--mount",
        f"type=bind,src={records.resolve()},dst=/records,readonly",
        "--workdir",
        "/research",
    ]
    if gpus:
        args.extend(["--gpus", gpus])
    for model_id, path in (models or {}).items():
        if not re.fullmatch(r"hf-[0-9a-f]{32}", model_id) or not path.is_dir():
            raise ValueError("An admitted model must have a valid identity and local snapshot")
        args.extend([
            "--mount", f"type=bind,src={path.resolve()},dst=/models/{model_id},readonly",
        ])
    if models is not None:
        args.extend(["--env", "HF_HUB_OFFLINE=1", "--env", "TRANSFORMERS_OFFLINE=1"])
    if runtime_dir is not None:
        for folder in ("python", "huggingface", "torch", "cache", "pip", "tmp", "home"):
            (runtime_dir / folder).mkdir(parents=True, exist_ok=True)
        args.extend(["--mount", f"type=bind,src={runtime_dir.resolve()},dst=/runtime"
                     + (",readonly" if readonly or runtime_readonly else "")])
    if readonly or (runtime_readonly and runtime_dir is not None):
        for setting in (
            "HOME=/tmp", "TMPDIR=/tmp", "XDG_CACHE_HOME=/tmp/cache",
            "HF_HOME=/tmp/huggingface", "TORCH_HOME=/tmp/torch",
            "MPLCONFIGDIR=/tmp/matplotlib", "PYTHONDONTWRITEBYTECODE=1",
        ):
            args.extend(["--env", setting])
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
