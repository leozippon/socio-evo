"""A thin typed wrapper over the git CLI for one repository directory.

Every command is pinned to `<path>/.git`, so a missing repository is an error rather than
a silent walk up to an enclosing one. Commands run with system and global git config
disabled, inherited `GIT_*` variables removed and the C locale, so behaviour and messages
never depend on the host setup.
"""

import io
import os
import subprocess
import tarfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class GitError(RuntimeError):
    """A git command exited non-zero."""

    def __init__(self, command: list[str], returncode: int, stderr: str, stdout: str) -> None:
        super().__init__(
            f"{' '.join(command)} exited with {returncode}: {(stderr or stdout).strip()}"
        )
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


@dataclass(frozen=True)
class Commit:
    id: str
    parent: str | None
    """First parent; None for a root commit."""
    date: datetime
    """Author date."""
    subject: str
    body: str


class Repository:
    """The git repository whose work tree is `path`."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    @classmethod
    def init(cls, path: Path, *, user_name: str, user_email: str) -> "Repository":
        """Create (or reinitialise) a repository at `path` with a local identity and no hooks."""
        path.mkdir(parents=True, exist_ok=True)
        _run(["git", "init", "--quiet", "--initial-branch=main"], cwd=path)
        repository = cls(path)
        for key, value in (
            ("user.name", user_name),
            ("user.email", user_email),
            ("commit.gpgSign", "false"),
            ("tag.gpgSign", "false"),
            ("core.hooksPath", os.devnull),
        ):
            repository._git("config", key, value)
        return repository

    def commit(self, message: str, *, date: datetime, allow_empty: bool = False) -> str:
        """Stage every change and commit it, authored and committed at `date`; returns its id.

        `date` must be timezone-aware. Raises GitError if there is nothing to commit, unless
        `allow_empty`, which records the commit with an unchanged tree.
        """
        if date.tzinfo is None:
            raise ValueError("commit date must be timezone-aware")
        stamp = f"{int(date.timestamp())} {date.strftime('%z')}"
        self._git("add", "--all")
        self._git(
            "commit",
            "--quiet",
            "--no-verify",
            *(["--allow-empty"] if allow_empty else []),
            f"--message={message}",
            env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp},
        )
        return self.head()

    def has_changes(self) -> bool:
        """Whether the work tree differs from HEAD, untracked files included."""
        return bool(self._git("status", "--porcelain", "--untracked-files=all").strip())

    def head(self) -> str:
        return self._git("rev-parse", "HEAD").strip()

    def log(self, revision: str = "HEAD") -> list[Commit]:
        """Commits reachable from `revision`, newest first."""
        output = self._git("log", "-z", "--format=%H%x1f%P%x1f%aI%x1f%s%x1f%b", revision, "--")
        commits = []
        for record in filter(None, output.split("\0")):
            commit_id, parents, date, subject, body = record.split("\x1f")
            commits.append(
                Commit(
                    id=commit_id,
                    parent=parents.split()[0] if parents else None,
                    date=datetime.fromisoformat(date),
                    subject=subject,
                    body=body.strip("\n"),
                )
            )
        return commits

    def diff(self, old: str, new: str) -> str:
        """Unified diff from revision `old` to revision `new`."""
        return self._git("diff", old, new, "--")

    def read_file(self, revision: str, path: str) -> str:
        """Content of `path` (relative to the work tree) at `revision`."""
        return self._git("show", f"{revision}:{path}")

    def tag(self, name: str, revision: str = "HEAD") -> None:
        self._git("tag", name, revision)

    def reset_hard(self, revision: str) -> None:
        """Make HEAD, index and work tree exactly `revision`, deleting untracked files."""
        self._git("reset", "--hard", "--quiet", revision)
        self._git("clean", "-d", "--force", "--quiet")

    def export(self, revision: str, destination: Path) -> None:
        """Write the tree of `revision`, without history, into the new directory `destination`.

        Raises FileExistsError if `destination` already exists.
        """
        archive = _run(self._command("archive", "--format=tar", revision), cwd=self.path)
        destination.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(destination, filter="data")

    def _command(self, *args: str) -> list[str]:
        return ["git", f"--git-dir={self.path / '.git'}", f"--work-tree={self.path}", *args]

    def _git(self, *args: str, env: dict[str, str] | None = None) -> str:
        return _run(self._command(*args), cwd=self.path, env=env).decode()


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> bytes:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, LC_ALL="C")
    environment.update(env or {})
    result = subprocess.run(command, cwd=cwd, env=environment, capture_output=True)
    if result.returncode != 0:
        raise GitError(
            command,
            result.returncode,
            result.stderr.decode(errors="replace"),
            result.stdout.decode(errors="replace"),
        )
    return result.stdout
