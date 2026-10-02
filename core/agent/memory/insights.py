"""Insights: consolidated reflections, including beliefs about particular agents."""

import json
from collections.abc import Iterable
from pathlib import Path

from pydantic import PositiveInt

from infrastructure.config import StrictModel
from infrastructure.storage import read_jsonl


class Insight(StrictModel):
    """A belief the agent holds. `day` is when it was last written; `subject` is the id of the
    agent it concerns, if any."""

    id: PositiveInt
    day: PositiveInt
    text: str
    subject: str | None = None


class InsightStore:
    """`memory/insights.jsonl`, rewritten as a whole whenever the insights change."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> list[Insight]:
        return [Insight.model_validate(line) for line in read_jsonl(self.path)]

    def write(self, insights: Iterable[Insight]) -> None:
        self.path.write_text(
            "".join(
                json.dumps(insight.model_dump(mode="json"), ensure_ascii=False) + "\n"
                for insight in insights
            ),
            encoding="utf-8",
        )
