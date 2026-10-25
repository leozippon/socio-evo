"""A worker's workspace on a task: a container of the task image, cut off from the network.

`Workspace.open` starts a container of the task's image without network and with limited CPUs,
memory and processes. The worker runs shell commands in it (`exec`: a login shell, as the
image's user, in /testbed, with the conda environment `testbed` active), reads and writes
files, and hands in `diff`, its changes as a patch; `close` removes the container.

Before the worker starts, `open` checks that the base commit is checked out and removes the
history newer than it. The images were made by cloning the whole repository, so their git
objects hold the upstream history up to the image build, the fix included. Like SWE-bench's own
setup since, `open` deletes every tag on a newer commit and every ref but the checked-out
branch, expires the reflogs, prunes what is no longer reachable and checks that no newer commit
remains (about 10 s for Django).

The patch is taken against the working tree as `open` found it rather than against the base
commit: the images leave SWE-bench's pre-install edits uncommitted (astropy's pinned build
requirement, for one), and acceptance applies the patch to a fresh container of the same image,
where those edits already are. It holds every change to a tracked file and every new file git
does not ignore, whatever the worker did with commits, the index or HEAD, and leaves out binary
files, which a text patch cannot carry.

Containers are named uniquely and labelled with the process that started them. Those a process
leaves behind are removed when it exits normally; those of a process that was killed are
removed by `python -m tasks.swebench.cleanup`. Each call runs one `docker` command line, so
many workspaces may be open at once.
"""

import asyncio
import atexit
import os
import re
import subprocess
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Self

from tasks.swebench.dataset import Task
from tasks.swebench.images import require

LABEL = "socio-evo.swebench.owner"
WORKDIR = "/testbed"
_GRACE = 5  # seconds between the end of a command's time and killing it
_live: set[str] = set()  # containers this process started and has not removed

# The history newer than the checked-out base commit, removed.
_FORGET = r"""set -euo pipefail
base=$(git show -s --format=%ct HEAD)
git for-each-ref --format='%(refname) %(*committerdate:unix)%(committerdate:unix)' refs/tags |
    while read -r ref when; do
        if [ -z "$when" ] || [ "$when" -gt "$base" ]; then echo "delete $ref"; fi
    done | git update-ref --stdin
branch=$(git symbolic-ref -q HEAD || true)
git for-each-ref --format='%(refname)' | { grep -v -x -e "$branch" -e 'refs/tags/.*' || true; } |
    sed 's/^/delete /' | git update-ref --stdin
rm -f .git/ORIG_HEAD .git/FETCH_HEAD
git reflog expire --expire=now --all
git gc --prune=now --quiet
newer=$(git rev-list --all --since="$((base + 1))" | wc -l)
[ "$newer" -eq 0 ] || { echo "$newer commits newer than the base commit remain" >&2; exit 1; }
"""

# The working tree as a tree object, staged in a scratch index so the worker's index is left
# alone, and the patch from the baseline tree to it, by plumbing that ignores git's diff config.
_STAGE = "set -e; export GIT_INDEX_FILE=$(mktemp -u); trap 'rm -f \"$GIT_INDEX_FILE\"' EXIT; "
_STAGE += 'cp .git/index "$GIT_INDEX_FILE"; git add --all; '
_SNAPSHOT = _STAGE + "git write-tree"
_DIFF = _STAGE + "git diff-index --cached --patch --no-color {baseline}"


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


class Container:
    """A running container of a task image without network, removed by `remove`."""

    def __init__(self, name: str) -> None:
        self.name = name

    @classmethod
    async def start(
        cls, image: str, name: str, *, cpus: float = 4, memory: str = "16g", pids: int = 4096
    ) -> Self:
        """Start a container of `image`, which must be pulled, named after `name`."""
        await asyncio.to_thread(require, image)
        slug = re.sub(r"[^a-zA-Z0-9_.-]", "-", name)
        container = cls(f"socio-evo-swe-{slug}-{uuid.uuid4().hex[:8]}")
        _live.add(container.name)
        code, _, err = await _docker(
            "run",
            "--detach",
            "--init",
            "--name",
            container.name,
            "--label",
            f"{LABEL}={os.getpid()}",
            "--network",
            "none",
            "--cpus",
            str(cpus),
            "--memory",
            memory,
            "--pids-limit",
            str(pids),
            "--workdir",
            WORKDIR,
            image,
            "sleep",
            "infinity",
            timeout=600,
        )
        if code != 0:
            await container.remove()
            raise RuntimeError(f"cannot start a container of {image}: {err.strip()}")
        return container

    async def exec(
        self, argv: Sequence[str], timeout_s: float, stdin: str | None = None
    ) -> ExecResult:
        """Run `argv` in /testbed, killing it with everything it started in its process group
        once `timeout_s` has passed."""
        started = time.monotonic()
        code, out, err = await _docker(
            "exec",
            *(["--interactive"] if stdin is not None else []),
            "--workdir",
            WORKDIR,
            self.name,
            "timeout",
            f"--kill-after={_GRACE}",
            str(timeout_s),
            *argv,
            stdin=stdin,
            timeout=timeout_s + _GRACE + 60,
        )
        timed_out = code in (124, 137) and time.monotonic() - started >= timeout_s
        return ExecResult(code, out, err, timed_out)

    async def write(self, path: str, content: str) -> None:
        """Write `content` to `path`, creating its directories."""
        script = 'mkdir -p -- "$(dirname -- "$1")" && cat > "$1"'
        result = await self.exec(["bash", "-c", script, "write", path], 120, stdin=content)
        if result.exit_code != 0:
            raise OSError(f"cannot write {path}: {result.stderr.strip()}")

    async def remove(self) -> None:
        code, _, err = await _docker("rm", "--force", self.name, timeout=300)
        if code != 0 and "No such container" not in err:
            raise RuntimeError(f"cannot remove container {self.name}: {err.strip()}")
        _live.discard(self.name)


