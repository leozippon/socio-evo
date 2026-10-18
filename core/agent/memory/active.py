"""Private lexical recall of persisted memories; never reads the run's truth log or Git.

Sources are enumerated by the system, not supplied by the model. Search document chunks,
not only prefixes, so a query can recover a fact late in a diary or skill note.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field

from core.agent.config import ActiveRecallConfig
from core.agent.memory import Memory
from core.agent.memory.retrieval import _STOPWORDS, _relevance, _words
from core.interaction import Setting, clock_of, day_of, lived_day
from infrastructure.config import StrictModel


class Remember(StrictModel):
    thought: str = Field(max_length=1000)
    do: Literal["recall something"]
    query: str = Field(min_length=1, max_length=500, pattern=r"\S")


@dataclass(frozen=True)
class MemoryHit:
    source: str
    when: str
    text: str
    time: int

    def render(self, setting: Setting) -> str:
        """Residents see the calendar and their own kind of note; logs retain file IDs."""
        date = lived_day(day_of(self.time), setting.start_date)
        if self.source.startswith("memory/episodic"):
            source = f"your recollection, {date}, {clock_of(self.time)}"
        elif self.source.startswith("memory/diary"):
            source = f"your diary for {date}"
        elif self.source.startswith("memory/insights"):
            source = f"what you wrote you believed on {date}"
        elif self.source.startswith("memory/work/"):
            task = self.source.split("/")[2].removeprefix("task-")
            source = f"your work notes for job {task}, {date}, {clock_of(self.time)}"
        else:
            title = Path(self.source.split("#", 1)[0]).stem.replace("-", " ")
            source = f"your notebook, {title}; read on {date}; date of writing unknown"
        return f"[{source}]\n{self.text}"


def search(memory: Memory, query: str, now: int, config: ActiveRecallConfig) -> list[MemoryHit]:
    root = memory.episodic.path.parent

    def safe(path: Path) -> bool:
        # An exported agent directory may itself be reached through a deployment symlink;
        # inside its memory directory no symlinks are accepted, even to another own file.
        relative = path.relative_to(root)
        return not root.is_symlink() and all(
            not (root.joinpath(*relative.parts[:i])).is_symlink()
            for i in range(1, len(relative.parts) + 1)
        )

    documents: list[MemoryHit] = []

    def add(source: str, when: str, text: str, time: int) -> None:
        size = config.snippet_chars
        for offset in range(0, len(text), max(1, size - 100)):
            documents.append(
                MemoryHit(f"{source}#char={offset}", when, text[offset : offset + size], time)
            )

    if safe(memory.episodic.path):
        for index, record in enumerate(memory.episodic.read()):
            if record.time <= now:
                minute = record.time % 1440
                add(
                    f"memory/episodic.jsonl:record={index + 1}",
                    f"day {day_of(record.time)}, {minute // 60:02}:{minute % 60:02}",
                    record.text,
                    record.time,
                )
    if safe(memory.insights.path):
        for insight in memory.insights.read():
            if insight.day <= day_of(now):
                add(
                    f"memory/insights.jsonl:id={insight.id}",
                    f"day {insight.day}",
                    f"{insight.subject + ': ' if insight.subject else ''}{insight.text}",
                    (insight.day - 1) * 1440,
                )
    if safe(memory.diary.directory):
        for path in sorted(memory.diary.directory.glob("day-*.md")):
            if safe(path) and path.stem[4:].isdigit():
                day = int(path.stem[4:])
                # Diaries are written after that day's actions, not available earlier.
                if day < day_of(now):
                    add(
                        f"memory/diary/{path.name}",
                        f"day {day}",
                        path.read_text(encoding="utf-8"),
                        (day - 1) * 1440,
                    )
    if safe(memory.skills.directory):
        for path in sorted(memory.skills.directory.glob("*.md")):
            if safe(path):
                add(
                    f"memory/skills/{path.name}",
                    f"current note, read on day {day_of(now)}; creation time not recorded",
                    path.read_text(encoding="utf-8"),
                    now,
                )
    for task in memory.work.tasks():
        for entry in memory.work.entries(task, now):
            if entry["type"] == "work_view":
                continue
            label = (
                "Intended action, not a confirmed outcome"
                if entry["type"] == "intention"
                else "Observed"
            )
            add(
                f"memory/work/{task}/events.jsonl:id={entry['id']}",
                f"day {day_of(entry['time'])}",
                f"{label} for job {task.removeprefix('task-')}: {entry['text']}",
                entry["time"],
            )
    scores = _relevance(_words(query) - _STOPWORDS, [hit.text for hit in documents])
    ranked = sorted(
        zip(documents, scores, strict=True), key=lambda item: (item[1], item[0].time), reverse=True
    )
    seen: set[str] = set()
    hits = []
    for hit, score in ranked:
        if score > 0 and hit.text not in seen:
            hits.append(hit)
            seen.add(hit.text)
            if len(hits) == config.max_results:
                break
    return hits
