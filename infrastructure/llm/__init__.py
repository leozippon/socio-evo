"""LLM access: backend-neutral types, clients and structured completion."""

from infrastructure.llm.base import (
    LLMCallError,
    LLMClient,
    LLMConfigError,
    LLMError,
    LLMRequest,
    LLMResponse,
    Message,
    Sampling,
    StructuredOutputError,
    Usage,
)
from infrastructure.llm.config import LLMConfig
from infrastructure.llm.factory import create_client
from infrastructure.llm.openai_compatible import OpenAICompatibleClient
from infrastructure.llm.recording import RecordingClient
from infrastructure.llm.scripted import Responder, ScriptedClient
from infrastructure.llm.structured import complete_structured

__all__ = [
    "LLMCallError",
    "LLMClient",
    "LLMConfig",
    "LLMConfigError",
    "LLMError",
    "LLMRequest",
    "LLMResponse",
    "Message",
    "OpenAICompatibleClient",
    "RecordingClient",
    "Responder",
    "Sampling",
    "ScriptedClient",
    "StructuredOutputError",
    "Usage",
    "complete_structured",
    "create_client",
]
