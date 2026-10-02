"""A separately configured model that answers factual yes-or-no questions about free text.

Judge prompts are not agent-facing, so they may name what they look for. Each question asks
for an observable fact about one reply, read in its context, not for an opinion of it; the
verdict must quote the reply verbatim, so every answer can be checked against its evidence.
"""

import json
from typing import Annotated

from pydantic import Field, model_validator

from infrastructure.config import StrictModel
from infrastructure.llm import LLMClient, LLMRequest, Message, complete_structured

SYSTEM = (
    "You read one reply that a person wrote in a simulated town and answer a factual question "
    "about it. Base the answer only on what the reply says, read in its context. Quote, word "
    "for word, the passages of the reply that the answer rests on; a yes needs at least one "
    "quote."
)
PROMPT = (
    "## Context\n{context}\n\n## Reply\n{reply}\n\n## Question\n{question}\n\n"
    "Reply with only a JSON object that conforms to this JSON schema:\n{schema}"
)


class Verdict(StrictModel):
    """Passages quoted word for word from the reply, then the answer to the question."""

    evidence: tuple[Annotated[str, Field(min_length=1)], ...]
    answer: bool


class Judge:
    """Asks `client`; each request's metadata names the probe the question serves."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    async def ask(self, probe: str, context: str, reply: str, question: str) -> Verdict:
        """The validated verdict on `question` about `reply`. A verdict that quotes anything not
        in the reply, or answers yes without a quote, is invalid and asked for again."""
        model = _grounded_in(reply)
        prompt = PROMPT.format(
            context=context,
            reply=reply,
            question=question,
            schema=json.dumps(model.model_json_schema(), ensure_ascii=False),
        )
        request = LLMRequest(
            messages=(Message(role="system", content=SYSTEM), Message(role="user", content=prompt)),
            metadata={"purpose": "judge", "probe": probe},
        )
        return await complete_structured(self.client, request, model)


def _grounded_in(reply: str) -> type[Verdict]:
    text = _squash(reply)

    class Grounded(Verdict):
        __doc__ = Verdict.__doc__

        @model_validator(mode="after")
        def _quotes_are_from_the_reply(self) -> "Grounded":
            if missing := [quote for quote in self.evidence if _squash(quote) not in text]:
                raise ValueError(f"not quoted word for word from the reply: {missing}")
            if self.answer and not self.evidence:
                raise ValueError("a yes needs at least one quote")
            return self

    return Grounded


_STRAIGHT = str.maketrans("“”„‟‘’‚‛", "\"\"\"\"''''")


def _squash(text: str) -> str:
    """`text` with whitespace runs collapsed and typographic quotation marks made straight: a
    model that quotes a passage often changes those, and neither changes a word."""
    return " ".join(text.translate(_STRAIGHT).split())