class Workspace:
    """A worker's container of a task, whose changes to the repository `diff` returns."""

    def __init__(self, task: Task, container: Container, baseline: str) -> None:
        self.task = task
        self.container = container
        self.baseline = baseline

    @classmethod
    async def open(cls, task: Task, name: str, *, cpus: float = 4, memory: str = "16g") -> Self:
        """Start a workspace on `task` for the worker `name`."""
        container = await Container.start(task.image, name, cpus=cpus, memory=memory)
        try:
            head = await container.exec(["git", "rev-parse", "HEAD"], 120)
            if head.stdout.strip() != task.base_commit:
                raise RuntimeError(
                    f"{task.image} has {head.stdout.strip() or head.stderr.strip()} checked out, "
                    f"not the base commit {task.base_commit}"
                )
            forget = await container.exec(["bash", "-c", _FORGET], 600)
            if forget.exit_code != 0:
                raise RuntimeError(f"cannot remove the newer history: {forget.stderr.strip()}")
            snapshot = await container.exec(["bash", "-c", _SNAPSHOT], 600)
            if snapshot.exit_code != 0:
                raise RuntimeError(f"cannot record the initial tree: {snapshot.stderr.strip()}")
        except BaseException:
            await container.remove()
            raise
        return cls(task, container, snapshot.stdout.strip())

    async def exec(self, cmd: str, timeout_s: int, max_output: int = 30_000) -> ExecResult:
        """Run `cmd` in a login shell, keeping at most `max_output` characters of each of its
        outputs, the beginning and the end."""
        result = await self.container.exec(["bash", "-lc", cmd], timeout_s)
        return ExecResult(
            result.exit_code,
            clip(result.stdout, max_output),
            clip(result.stderr, max_output),
            result.timed_out,
        )

    async def read_file(self, path: str) -> str:
        """The text of `path`, relative to /testbed unless absolute."""
        result = await self.container.exec(["cat", "--", path], 120)
        if result.exit_code != 0:
            raise OSError(f"cannot read {path}: {result.stderr.strip()}")
        return result.stdout

    async def write_file(self, path: str, content: str) -> None:
        """Write `content` to `path`, relative to /testbed unless absolute."""
        await self.container.write(path, content)

    async def diff(self) -> str:
        """The worker's changes to the repository as a patch to the initial tree."""
        script = _DIFF.format(baseline=self.baseline)
        result = await self.container.exec(["bash", "-c", script], 600)
        if result.exit_code != 0:
            raise RuntimeError(f"cannot take the diff: {result.stderr.strip()}")
        return drop_binary(result.stdout)

    async def close(self) -> None:
        await self.container.remove()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


def drop_binary(patch: str) -> str:
    """`patch` without the files git reports as binary."""
    files = re.split(r"(?m)^(?=diff --git )", patch)
    return "".join(
        file
        for file in files
        if not re.search(r"(?m)^(Binary files .* differ|GIT binary patch)$", file)
    )


def clip(text: str, limit: int) -> str:
    """`text` cut to its first and last characters when longer than `limit`."""
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    return f"{text[:head]}\n[... {len(text) - limit} characters cut ...]\n{text[-tail:]}"


async def _docker(*args: str, timeout: float, stdin: str | None = None) -> tuple[int, str, str]:
    """Run the Docker command line and return its exit code and outputs. A command line still
    running after `timeout` seconds is killed and raises."""
    process = await asyncio.create_subprocess_exec(
        "docker",
        *args,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        data = stdin.encode() if stdin is not None else None
        out, err = await asyncio.wait_for(process.communicate(data), timeout)
    except TimeoutError:
        raise TimeoutError(f"docker {args[0]} did not return in {timeout:.0f} s") from None
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    return process.returncode, out.decode(errors="replace"), err.decode(errors="replace")


@atexit.register
def _remove_live() -> None:
    if _live:
        subprocess.run(["docker", "rm", "--force", *_live], capture_output=True, timeout=600)
