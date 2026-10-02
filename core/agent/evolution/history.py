"""An agent's version history: its git repository, in domain terms.

Each commit message ends with a trailer block: `Sim-Time` (simulated minutes) on every
commit, and `Level` and `Trigger` on evolution steps. The commit date is `EPOCH` plus the
simulated time, so history is deterministic.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.agent.evolution.levels import Level, Trigger
from core.interaction import format_time
from infrastructure.git import Commit, Repository

EPOCH = datetime(2001, 1, 1, tzinfo=UTC)
"""The commit date of simulated time 0."""


def commit_date(time: int) -> datetime:
    return EPOCH + timedelta(minutes=time)


@dataclass(frozen=True)
class Version:
    """One commit: an evolution step, or an experience record with `level` and `trigger` None.
    `body` excludes the trailers."""

    commit: str
    time: int
    level: Level | None
    trigger: Trigger | None
    subject: str
    body: str


class History:
    """The git history of the agent directory `path`."""

    def __init__(self, path: Path) -> None:
        self._repository = Repository(path)

    @classmethod
    def init(cls, path: Path, agent_id: str) -> "History":
        """Make the existing agent directory `path` a repository committing as `agent_id`."""
        Repository.init(path, user_name=agent_id, user_email=f"{agent_id}@agents.invalid")
        return cls(path)

    def commit_experience(self, time: int) -> Version | None:
        """Commit whatever is uncommitted as plain experience; None if nothing is."""
        return self._commit(f"Record experience up to {format_time(time)}", "", time, {})

    def commit_step(
        self, level: Level, trigger: Trigger, time: int, subject: str, body: str = ""
    ) -> Version | None:
        """Commit one evolution step; None if it changed no file."""
        return self._commit(subject, body, time, {"Level": level, "Trigger": trigger})

    def log(self) -> list[Version]:
        """Every version, newest first."""
        return [_parse(commit) for commit in self._repository.log()]

    def head(self) -> str:
        return self._repository.head()

    def reset(self, commit: str) -> None:
        """Make the directory exactly `commit`, discarding everything after it."""
        self._repository.reset_hard(commit)

    def tag(self, name: str, commit: str = "HEAD") -> None:
        self._repository.tag(name, commit)

    def export(self, commit: str, destination: Path) -> None:
        """Write `commit` without history into the new directory `destination`, which
        `Agent.load` can open."""
        self._repository.export(commit, destination)

    def _commit(
        self, subject: str, body: str, time: int, trailers: dict[str, str]
    ) -> Version | None:
        block = "\n".join(
            f"{key}: {value}" for key, value in {**trailers, "Sim-Time": time}.items()
        )
        message = "\n\n".join(part for part in (subject, body.strip(), block) if part)
        if not self._repository.has_changes():
            return None
        self._repository.commit(message, date=commit_date(time))
        return self.log()[0]


def _parse(commit: Commit) -> Version:
    body, _, block = commit.body.rpartition("\n\n")
    trailers = dict(line.split(": ", 1) for line in block.splitlines())
    return Version(
        commit=commit.id,
        time=int(trailers["Sim-Time"]),
        level=Level(trailers["Level"]) if "Level" in trailers else None,
        trigger=Trigger(trailers["Trigger"]) if "Trigger" in trailers else None,
        subject=commit.subject,
        body=body,
    )
