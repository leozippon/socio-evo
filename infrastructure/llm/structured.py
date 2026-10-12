"""Completion with bounded attempts: of free text that is cut off by the token limit or empty,
and of structured replies that are cut off or invalid, the latter told what was wrong.

An attempt also fails when the client gives up on a reply that does not come in time
(LLMBusyError). After the last attempt StructuredOutputError says how each one failed. Any
other error of the client propagates at once: the backend itself failed.
"""

import re
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from infrastructure.config import describe_validation_error
from infrastructure.llm.base import (
    LLMBusyError,
    LLMClient,
    LLMRequest,
    LLMResponse,
    Message,
    StructuredOutputError,
)

T = TypeVar("T", bound=BaseModel)

TRUNCATED = "cut off by the token limit"
EMPTY = "empty"
INVALID = "invalid: {error}"

_ESCAPE = re.compile(r"\\(.)", re.DOTALL)
_ESCAPED = set('"\\/bfnrtu')

Correction = Callable[[type[BaseModel], ValidationError], str]
"""What the model is told after an invalid reply, from the reply model and the reply's
validation error."""


def technical(model: type[BaseModel], error: ValidationError) -> str:
    """The default correction, in technical terms, for models that are not residents."""
    return (
        f"That reply was invalid ({describe_validation_error(error)}). "
        "Reply again with only a JSON object in the required format."
    )


async def complete_text(client: LLMClient, request: LLMRequest, *, attempts: int = 3) -> str:
    """The text of a reply to `request` that is neither cut off by the token limit nor empty,
    asked for as it is up to `attempts` times. Each call's metadata gains its `attempt`
    number."""
    failures: list[str] = []
    text = ""
    for attempt in range(1, _check(attempts) + 1):
        response = await _call(client, _attempt(request, request.messages, attempt), failures)
        if response is None:
            continue
        text = response.text
        if text.strip():
            return text
        failures.append(EMPTY)
    raise StructuredOutputError("text", failures, text)


async def complete_structured(
    client: LLMClient,
    request: LLMRequest,
    model: type[T],
    *,
    attempts: int = 3,
    correction: Correction = technical,
) -> T:
    """Ask for a reply matching `model`'s JSON schema and return it validated.

    A reply is read as JSON in which a backslash that begins no escape stands for itself. A
    reply cut off by the token limit, or not answered in time, is asked for again as it was;
    an invalid one is sent back with `correction` of its validation error and the reply
    requested again, this and every later request marked `after_invalid` (a client may then
    enforce the schema). Each call's metadata gains its `attempt` number.
    """
    schema = model.model_json_schema()
    messages = request.messages
    failures: list[str] = []
    text = ""
    for attempt in range(1, _check(attempts) + 1):
        asked = _attempt(request, messages, attempt).model_copy(update={"json_schema": schema})
        response = await _call(client, asked, failures)
        if response is None:
            continue
        text = response.text
        try:
            return model.model_validate_json(_lone_backslashes(text))
        except ValidationError as error:
            failures.append(INVALID.format(error=describe_validation_error(error)))
            messages = (
                *messages,
                Message(role="assistant", content=text),
                Message(role="user", content=correction(model, error)),
            )
            request = request.model_copy(update={"after_invalid": True})
    raise StructuredOutputError(model.__name__, failures, text)


async def _call(client: LLMClient, request: LLMRequest, failures: list[str]) -> LLMResponse | None:
    """The reply to `request`, or None, with the failure added to `failures`, if it was cut
    off or did not come in time."""
    try:
        response = await client.complete(request)
    except LLMBusyError as error:
        failures.append(str(error))
        return None
    if response.truncated:
        failures.append(TRUNCATED)
        return None
    return response


def _lone_backslashes(text: str) -> str:
    """`text` with every backslash that begins no JSON escape doubled, so that it stands for
    itself as its writer meant: a reply that quotes code in a string often leaves a
    regular expression's `\\d` as it is. Valid JSON is unchanged."""
    return _ESCAPE.sub(
        lambda escape: escape[0] if escape[1] in _ESCAPED else "\\" + escape[0], text
    )


def _check(attempts: int) -> int:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    return attempts


def _attempt(request: LLMRequest, messages: tuple[Message, ...], attempt: int) -> LLMRequest:
    return request.model_copy(
        update={"messages": messages, "metadata": {**request.metadata, "attempt": attempt}}
    )
