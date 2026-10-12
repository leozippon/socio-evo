"""An agent's version history: its git repository, in domain terms.

Each commit message ends with a trailer block: `Sim-Time` (simulated minutes) on every
commit, and `Level` and `Trigger` on evolution steps. The commit date is the simulated time
itself, counted from midnight (UTC) of the date of day 1 in the town's setting, so history is
deterministic.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from core.agent.evolution.levels import Level, Trigger
from core.interaction import format_time
from infrastructure.git import Commit, Repository


def commit_date(time: int, start: date) -> datetime:
    """The commit date of simulated `time` in a town whose day 1 is `start`."""
    return datetime(start.year, start.month, start.day, tzinfo=UTC) + timedelta(minutes=time)


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
    """The git history of the agent directory `path`, in a town whose day 1 is `start`, from
    which the dates of new commits follow. A history opened without `start` can be read, reset
    and exported, but not committed to."""

    def __init__(self, path: Path, start: date | None = None) -> None:
        self._repository = Repository(path)
        self._start = start

    @classmethod
    def init(cls, path: Path, agent_id: str, start: date) -> "History":
        """Make the existing agent directory `path` a repository committing as `agent_id`."""
        Repository.init(path, user_name=agent_id, user_email=f"{agent_id}@agents.invalid")
        return cls(path, start)

    def commit_experience(self, time: int) -> Version | None:
        """Commit whatever is uncommitted as plain experience; None if nothing is."""
        if not self._repository.has_changes():
            return None
        return self._commit(f"Record experience up to {format_time(time)}", "", time, {}, False)

    def commit_step(
        self, level: Level, trigger: Trigger, time: int, subject: str, body: str = ""
    ) -> Version:
        """Commit one applied evolution step, as an empty commit if it changed no file: the
        step happened either way."""
        return self._commit(subject, body, time, {"Level": level, "Trigger": trigger}, True)

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
        self, subject: str, body: str, time: int, trailers: dict[str, str], allow_empty: bool
    ) -> Version:
        if self._start is None:
            raise ValueError("a history opened without the date of day 1 cannot be committed to")
        block = "\n".join(
            f"{key}: {value}" for key, value in {**trailers, "Sim-Time": time}.items()
        )
        message = "\n\n".join(part for part in (subject, body.strip(), block) if part)
        when = commit_date(time, self._start)
        self._repository.commit(message, date=when, allow_empty=allow_empty)
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
