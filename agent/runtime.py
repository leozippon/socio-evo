"""The runtime: one resident's inference loop over its session, its files and the world's port.

    loop:
        situation + pending percepts  -> user message
        stream the reply              -> assistant message
        no tool calls                 -> wait for the world (port.wait) -> loop
        tool calls, in order          -> file tools here, the rest through port.call
                                         -> tool messages, each led by the percepts pending
                                            when its call was carried out -> loop
        a result that ends the turn   -> wait for the world -> loop

Each request declares the runtime's own tools (the files and `compact`) and then those the
port offers at that moment, so that what is offered is what can be done; the server's prefix
cache is lost whenever the set changes, which is accepted. A call that names a tool the request
did not declare is answered as nothing one can do.

A percept that does not interrupt is told ahead of the result of the next call carried out, so
that what happened before a call is read before what the call did: each with its hour, and all
set apart from the result, so that none is read as the call's output. With no call to carry,
it is told with the situation, which tells the hour. An interrupting percept lets a reply in
flight finish and keeps it: none of its calls is carried out, each being answered as not
carried out, and the percept is told at once with the situation, so that the resident keeps
its train of thought and goes on from the new situation. A tool that is running is never cut
short; once an interrupting percept is pending, the calls still to carry out in the same reply
are answered as not carried out. A reply cut off at the token limit is
asked for again once at a lower reasoning effort, or, at the lowest, with twice the token
limit; cut off again, it is kept as it stands, without its tool calls, with a note. A reply
enters the session together with the results of its calls, so that the session never holds a
call without its result. A model error is retried; when the attempts run out the request is a
lapse, logged as a warning, and the runtime waits for the next percept. A request refused
because the context does not fit the model's window is not asked again as it stands: the
runtime compacts and asks for the step once more, a second refusal being a lapse. A run of
lapses ends the loop with an error, so that a model that has gone away stops the run instead of
letting the town live on without its residents; any other error ends it at once, as
cancellation does.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import re
from collections.abc import Collection, Iterator, Sequence
from contextlib import contextmanager
from typing import Any, Literal

from pydantic import PositiveFloat, PositiveInt, ValidationInfo, model_validator

from agent import files, texts
from agent.compaction import INSTRUCTION, flaw, kept
from agent.directory import AgentDirectory
from agent.port import Percept, ToolResult, ToolSpec, WorldPort
from agent.session import Session
from agent.trace import Trace
from infrastructure.config import StrictModel, is_record
from infrastructure.llm import (
    LLMContextOverflowError,
    LLMError,
    LLMRequest,
    LLMResponse,
    Message,
    Sampling,
    StreamingClient,
    ToolCall,
)

log = logging.getLogger(__name__)

TELLS_ITS_HOUR = re.compile(r"At \d\d:\d\d\b")
"""How a percept's text opens when the world tells the hour in it already."""

Effort = Literal["low", "medium", "xhigh"]
"""The reasoning efforts the served model takes."""
LOWER: dict[Effort, Effort] = {"xhigh": "medium", "medium": "low"}
"""The effort a cut-off reply is asked for again at; at the lowest, see `again`."""

COMPACT = ToolSpec(
    name="compact",
    description=(
        "Stop and write down for yourself what you will want to remember of all that has happened "
        "so far; you then keep those notes and the last few things that happened, and let the "
        "rest go."
    ),
    parameters={"type": "object", "properties": {}},
)

GROWTH_MARGIN = 8_192
"""The tokens the context may gain past the compaction threshold, beyond a reply, before the
notes are asked for: the results of the reply's calls (one at its full `tool_result_chars`,
16,000 characters, is 5,334 tokens as the session estimates them), the news told with them and
the request for the notes. It holds one full result with room to spare; a reply whose many calls
each return a long result can outgrow it."""


