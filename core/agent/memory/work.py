"""Owned, task-scoped work journals. Facts are percepts; intentions are never outcomes.

The append-only entries are authoritative. state.json is a readable projection rebuilt on
write; reads derive it from the log so a checkpoint or interrupted write cannot leave stale
progress. Neither hidden environment payloads nor another resident's journal are accepted.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import Field

from core.agent.config import WorkNotesConfig
from core.agent.context import Block
from core.agent.memory.retrieval import _STOPWORDS, _relevance, _words
from core.interaction import (
    EventKind,
    Observation,
    Percept,
    Setting,
    clock_of,
    day_of,
    job_id,
    job_name,
    lived_day,
)
from infrastructure.config import StrictModel
from infrastructure.storage import append_jsonl, read_jsonl

_GENERIC = _STOPWORDS | set(
    (
        "job jobs work working office home here there now today says said "
        "people clerk board note notes"
    ).split()
)


# Only operational receipts are compressed; task-related conversation remains ordinary memory.
OPERATIONS = {
    EventKind.COMMAND_EXECUTED,
    EventKind.WORK_CHECKED,
    EventKind.WORK_DELAYED,
    EventKind.ACTIVITY_FEEDBACK,
    EventKind.CODE_HANDOFF,
    EventKind.DESK,
    EventKind.ACTIVITY_LEFT,
}


def operation(record) -> bool:
    return record.task_id is not None and record.kind in OPERATIONS


def reference(record):
    if not operation(record):
        return record
    return record.model_copy(
        update={
            "text": f"Your operation on {job_name(record.task_id)} is in your private work record "
            f"(source: percept:{record.seq}). Read that job's notes for the result."
        }
    )


class ReadWorkLog(StrictModel):
    thought: str = Field(max_length=1000)
    do: Literal["read work record"]
    start: int = Field(default=1, ge=1)
    offset: int = Field(default=0, ge=0)


class WorkNotes:
    def __init__(self, root: Path):
        self.root = root

    def _safe(self, path: Path) -> bool:
        relative = path.relative_to(self.root)
        return (
            not self.root.parent.is_symlink()
            and not self.root.is_symlink()
            and all(
                not self.root.joinpath(*relative.parts[:i]).is_symlink()
                for i in range(1, len(relative.parts) + 1)
            )
        )

    def _directory(self, task: str) -> Path:
        if not re.fullmatch(r"task-\d+", task):
            raise ValueError("work notes require a canonical task identifier")
        directory = self.root / task
        if not self._safe(directory) or not self._safe(directory / "events.jsonl"):
            raise ValueError("symlinked work notes are not accessible")
        return directory

    def entries(self, task: str, now: int | None = None) -> list[dict]:
        path = self._directory(task) / "events.jsonl"
        if not path.exists():
            return []
        # Physical append order supplies stable identities for old journals too.
        return [
            dict(entry, entry=index)
            for index, entry in enumerate(read_jsonl(path), 1)
            if now is None or entry["time"] <= now
        ]

    def tasks(self) -> list[str]:
        if not self._safe(self.root):
            return []
        return [
            p.name
            for p in sorted(self.root.glob("task-*"))
            if re.fullmatch(r"task-\d+", p.name)
            and self._safe(p)
            and self._safe(p / "events.jsonl")
        ]

    def append(self, task: str, entry: dict) -> None:
        directory = self._directory(task)
        records = self.entries(task)
        if any(old["id"] == entry["id"] for old in records):
            return
        directory.mkdir(parents=True, exist_ok=True)
        if not self._safe(directory / "state.json") or not self._safe(directory / "state.tmp"):
            raise ValueError("symlinked note state is not writable")
        append_jsonl(directory / "events.jsonl", dict(entry, entry=len(records) + 1))
        temporary = directory / "state.tmp"
        temporary.write_text(json.dumps(self.state(task), ensure_ascii=False, indent=2) + "\n")
        temporary.replace(directory / "state.json")

    def observe(self, percept: Percept) -> None:
        if not operation(percept):
            return
        self.append(
            percept.task_id,
            {
                "id": f"event:{percept.seq}",
                "time": percept.time,
                "type": "observation",
                "kind": percept.kind.value,
                "text": percept.text,
                "actor": percept.actor,
                "source": f"percept:{percept.seq}",
            },
        )

    def record(self, task: str, time: int, kind: str, text: str) -> None:
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        self.append(
            task,
            {
                "id": f"{kind}:{time}:{digest}",
                "time": time,
                "type": kind,
                "text": text,
                "source": f"own:{kind}:{time}",
            },
        )

    def write_note(self, task: str, time: int, text: str) -> None:
        # Agent-authored interpretation, kept separately from witnessed facts.
        directory = self._directory(task)
        target = directory / "note.md"
        temporary = directory / "note.tmp"
        if not self._safe(target) or not self._safe(temporary):
            raise ValueError("symlinked notebook is not writable")
        self.record(task, time, "note", text)
        temporary.write_text(text.strip() + "\n", encoding="utf-8")
        temporary.replace(target)

    def state(self, task: str, now: int | None = None) -> dict:
        entries = self.entries(task, now)

        def latest(kind):
            return next((e for e in reversed(entries) if e["type"] == kind), None)

        return {
            "task_id": task,
            "updated_at": max((e["time"] for e in entries), default=0),
            "entry_count": len(entries),
            "last_observation": latest("observation"),
            "last_intention": latest("intention"),
            "last_work_view": latest("work_view"),
            "last_note": latest("note"),
            "summary_through": list(self.cursor(task)),
        }

    @staticmethod
    def current(observation: Observation) -> set[str]:
        # Work-only allowances already identify the resident's own assigned job. No access
        # to the global board or another agent's assignment is needed.
        return ({observation.own_task_id} if observation.own_task_id else set()) | {
            task
            for allowance in observation.allowed
            if (reference := getattr(allowance, "task_id", None)) is not None
            and (task := job_id(reference)) is not None
        }

    def summaries(self, task: str, now: int | None = None) -> list[dict]:
        records = self.entries(task, now)
        replaced = {identity for e in records for identity in e.get("replaces", [])}
        active = [
            e for e in records if e["type"] in {"summary", "note"} and e["id"] not in replaced
        ]
        return sorted(
            active,
            key=lambda entry: (
                tuple(entry.get("from", (0, 0))),
                tuple(entry.get("through", (0, 0))),
            ),
        )

    def cursor(self, task: str) -> tuple[int, int]:
        summaries = self.summaries(task)
        return max((tuple(e.get("through", (0, 0))) for e in summaries), default=(0, 0))

    def chunk(
        self, task: str, start: tuple[int, int], upper: int, size: int
    ) -> tuple[str, tuple[int, int]]:
        pieces, used, through = [], 0, start
        for e in self.entries(task):
            index = e["entry"]
            if index > upper or index < start[0] or e["type"] not in {"observation", "intention"}:
                continue
            offset = start[1] if index == start[0] else 0
            text = e["text"]
            if offset >= len(text):
                continue
            header = f"Entry {index}, time {e['time']}, {e['type']}, characters {offset}:\n"
            room = size - used - len(header)
            if room <= 0:
                break
            part = text[offset : offset + room]
            pieces.append(header + part)
            used += len(header) + len(part)
            through = (index, offset + len(part))
            if through[1] < len(text):
                break
        return "\n".join(pieces), through

    def save_summary(
        self,
        task: str,
        time: int,
        text: str,
        start: tuple[int, int],
        through: tuple[int, int],
        replaces: list[str] | None = None,
    ) -> None:
        records = self.entries(task)
        covered = [
            e
            for e in records
            if start[0] <= e["entry"] <= through[0]
            and e["type"] in {"observation", "intention"}
            and not (e["entry"] == start[0] and start[1] >= len(e["text"]))
        ]
        self.append(
            task,
            {
                "id": f"summary:{len(records) + 1}",
                "time": time,
                "type": "summary",
                "text": text,
                "source": "your working summary",
                "from": list(start),
                "through": list(through),
                "period": [
                    min((e["time"] for e in covered), default=time),
                    max((e["time"] for e in covered), default=time),
                ],
                "replaces": replaces or [],
            },
        )

    def read_range(self, task: str, start: int, offset: int, size: int = 6000) -> str:
        text, through = self.chunk(task, (start, offset), len(self.entries(task)), size)
        return (text or "No work operations in that range.") + (
            f"\nContinue at entry {through[0]}, character {through[1]}." if text else ""
        )

    def project(self, records):
        return [record for record in records if not operation(record)]

    def render(
        self,
        task: str,
        now: int,
        config: WorkNotesConfig,
        setting: Setting,
        *,
        recent: bool = False,
    ) -> str:
        lines = [
            f"Your work notes for {job_name(task)}:",
            "Your own working summaries are interpretations, not verified results.",
        ]
        for record in self.summaries(task, now):
            begin, end = record.get("period", [record["time"], record["time"]])

            def when(time):
                return f"{lived_day(day_of(time), setting.start_date)}, {clock_of(time)}"

            lines.append(f"{when(begin)} to {when(end)} — {record['text']}")
        if len(lines) == 2:
            lines.append("Operations are saved; no working summary has been written yet.")
        if recent:
            records = [e for e in self.entries(task, now) if e["type"] == "observation"]
            for record in records[-config.recent_entries :]:
                text = record["text"]
                if len(text) > config.excerpt_chars:
                    half = (config.excerpt_chars - 30) // 2
                    text = text[:half] + "\n[excerpt shortened]\n" + text[-half:]
                lines.append(f"Recent operation (source: {record['source']}):\n{text}")
        return "\n\n".join(lines)

    def select(
        self,
        observation: Observation,
        config: WorkNotesConfig,
        setting: Setting,
        *,
        recent=True,
    ) -> list[Block]:
        current = self.current(observation)
        owned = self.tasks()
        query_text = " ".join([observation.situation, *(p.text for p in observation.percepts)])
        explicit = {f"task-{int(n)}" for n in re.findall(r"\bjob\s+(\d+)\b", query_text, re.I)}
        query = _words(query_text) - _GENERIC
        candidates = [task for task in owned if task not in current]
        texts = [
            "\n".join(e["text"] for e in self.summaries(task, observation.time))
            for task in candidates
        ]
        scores = _relevance(query, texts)
        ranked = sorted(
            zip(candidates, texts, scores, strict=True),
            key=lambda row: (row[0] in explicit, row[2]),
            reverse=True,
        )
        related = [
            task
            for task, text, score in ranked
            if task in explicit or (score > 0 and len(query & _words(text)) >= 2)
        ][: config.related_notes]
        return [
            Block(
                f"work-note:{task}",
                self.render(
                    task,
                    observation.time,
                    config,
                    setting,
                    recent=recent and observation.work_activity and task in current,
                ),
                95 if task in current else 60,
            )
            for task in [*sorted(current & set(owned)), *related]
            if self.entries(task, observation.time)
        ]

    def daily(self, now: int, config: WorkNotesConfig, setting: Setting) -> list[Block]:
        """A compact view of jobs actually touched today, not the entire work archive."""
        return [
            Block(f"work-note:{task}", self.render(task, now, config, setting), 75)
            for task in self.tasks()
            if any(day_of(entry["time"]) == day_of(now) for entry in self.entries(task, now))
        ]
