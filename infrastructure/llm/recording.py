"""Client wrapper that logs every call as one JSON line."""

import asyncio
import time
from pathlib import Path

from infrastructure.llm.base import LLMClient, LLMPartial, LLMRequest, LLMResponse
from infrastructure.storage.jsonl import append_jsonl


class RecordingClient:
    """Delegates to `inner` and appends one record per call to `path`, failed calls included.

    Record fields: `metadata`; `request` (without metadata); `response` (text, whether it was
    cut off by the token limit, the limit it was given, reasoning, usage, latency) or null;
    `failure`, the request's verdict on the reply: how it fails, or null if it serves, there
    is no reply or the request carries no verdict; `error` (`type`, `message`) or null. A
    failure of the call is re-raised after it is recorded.
    """

    def __init__(self, inner: LLMClient, path: Path) -> None:
        self._inner = inner
        self._path = path

    async def complete(self, request: LLMRequest) -> LLMResponse:
        try:
            response = await self._inner.complete(request)
        except asyncio.CancelledError as exc:
            self._record(request, None, exc, interrupted=True)
            raise
        except Exception as exc:
            self._record(request, None, exc)
            raise
        self._record(request, response, None)
        return response

    async def complete_stream(self, request: LLMRequest, partial: LLMPartial) -> LLMResponse:
        stream = getattr(self._inner, "complete_stream", None)
        if stream is None:
            return await self.complete(request)
        started = time.perf_counter()
        try:
            response = await stream(request, partial)
        except asyncio.CancelledError as exc:
            self._record(
                request,
                partial.response(latency=time.perf_counter() - started),
                exc,
                interrupted=True,
            )
            raise
        except Exception as exc:
            self._record(request, partial.response(latency=time.perf_counter() - started), exc)
            raise
        self._record(request, response, None)
        return response

    def _record(
        self,
        request: LLMRequest,
        response: LLMResponse | None,
        error: BaseException | None,
        *,
        interrupted: bool = False,
    ) -> None:
        task = asyncio.current_task()
        interrupted = interrupted or bool(task is not None and task.cancelling())
        append_jsonl(
            self._path,
            {
                "metadata": request.metadata,
                "interrupted": interrupted,
                "request": {
                    **request.model_dump(mode="json", exclude={"metadata", "messages"}),
                    "messages": [m.model_dump(exclude_none=True) for m in request.messages],
                },
                "response": None if response is None else response.model_dump(mode="json"),
                "failure": None
                if interrupted or response is None or request.verdict is None
                else request.verdict(response),
                "error": None
                if error is None
                else {"type": type(error).__name__, "message": str(error)},
            },
        )