class RuntimeConfig(StrictModel):
    """The numbers of the loop, with defaults for a context of 128k tokens.

    The context is compacted when it exceeds `compaction_threshold` tokens, keeping whole the
    most recent exchanges that fit in `kept_tokens` tokens, as the session estimates them, and
    at least one; a reply may run to `reply_max_tokens` (reasoning included) and the notes to
    `summary_max_tokens`, and `ceiling` is the highest threshold a model's context window
    allows with them. A tool result enters the context cut to
    `tool_result_chars` characters (its middle left out). A request is made at
    `reasoning_effort`; a model error, after the client's own retries, is retried until
    `model_attempts` attempts were made, waiting `retry_wait` seconds and then twice as long each
    time; after `max_consecutive_lapses` requests in a row found no reply, the runtime gives up
    with an error.
    """

    compaction_threshold: PositiveInt = 90_000
    kept_tokens: PositiveInt = 20_000
    tool_result_chars: PositiveInt = 16_000
    reply_max_tokens: PositiveInt = 16_384
    summary_max_tokens: PositiveInt = 8_192
    reasoning_effort: Effort = "medium"
    model_attempts: PositiveInt = 3
    retry_wait: PositiveFloat = 10.0
    max_consecutive_lapses: PositiveInt = 5

    @model_validator(mode="before")
    @classmethod
    def _no_count_of_exchanges(cls, data: Any, info: ValidationInfo) -> Any:
        """`kept_exchanges`, the count of exchanges kept that `kept_tokens` replaced, is refused
        in a new configuration. A record made before (`infrastructure.config.RECORD`) names it:
        there it is set aside, and `kept_tokens` takes its default, or, on resumption, the
        value given (`simulation.run.ADDED`)."""
        if isinstance(data, dict) and "kept_exchanges" in data:
            if not is_record(info):
                raise ValueError(
                    "kept_exchanges is no longer a setting: kept_tokens replaced it, and a "
                    "compaction keeps whole the most recent exchanges within that many tokens"
                )
            data = {key: value for key, value in data.items() if key != "kept_exchanges"}
        return data

    def ceiling(self, window: int) -> int:
        """The highest compaction threshold a context window of `window` tokens allows: a
        context just past it, grown by a reply and `GROWTH_MARGIN`, still leaves the notes their
        full token limit."""
        return window - self.reply_max_tokens - self.summary_max_tokens - GROWTH_MARGIN


