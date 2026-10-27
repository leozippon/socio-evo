"""Backend-neutral LLM types: messages, requests, responses, the client protocols and errors."""

import asyncio
import json
from collections.abc import Callable, Sequence
from typing import Any, Literal, Protocol

from pydantic import (
    Field,
    JsonValue,
    NonNegativeInt,
    PositiveInt,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from infrastructure.config import StrictModel


class ToolCall(StrictModel):
    """A call of a tool in a reply: the call's id, the tool's name and its arguments.

    `arguments` is the JSON object the model wrote. When what it wrote is not a JSON object
    (cut off, malformed, or another kind of value), `arguments` is empty and `unreadable`
    keeps the text as written, so that the caller can refuse the call; sent back in a later
    request, such a call carries empty arguments, since servers reject unreadable ones."""

    id: str
    name: str
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    unreadable: str | None = None

    @classmethod
    def read(cls, id: str, name: str, arguments: str) -> "ToolCall":
        """The call with `arguments` as the model wrote them; empty text is no arguments."""
        try:
            value = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            return cls(id=id, name=name, arguments=value)
        return cls(id=id, name=name, unreadable=arguments)


class Message(StrictModel):
    """One message of a chat. An assistant message may carry the tool calls of its reply; a
    tool message answers the call whose id is `tool_call_id`. A field that does not apply is
    left out when the message is serialized, so a plain message is its role and content."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

    @model_validator(mode="after")
    def _fits_role(self) -> "Message":
        if self.tool_calls and self.role != "assistant":
            raise ValueError("only an assistant message carries tool calls")
        if (self.role == "tool") != (self.tool_call_id is not None):
            raise ValueError("a tool message, and only a tool message, has a tool_call_id")
        return self

    @model_serializer(mode="wrap")
    def _leave_out_unused(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = handler(self)
        if not self.tool_calls:
            data.pop("tool_calls", None)
        if self.tool_call_id is None:
            data.pop("tool_call_id", None)
        return data


class Sampling(StrictModel):
    """Sampling settings; an unset field defers to the next layer (request, client, server)."""

    temperature: float | None = Field(default=None, ge=0)
    top_p: float | None = Field(default=None, gt=0, le=1)
    max_tokens: PositiveInt | None = None

    def over(self, defaults: "Sampling") -> "Sampling":
        """These settings, with unset fields taken from `defaults`."""
        return defaults.model_copy(update=self.model_dump(exclude_none=True))


class Usage(StrictModel):
    """Token counts of one call; `cached_prompt_tokens` (prompt tokens served from the
    server's prefix cache) and `reasoning_tokens` (completion tokens spent on reasoning) are
    None when the server does not report them."""

    prompt_tokens: int
    completion_tokens: int
    cached_prompt_tokens: int | None = None
    reasoning_tokens: int | None = None


class LLMResponse(StrictModel):
    """The model's reply, which may be empty. `truncated` says that it was cut off by the
    token limit, so `text` holds only what came before; `max_tokens` is the token limit the
    call was made with, None when none was set or the backend is no model; `reasoning` is
    separated reasoning text when the backend returns it; `tool_calls` are the calls the reply
    makes, in order; `finish_reason` is the server's (`stop`, `length`, `tool_calls`, ...),
    None when it gave none; `aborted` says that a streamed reply was abandoned on request
    before it ended, so it holds only what had arrived, with no usage and no finish reason;
    `usage` is None when the backend reports none; `latency` is in seconds."""

    text: str
    truncated: bool = False
    max_tokens: int | None = None
    reasoning: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str | None = None
    aborted: bool = False
    usage: Usage | None = None
    latency: float


class LLMRequest(StrictModel):
    """One chat completion.

    `model` and `sampling` override the client's configuration where set. `json_schema` asks
    for a reply matching that schema; how it is enforced depends on the client's
    structured-output mode, so the prompt should still describe the expected reply, and on
    `after_invalid`, which says that the reply is asked for again after an invalid one.
    `tools` declares the tools the model may call, as OpenAI function tools
    (`{"type": "function", "function": {"name", "description", "parameters"}}`), and
    `tool_choice` (`auto`, `none`, `required` or a named tool) constrains it; both are sent
    only when set, as is `reasoning_effort`. `extra_body` is merged over the configuration's
    for this request, key by key at the top level (`chat_template_kwargs`, for instance).
    `replica` keeps a conversation on one replica of a server that runs several: the request
    goes to replica `replica` modulo their number, whose prefix cache then serves the
    conversation's next request.
    `metadata` (agent id, purpose, simulated time, ...) is logged and never sent to the model.
    `verdict` is how the caller will judge the reply, for a log of the calls to record with
    it: None if the reply serves, else how it fails; it is neither sent nor logged itself.
    """

    messages: tuple[Message, ...] = Field(min_length=1)
    model: str | None = None
    sampling: Sampling = Sampling()
    json_schema: dict[str, JsonValue] | None = None
    after_invalid: bool = False
    tools: tuple[dict[str, JsonValue], ...] = ()
    tool_choice: str | dict[str, JsonValue] | None = None
    reasoning_effort: str | None = None
    extra_body: dict[str, JsonValue] = Field(default_factory=dict)
    replica: NonNegativeInt | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    verdict: Callable[[LLMResponse], str | None] | None = Field(
        default=None, exclude=True, repr=False
    )


class LLMClient(Protocol):
    async def complete(self, request: LLMRequest) -> LLMResponse: ...


class StreamingClient(LLMClient, Protocol):
    """A client that can also stream a reply and abandon it on request."""

    async def stream(
        self, request: LLMRequest, *, abort: asyncio.Event | None = None
    ) -> LLMResponse:
        """The reply to `request`, received as a stream. If `abort` is set before the reply
        ends, the stream is closed at once and the reply returned marked `aborted` with what
        had arrived. Errors are those of `complete`."""
        ...


class LLMError(Exception):
    """Base of all LLM-layer errors."""


class LLMConfigError(LLMError):
    """A client cannot be built from the given configuration."""


class LLMCallError(LLMError):
    """The backend failed: it cannot be reached, refused the credentials or the request, or
    answered with an error. Nothing a caller can retry fixes it."""


class LLMContextOverflowError(LLMCallError):
    """The backend refused the request because its messages do not fit the model's context
    window; asked again as it stands, it is refused again."""


class LLMBusyError(LLMError):
    """The backend gave no reply in time: it kept rejecting the call as rate-limited, or the
    call kept timing out, through every retry the client allows. To the caller this is one
    failed attempt at a reply, not a failure of the backend."""


class StructuredOutputError(LLMError):
    """No valid reply could be obtained in the bounded attempts: each of them was cut off by
    the token limit, invalid, empty or not answered in time. `failures` says how each attempt
    failed, in order; `text` is the last reply received."""

    def __init__(self, what: str, failures: Sequence[str], text: str) -> None:
        self.failures = tuple(failures)
        self.attempts = len(self.failures)
        self.text = text
        self.error = self.failures[-1]
        super().__init__(
            f"no valid {what} after {self.attempts} attempt(s); last error: {self.error}"
        )
