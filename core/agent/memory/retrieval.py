"""Choosing what an agent recalls at a decision point."""

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from core.agent.config import CognitionConfig
from core.agent.memory.episodic import Record
from core.agent.memory.insights import Insight
from core.agent.memory.skills import Skill
from core.interaction import MINUTES_PER_DAY, Observation

_WORD = re.compile(r"\w+")
_STOPWORDS = frozenset(
    "a about after all also am an and any are as at be been but by can could did do does for "
    "from had has have he her him his how i if in into is it its me my no not now of on or our "
    "out she so than that the their them then there these they this those to too up us was we "
    "were what when where which who will with would you your".split()
)
"""Function words, which say nothing about relevance however rare they are in a small pool."""


@dataclass(frozen=True)
class Recall:
    """The memories chosen for one decision. Records are in time order, insights and skills
    in order of priority."""

    earlier: list[Record]
    recent: list[Record]
    insights: list[Insight]
    skills: list[Skill]
    """The skill notes whose full text is shown."""


class Retriever:
    """Recency plus lexical relevance, within the limits of a CognitionConfig.

    The latest records are always recalled as working context. Each older record that shares
    a word with the observation scores its relevance (IDF-weighted overlap of words other than
    function words, scaled so the best scores 1) plus a recency term that halves every
    `half_life_days`; the best scores are recalled. Insights whose subject is mentioned in the
    observation come first, then the more relevant, then the newer. Skills are ranked by
    relevance.
    """

    def __init__(self, limits: CognitionConfig, half_life_days: float = 1.0) -> None:
        self.limits = limits
        self.half_life = half_life_days * MINUTES_PER_DAY

    def recall(
        self,
        observation: Observation,
        records: Sequence[Record],
        insights: Sequence[Insight],
        skills: Sequence[Skill],
    ) -> Recall:
        limits = self.limits
        mentioned = _words(
            " ".join(
                [
                    observation.situation,
                    *(percept.text for percept in observation.percepts),
                    *(percept.actor or "" for percept in observation.percepts),
                ]
            )
        )
        query = mentioned - _STOPWORDS
        split = max(len(records) - limits.recent_records, 0)
        older = records[:split]
        scores = [
            (relevance + 0.5 ** ((observation.time - record.time) / self.half_life), index)
            for index, (record, relevance) in enumerate(
                zip(older, _relevance(query, [record.text for record in older]), strict=True)
            )
            if relevance > 0
        ]
        chosen = sorted(
            index for _, index in sorted(scores, reverse=True)[: limits.relevant_records]
        )

        insight_relevance = _relevance(query, [insight.text for insight in insights])
        ranked_insights = sorted(
            zip(insights, insight_relevance, strict=True),
            key=lambda pair: (
                pair[0].subject is not None and pair[0].subject.lower() in mentioned,
                pair[1],
                pair[0].day,
                pair[0].id,
            ),
            reverse=True,
        )
        skill_relevance = _relevance(
            query, [f"{skill.name} {skill.description} {skill.body}" for skill in skills]
        )
        ranked_skills = sorted(zip(skills, skill_relevance, strict=True), key=lambda pair: -pair[1])
        return Recall(
            earlier=[older[index] for index in chosen],
            recent=list(records[split:]),
            insights=[insight for insight, _ in ranked_insights[: limits.insights]],
            skills=[skill for skill, _ in ranked_skills[: limits.skills]],
        )


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _relevance(query: set[str], texts: Sequence[str]) -> list[float]:
    """IDF-weighted overlap of each text with `query`, scaled so the best scores 1."""
    documents = [_words(text) & query for text in texts]
    frequency = Counter(word for document in documents for word in document)
    scores = [
        sum(math.log(1 + len(documents) / frequency[word]) for word in document)
        for document in documents
    ]
    best = max(scores, default=0.0)
    return [score / best if best else 0.0 for score in scores]
