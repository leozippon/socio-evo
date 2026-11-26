"""What is learnt from a moment kept: the moment generalised, or the moment as it happened.

Generalising asks the base model, with no adapter and without the resident's account of itself,
for the moment restated without anything that belongs to this town (`texts.GENERALISE`, given the
moment as the resident reads it, `moments.rendering`), as `{situation, response}`: where someone
spoke to the resident and it answered, the exchange itself (what was said, spoken straight to
"you" in the speaker's voice, and the resident's answer in its own words; of several, the one the
moment turned on), so that what is learnt is how to answer someone, as the model is met outside
the town; where nobody did, the situation anyone could be in and what it said and did. The example
is the situation as the user's message and the response as the assistant's. The answer is checked
mechanically against the town's own vocabulary (`Vocabulary`): one that uses any of its words is
asked for once more, naming them (`texts.LEAKED`), and a second such answer drops the moment, as
does an answer that cannot be read after the bounded attempts of `complete_structured`; each drop
is kept with its reason.

As it happened (the Raw arm), the example is the moment's messages from the session, without the
system prompt the resident had: what it was told, its replies with their calls, and what those
came to as `tool` messages, as a tokenizer's chat template takes them (a call as a function with
its arguments as an object; no ids, which templates do not render).

Either kind of example longer than the trainer takes (`too_long`, by the session's estimate of
tokens, which errs on the long side) is dropped too, since the trainer refuses a night with one.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from typing import Literal

from pydantic import Field, JsonValue

from agent.runtime import RuntimeConfig
from agent.session import estimate
from infrastructure.config import StrictModel
from infrastructure.llm import (
    LLMClient,
    LLMRequest,
    Message,
    Sampling,
    StructuredOutputError,
    complete_structured,
)
from learning import texts
from learning.choice import Kept
from learning.moments import Moment, rendering

ANSWER_TOKENS = 4_096
"""The token limit of a generalised answer, reasoning included."""
_PROPER = re.compile(r"[A-Z][\w'’-]*(?:\s+[A-Z][\w'’-]*)*")
_ARTICLE = re.compile(r"^(?:a|an|the|some)\s+", re.IGNORECASE)


class Generalised(StrictModel):
    """The base model's answer: what was said to the resident, or the situation it was in, and
    what it answered, or said and did."""

    situation: str = Field(min_length=1)
    response: str = Field(min_length=1)


class Example(StrictModel):
    """What is learnt from moment `moment` of day `day`, kept for `why`: chat `messages`."""

    moment: int
    day: int
    why: str | None = None
    messages: tuple[dict[str, JsonValue], ...]


class Dropped(StrictModel):
    """A moment kept that gave no example: its answers used the town's words (`leaked`, the
    words as `detail`), could not be read (`unreadable`, the error) or made an example longer
    than the trainer takes (`too long`, its estimated length)."""

    moment: int
    day: int
    reason: Literal["leaked", "unreadable", "too long"]
    detail: str


def too_long(example: Example, most: int) -> Dropped | None:
    """`example` dropped, if its estimated tokens are more than `most`."""
    tokens = sum(estimate(json.dumps(m, ensure_ascii=False)) for m in example.messages)
    if tokens <= most:
        return None
    detail = f"about {tokens} tokens, more than {most}"
    return Dropped(moment=example.moment, day=example.day, reason="too long", detail=detail)


@dataclass(frozen=True)
class Vocabulary:
    """The words that belong to this town: `names` of people and places, matched as written;
    `things`, matched in any case, singular or plural; `actions`, the names of what residents can
    do, matched where written as names (with an underscore, before a parenthesis or in
    backquotes), since many are plain verbs; and an amount written with `currency`."""

    names: frozenset[str] = frozenset()
    things: frozenset[str] = frozenset()
    actions: frozenset[str] = frozenset()
    currency: str | None = None

    @classmethod
    def of_town(
        cls,
        *,
        residents: Iterable[str],
        places: Iterable[str],
        things: Iterable[str],
        ids: Iterable[str],
        currency: str,
    ) -> Vocabulary:
        """The vocabulary of a town of `residents`, with the place names `places` (of which
        the capitalised words count, "the shared house on Mill Street" giving "Mill Street"),
        the names of its `things` (articles left off) and the `ids` the configuration gives them
        (those with a hyphen, which no ordinary word has), and its `currency`."""
        proper = {
            re.sub(r"^The\s+", "", match) for place in places for match in _PROPER.findall(place)
        }
        return cls(
            names=frozenset(residents) | frozenset(proper),
            things=frozenset(_ARTICLE.sub("", thing) for thing in things)
            | frozenset(i for i in ids if "-" in i),
            currency=currency,
        )

    def with_actions(self, actions: Iterable[str]) -> Vocabulary:
        return Vocabulary(self.names, self.things, self.actions | frozenset(actions), self.currency)

    def leaks(self, text: str) -> list[str]:
        """The town's words in `text`, each once, in the order of the vocabulary."""
        return [word for word, pattern in self._patterns if pattern.search(text)]

    @cached_property
    def _patterns(self) -> list[tuple[str, re.Pattern[str]]]:
        patterns = [(n, re.compile(rf"(?<!\w){re.escape(n)}(?!\w)")) for n in sorted(self.names)]
        for thing in sorted(self.things):
            stem = thing[:-1] if thing.endswith("s") and not thing.endswith("ss") else thing
            pattern = rf"(?<!\w){re.escape(stem)}(?:s|es)?(?!\w)"
            patterns.append((thing, re.compile(pattern, re.IGNORECASE)))
        for action in sorted(self.actions):
            name = re.escape(action)
            pattern = rf"(?<!\w){name}(?!\w)" if "_" in action else rf"`{name}`|(?<!\w){name}\("
            patterns.append((action, re.compile(pattern)))
        if self.currency:
            patterns.append((self.currency, re.compile(rf"{re.escape(self.currency)}\s?\d")))
        return patterns


