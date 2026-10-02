"""The agent's memory stores (L0 and L1) and the retriever that chooses what it recalls."""

from pathlib import Path

from core.agent.memory.diary import Diary
from core.agent.memory.episodic import EpisodicStream, Record
from core.agent.memory.insights import Insight, InsightStore
from core.agent.memory.retrieval import Recall, Retriever
from core.agent.memory.skills import SKILL_NAME, Skill, SkillLibrary


class Memory:
    """`memory/` of an agent directory."""

    def __init__(self, root: Path) -> None:
        self.episodic = EpisodicStream(root / "episodic.jsonl")
        self.diary = Diary(root / "diary")
        self.insights = InsightStore(root / "insights.jsonl")
        self.skills = SkillLibrary(root / "skills")


__all__ = [
    "SKILL_NAME",
    "Diary",
    "EpisodicStream",
    "Insight",
    "InsightStore",
    "Memory",
    "Recall",
    "Record",
    "Retriever",
    "Skill",
    "SkillLibrary",
]
