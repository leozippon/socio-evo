"""The episodic stream: the agent's experience in the order it happened."""

from collections.abc import Iterable, Mapping
from pathlib import Path

from pydantic import Field, JsonValue, NonNegativeInt

from core.interaction import EventKind, Percept, SimTime
from infrastructure.config import StrictModel
from infrastructure.storage import append_jsonl, read_jsonl


class Record(StrictModel):
    """One experience: a witnessed event, with its event `seq` and `kind`, or one of the
    agent's own decisions, with both None. `text` is what the agent perceived or did; `place`
    is the id of where it happened, and `where` the name the agent knows that place by, when
    it was known as the record was made (records made before names, or kinds, were kept have
    none)."""

    time: SimTime
    place: str | None = None
    where: str | None = None
    seq: NonNegativeInt | None = None
    kind: EventKind | None = None
    text: str
    task_id: str | None = None
    activity_id: str | None = None
    decision_id: str | None = None
    action: dict[str, JsonValue] | None = None
    skill_trace: dict[str, JsonValue] = Field(default_factory=dict)
    related_decisions: tuple[str, ...] = ()

    @classmethod
    def of(cls, percept: Percept, names: Mapping[str, str] | None = None) -> "Record":
        """The record of `percept`, naming its place as `names` (by place id) do; a move,
        witnessed at either of its ends and told with both, names none."""
        known = names is not None and percept.place is not None
        where = names.get(percept.place) if known and percept.kind is not EventKind.MOVE else None
        return cls(
            time=percept.time,
            place=percept.place,
            where=where,
            seq=percept.seq,
            kind=percept.kind,
            text=percept.text,
            task_id=percept.task_id,
            activity_id=percept.activity_id,
        )


class EpisodicStream:
    """`memory/episodic.jsonl`, one record per line in time order. It is only appended to,
    except by consolidation, which drops a prefix of old records."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, records: Iterable[Record]) -> None:
        for record in records:
            append_jsonl(self.path, record.model_dump(mode="json"))

    def read(self) -> list[Record]:
        return [Record.model_validate(line) for line in read_jsonl(self.path)]

    def drop_before(self, time: int) -> int:
        """Remove the records earlier than `time`, keeping the other lines byte for byte;
        returns how many were removed."""
        lines = self.path.read_text(encoding="utf-8").splitlines(keepends=True)
        kept = [
            line for line, record in zip(lines, self.read(), strict=True) if record.time >= time
        ]
        self.path.write_text("".join(kept), encoding="utf-8")
        return len(lines) - len(kept)