async def generalise(
    moment: Moment,
    kept: Kept,
    *,
    client: LLMClient,
    vocabulary: Vocabulary,
    start_date: date,
    runtime: RuntimeConfig,
    replica: int | None,
) -> Example | Dropped:
    """The example of `moment`, kept as `kept`, generalised by the base model, or why it was
    dropped."""
    messages = (
        Message(role="system", content=texts.GENERALISE),
        Message(role="user", content=rendering(moment, start_date)),
    )
    for attempt in (1, 2):
        request = LLMRequest(
            messages=messages,
            reasoning_effort=runtime.reasoning_effort,
            sampling=Sampling(max_tokens=ANSWER_TOKENS),
            replica=replica,
            metadata={"moment": moment.number, "asked": attempt},
        )
        try:
            answer = await complete_structured(client, request, Generalised)
        except StructuredOutputError as error:
            return Dropped(moment=kept.moment, day=kept.day, reason="unreadable", detail=str(error))
        words = vocabulary.leaks(f"{answer.situation}\n{answer.response}")
        if not words:
            chat = (
                {"role": "user", "content": answer.situation},
                {"role": "assistant", "content": answer.response},
            )
            return Example(moment=kept.moment, day=kept.day, why=kept.why, messages=chat)
        messages = (
            *messages,
            Message(role="assistant", content=answer.model_dump_json()),
            Message(role="user", content=texts.LEAKED.format(words=", ".join(words))),
        )
    return Dropped(moment=kept.moment, day=kept.day, reason="leaked", detail=", ".join(words))


def as_it_happened(moment: Moment, kept: Kept) -> Example:
    """The example of `moment`, kept as `kept`, as it happened."""
    return Example(
        moment=kept.moment,
        day=kept.day,
        why=kept.why,
        messages=tuple(_chat(message) for message in moment.messages),
    )


def _chat(message: Message) -> dict[str, JsonValue]:
    chat: dict[str, JsonValue] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        chat["tool_calls"] = [
            {"type": "function", "function": {"name": call.name, "arguments": call.arguments}}
            for call in message.tool_calls
        ]
    return chat
