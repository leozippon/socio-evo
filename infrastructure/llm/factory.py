"""Build the client an LLMConfig asks for."""

from infrastructure.llm.base import LLMClient, LLMConfigError
from infrastructure.llm.config import LLMConfig
from infrastructure.llm.openai_compatible import OpenAICompatibleClient
from infrastructure.llm.scripted import Responder, ScriptedClient


def create_client(config: LLMConfig, responder: Responder | None = None) -> LLMClient:
    """The configured backend. `responder` is required by, and only allowed for, `scripted`."""
    if config.backend == "scripted":
        if responder is None:
            raise LLMConfigError("the scripted backend needs a responder supplied in code")
        return ScriptedClient(responder, enforces_schema=config.structured_output == "json_schema")
    if responder is not None:
        raise LLMConfigError(f"a responder cannot be used with the {config.backend} backend")
    return OpenAICompatibleClient(config)
