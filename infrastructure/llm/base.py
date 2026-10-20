"""Backend-neutral LLM types: messages, requests, responses, the client protocol and errors."""

from collections.abc import Callable, Sequence
from typing import Literal, Protocol

from pydantic import Field, JsonValue, PositiveInt

from infrastructure.config import StrictModel


class Message(StrictModel):
    role: Literal["system", "user", "assistant"]
    content: str
    reasoning_content: str | None = None


class Sampling(StrictModel):
    """Sampling settings; an unset field defers to the next layer (request, client, server)."""

    temperature: float | None = Field(default=None, ge=0)
    top_p: float | None = Field(default=None, gt=0, le=1)
    max_tokens: PositiveInt | None = None

    def over(self, defaults: "Sampling") -> "Sampling":
        """These settings, with unset fields taken from `defaults`."""
        return defaults.model_copy(update=self.model_dump(exclude_none=True))


class Usage(StrictModel):
    prompt_tokens: int
    completion_tokens: int


class LLMResponse(StrictModel):
    """The model's reply, which may be empty. `truncated` says that it was cut off by the
    token limit, so `text` holds only what came before; `max_tokens` is the token limit the
    call was made with, None when none was set or the backend is no model; `reasoning` is
    separated reasoning text when the backend returns it; `usage` is None when the backend
    reports none; `latency` is in seconds."""

    text: str
    truncated: bool = False
    max_tokens: int | None = None
    reasoning: str | None = None
    usage: Usage | None = None
    latency: float


class LLMRequest(StrictModel):
    """One chat completion.

    `model` and `sampling` override the client's configuration where set. `json_schema` asks
    for a reply matching that schema; how it is enforced depends on the client's
    structured-output mode, so the prompt should still describe the expected reply, and on
    `after_invalid`, which says that the reply is asked for again after an invalid one.
    `metadata` (agent id, purpose, simulated time, ...) is logged and never sent to the model.
    `verdict` is how the caller will judge the reply, for a log of the calls to record with
    it: None if the reply serves, else how it fails; it is neither sent nor logged itself.
    """

    messages: tuple[Message, ...] = Field(min_length=1)
    model: str | None = None
    sampling: Sampling = Sampling()
    json_schema: dict[str, JsonValue] | None = None
    after_invalid: bool = False
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    verdict: Callable[[LLMResponse], str | None] | None = Field(
        default=None, exclude=True, repr=False
    )


class LLMClient(Protocol):
    async def complete(self, request: LLMRequest) -> LLMResponse: ...


class LLMError(Exception):
    """Base of all LLM-layer errors."""


class LLMConfigError(LLMError):
    """A client cannot be built from the given configuration."""


class LLMCallError(LLMError):
    """The backend failed: it cannot be reached, refused the credentials or the request, or
    answered with an error. Nothing a caller can retry fixes it."""


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


class LLMPartial:
    """Mutable received stream data; remains available after cancellation."""

    def __init__(self) -> None:
        self.text = ""
        self.reasoning = ""

    def response(self, *, latency: float = 0, **fields) -> LLMResponse:
        return LLMResponse(
            text=self.text, reasoning=self.reasoning or None, latency=latency, **fields
        )
