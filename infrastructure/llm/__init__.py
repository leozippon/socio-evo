"""LLM access: backend-neutral types, clients and structured completion."""

from infrastructure.llm.base import (
    LLMBusyError,
    LLMCallError,
    LLMClient,
    LLMConfigError,
    LLMError,
    LLMRequest,
    LLMResponse,
    Message,
    Sampling,
    StreamingClient,
    StructuredOutputError,
    ToolCall,
    Usage,
)
from infrastructure.llm.config import LLMConfig
from infrastructure.llm.factory import create_client
from infrastructure.llm.openai_compatible import OpenAICompatibleClient
from infrastructure.llm.recording import RecordingClient
from infrastructure.llm.scripted import Responder, ScriptedClient
from infrastructure.llm.structured import complete_structured, complete_text

__all__ = [
    "LLMBusyError",
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
    "StreamingClient",
    "StructuredOutputError",
    "ToolCall",
    "Usage",
    "complete_structured",
    "complete_text",
    "create_client",
]
