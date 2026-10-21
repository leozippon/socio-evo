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
    job: str
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
                "activity_id": percept.activity_id,
                "visit_id": percept.activity_visit_id,
                "source": f"percept:{percept.seq}",
            },
        )

    def record(
        self,
        task: str,
        time: int,
        kind: str,
        text: str,
        *,
        activity_id: str | None = None,
        visit_id: str | None = None,
    ) -> None:
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        self.append(
            task,
            {
                "id": f"{kind}:{time}:{digest}"
                + (f":{activity_id}:{visit_id or 'legacy'}" if activity_id else ""),
                "time": time,
                "type": kind,
                "text": text,
                "source": f"own:{kind}:{time}",
                "activity_id": activity_id,
                "visit_id": visit_id,
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
        active = observation.activity_task_id if observation.work_activity else None
        return (
            ({active} if active else set())
            | ({observation.own_task_id} if observation.own_task_id else set())
            | {
                task
                for allowance in observation.allowed
                if (reference := getattr(allowance, "task_id", None)) is not None
                and (task := job_id(reference)) is not None
            }
        )

    def begin_activity(
        self, activity_id: str, task: str, time: int, *, visit_id: str | None = None
    ) -> None:
        """Persist a job membership boundary before its first observation is ingested."""
        self.append(
            task,
            {
                "id": f"activity:{activity_id}:{visit_id or 'legacy'}",
                "type": "activity",
                "time": time,
                "activity_id": activity_id,
                "visit_id": visit_id,
                "text": "",
            },
        )

    def pending_scopes(
        self, activity_id: str | None = None, visit_id: str | None = None
    ) -> list[tuple[str, dict]]:
        result = []
        for task in self.tasks():
            records = self.entries(task)
            completed = {e.get("scope_id") for e in records if e["type"] == "summary"}
            result.extend(
                (task, e)
                for e in records
                if e["type"] == "scope"
                and e["id"] not in completed
                and (activity_id is None or e.get("activity_id") == activity_id)
                and (visit_id is None or e.get("visit_id") == visit_id)
            )
        return result

    def freeze_scopes(
        self, time: int, activity_id: str | None = None, visit_id: str | None = None
    ) -> list[tuple[str, dict]]:
        """Snapshot actual job operations, independently of current job ownership.

        An excerpted overview completes a range overview, never character-level reading.
        Untagged legacy records are handled only by nightly catch-up.
        """
        substantive = {
            EventKind.COMMAND_EXECUTED.value,
            EventKind.WORK_CHECKED.value,
        }
        for task in self.tasks():
            records = self.entries(task)
            claimed = {n for e in records if e["type"] == "scope" for n in e["source_entries"]}
            groups = {}
            work_activities = {
                (e["activity_id"], e.get("visit_id")) for e in records if e["type"] == "activity"
            }
            scoped_activities = {
                (e.get("activity_id"), e.get("visit_id")) for e in records if e["type"] == "scope"
            }
            legacy_cursor = self.cursor(task)
            for e in records:
                if e["type"] not in {"observation", "intention"} or e["entry"] in claimed:
                    continue
                activity = e.get("activity_id")
                visit = e.get("visit_id")
                if activity is not None and (activity, visit) not in work_activities:
                    continue
                # A cancelled exit retains its exact snapshot. Late receipts are left
                # for nightly supplemental catch-up, never another exit-time call.
                if activity_id is not None and (activity, visit) in scoped_activities:
                    continue
                if activity_id is not None and (
                    activity != activity_id or (visit_id is not None and visit != visit_id)
                ):
                    continue
                if activity is None and (e["entry"], len(e["text"])) <= legacy_cursor:
                    continue
                groups.setdefault((activity, visit), []).append(e)
            for (activity, visit), entries in groups.items():
                # Only receipts emitted after executing a command or test establish actual work.
                if not any(
                    e["type"] == "observation" and e.get("kind") in substantive for e in entries
                ):
                    continue
                scope = {
                    "id": (
                        f"scope:{activity or 'legacy'}:{visit or 'legacy'}:"
                        f"{entries[0]['entry']}:{entries[-1]['entry']}"
                    ),
                    "type": "scope",
                    "time": time,
                    "text": "",
                    "activity_id": activity,
                    "visit_id": visit,
                    "legacy": activity is None,
                    "source_entries": [e["entry"] for e in entries],
                }
                self.append(task, scope)
        return self.pending_scopes(activity_id, visit_id)

    def scope_records(self, task: str, scope: dict) -> list[dict]:
        wanted = set(scope["source_entries"])
        return [e for e in self.entries(task) if e["entry"] in wanted]

    def save_overview(self, task: str, scope: dict, time: int, text: str, input_mode: str) -> None:
        if any(
            e.get("scope_id") == scope["id"] for e in self.entries(task) if e["type"] == "summary"
        ):
            return
        records = self.scope_records(task, scope)
        self.append(
            task,
            {
                "id": f"overview:{scope['id']}",
                "type": "summary",
                "time": time,
                "text": text,
                "source": "your activity overview",
                "scope_id": scope["id"],
                "activity_id": scope.get("activity_id"),
                "visit_id": scope.get("visit_id"),
                "legacy": scope.get("legacy", False),
                "source_entries": scope["source_entries"],
                "input_mode": input_mode,
                "period": [min(e["time"] for e in records), max(e["time"] for e in records)],
                "from": [records[0]["entry"], 0],
                "through": [0, 0],
                "replaces": [],
            },
        )

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
        summaries = [e for e in self.entries(task) if e["type"] == "summary"]
        return max((tuple(e.get("through", (0, 0))) for e in summaries), default=(0, 0))

    def chunk(
        self, task: str, start: tuple[int, int], upper: int, size: int, *, now: int | None = None
    ) -> tuple[str, tuple[int, int]]:
        pieces, used, through = [], 0, start
        for e in self.entries(task, now):
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
        sources = [e for e in records if e["id"] in (replaces or [])]
        periods = [e.get("period", [e["time"], e["time"]]) for e in sources]
        periods.extend([e["time"], e["time"]] for e in covered)
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
                    min((period[0] for period in periods), default=time),
                    max((period[1] for period in periods), default=time),
                ],
                "replaces": replaces or [],
            },
        )

    def previous(self, observation: Observation) -> list[str]:
        """Only this resident's previously observed jobs, excluding current assignments."""
        current = self.current(observation)
        return [
            task
            for task in self.tasks()
            if task not in current
            and any(e["type"] == "observation" for e in self.entries(task, observation.time))
        ]

    def read_range(
        self, task: str, start: int, offset: int, size: int = 6000, *, now: int | None = None
    ) -> str:
        records = self.entries(task, now)
        upper = records[-1]["entry"] if records else 0
        text, through = self.chunk(task, (start, offset), upper, size, now=now)
        return (text or "No work operations in that range.") + (
            f"\nContinue at entry {through[0]}, character {through[1]}." if text else ""
        )

    def raw(self, task: str, now: int) -> list[Block]:
        records = [e for e in self.entries(task, now) if e["type"] == "observation"]
        if not records:
            return []

        def render(entry):
            return (
                f"Original feedback for {job_name(task)}, entry {entry['entry']} "
                f"(source: {entry['source']}, day {day_of(entry['time'])} "
                f"{clock_of(entry['time'])}):\n{entry['text']}"
            )

        latest = next(
            (
                i
                for i in range(len(records) - 1, -1, -1)
                if records[i].get("kind")
                in {
                    EventKind.COMMAND_EXECUTED.value,
                    EventKind.WORK_CHECKED.value,
                }
            ),
            len(records) - 1,
        )
        entry = records[latest]["entry"]
        return [
            *(
                [
                    Block(
                        f"work-log:{task}:before-{entry}",
                        "\n\n".join(render(e) for e in records[:latest]),
                        95,
                        tail=True,
                    )
                ]
                if latest
                else []
            ),
            Block(
                f"work-log:{task}:{entry}",
                "\n\n".join(render(e) for e in records[latest:]),
                100,
                required=True,
            ),
        ]

    def project(self, records):
        return [record for record in records if not operation(record)]

    def render(
        self,
        task: str,
        now: int,
        config: WorkNotesConfig,
        setting: Setting,
    ) -> str:
        lines = [
            f"Your work notes for {job_name(task)}:",
            "Your own working summaries are interpretations, not verified results.",
        ]
        for record in self.summaries(task, now)[-3:]:
            begin, end = record.get("period", [record["time"], record["time"]])

            def when(time):
                return f"{lived_day(day_of(time), setting.start_date)}, {clock_of(time)}"

            lines.append(f"{when(begin)} to {when(end)} — {record['text']}")
        if len(lines) == 2:
            lines.append("Operations are saved; no working summary has been written yet.")
        return "\n\n".join(lines)

    def select(
        self,
        observation: Observation,
        config: WorkNotesConfig,
        setting: Setting,
    ) -> list[Block]:
        if observation.work_activity:
            return [
                block
                for task in sorted(self.current(observation))
                for block in self.raw(task, observation.time)
            ]
        if observation.activity_kind is not None:
            task = observation.activity_task_id
            if task is None or observation.activity_kind not in {"work", "conversation"}:
                return []
            if not self.entries(task, observation.time):
                return []
            return [
                Block(
                    f"work-note:{task}",
                    self.render(
                        task,
                        observation.time,
                        config,
                        setting,
                    ),
                    95,
                )
            ]
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
