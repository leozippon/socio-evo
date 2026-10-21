"""Completion with bounded attempts: of free text that is cut off by the token limit or empty,
and of structured replies that are cut off or invalid, the latter told what was wrong.

An attempt also fails when the client gives up on a reply that does not come in time
(LLMBusyError). After the last attempt StructuredOutputError says how each one failed. Any
other error of the client propagates at once: the backend itself failed.

Every request carries the verdict its reply will be given, so that a log of the calls says how
each attempt failed. Retries retain the requested output allowance; the client's context
guard checks the assembled conversation before it reaches the backend.
"""

import re
from collections.abc import Callable
from typing import NamedTuple, TypeVar

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
_ESCAPED = set('"\\/ntu')

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
    request = request.model_copy(update={"verdict": _text_failure})
    failures: list[str] = []
    text = ""
    for attempt in range(1, _check(attempts) + 1):
        asked = _attempt(request, request.messages, attempt)
        response = await _call(client, asked, failures)
        if response is None:
            continue
        text = response.text
        failure = _text_failure(response)
        if failure is None:
            return text
        failures.append(failure)
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

    A reply is read as JSON in which a backslash stands for itself unless it begins a quote, a
    backslash, a slash, a newline, a tab or a unicode escape. A reply cut off by the token
    limit is discarded and a complete, concise reply requested; an invalid one is sent back
    with `correction` of its validation error. Both mark this and every later retry
    `after_invalid` (a client may then enforce the schema). A reply not answered in time is
    asked for again as it was. Each call's metadata gains its `attempt` number.
    """

    def verdict(response: LLMResponse) -> str | None:
        reply = _read(model, response)
        return reply.failure if isinstance(reply, _Unread) else None

    request = request.model_copy(
        update={"json_schema": model.model_json_schema(), "verdict": verdict}
    )
    messages = request.messages
    failures: list[str] = []
    text = ""
    for attempt in range(1, _check(attempts) + 1):
        response = await _call(client, _attempt(request, messages, attempt), failures)
        if response is None:
            continue
        text = response.text
        reply = _read(model, response)
        if not isinstance(reply, _Unread):
            return reply
        failures.append(reply.failure)
        if response.truncated:
            messages = (
                *request.messages,
                Message(
                    role="user",
                    content=(
                        "Your reply was cut off before it was complete. "
                        "Give a complete reply in the required format, "
                        "keeping the explanation brief."
                    ),
                ),
            )
            request = request.model_copy(update={"after_invalid": True})
        elif reply.error is not None:
            messages = (
                *messages,
                Message(role="assistant", content=text),
                Message(role="user", content=correction(model, reply.error)),
            )
            request = request.model_copy(update={"after_invalid": True})
    raise StructuredOutputError(model.__name__, failures, text)


class _Unread(NamedTuple):
    """Why a structured reply cannot be read, and its validation error if it was invalid."""

    failure: str
    error: ValidationError | None = None


def _read(model: type[T], response: LLMResponse) -> T | _Unread:
    """The reply in `response` validated as `model`, or why it cannot be read."""
    if response.truncated:
        return _Unread(TRUNCATED)
    try:
        return model.model_validate_json(_lone_backslashes(response.text))
    except ValidationError as error:
        return _Unread(INVALID.format(error=describe_validation_error(error)), error)


def _text_failure(response: LLMResponse) -> str | None:
    """Why a free text reply cannot be used, or None if it is whole."""
    if response.truncated:
        return TRUNCATED
    return None if response.text.strip() else EMPTY


async def _call(client: LLMClient, request: LLMRequest, failures: list[str]) -> LLMResponse | None:
    """The reply to `request`, or None, with the failure added to `failures`, if it did not
    come in time."""
    try:
        return await client.complete(request)
    except LLMBusyError as error:
        failures.append(str(error))
        return None


def _lone_backslashes(text: str) -> str:
    """`text` with every backslash doubled that begins no JSON escape, or the escape of a
    backspace, a form feed or a carriage return, which no reply means, so that it stands for
    itself as its writer meant: a reply that quotes code in a string often leaves a regular
    expression's `\\d` or `\\b` as it is, and one that writes mathematics LaTeX's `\\frac`,
    `\\beta` or `\\right`. Other valid JSON is unchanged."""
    return _ESCAPE.sub(
        lambda escape: escape[0] if escape[1] in _ESCAPED else "\\" + escape[0], text
    )


def _check(attempts: int) -> int:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    return attempts


def _attempt(request: LLMRequest, messages: tuple[Message, ...], attempt: int) -> LLMRequest:
    """Keep the output allowance and label this bounded attempt."""
    return request.model_copy(
        update={"messages": messages, "metadata": {**request.metadata, "attempt": attempt}}
    )
