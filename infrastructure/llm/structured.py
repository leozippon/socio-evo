"""Schema-constrained completion with bounded, error-informed retries."""

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from infrastructure.config import describe_validation_error
from infrastructure.llm.base import LLMClient, LLMRequest, Message, StructuredOutputError

T = TypeVar("T", bound=BaseModel)


async def complete_structured(
    client: LLMClient, request: LLMRequest, model: type[T], *, attempts: int = 3
) -> T:
    """Ask for a reply matching `model`'s JSON schema and return it validated.

    An invalid reply is sent back with its validation errors and the reply requested again,
    up to `attempts` calls in total; then StructuredOutputError is raised. Each call's
    metadata gains its `attempt` number. Errors from the client propagate unchanged.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    schema = model.model_json_schema()
    messages = request.messages
    for attempt in range(1, attempts + 1):
        response = await client.complete(
            request.model_copy(
                update={
                    "messages": messages,
                    "json_schema": schema,
                    "metadata": {**request.metadata, "attempt": attempt},
                }
            )
        )
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
