"""Completion with bounded retries: of free text cut off by the token limit, and of structured
replies that are cut off or invalid, the latter informed by their errors."""

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from infrastructure.config import describe_validation_error
from infrastructure.llm.base import (
    LLMCallError,
    LLMClient,
    LLMRequest,
    Message,
    StructuredOutputError,
)

T = TypeVar("T", bound=BaseModel)

TRUNCATED = "cut off by the token limit"


async def complete_text(client: LLMClient, request: LLMRequest, *, attempts: int = 3) -> str:
    """The text of a reply to `request` that was not cut off by the token limit, asked for up
    to `attempts` times; then LLMCallError. Each call's metadata gains its `attempt` number.
    Errors from the client propagate unchanged."""
    for attempt in range(1, _check(attempts) + 1):
        response = await client.complete(_attempt(request, request.messages, attempt))
        if not response.truncated:
            return response.text
    raise LLMCallError(f"every reply in {attempts} attempt(s) was {TRUNCATED}")


async def complete_structured(
    client: LLMClient, request: LLMRequest, model: type[T], *, attempts: int = 3
) -> T:
    """Ask for a reply matching `model`'s JSON schema and return it validated.

    A reply cut off by the token limit is asked for again as it was; an invalid one is sent
    back with its validation errors and the reply requested again. After `attempts` calls in
    total StructuredOutputError is raised. Each call's metadata gains its `attempt` number.
    Errors from the client propagate unchanged.
    """
    schema = model.model_json_schema()
    messages = request.messages
    for attempt in range(1, _check(attempts) + 1):
        response = await client.complete(
            _attempt(request, messages, attempt).model_copy(update={"json_schema": schema})
        )
        if response.truncated:
            error = TRUNCATED
            continue
        try:
            return model.model_validate_json(response.text)
        except ValidationError as exc:
            error = describe_validation_error(exc)
        messages = (
            *messages,
            Message(role="assistant", content=response.text),
            Message(
                role="user",
                content=f"That reply was invalid ({error}). "
                "Reply again with only a JSON object in the required format.",
            ),
        )
    raise StructuredOutputError(model.__name__, attempts, response.text, error)


def _check(attempts: int) -> int:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    return attempts


def _attempt(request: LLMRequest, messages: tuple[Message, ...], attempt: int) -> LLMRequest:
    return request.model_copy(
        update={"messages": messages, "metadata": {**request.metadata, "attempt": attempt}}
    )