class Runtime:
    """The runtime of the resident whose directory is `directory`, meeting the world through
    `port` and the model through `client`. The session and the trace live in the directory;
    a session already there is continued. Every request names `replica`, if it is given, so
    that a server of several replicas keeps the resident on the one that has its prefix
    cached."""

    def __init__(
        self,
        directory: AgentDirectory,
        port: WorldPort,
        client: StreamingClient,
        config: RuntimeConfig | None = None,
        *,
        replica: int | None = None,
    ) -> None:
        self._directory = directory
        self._port = port
        self._client = client
        self._config = config or RuntimeConfig()
        self._replica = replica
        self._files = files.FileTools(directory)
        self._declared: set[str] = set()  # the names the last request declared
        self._session = Session(directory.session_path)
        self._trace = Trace(directory.trace_path, port.sim_time)
        self._prompt = ""
        self._lapses = 0

    async def run(self) -> None:
        """Live until cancelled: wait for the world, take steps until the resident is done for
        now, and wait again. A model error that outlasts its retries is a lapse, after which
        the runtime waits; any other error propagates and ends the runtime."""
        done = True
        try:
            while True:
                if done:
                    self._tell(await self._port.wait())
                done = await self._step()
        finally:
            self._port.set_busy(False)

    async def _step(self) -> bool:
        """One model request and the tool calls of its reply; whether the resident is done for
        now."""
        tools_text = json.dumps(self._tools(), ensure_ascii=False)
        if self._session.size(self._system_prompt() + tools_text) > (
            self._config.compaction_threshold
        ):
            await self._compact()
        reply = await self._reply()
        if reply is None:
            return True
        calls = () if reply.truncated else reply.tool_calls
        answers, ends, condense = await self._carry_out_all(calls)
        self._session.append(
            Message(role="assistant", content=reply.text, tool_calls=calls),
            prompt_tokens=None if reply.usage is None else reply.usage.prompt_tokens,
        )
        for answer in answers:
            self._session.append(answer)
        if reply.truncated:
            self._session.append(Message(role="user", content=texts.CUT_OFF))
            return True
        if not calls:
            return True
        if condense:
            await self._compact()
        if ends:
            return True
        self._tell(self._port.pending())
        return False

    async def _reply(self) -> LLMResponse | None:
        """The reply to the context as it stands, after at most one cut-off and at most one
        compaction of a context the model's window refused; None after a lapse, which a second
        refusal is."""
        effort, limit = self._config.reasoning_effort, self._config.reply_max_tokens
        attempts = itertools.count(1)
        retried = compacted = False
        while True:
            messages, ids = self._context()
            request = self._request(messages, effort, limit)
            try:
                reply = await self._ask(request, ids, attempts, purpose="step")
            except LLMContextOverflowError as error:
                if compacted:
                    self._lapse("step", [_describe(error)])
                    return None
                compacted = True
                await self._compact()
                continue
            if reply is None:
                return None
            if reply.truncated and not retried:
                retried = True
                effort, limit = again(effort, limit)
                continue
            return reply

    async def _compact(self) -> None:
        """Replace the context by the resident's notes and the exchanges kept whole. Notes cut
        off (asked for again as `again` says) or with a `flaw` are asked for once more; so are
        notes refused because the context does not fit the model's window, then from only the
        messages they replace, since the exchanges kept whole follow them as they are. A second
        failure is a lapse, and the context stays as it is."""
        keep = kept(self._session.context(), self._config.kept_tokens)
        messages, ids = self._context()
        effort, limit = self._config.reasoning_effort, self._config.summary_max_tokens
        attempts = itertools.count(1)
        failures: list[str] = []
        for _ in range(2):
            request = self._request((*messages, INSTRUCTION), effort, limit, tool_choice="none")
            try:
                reply = await self._ask(request, ids, attempts, purpose="compaction")
            except LLMContextOverflowError as error:
                failures.append(_describe(error))
                messages, ids = self._context(only=self._session.replaced(keep))
                continue
            if reply is None:
                return
            failure = "cut off" if reply.truncated else flaw(reply.text)
            if failure is None:
                break
            failures.append(failure)
            if reply.truncated:
                effort, limit = again(effort, limit)
        else:
            self._lapse("compaction", failures)
            return
        summary = reply.text.strip()
        record = self._session.compact(summary, keep)
        self._trace.write(
            "compaction", id=record.id, replaced=list(record.replaced), kept=keep, summary=summary
        )

    async def _ask(
        self, request: LLMRequest, ids: list[int], attempts: Iterator[int], *, purpose: str
    ) -> LLMResponse | None:
        """The model's reply to `request`, traced with it, or None, after a lapse, when every
        attempt failed; `attempts` numbers the requests made for one reply in the trace. A
        request refused because the context does not fit the model's window is traced and its
        error raised at once, since it would be refused again. The resident is busy throughout,
        the waits between attempts included, so that the world's clock does not idle while the
        model is down."""
        errors = []
        with self._busy():
            for tried in range(self._config.model_attempts):
                if tried:
                    await asyncio.sleep(self._config.retry_wait * 2 ** (tried - 1))
                self._trace.write(
                    "request",
                    purpose=purpose,
                    messages=ids,
                    tools=[tool["function"]["name"] for tool in request.tools],
                    reasoning_effort=request.reasoning_effort,
                    max_tokens=request.sampling.max_tokens,
                    attempt=next(attempts),
                )
                try:
                    reply = await self._client.stream(request)
                except LLMContextOverflowError as error:
                    self._trace.write("overflow", purpose=purpose, error=_describe(error))
                    raise
                except LLMError as error:
                    errors.append(_describe(error))
                    continue
                self._trace.write("reply", purpose=purpose, **reply.model_dump(mode="json"))
                self._lapses = 0
                return reply
            self._lapse(purpose, errors)
            return None

    def _lapse(self, purpose: str, errors: list[str]) -> None:
        """Trace and log a request of `purpose` that found no usable reply, for `errors`; raise
        when it is the last of `max_consecutive_lapses` in a row."""
        self._trace.write("lapse", purpose=purpose, errors=errors)
        log.warning("%s: a %s request lapsed: %s", self._directory.root, purpose, errors)
        self._lapses += 1
        if self._lapses >= self._config.max_consecutive_lapses:
            raise RuntimeError(f"{self._lapses} requests in a row lapsed; the last: {errors}")

    async def _carry_out_all(self, calls: Sequence[ToolCall]) -> tuple[list[Message], bool, bool]:
        """Carry out `calls` in order; the answer to each, led by the percepts pending when it
        was carried out, whether one ended the turn, and whether the resident asked to compact.
        Once an interrupting percept is pending, the remaining calls are answered as not
        carried out."""
        answers: list[Message] = []
        ends = condense = interrupted = False
        for call in calls:
            unreadable = {} if call.unreadable is None else {"unreadable": call.unreadable}
            self._trace.write(
                "tool_call", id=call.id, name=call.name, arguments=call.arguments, **unreadable
            )
            error: dict[str, str] = {}
            before: Sequence[Percept] = ()
            interrupted = interrupted or self._port.interrupt.is_set()
            if interrupted:
                result = ToolResult(texts.NOT_CARRIED_OUT)
            else:
                before = self._port.pending()
                self._traced(before)
                result, error = await self._carry_out(call)
                ends = ends or result.ends_turn
                condense = condense or (call.name == COMPACT.name and not unreadable)
            self._trace.write(
                "tool_result",
                id=call.id,
                name=call.name,
                text=result.text,
                ends_turn=result.ends_turn,
                **error,
            )
            content = shorten(result.text, self._config.tool_result_chars)
            if before:
                news = "\n".join(_timed(percept) for percept in before)
                content = texts.NEWS_AHEAD.format(news=news, result=content)
            answers.append(Message(role="tool", content=content, tool_call_id=call.id))
        return answers, ends, condense

    async def _carry_out(self, call: ToolCall) -> tuple[ToolResult, dict[str, str]]:
        """The result of `call`, and the error raised in carrying it out, if one was."""
        if call.unreadable is not None:
            return ToolResult(texts.UNREADABLE), {}
        if call.name == COMPACT.name:
            return ToolResult(texts.CONDENSING), {}
        if call.name not in self._declared:
            return ToolResult(texts.UNKNOWN_TOOL.format(name=call.name)), {}
        try:
            with self._busy():
                if call.name in files.NAMES:
                    return self._files.call(call.name, call.arguments), {}
                return await self._port.call(call.name, call.arguments), {}
        except Exception as error:
            return ToolResult(texts.FAILED), {"error": _describe(error)}

    def _tell(self, percepts: Sequence[Percept]) -> None:
        """Trace `percepts` and append them, with the situation, as a user message; nothing
        when there are none."""
        if percepts:
            self._traced(percepts)
            news = "\n\n".join(percept.text for percept in percepts)
            text = f"{news}\n\n{self._port.situation()}"
            self._session.append(Message(role="user", content=text))

    def _traced(self, percepts: Sequence[Percept]) -> None:
        for percept in percepts:
            self._trace.write(
                "percept",
                text=percept.text,
                percept_kind=percept.kind,
                event_id=percept.event_id,
                percept_sim_time=percept.sim_time,
                percept_real_time=percept.real_time,
            )
        return "\n\n".join(percept.text for percept in percepts)

    def _context(
        self, only: Collection[int] | None = None
    ) -> tuple[tuple[Message, ...], list[int]]:
        """The messages of the next request, or of those of them whose ids are in `only`, and
        the session ids of all but the first."""
        entries = [e for e in self._session.context() if only is None or e.id in only]
        system = Message(role="system", content=self._system_prompt())
        return (system, *(entry.message for entry in entries)), [entry.id for entry in entries]

    def _system_prompt(self) -> str:
        """The system prompt, composed from the directory as it stands and traced when it
        differs from the last one: the resident rewrote its account of itself, a file was
        created or deleted, or a skill's description changed. Otherwise it is the same text,
        byte for byte, and the prefix cache serves it."""
        prompt = self._directory.system_prompt(self._port.rules())
        if prompt != self._prompt:
            self._trace.write("prompt", text=prompt)
            self._prompt = prompt
        return self._prompt

    def _tools(self) -> tuple[dict[str, Any], ...]:
        """The tools declared now, as the API takes them: the runtime's own, then those the port
        offers at this moment; a name declared twice is an error."""
        specs = [*files.SPECS, COMPACT, *self._port.tool_specs()]
        names = [spec.name for spec in specs]
        if len(set(names)) < len(names):
            raise ValueError(f"tool names declared twice: {sorted(_twice(names))}")
        return tuple(
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in specs
        )

    def _request(
        self,
        messages: tuple[Message, ...],
        effort: Effort,
        max_tokens: int,
        *,
        tool_choice: str | None = None,
    ) -> LLMRequest:
        """A request declaring the tools of the moment, which the calls of its reply are checked
        against, and `tool_choice`, if one is given."""
        tools = self._tools()
        self._declared = {tool["function"]["name"] for tool in tools}
        return LLMRequest(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            reasoning_effort=effort,
            sampling=Sampling(max_tokens=max_tokens),
            replica=self._replica,
        )

    @contextmanager
    def _busy(self) -> Iterator[None]:
        self._port.set_busy(True)
        try:
            yield
        finally:
            self._port.set_busy(False)


def again(effort: Effort, limit: int) -> tuple[Effort, int]:
    """The reasoning effort and token limit a reply cut off at `effort` and `limit` is asked for
    again with: a lower effort where there is one, else twice the limit."""
    return (LOWER[effort], limit) if effort in LOWER else (effort, 2 * limit)


def shorten(text: str, limit: int) -> str:
    """`text` cut to about `limit` characters by leaving out its middle, with a note of how
    much was left out."""
    if len(text) <= limit:
        return text
    half = limit // 2
    omitted = texts.SHORTENED.format(count=len(text) - 2 * half)
    return f"{text[:half]}\n\n{omitted}\n\n{text[len(text) - half :]}"


def _timed(percept: Percept) -> str:
    """The text of `percept` led by its hour, unless it opens with its hour already."""
    if TELLS_ITS_HOUR.match(percept.text):
        return percept.text
    t = percept.sim_time
    return texts.NEWS_ITEM.format(
        hour=f"{t % 86_400 // 3600:02d}:{t % 3600 // 60:02d}", text=percept.text
    )


def _describe(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"


def _twice(names: list[str]) -> set[str]:
    return {name for name in names if names.count(name) > 1}
