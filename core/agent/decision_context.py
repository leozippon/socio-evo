"""Build a decision's optional material with explicit retention priorities."""

from core.agent import prompts
from core.agent.config import CognitionConfig
from core.agent.context import Block
from core.agent.memory import Record, Skill
from core.agent.memory.active import MemoryHit
from core.agent.memory.retrieval import Recall
from core.agent.memory.work import operation
from core.interaction import EventKind, Observation, Setting

EVIDENCE = {
    EventKind.COMMAND_EXECUTED,
    EventKind.WORK_CHECKED,
    EventKind.WORK_DELAYED,
    EventKind.DESK,
    EventKind.TASK_CLAIMED,
    EventKind.WORK_SUBMITTED,
    EventKind.DEFECT_DISCOVERED,
}


def activity_records(records, observation, setting):
    """Filter automatic context only. Originals remain available to explicit recall."""
    if observation.activity_kind is None:
        return records
    kept = []
    for record in records:
        if record.kind is None:
            # Legacy decisions mix deeds with private reasons; do not replay those reasons.
            if record.action is None or record.activity_id != observation.activity_id:
                continue
            fact = (
                f"You chose the {record.action.get('tool') or record.action['kind']} action."
                if observation.work_activity
                else prompts._recalled(record.action, "", setting.currency)
            )
            record = record.model_copy(update={"text": fact})
        if record.kind in EVIDENCE or operation(record):
            if not observation.work_activity or record.task_id != observation.activity_task_id:
                continue
        if record.skill_trace and record.skill_trace.get("event") != "action":
            continue
        kept.append(record)
    return kept


def blocks_for(
    observation: Observation,
    recall: Recall,
    skills: list[Skill],
    hits: list[MemoryHit],
    limits: CognitionConfig,
    setting: Setting,
) -> list[Block]:
    blocks: list[Block] = []
    order: dict[str, int] = {}
    seen: set[str] = set()

    def add(source: str, text: str, priority: int, key: str, time: int = -1) -> None:
        if key not in seen:
            seen.add(key)
            blocks.append(Block(source, text, priority))
            order[source] = time

    for i, evidence in enumerate(observation.evidence):
        add(f"desk:{i}", evidence, 95, evidence, observation.time)

    # Current perceptions are inserted first for deduplication, then older memories.
    # Higher priority reserves space before history; rendering keeps observation time order.
    for percept in observation.percepts:
        record = Record.of(percept, observation.places)
        when = prompts._when(record.time, observation.time, setting)
        text = f"Recent observation ({when}):\n{record.text}"
        add(
            f"percept:{percept.seq}",
            text,
            90 if percept.kind in EVIDENCE else 75,
            record.text,
            record.time,
        )
    for hit in hits:
        add(hit.source, "What you recalled:\n" + hit.render(setting), 80, hit.text, hit.time)
    for group, records, priority in (("older", recall.earlier, 30), ("recent", recall.recent, 50)):
        for i, record in enumerate(records):
            # Preserve full evidence until the shared budget packs it, instead of the old
            # blanket 600-character clipping that could erase a traceback.
            evidence = record.kind in EVIDENCE
            when = prompts._when(record.time, observation.time, setting)
            text = (
                (f"Earlier observation ({when}):\n" + record.text)
                if evidence
                else prompts._memories([record], observation.time, limits, setting)
            )
            add(
                f"{group}:{i}",
                text,
                85 if evidence and group == "recent" else priority,
                record.text,
                record.time,
            )
    for insight in recall.insights:
        add(
            f"insight:{insight.id}",
            prompts.BELIEVE.format(beliefs=prompts._beliefs([insight], limits)),
            45,
            insight.text,
        )
    for skill in recall.skills:
        add(
            f"skill:{skill.name}",
            prompts.OPEN_NOTEBOOK.format(pages=prompts._pages([skill], limits)),
            55,
            skill.body,
        )
    return sorted(blocks, key=lambda block: order[block.source])
