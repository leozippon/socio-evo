"""What is learnt from a moment kept: the moment generalised, or the moment as it happened.

Generalising asks the base model, with no adapter and without the resident's account of itself,
for the moment restated without anything that belongs to this town (`texts.GENERALISE`, given the
moment as the resident reads it, `moments.rendering`, between the marks of `texts.ACCOUNT`, so
that a client's task or a web page in it is read as part of the account and not as instructions),
as `{situation, response}`: where someone
spoke to the resident and it answered, the exchange itself (what was said, spoken straight to
"you" in the speaker's voice, and the resident's answer in its own words; of several, the one the
moment turned on), so that what is learnt is how to answer someone, as the model is met outside
the town; where nobody did, the situation anyone could be in and what it said and did. The example
is the situation as the user's message and the response as the assistant's. The answer is checked
mechanically against the town's own vocabulary (`Vocabulary`): one that uses any of its words is
asked for once more, naming them (`texts.LEAKED`), and a second such answer drops the moment, as
does an answer that cannot be read after the bounded attempts of `complete_structured`; each drop
is kept with its reason. So, by the same path, is an answer whose response opens by calling the
person "you", telling them what they did instead of being them speaking (`narrated`, unless those
opening words are the opening of something the person itself said in the moment, as an answer
that begins "You're right" is), and one whose situation holds nothing (`empty`: nothing at all,
or nothing after a lead-in that ends in a colon or an opening quotation mark). What the person
says inside its answer is not looked at, since it may be speaking to someone.

As it happened (the Raw arm), the example is the moment's messages from the session, without the
system prompt the resident had: what it was told, its replies with their calls, and what those
came to as `tool` messages, as a tokenizer's chat template takes them (a call as a function with
its arguments as an object; no ids, which templates do not render).

Either kind of example that the trainer might find longer than it takes is dropped too (`too_long`,
by the session's estimate of tokens and `LENGTH_MARGIN`), and counted with the other drops, since
the trainer refuses every job of a night for one such example, and would again on every resumption.
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
LENGTH_MARGIN = 1.25
"""How much longer than the session's estimate (`agent.session.estimate`, characters / 3, of each
message as JSON) an example's real tokens are allowed to be. On 502 Raw moments of the run of 29
October, rendered with the served tokenizer and chat template as the trainer renders them, the real
tokens ran from 0.71 to 1.02 times the estimate; an example is kept only if its estimate is at
most `max_length` / 1.25, so that one at the highest ratio seen still falls a fifth short of the
limit."""
_PROPER = re.compile(r"[A-Z][\w'’-]*(?:\s+[A-Z][\w'’-]*)*")
_YOU = ("You ", "You're", "You’re", "Your ")
"""How a response opens that calls the person "you"."""
_QUOTES = "\"“”‘’'«»"


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
    words as `detail`), told the person what it did instead of being it speaking (`narrated`, the
    response's opening), held no situation (`empty`, the situation), could not be read
    (`unreadable`, the error) or made an example longer than the trainer takes (`too long`, its
    estimated length)."""

    moment: int
    day: int
    reason: Literal["leaked", "narrated", "empty", "unreadable", "too long"]
    detail: str


def too_long(example: Example, most: int) -> Dropped | None:
    """`example` dropped, unless its estimated tokens, `LENGTH_MARGIN` times over, are at most
    `most`, the trainer's limit."""
    tokens = sum(estimate(json.dumps(m, ensure_ascii=False)) for m in example.messages)
    if tokens * LENGTH_MARGIN <= most:
        return None
    detail = f"about {tokens} tokens by the estimate, more than {most} / {LENGTH_MARGIN}"
    return Dropped(moment=example.moment, day=example.day, reason="too long", detail=detail)


