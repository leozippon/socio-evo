"""The append-only event log and each agent's perception cursor."""

import os
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from pydantic import JsonValue

from core.interaction import Event, EventKind, Percept
from infrastructure.storage import append_jsonl


class EventLog:
    """Events appended to the JSONL file at `path`, numbered by `seq` from 0.

    An agent's cursor is the length of the log when it last perceived; its unread events are
    the later ones whose audience includes it. They are held in memory, so the file is only
    appended to, except when a log is resumed.
    """

    def __init__(
        self, path: Path, count: int, cursors: dict[str, int], unread: dict[str, list[Event]]
    ) -> None:
        self.path = path
        self.count = count
        self.cursors = cursors
        self._unread = unread

    @classmethod
    def create(cls, path: Path, agents: Sequence[str]) -> "EventLog":
        """A new, empty log at `path` for `agents`; raises FileExistsError if the file exists."""
        path.touch(exist_ok=False)
        return cls(path, 0, dict.fromkeys(agents, 0), {agent: [] for agent in agents})

    @classmethod
    def resume(cls, path: Path, count: int, cursors: Mapping[str, int]) -> "EventLog":
        """The log at `path` cut back to its first `count` events, with the given cursors.

        Everything written after those events, complete or not, is removed from the file.
        Raises ValueError if the file holds fewer than `count` complete events or an unread
        event out of sequence.
        """
        unread: dict[str, list[Event]] = {agent: [] for agent in cursors}
        oldest_unread = min(cursors.values(), default=count)
        with path.open("r+b") as file:
            for seq in range(count):
                line = file.readline()
                if not line.endswith(b"\n"):
                    raise ValueError(f"{path}: {seq} complete events, expected {count}")
                if seq < oldest_unread:
                    continue
                event = Event.model_validate_json(line)
                if event.seq != seq:
                    raise ValueError(f"{path}:{seq + 1}: event numbered {event.seq}")
                for agent in event.audience:
                    if seq >= cursors[agent]:
                        unread[agent].append(event)
            file.truncate(file.tell())
            os.fsync(file.fileno())
        return cls(path, count, dict(cursors), unread)

    def append(
        self,
        kind: EventKind,
        text: str,
        *,
        time: int,
        audience: Collection[str] = (),
        actor: str | None = None,
        place: str | None = None,
        scene: str | None = None,
        payload: dict[str, JsonValue] | None = None,
    ) -> Event:
        """Record the next event, witnessed by the agents in `audience`, and return it.

        The audience is stored in the log's agent order; an unknown agent raises ValueError.
        """
        witnesses = set(audience)
        if unknown := witnesses - self.cursors.keys():
            raise ValueError(f"unknown agents in audience: {sorted(unknown)}")
        event = Event(
            seq=self.count,
            time=time,
            kind=kind,
            actor=actor,
            place=place,
            scene=scene,
            audience=tuple(agent for agent in self.cursors if agent in witnesses),
            text=text,
            payload=payload or {},
        )
        append_jsonl(self.path, event.model_dump(mode="json"))
        self.count += 1
        for agent in event.audience:
            self._unread[agent].append(event)
        return event

    def perceive(self, agent: str) -> tuple[Percept, ...]:
        """The percepts of the events `agent` witnessed since it last perceived; advances its
        cursor to the end of the log."""
        unread, self._unread[agent] = self._unread[agent], []
        self.cursors[agent] = self.count
        return tuple(event.percept() for event in unread)
