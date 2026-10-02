"""Configuration of the LLM backend."""

from typing import Literal

from pydantic import Field, JsonValue, NonNegativeInt, PositiveFloat, PositiveInt

from infrastructure.config import StrictModel
from infrastructure.llm.base import Sampling


class LLMConfig(StrictModel):
    """An OpenAI-compatible endpoint and its defaults.

    The API key is read from the environment variable named by `api_key_env`.
    `structured_output` chooses how a request's JSON schema is enforced: guided decoding
    (`json_schema`), JSON mode (`json_object`) or not at all (`none`); replies are validated
    in every mode. `extra_body` is merged into every request body for server-specific options.
    `backend: scripted` keeps these settings but replaces the endpoint with a responder
    supplied in code, for dry runs; the endpoint fields are then unused.
    """

    backend: Literal["openai_compatible", "scripted"] = "openai_compatible"
    base_url: str
    api_key_env: str
    model: str
    sampling: Sampling = Sampling()
    timeout: PositiveFloat = 300.0
    max_retries: NonNegativeInt = 2
    max_concurrency: PositiveInt = 8
    structured_output: Literal["json_schema", "json_object", "none"] = "json_schema"
    extra_body: dict[str, JsonValue] = Field(default_factory=dict)
