"""Backend-neutral LLM types: messages, requests, responses, the client protocol and errors."""

from typing import Literal, Protocol

from pydantic import Field, JsonValue, PositiveInt

from infrastructure.config import StrictModel


class Message(StrictModel):
    role: Literal["system", "user", "assistant"]
    content: str


class Sampling(StrictModel):
    """Sampling settings; an unset field defers to the next layer (request, client, server)."""

    temperature: float | None = Field(default=None, ge=0)
    top_p: float | None = Field(default=None, gt=0, le=1)
    max_tokens: PositiveInt | None = None

    def over(self, defaults: "Sampling") -> "Sampling":
        """These settings, with unset fields taken from `defaults`."""
        return defaults.model_copy(update=self.model_dump(exclude_none=True))


class LLMRequest(StrictModel):
    """One chat completion.

    `model` and `sampling` override the client's configuration where set. `json_schema` asks
    for a reply matching that schema; how it is enforced depends on the client's
    structured-output mode, so the prompt must describe the expected reply unless the client
    `enforces_schema`.
    `metadata` (agent id, purpose, simulated time, ...) is logged and never sent to the model.
    """

    messages: tuple[Message, ...] = Field(min_length=1)
    model: str | None = None
    sampling: Sampling = Sampling()
    json_schema: dict[str, JsonValue] | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class Usage(StrictModel):
    prompt_tokens: int
    completion_tokens: int


class LLMResponse(StrictModel):
    """The model's reply. `reasoning` is separated reasoning text when the backend returns it;
    `usage` is None when the backend reports none; `latency` is in seconds."""

    text: str
    reasoning: str | None = None
    usage: Usage | None = None
    latency: float


class LLMClient(Protocol):
    enforces_schema: bool
    """Whether a request's `json_schema` is enforced while the reply is generated (guided
    decoding), so that the prompt need not describe the reply's structure."""

    async def complete(self, request: LLMRequest) -> LLMResponse: ...


class LLMError(Exception):
    """Base of all LLM-layer errors."""


class LLMConfigError(LLMError):
    """A client cannot be built from the given configuration."""


class LLMCallError(LLMError):
    """The backend call failed or returned no usable reply (error status, timeout, truncation)."""


class StructuredOutputError(LLMError):
    """The reply still failed schema validation after the last allowed attempt."""

    def __init__(self, model_name: str, attempts: int, text: str, error: str) -> None:
        super().__init__(f"no valid {model_name} after {attempts} attempt(s); last error: {error}")
        self.attempts = attempts
        self.text = text
        self.error = error
