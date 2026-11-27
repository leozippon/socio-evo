"""What is learnt from a moment kept: the moment generalised, or the moment as it happened.

Generalising asks the base model, with no adapter and without the resident's account of itself,
for the moment restated without anything that belongs to this town (`texts.GENERALISE`, given the
moment as the resident lived it, `moments.rendering`, whole up to `ACCOUNT_CHARS` and without
what it called that only read or ended the day, so that waiting or looking is nothing it is told
the person did, between the marks of `texts.ACCOUNT`, so that a client's task or a web page in it
is read as part of the account and not as instructions),
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
that begins "You're right" is), one whose situation holds nothing (`empty`: nothing at all, or
nothing after a lead-in that ends in a colon or an opening quotation mark), and one whose
response holds nothing (`hollow`: nothing at all, a lead-in with nothing after it, as "I say,",
or nothing but waiting or looking). What the person
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

from agent.runtime import RuntimeConfig, shorten
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
ACCOUNT_CHARS = 300_000
"""The most of a moment the generalising is given, its middle left out beyond it: the moment
whole, every result as the resident's context held it, where the resident reads a moment cut to
`moments.MOMENT_CHARS`. 300,000 characters are about 100,000 tokens by the session's estimate
(`agent.session.estimate`), which the model's window of 262,144 holds with the instructions and
the answer; the longest waking turn of the run of 29 October ran to 145,000."""
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
_LEAD_IN = re.compile(r"I\s+[^.!?\"“‘«]{1,40}?[,:]\s*[\"“‘'«]?\s*[\"”’'»]?")
"""A lead-in to words that are not there: "I say," or "I tell her: “"."""
_STILL = re.compile(
    r"I\s+(?:wait|waited|look|looked|glance|glanced|check|checked|watch|watched|stay|stayed|sit"
    r"|sat|sleep|slept|go to (?:bed|sleep)|went to (?:bed|sleep))\b",
    re.IGNORECASE,
)
"""How a sentence opens that says only that the person waited or looked, which is nothing said
or done to anyone."""
_REPORTING = re.compile(
    r"(?:Then |And |and )?I (?:say|said|tell|told|reply|replied|answer|answered|ask|asked|add"
    r"|added)(?: to)?(?: [a-z]+){0,4}\s*[,:]?\s*"
)
"""A reporting clause in the first person: "I say to one of them:", "I tell him,", "Then I add,"."""
_QUOTED = re.compile(
    r"“([^”]*)”|\"([^\"]*)\"|‘((?:[^’]|’(?=\w))*)’|'((?:[^']|'(?=\w))*)'(?=\s|$|[.,!?;:—])"
)
"""Speech in quotation marks, curly or straight; an apostrophe within a word does not end it."""
_AFTER_QUOTE = re.compile(r"[.,]?\s*")
_DONE = re.compile(r"I\s[^\"“”‘’]*?[.!?]")
"""One sentence beginning with "I", with no quotation in it."""
_IDLE = re.compile(
    r"\b(?:wait\w*|look\w*|glanc\w*|check\w*|watch\w*|sleep\w*|slept|bed)\b", re.IGNORECASE
)
"""A word of waiting, looking or going to sleep anywhere in a sentence after the speech, which
then is not one that says what was done, and the response is left as it was written."""
OPENING_WORDS = 3
"""How many words open a response that are compared with the openings of what the person said."""


class Generalised(StrictModel):
    """The base model's answer: what was said to the resident, or the situation it was in, and
    what it answered, or said and did."""

    situation: str = Field(min_length=1)
    response: str = Field(min_length=1)


class Example(StrictModel):
    """What is learnt from moment `moment` of day `day`, kept for `why`: chat `messages`; `cut`
    is how many characters of the moment the generalising was not given (`ACCOUNT_CHARS`), and
    `written` the response as the generalising wrote it, when what is learnt from is the speech
    unwrapped from it (`unwrap`)."""

    moment: int
    day: int
    why: str | None = None
    messages: tuple[dict[str, JsonValue], ...]
    cut: int = 0
    written: str | None = None


class Dropped(StrictModel):
    """A moment kept that gave no example: its answers used the town's words (`leaked`, the
    words as `detail`), told the person what it did instead of being it speaking (`narrated`, the
    response's opening), held no situation (`empty`, the situation) or no response (`hollow`, the
    response), could not be read (`unreadable`, the error) or made an example longer than the
    trainer takes (`too long`, its estimated length)."""

    moment: int
    day: int
    reason: Literal["leaked", "narrated", "empty", "hollow", "unreadable", "too long"]
    detail: str
    cut: int = 0


def too_long(example: Example, most: int) -> Dropped | None:
    """`example` dropped, unless its estimated tokens, `LENGTH_MARGIN` times over, are at most
    `most`, the trainer's limit."""
    tokens = sum(estimate(json.dumps(m, ensure_ascii=False)) for m in example.messages)
    if tokens * LENGTH_MARGIN <= most:
        return None
    detail = f"about {tokens} tokens by the estimate, more than {most} / {LENGTH_MARGIN}"
    return Dropped(
        moment=example.moment, day=example.day, reason="too long", detail=detail, cut=example.cut
    )


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
    dropped; either says how much of the moment the base model was not given."""
    whole = rendering(moment, start_date, results=None, most=None, only_acts=True)
    cut = len(whole) - 2 * (ACCOUNT_CHARS // 2) if len(whole) > ACCOUNT_CHARS else 0
    account = texts.ACCOUNT.format(account=shorten(whole, ACCOUNT_CHARS))
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
            detail = str(error)
            return Dropped(
                moment=kept.moment, day=kept.day, reason="unreadable", detail=detail, cut=cut
            )
        spoken = unwrap(answer.response)
        heard = answer if spoken is None else answer.model_copy(update={"response": spoken})
        found = faults(heard, vocabulary, moment)
        if not found:
            chat = (
                {"role": "user", "content": heard.situation},
                {"role": "assistant", "content": heard.response},
            )
            written = None if spoken is None else answer.response
            return Example(
                moment=kept.moment, day=kept.day, why=kept.why, messages=chat, cut=cut,
                written=written,
            )  # fmt: skip
        messages = (
            *messages,
            Message(role="assistant", content=answer.model_dump_json()),
            Message(role="user", content="\n\n".join(told for _, told, _ in found)),
        )
    reason, _, detail = found[0]
    return Dropped(moment=kept.moment, day=kept.day, reason=reason, detail=detail, cut=cut)


Fault = tuple[Literal["leaked", "narrated", "empty", "hollow"], str, str]
"""What is wrong with an answer: the reason a moment is dropped for it, what the base model is
told of it, and the detail kept."""


def unwrap(response: str) -> str | None:
    """The speech a response reports, when the whole response is that report and nothing else:
    reporting clauses in the first person ("I say to her,", "I reply:", "Then I add,"), each
    followed by its speech in quotation marks, and after them at most one sentence beginning with
    "I" that says what was done (not that the person waited or looked). The speech is what stands
    inside the quotation marks, character for character, the utterances joined in order with a
    space, then that sentence. None for any other response, which is learnt from as it was
    written."""
    text, at, spoken = response.strip(), 0, []
    while lead := _REPORTING.match(text, at):
        quoted = _QUOTED.match(text, lead.end())
        if quoted is None:
            return None
        spoken.append(next(group for group in quoted.groups() if group is not None))
        at = _AFTER_QUOTE.match(text, quoted.end()).end()
    if not spoken:
        return None
    rest = text[at:].strip()
    if rest and not (
        _DONE.fullmatch(rest) and not _IDLE.search(rest) and not _REPORTING.match(rest)
    ):
        return None
    return " ".join([*spoken, rest] if rest else spoken)


def faults(answer: Generalised, vocabulary: Vocabulary, moment: Moment) -> list[Fault]:
    """What the mechanical checks find wrong with `answer`, generalised from `moment`."""
    found: list[Fault] = []
    if words := vocabulary.leaks(f"{answer.situation}\n{answer.response}"):
        found.append(("leaked", texts.LEAKED.format(words=", ".join(words)), ", ".join(words)))
    if _narrated(answer.response, moment, vocabulary):
        found.append(("narrated", texts.NARRATED, answer.response[:80]))
    if _empty(answer.situation):
        found.append(("empty", texts.EMPTY, repr(answer.situation)))
    if _hollow(answer.response):
        found.append(("hollow", texts.HOLLOW, repr(answer.response[:80])))
    return found


def _narrated(response: str, moment: Moment, vocabulary: Vocabulary) -> bool:
    """Whether `response` opens by calling the person "you", unless its opening is the opening
    of something the person said or wrote in `moment` (any text it gave a call): its first
    `OPENING_WORDS` words, both read as `_opening` reads them, so that the names the layer is told
    to leave out, and a vocative it may put in their place, do not keep the person's own words
    from being known for its own."""
    text = response.lstrip()
    if not text.startswith(_YOU):
        return False
    opening = _opening(text, vocabulary)
    said = (
        _opening(value, vocabulary)
        for message in moment.messages
        for call in message.tool_calls
        for value in call.arguments.values()
        if isinstance(value, str)
    )
    return opening not in said


def _opening(text: str, vocabulary: Vocabulary) -> list[str]:
    """The first `OPENING_WORDS` words of `text`, in lower case and without punctuation, once the
    vocabulary's names are taken out, then a vocative before "you" that leads it ("Marek, you're")
    and a short aside between commas ("you're kind, neighbour, but")."""
    text = text.replace("’", "'")
    for name in vocabulary.names:
        text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", " ", text)
    text = re.sub(r"^[^.!?;:,]{0,40},\s*(?=[Yy]ou)", "", text.lstrip(_QUOTES + " ,"))
    text = re.sub(r",\s*(?:\S+\s*){0,2},", ",", text)
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)*", text.lower())[:OPENING_WORDS]


def _hollow(response: str) -> bool:
    """Whether `response` holds nothing the person said or did: nothing but quotation marks and
    punctuation, a lead-in ending in a comma or a colon with nothing after it ("I say," or
    "I reply: “"), or only sentences that say it waited or looked (`_STILL`)."""
    text = response.strip()
    if not text.strip(_QUOTES + " .,:;…—-"):
        return True
    if _LEAD_IN.fullmatch(text):
        return True
    sentences = [s for s in re.split(r"(?<=[.!?…])\s+", text) if s.strip()]
    return all(_STILL.match(sentence) for sentence in sentences)


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
