"""Configuration of the LLM backend."""

from typing import Literal

from pydantic import Field, JsonValue, NonNegativeInt, PositiveFloat, PositiveInt

from infrastructure.config import StrictModel
from infrastructure.llm.base import Sampling

StructuredMode = Literal["json_schema", "json_object", "none"]
"""How a request's JSON schema is enforced: guided decoding, JSON mode, or not at all."""


class LLMConfig(StrictModel):
    """An OpenAI-compatible endpoint and its defaults.

    The API key is read from the environment variable named by `api_key_env`.
    `structured_output` chooses how a request's JSON schema is enforced: guided decoding
    (`json_schema`), JSON mode (`json_object`) or not at all (`none`); replies are validated
    in every mode, and one that is invalid is asked for again, enforced as
    `structured_retry` says if it is set. Under a grammar, a quotation mark left unescaped
    in a string ends the string, and the model, unable to write what it meant, may fill the
    reply with whitespace up to the token limit; unenforced, a model asked again tends to
    repeat its slip word for word. `extra_body` is merged into every request body for
    server-specific options. `backend: scripted` keeps these settings but replaces the
    endpoint with a responder supplied in code, for dry runs; the endpoint fields are then
    unused.

    The defaults suit a shared server that is sometimes saturated: a call may wait `timeout`
    seconds for the server (a whole reply, or each piece of a stream), long enough for the
    first token of a full context (about two minutes on the local server) and for a reply of
    16,384 tokens at the local server's 25 tokens a second, and a call the server rejects as
    rate-limited, or that times out, is retried up to `max_retries` times, after `backoff`
    seconds and then twice as long each time (at most a minute), before it counts as one
    failed attempt at a reply. A call that cannot connect or meets a server error is retried
    twice; that and every other failure of the call is final.
    """

    backend: Literal["openai_compatible", "scripted"] = "openai_compatible"
    base_url: str
    api_key_env: str
    model: str
    sampling: Sampling = Sampling()
    timeout: PositiveFloat = 900.0
    max_retries: NonNegativeInt = 6
    backoff: PositiveFloat = 2.0
    max_concurrency: PositiveInt = 8
    structured_output: StructuredMode = "json_schema"
    structured_retry: StructuredMode | None = None
    extra_body: dict[str, JsonValue] = Field(default_factory=dict)