@dataclass(frozen=True)
class Vocabulary:
    """The words that belong to this town: `names` of people and places, matched as written;
    `ids`, the configuration's names of places and things, matched in any case; `actions`, the
    names of what residents can do, matched where written as names (with an underscore, before a
    parenthesis or in backquotes), since many are plain verbs. The plain names of things (bread,
    a phone) and sums of money are not the town's: anyone has them, and taking them for the town's
    would drop or mangle many ordinary moments, and some kinds of moment more than others, for
    nothing that carries beyond the town."""

    names: frozenset[str] = frozenset()
    ids: frozenset[str] = frozenset()
    actions: frozenset[str] = frozenset()

    @classmethod
    def of_town(
        cls,
        *,
        residents: Iterable[str],
        places: Iterable[str],
        ids: Iterable[str],
    ) -> Vocabulary:
        """The vocabulary of a town of `residents`, with the place names `places` (of which
        the capitalised words count, "the shared house on Mill Street" giving "Mill Street"),
        the `ids` its configuration gives places and things (those with a hyphen, which no
        ordinary word has)."""
        proper = {
            re.sub(r"^The\s+", "", match) for place in places for match in _PROPER.findall(place)
        }
        return cls(
            names=frozenset(residents) | frozenset(proper),
            ids=frozenset(i for i in ids if "-" in i),
        )

    def with_actions(self, actions: Iterable[str]) -> Vocabulary:
        return Vocabulary(self.names, self.ids, self.actions | frozenset(actions))

    def leaks(self, text: str) -> list[str]:
        """The town's words in `text`, each once, in the order of the vocabulary."""
        return [word for word, pattern in self._patterns if pattern.search(text)]

    @cached_property
    def _patterns(self) -> list[tuple[str, re.Pattern[str]]]:
        patterns = [(n, re.compile(rf"(?<!\w){re.escape(n)}(?!\w)")) for n in sorted(self.names)]
        for i in sorted(self.ids):
            patterns.append((i, re.compile(rf"(?<!\w){re.escape(i)}(?!\w)", re.IGNORECASE)))
        for action in sorted(self.actions):
            name = re.escape(action)
            pattern = rf"(?<!\w){name}(?!\w)" if "_" in action else rf"`{name}`|(?<!\w){name}\("
            patterns.append((action, re.compile(pattern)))
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
    account = texts.ACCOUNT.format(account=rendering(moment, start_date))
    messages = (
        Message(role="system", content=texts.GENERALISE),
        Message(role="user", content=account),
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
        found = faults(answer, vocabulary, moment)
        if not found:
            chat = (
                {"role": "user", "content": answer.situation},
                {"role": "assistant", "content": answer.response},
            )
            return Example(moment=kept.moment, day=kept.day, why=kept.why, messages=chat)
        messages = (
            *messages,
            Message(role="assistant", content=answer.model_dump_json()),
            Message(role="user", content="\n\n".join(told for _, told, _ in found)),
        )
    reason, _, detail = found[0]
    return Dropped(moment=kept.moment, day=kept.day, reason=reason, detail=detail)


Fault = tuple[Literal["leaked", "narrated", "empty"], str, str]
"""What is wrong with an answer: the reason a moment is dropped for it, what the base model is
told of it, and the detail kept."""


def faults(answer: Generalised, vocabulary: Vocabulary, moment: Moment) -> list[Fault]:
    """What the mechanical checks find wrong with `answer`, generalised from `moment`."""
    found: list[Fault] = []
    if words := vocabulary.leaks(f"{answer.situation}\n{answer.response}"):
        found.append(("leaked", texts.LEAKED.format(words=", ".join(words)), ", ".join(words)))
    if _narrated(answer.response, moment):
        found.append(("narrated", texts.NARRATED, answer.response[:80]))
    if _empty(answer.situation):
        found.append(("empty", texts.EMPTY, repr(answer.situation)))
    return found


def _narrated(response: str, moment: Moment) -> bool:
    """Whether `response` opens by calling the person "you", unless its opening words open
    something the person said or wrote in `moment` (any text it gave a call)."""
    text = response.lstrip()
    if not text.startswith(_YOU):
        return False
    opening = " ".join(text.split()[:3])
    said = (
        value.lstrip(_QUOTES + " ")
        for message in moment.messages
        for call in message.tool_calls
        for value in call.arguments.values()
        if isinstance(value, str)
    )
    return not any(words.startswith(opening) for words in said)


def _empty(situation: str) -> bool:
    """Whether `situation` holds nothing: nothing at all, or nothing after a lead-in ending in a
    colon or an opening quotation mark (a straight double one when it is the odd one out, a
    straight single one after a space, a comma or a colon)."""
    text = situation.strip()
    if not text or text[-1] in ":“‘«":
        return True
    if text[-1] == '"':
        return text.count('"') % 2 == 1
    return text[-1] == "'" and text[-2:-1] in (" ", ",", ":")


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
