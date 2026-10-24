"""Build the client an LLMConfig asks for."""

import os

from infrastructure.llm.base import LLMConfigError, StreamingClient
from infrastructure.llm.config import LLMConfig
from infrastructure.llm.openai_compatible import OpenAICompatibleClient
from infrastructure.llm.scripted import Responder, ScriptedClient


def create_client(config: LLMConfig, responder: Responder | None = None) -> StreamingClient:
    """The configured backend. `responder` is required by, and only allowed for, `scripted`.
    Environment variables written `${NAME}` in `base_url` are expanded here, so a frozen
    configuration can name the server without holding its address."""
    if config.backend == "scripted":
        if responder is None:
            raise LLMConfigError("the scripted backend needs a responder supplied in code")
        return ScriptedClient(responder)
    if responder is not None:
        raise LLMConfigError(f"a responder cannot be used with the {config.backend} backend")
    base_url = os.path.expandvars(config.base_url)
    if "$" in base_url:
        raise LLMConfigError(f"base_url {config.base_url} names an unset environment variable")
    return OpenAICompatibleClient(config.model_copy(update={"base_url": base_url}))
