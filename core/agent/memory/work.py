"""Owned, task-scoped work journals. Facts are percepts; intentions are never outcomes.

The append-only entries are authoritative. state.json is a readable projection rebuilt on
write; reads derive it from the log so a checkpoint or interrupted write cannot leave stale
progress. Neither hidden environment payloads nor another resident's journal are accepted.
"""

import hashlib
import json
import re
from pathlib import Path

from core.agent.config import WorkNotesConfig
from core.agent.context import Block
from core.agent.memory.retrieval import _STOPWORDS, _relevance, _words
from core.interaction import (
    Observation,
    Percept,
    Setting,
    clock_of,
    day_of,
    job_id,
    job_name,
    lived_day,
)
from infrastructure.storage import append_jsonl, read_jsonl

_GENERIC = _STOPWORDS | set(
    (
        "job jobs work working office home here there now today says said "
        "people clerk board note notes"
    ).split()
)


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
        return [entry for entry in read_jsonl(path) if now is None or entry["time"] <= now]

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
        append_jsonl(directory / "events.jsonl", entry)
        temporary = directory / "state.tmp"
        temporary.write_text(json.dumps(self.state(task), ensure_ascii=False, indent=2) + "\n")
        temporary.replace(directory / "state.json")

    def observe(self, percept: Percept) -> None:
        if percept.task_id is None:
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
        }

    @staticmethod
    def current(observation: Observation) -> set[str]:
        # Work-only allowances already identify the resident's own assigned job. No access
        # to the global board or another agent's assignment is needed.
        return {
            task
            for allowance in observation.allowed
            if (reference := getattr(allowance, "task_id", None)) is not None
            and (task := job_id(reference)) is not None
        }

    def render(self, task: str, now: int, config: WorkNotesConfig, setting: Setting) -> str:
        records = self.entries(task, now)
        selected = [r for r in records if r["type"] != "work_view"][-config.recent_entries :]
        view = next((r for r in reversed(records) if r["type"] == "work_view"), None)
        if not selected and view:
            selected = [view]
        lines = [f"Your work notes for {job_name(task)}:"]
        for record in selected:
            date = lived_day(day_of(record["time"]), setting.start_date)
            when = f"{date}, {clock_of(record['time'])}"
            label = (
                "Chosen action and thought (not a confirmed result)"
                if record["type"] == "intention"
                else "What you saw"
            )
            text = record["text"]
            size = config.excerpt_chars
            if len(text) > size:
                half = max(1, (size - 30) // 2)
                text = text[:half] + "\n[excerpt shortened]\n" + text[-half:]
            lines.append(f"{when} — {label} (source: {record['source']}):\n{text}")
        return "\n\n".join(lines)

    def select(
        self, observation: Observation, config: WorkNotesConfig, setting: Setting
    ) -> list[Block]:
        current = self.current(observation)
        owned = self.tasks()
        query_text = " ".join([observation.situation, *(p.text for p in observation.percepts)])
        explicit = {f"task-{int(n)}" for n in re.findall(r"\bjob\s+(\d+)\b", query_text, re.I)}
        query = _words(query_text) - _GENERIC
        candidates = [task for task in owned if task not in current]
        texts = [
            "\n".join(
                e["text"] for e in self.entries(task, observation.time) if e["type"] != "work_view"
            )
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
                self.render(task, observation.time, config, setting),
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
