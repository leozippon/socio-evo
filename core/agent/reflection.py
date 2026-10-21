"""Bounded private reflection, with frozen owned sources and durable completion records."""

import asyncio
from typing import Literal

from pydantic import Field, RootModel, create_model, model_validator

from core.agent import prompts
from core.agent.config import ContextBudgetConfig
from core.agent.context import ContextOverflow, Counter, input_limit
from core.agent.continuation import ContinuationClient, DecisionContinuation, current
from core.interaction import day_of, form, job_name
from infrastructure.config import StrictModel
from infrastructure.llm import Message, complete_structured
from infrastructure.storage import append_jsonl, read_jsonl


def _check_cancelled():
    running = asyncio.current_task()
    if running is not None and running.cancelling():
        raise asyncio.CancelledError


async def _generate(
    agent,
    time,
    purpose,
    instruction,
    records,
    model_for,
    *,
    scope_id=None,
    reserve=4,
    allow_read=False,
    source_reader=None,
):
    budget = agent.cognition.context_budget
    counting = budget if budget.enabled else ContextBudgetConfig(enabled=True)
    counter = Counter(counting)
    parent = current.get()
    base = agent._request(
        purpose, time, "You are writing your private reflective notes.", instruction
    )
    room = input_limit(counting, base) - counter.request(base) - 600
    length = min(1600, max(1, room // 12))
    final_model = model_for(length)
    model = final_model
    source_index = {record["entry"]: record for record in records}

    class ReadSource(StrictModel):
        do: Literal["read source"]
        entry: int
        offset: int = Field(default=0, ge=0)

        @model_validator(mode="after")
        def owned_entry(self):
            if self.entry not in source_index:
                raise ValueError("Read only an entry in this reflection's source index.")
            return self

    class Leave(StrictModel):
        do: Literal["leave"]

    if allow_read:
        model = RootModel[ReadSource | final_model | Leave]
        instruction += (
            " You may first read source with an indexed entry and character offset; "
            "at most two reads of 6000 characters are available, then finish your reflection. "
            "You may leave without saving a reflection or changing your memories."
        )
    # Retain room for a bounded failed reply and the concise correction.
    target_limit = input_limit(counting, base) - length * reserve - 600
    index = "Operation index (entry, time, kind, original characters):\n" + "\n".join(
        f"{e['entry']} {e['time']} {e.get('kind', e['type'])} {len(e['text'])}" for e in records
    )

    def request_for(material, mode):
        return base.model_copy(
            update={
                "messages": (
                    *base.messages[:-1],
                    Message(
                        role="user",
                        content=(
                            instruction
                            + " Keep each response field within its schema; "
                            + f"reflection/summary limit: {length} characters."
                            + "\n\n"
                            + material
                            + "\n\n"
                            + form(model)
                        ),
                    ),
                ),
                "json_schema": model.model_json_schema(),
                "structured_output": "json_schema",
                "metadata": {
                    **base.metadata,
                    "work_scope_id": scope_id,
                    "reflection_id": scope_id,
                    "work_input_mode": mode,
                },
            }
        )

    # Rich experience schemas and read/leave alternatives also consume input space.
    # Reduce output bounds before clipping source text, retaining one authoritative budget.
    while counter.request(request_for(index, "excerpted")) > target_limit:
        if length == 1:
            raise ContextOverflow("Reflection schema and source index cannot fit the input budget")
        length = max(1, length // 2)
        final_model = model_for(length)
        model = RootModel[ReadSource | final_model | Leave] if allow_read else final_model
        target_limit = input_limit(counting, base) - length * reserve - 600

    full = index + "\n\n" + "\n\n".join(f"Entry {e['entry']}:\n{e['text']}" for e in records)
    request = request_for(full, "full")
    mode = "full"
    if counter.request(request) > target_limit:
        mode = "excerpted"
        notice = (
            "Only excerpts follow; omitted text has NOT been read. "
            "This is a range overview, "
            "not a claim to have checked every character. "
            "Use the original entries for details.\n"
        )
        allowance = max(0, target_limit - counter.request(request_for(index + notice, mode)) - 128)
        # Keep every operation in the index and distribute head/tail excerpts
        # across the range; no extra model call is made.
        while True:
            per_entry = allowance // max(1, len(records))
            excerpts = []
            for e in records:
                excerpt = counter.clip(e["text"], per_entry)
                if excerpt:
                    excerpts.append(f"Entry {e['entry']}:\n{excerpt}")
            request = request_for(index + "\n\n" + notice + "\n\n".join(excerpts), mode)
            if counter.request(request) <= target_limit:
                break
            if allowance == 0:
                raise ContextOverflow("Work operation index cannot fit the input budget")
            allowance //= 2
    isolated = DecisionContinuation()
    if parent is not None:
        isolated.metadata = dict(parent.metadata)
    client = ContinuationClient(agent.client, isolated, budget=counting)
    for attempt in range(3):
        reply = await complete_structured(client, request, model)
        _check_cancelled()
        if allow_read and isinstance(reply, RootModel):
            reply = reply.root
        if not isinstance(reply, ReadSource):
            return reply, mode
        record = source_index[reply.entry]
        original = source_reader(record) if source_reader is not None else record["text"]
        text = original[reply.offset : reply.offset + 6000]
        material = (
            index + f"\nRequested source entry {reply.entry}, character {reply.offset}:\n" + text
        )
        # Each lookup replaces earlier excerpts; the frozen record remains authoritative.
        isolated = DecisionContinuation()
        if parent is not None:
            isolated.metadata = dict(parent.metadata)
        client = ContinuationClient(agent.client, isolated, budget=counting)
        if attempt == 1:
            model = RootModel[final_model | Leave]
        request = request_for(material, mode)
        if counter.request(request) > target_limit:
            available = max(0, target_limit - counter.request(request_for(index, mode)) - 128)
            request = request_for(
                index + "\nRequested source excerpt:\n" + counter.clip(text, available), mode
            )
        if counter.request(request) > target_limit:
            raise ContextOverflow("Requested source cannot fit reflection input budget")
    raise AssertionError("Reflection source reads must end with a final result")


def _summary_model(length):
    return create_model("WorkSummary", summary=(str, Field(min_length=1, max_length=length)))


async def summarize_work(agent, time, tasks=None, *, activity_id=None, visit_id=None):
    if not agent.cognition.work_notes.enabled:
        return {"mode": "summary", "status": "completed", "completed": True, "summaries": []}
    notes = agent.memory.work
    parent = current.get()

    async def generate(task, records, *, merging=False, scope=None):
        instruction = (
            f"Organize your earlier notes for {job_name(task)} into one overview. "
            if merging
            else f"Reflect on your work on {job_name(task)} in this visit. "
        ) + (
            "Keep findings, actual changes, observed results, unresolved issues and next steps. "
            "Separate intentions from outcomes. The complete original work record remains "
            "available by entry number through read work record."
        )
        reply, mode = await _generate(
            agent,
            time,
            "work_summary_merge" if merging else "work_summary",
            instruction,
            records,
            _summary_model,
            scope_id=scope["id"] if scope else None,
        )
        return reply.summary, mode

    if parent is not None:
        parent.summarizing_work = True
    try:
        for task, scope in notes.freeze_scopes(time, activity_id, visit_id):
            if activity_id is None and tasks is not None and task not in tasks:
                continue
            text, mode = await generate(task, notes.scope_records(task, scope), scope=scope)
            _check_cancelled()
            notes.save_overview(task, scope, time, text, mode)
        if activity_id is None:
            for task in sorted(tasks if tasks is not None else notes.tasks()):
                summaries = notes.summaries(task)
                if len(summaries) > 3:
                    text, mode = await generate(task, summaries, merging=True)
                    _check_cancelled()
                    notes.save_summary(
                        task, time, text, (0, 0), (0, 0), [e["id"] for e in summaries]
                    )
    finally:
        if parent is not None:
            parent.summarizing_work = False
    return {
        "mode": "summary",
        "status": "completed",
        "completed": True,
        "summaries": [
            {"task_id": task, "text": entry["text"], "scope_id": entry.get("scope_id")}
            for task in notes.tasks()
            for entry in notes.entries(task)
            if entry["type"] == "summary"
            and (activity_id is None or entry.get("activity_id") == activity_id)
            and (visit_id is None or entry.get("visit_id") == visit_id)
        ],
    }


def _journal(agent):
    return agent.path / "memory" / "reflections.jsonl"


def _entries(agent):
    return list(read_jsonl(_journal(agent))) if _journal(agent).exists() else []


def _append(agent, entry):
    append_jsonl(_journal(agent), entry)


def _experience_model(length, scope, insights):
    sources = {r["seq"] for r in scope["records"] if r.get("seq") is not None}
    numbers = {i.id for i in insights}
    text_limit = max(1, length // 4)
    Add = create_model(
        "ReflectAddInsight",
        __base__=prompts.AddInsight,
        belief=(str, Field(min_length=1, max_length=text_limit)),
    )
    Revise = create_model(
        "ReflectReviseInsight",
        __base__=prompts.ReviseInsight,
        belief=(str, Field(min_length=1, max_length=text_limit)),
    )
    Write = create_model(
        "ReflectWriteSkill",
        __base__=prompts.WriteSkill,
        title=(str, Field(min_length=1, max_length=64)),
        summary=(str, Field(min_length=1, max_length=min(600, text_limit))),
        text=(str, Field(min_length=1, max_length=text_limit)),
    )

    Retire = create_model(
        "ReflectRetireSkill",
        __base__=prompts.RetireSkill,
        title=(str, Field(min_length=1, max_length=64)),
    )

    class Experience(StrictModel):
        do: Literal["finish"] = "finish"
        reflection: str = Field(min_length=1, max_length=length)
        sources: list[int] = Field(default_factory=list, max_length=12)
        insights: list[Add | Revise | prompts.RemoveInsight] = Field(
            default_factory=list, max_length=2
        )
        skills: list[Write | Retire] = Field(default_factory=list, max_length=1)

        @model_validator(mode="after")
        def owned_sources(self):
            if any(source not in sources for source in self.sources):
                raise ValueError(
                    "Sources must be witnessed event numbers in this reflection scope."
                )
            if any(
                getattr(change, "number", None) not in numbers
                for change in self.insights
                if hasattr(change, "number")
            ):
                raise ValueError("Use an existing insight number.")
            prompts._once_per_belief(self.insights)
            prompts._once_per_page(self.skills)
            return self

    return Experience


def _freeze_experience(
    agent,
    time,
    identity,
    activity_id,
    visit_id,
    source_since=None,
    source_through=None,
    source_start=None,
    source_end=None,
    source_seq_start=None,
    source_seq_end=None,
):
    existing = next(
        (e for e in _entries(agent) if e["id"] == identity and e["type"] == "scope"), None
    )
    if existing is not None:
        return existing
    records = []
    all_records = agent.memory.episodic.read()
    upper = min(
        len(all_records), source_through if source_through is not None else len(all_records)
    )
    lower = source_since or 0
    for index, record in enumerate(all_records):
        if (
            index < lower
            or index >= upper
            or record.time > time
            or (source_start is not None and record.time < source_start)
            or (source_end is not None and record.time > source_end)
        ):
            continue
        if record.seq is not None:
            if source_seq_start is not None and record.seq < source_seq_start:
                continue
            if source_seq_end is not None and record.seq >= source_seq_end:
                continue
        elif visit_id is not None and record.activity_visit_id != visit_id:
            continue
        if activity_id is not None:
            if record.activity_id != activity_id:
                continue
        elif day_of(record.time) != day_of(time):
            continue
        # Activity speakers may have another visit identity. Ownership is the resident's
        # witnessed stream between their entry/exit boundaries, not the speaker's visit.
        records.append(
            {
                "entry": index + 1,
                "time": record.time,
                "type": "experience",
                "text": record.text,
                "seq": record.seq,
                "activity_id": record.activity_id,
                "visit_id": record.activity_visit_id,
                "task_id": record.task_id,
            }
        )
    scope = {
        "id": identity,
        "type": "scope",
        "time": time,
        "mode": "experience",
        "activity_id": activity_id,
        "visit_id": visit_id,
        "source_since": lower,
        "source_through": upper,
        "source_start": source_start,
        "source_end": source_end,
        "source_seq_start": source_seq_start,
        "source_seq_end": source_seq_end,
        "records": records,
    }
    _append(agent, scope)
    return scope


def reflection_sources(agent, reflection_id, start=0, size=6000):
    if start < 0 or not 1 <= size <= 6000:
        raise ValueError("Use a nonnegative offset and at most 6000 characters.")
    scope = next(
        (e for e in _entries(agent) if e["id"] == reflection_id and e["type"] == "scope"), None
    )
    if scope is None:
        raise ValueError("No owned reflection source scope exists.")
    text = "\n\n".join(
        f"Entry {r['entry']}, source event {r['seq']}:\n{r['text']}" for r in scope["records"]
    )
    return text[start : start + size]


def recent_reflections(agent, time):
    return [
        e
        for e in _entries(agent)
        if e["type"] == "completed"
        and e.get("mode") == "experience"
        and day_of(e["time"]) == day_of(time)
    ]


async def _experience(
    agent,
    time,
    *,
    activity_id,
    visit_id,
    reflection_id,
    source_since=None,
    source_through=None,
    source_start=None,
    source_end=None,
    source_seq_start=None,
    source_seq_end=None,
):
    identity = reflection_id or f"experience:{activity_id or 'day'}:{visit_id or time}"
    completed = next(
        (e for e in _entries(agent) if e["id"] == identity and e["type"] == "completed"), None
    )
    if completed is not None:
        return completed
    scope = _freeze_experience(
        agent,
        time,
        identity,
        activity_id,
        visit_id,
        source_since,
        source_through,
        source_start,
        source_end,
        source_seq_start,
        source_seq_end,
    )
    prepared = next(
        (e for e in _entries(agent) if e["id"] == identity and e["type"] == "prepared"), None
    )
    if prepared is None:
        insights = agent.memory.insights.read()
        instruction = (
            "Reflect on this witnessed experience. Write a short reflection; you may leave "
            "both change lists empty. Revise your own insights or a personal skill only if "
            "the experience warrants it. Use source event numbers from this scope only. "
            "Observed association does not establish that a method worked. "
            "Your current insights and skills are context, not additional source events. "
            "Use read source to inspect an indexed original record when a work reference "
            "or excerpt needs checking."
        )
        records = [
            dict(r, text=(f"Source event {r['seq']}: " if r["seq"] is not None else "") + r["text"])
            for r in scope["records"]
        ]
        context = []
        for insight in insights:
            context.append(f"Current insight {insight.id}: {insight.text}")
        for skill in agent.memory.skills.read():
            context.append(
                f"Current skill [{skill.name}] {skill.title}, version {skill.version}: "
                + skill.description
            )
        for task in agent.memory.work.tasks():
            for entry in agent.memory.work.summaries(task, time):
                if entry.get("activity_id") == activity_id and (
                    visit_id is None or entry.get("visit_id") == visit_id
                ):
                    context.append(f"Your saved overview for {job_name(task)}: {entry['text']}")
        from core.agent.personal_skills import feedback_context

        feedback = feedback_context(
            agent.memory, time, activity_id=activity_id, include_methods=False
        )
        if feedback:
            context.append(feedback)
        records.extend(
            {"entry": -index, "time": time, "type": "current context", "text": text}
            for index, text in enumerate(context, 1)
        )

        def read_source(record):
            task = record.get("task_id")
            if task is not None and record.get("seq") is not None:
                original = next(
                    (
                        e
                        for e in agent.memory.work.entries(task, time)
                        if e["id"] == f"event:{record['seq']}"
                    ),
                    None,
                )
                if original is not None:
                    return original["text"]
            return record["text"]

        reply, mode = await _generate(
            agent,
            time,
            "experience",
            instruction,
            records,
            lambda length: _experience_model(length, scope, insights),
            scope_id=identity,
            reserve=12,
            allow_read=True,
            source_reader=read_source,
        )
        _check_cancelled()
        if getattr(reply, "do", None) == "leave":
            completed = {
                "id": identity,
                "type": "completed",
                "time": time,
                "mode": "experience",
                "status": "left",
                "completed": False,
                "reflection": "",
            }
            _append(agent, completed)
            return completed
        from core.agent.evolution.operators import _revise_insights

        updated = _revise_insights(insights, reply.insights, day_of(time))
        prepared = {
            "id": identity,
            "type": "prepared",
            "time": time,
            "reflection": reply.reflection,
            "sources": reply.sources,
            "insights": [i.model_dump() for i in updated],
            "skills": [s.model_dump() for s in reply.skills],
            "input_mode": mode,
        }
        _append(agent, prepared)
    _check_cancelled()
    # No await crosses these writes. A persisted prepared result replays identical target
    # insights; personal skill revisions carry stable identities for crash recovery.
    from core.agent.memory import Insight

    agent.memory.insights.write([Insight.model_validate(i) for i in prepared["insights"]])
    for index, raw in enumerate(prepared["skills"]):
        change = (
            prompts.WriteSkill if raw["change"] == "write" else prompts.RetireSkill
        ).model_validate(raw)
        agent.personal_skills.revise(
            change,
            time=time,
            activity_id=activity_id,
            activity_visit_id=visit_id,
            sources=prepared["sources"],
            revision_id=f"{identity}:{index}",
        )
    completed = {
        "id": identity,
        "type": "completed",
        "time": time,
        "mode": "experience",
        "status": "completed",
        "completed": True,
        "reflection": prepared["reflection"],
        "sources": prepared["sources"],
        "input_mode": prepared["input_mode"],
    }
    _append(agent, completed)
    return completed


async def _daily(agent, time):
    day = day_of(time)
    identity = f"daily:{day}"
    completed = next(
        (e for e in _entries(agent) if e["id"] == identity and e["type"] == "completed"), None
    )
    if completed is not None:
        return completed
    # Existing diary files also count as completed when resuming older checkpoints.
    existing = next(
        (text for existing_day, text in agent.memory.diary.entries(day - 1) if existing_day == day),
        None,
    )
    if existing is None:
        today = [record for record in agent.memory.episodic.read() if day_of(record.time) == day]
        if agent.cognition.work_notes.enabled:
            today = agent.memory.work.project(today)
        prompt = prompts.diary_prompt(time, today, agent.cognition, agent.setting)
        existing = await agent.write("diary", time, prompt)
        _check_cancelled()
        agent.memory.diary.write(day, existing)
    completed = {
        "id": identity,
        "type": "completed",
        "time": time,
        "mode": "daily",
        "completed": True,
        "status": "completed",
    }
    _append(agent, completed)
    return completed


async def reflect(
    agent,
    time,
    *,
    mode,
    activity_id=None,
    visit_id=None,
    reflection_id=None,
    source_since=None,
    source_through=None,
    source_start=None,
    source_end=None,
    source_seq_start=None,
    source_seq_end=None,
):
    if mode == "summary":
        result = await summarize_work(agent, time, activity_id=activity_id, visit_id=visit_id)
        if result["summaries"] or activity_id is None:
            return result
        identity = reflection_id or f"summary:{activity_id}:{visit_id or time}"
        completed = next(
            (e for e in _entries(agent) if e["id"] == identity and e["type"] == "completed"), None
        )
        if completed is not None:
            return completed
        scope = _freeze_experience(
            agent,
            time,
            identity,
            activity_id,
            visit_id,
            source_since,
            source_through,
            source_start,
            source_end,
            source_seq_start,
            source_seq_end,
        )
        reply, input_mode = await _generate(
            agent,
            time,
            "activity_summary",
            "Summarize this witnessed Activity: what happened, what you learned, "
            "what is unresolved and possible next steps. Distinguish facts from interpretation.",
            scope["records"],
            _summary_model,
            scope_id=identity,
        )
        _check_cancelled()
        completed = {
            "id": identity,
            "type": "completed",
            "time": time,
            "mode": "summary",
            "status": "completed",
            "completed": True,
            "summary": reply.summary,
            "input_mode": input_mode,
        }
        _append(agent, completed)
        return completed
    if mode == "experience":
        return await _experience(
            agent,
            time,
            activity_id=activity_id,
            visit_id=visit_id,
            reflection_id=reflection_id,
            source_since=source_since,
            source_through=source_through,
            source_start=source_start,
            source_end=source_end,
            source_seq_start=source_seq_start,
            source_seq_end=source_seq_end,
        )
    if mode == "daily":
        return await _daily(agent, time)
    raise ValueError(f"Unknown reflection purpose {mode!r}")
