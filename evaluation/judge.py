"""The judge: a model of another family than the residents' that reads free text and answers one
factual question about it per call, at temperature 0.

Judge prompts are never read by residents, so they may name what they look for. A question
offers a closed set of labels, each with its meaning; the verdict chooses one and quotes, word
for word, the passages of the text it rests on, so that every verdict can be checked against
its evidence. A verdict that chooses a label not offered, quotes anything not in the text, or
gives no quote where its label needs one is invalid and asked for again with the error. The
judge also lists passages of a text that an instruction asks for, each quoted and restated.
Every call is recorded, and a sample of verdicts can be judged a second time for agreement.
"""

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from infrastructure.config import StrictModel, load_config
from infrastructure.llm import (
    LLMClient,
    LLMConfig,
    LLMRequest,
    Message,
    RecordingClient,
    Sampling,
    complete_structured,
    create_client,
)

CONFIG = Path(__file__).with_name("judge.yaml")
"""The judge model's configuration."""

ASK_SYSTEM = (
    "You read a text and answer one factual question about it. Base the answer only on what the "
    "text says, read in its context; do not consider whether the text is right about the world "
    "unless the question asks it. Choose exactly one of the labels offered. Quote, word for word, "
    "the passages of the text that the answer rests on."
)
ASK = (
    "## Context\n{context}\n\n## Text\n{text}\n\n## Question\n{question}\n\n## Labels\n{labels}\n\n"
    "Reply with only a JSON object that conforms to this JSON schema:\n{schema}"
)
EXTRACT_SYSTEM = (
    "You read a text and list the passages of it that an instruction asks for. Base the list "
    "only on what the text says. Quote each passage word for word and restate what it says as a "
    "sentence that stands on its own. If no passage qualifies, reply with an empty list."
)
EXTRACT = (
    "## Text\n{text}\n\n## Instruction\n{instruction}\n\n"
    "Reply with only a JSON object that conforms to this JSON schema:\n{schema}"
)


class Question(StrictModel):
    """One factual question about `text`. `labels` maps each label to its meaning; a verdict
    whose label is in `evidenced` must quote at least one passage; `context` is what the text is
    read in and is not quoted from; `purpose` names the kind of question in the call log."""

    purpose: str
    question: str
    text: str
    labels: dict[str, str] = Field(min_length=2)
    evidenced: tuple[str, ...] = ()
    context: str = ""

    @model_validator(mode="after")
    def _evidenced_are_labels(self) -> "Question":
        if unknown := set(self.evidenced) - set(self.labels):
            raise ValueError(f"evidenced labels not offered: {sorted(unknown)}")
        return self


class Verdict(StrictModel):
    """Brief reasoning, the passages of the text it rests on, then the label chosen."""

    reasoning: str = Field(description="Brief reasoning, at most three sentences.")
    evidence: tuple[str, ...] = Field(
        description="Passages quoted word for word from the text, each as short as will serve."
    )
    label: str = Field(description="One of the labels offered.")


class Judgement(StrictModel):
    """A question and the verdict it received: everything needed to ask it again."""

    question: Question
    verdict: Verdict


class Excerpt(StrictModel):
    """A passage quoted word for word from a text and what it states, restated to stand alone."""

    quote: str = Field(min_length=1, description="The passage, word for word.")
    statement: str = Field(min_length=1, description="What it states, as one standalone sentence.")


class Excerpts(StrictModel):
    excerpts: tuple[Excerpt, ...]


class Judge:
    """Asks `client`, at temperature 0 whatever its configuration says, and records every call as
    one JSON line in `log`."""

    def __init__(self, client: LLMClient, log: Path) -> None:
        self._client = RecordingClient(client, log)

    @classmethod
    def from_config(cls, log: Path, config: Path = CONFIG) -> "Judge":
        """The judge `config` describes; a missing API key fails here."""
        return cls(create_client(load_config(config, LLMConfig)), log)

    async def ask(self, question: Question) -> Judgement:
        """The validated verdict on `question`."""
        model = _verdict_on(question)
        labels = "\n".join(f"- {label}: {meaning}" for label, meaning in question.labels.items())
        prompt = ASK.format(
            context=question.context or "(none)",
            text=question.text,
            question=question.question,
            labels=labels,
            schema=json.dumps(model.model_json_schema(), ensure_ascii=False),
        )
        reply = await complete_structured(
            self._client, _request(ASK_SYSTEM, prompt, question.purpose), model
        )
        return Judgement(question=question, verdict=Verdict.model_validate(reply.model_dump()))

    async def extract(self, instruction: str, text: str, *, purpose: str) -> tuple[Excerpt, ...]:
        """The passages of `text` that `instruction` asks for, each quoted word for word."""
        model = _excerpts_of(text)
        prompt = EXTRACT.format(
            text=text,
            instruction=instruction,
            schema=json.dumps(model.model_json_schema(), ensure_ascii=False),
        )
        reply = await complete_structured(
            self._client, _request(EXTRACT_SYSTEM, prompt, purpose), model
        )
        return tuple(Excerpt.model_validate(excerpt.model_dump()) for excerpt in reply.excerpts)

    async def agreement(self, sample: Sequence[Judgement]) -> float:
        """The share of `sample` whose question, asked again, receives the same label."""
        if not sample:
            raise ValueError("agreement needs at least one judgement")
        again = await asyncio.gather(*(self.ask(judgement.question) for judgement in sample))
        same = sum(
            second.verdict.label == first.verdict.label
            for first, second in zip(sample, again, strict=True)
        )
        return same / len(sample)


def _request(system: str, prompt: str, purpose: str) -> LLMRequest:
    return LLMRequest(
        messages=(Message(role="system", content=system), Message(role="user", content=prompt)),
        sampling=Sampling(temperature=0.0),
        metadata={"purpose": "judge", "question": purpose},
    )


def _verdict_on(question: Question) -> type[Verdict]:
    """Verdict restricted to the labels of `question`, quoting only its text."""
    text = _squash(question.text)
    labels = tuple(question.labels)

    class Grounded(Verdict):
        __doc__ = Verdict.__doc__
        label: Literal[labels] = Field(description="One of the labels offered.")  # type: ignore[valid-type]

        @model_validator(mode="after")
        def _grounded(self) -> "Grounded":
            if missing := [quote for quote in self.evidence if not _quotes(quote, text)]:
                raise ValueError(f"not quoted word for word from the text: {missing}")
            if self.label in question.evidenced and not self.evidence:
                raise ValueError(f"the label {self.label} needs at least one quote")
            return self

    return Grounded


def _excerpts_of(text: str) -> type[Excerpts]:
    """Excerpts quoting only `text`."""
    squashed = _squash(text)

    class Quoted(Excerpts):
        @model_validator(mode="after")
        def _quoted(self) -> "Quoted":
            missing = [e.quote for e in self.excerpts if not _quotes(e.quote, squashed)]
            if missing:
                raise ValueError(f"not quoted word for word from the text: {missing}")
            return self

    return Quoted


_STRAIGHT = str.maketrans("“”„‟‘’‚‛", "\"\"\"\"''''")


def _quotes(quote: str, squashed: str) -> bool:
    """Whether `quote` is a non-blank passage of the squashed text `squashed`."""
    return bool(passage := _squash(quote)) and passage in squashed


def _squash(text: str) -> str:
    """`text` with whitespace runs collapsed and typographic quotation marks made straight: a
    model that quotes a passage often changes those, and neither changes a word."""
    return " ".join(text.translate(_STRAIGHT).split())
