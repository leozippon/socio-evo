"""The episodic stream: the agent's experience in the order it happened."""

from collections.abc import Iterable
from pathlib import Path

from pydantic import NonNegativeInt

from core.interaction import Percept, SimTime
from infrastructure.config import StrictModel
from infrastructure.storage import append_jsonl, read_jsonl


class Record(StrictModel):
    """One experience: a witnessed event, with its event `seq`, or one of the agent's own
    decisions, with `seq` None. `text` is what the agent perceived or did."""

    time: SimTime
    place: str | None = None
    seq: NonNegativeInt | None = None
    text: str

    @classmethod
    def of(cls, percept: Percept) -> "Record":
        return cls(time=percept.time, place=percept.place, seq=percept.seq, text=percept.text)


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
