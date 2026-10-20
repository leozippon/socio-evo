"""One interruptible decision, retaining received drafts until it is accepted."""

import asyncio
from contextvars import ContextVar

from infrastructure.llm.base import LLMPartial, Message


class DecisionContinuation:
    def __init__(self):
        self.messages = ()
        self.notes = []
        self._commit = None
        self.committed = False

    def begin(self):
        if self.committed:
            raise RuntimeError("decision already committed")
        self._commit = None
        self.notes.clear()

    def stage(self, commit):
        if self.committed:
            raise RuntimeError("decision already committed")
        self._commit = commit

    def commit(self):
        if self.committed:
            return
        if self._commit is None:
            raise RuntimeError("no completed decision to commit")
        for store, task, time, note in self.notes:
            store.write_note(task, time, note)
        self._commit()
        self.committed = True
        self._commit = None


current: ContextVar[DecisionContinuation | None] = ContextVar("decision_continuation", default=None)


class ContinuationClient:
    def __init__(self, client, continuation, *, budget=None):
        self.client, self.continuation, self.budget = client, continuation, budget

    async def complete(self, request):
        continuation = self.continuation
        if continuation.messages:
            request = request.model_copy(
                update={
                    "messages": (
                        *continuation.messages,
                        Message(
                            role="user",
                            content=(
                                "You have not acted yet. Here is the current situation. "
                                "Continue thinking and choose what to do.\n\n"
                            )
                            + request.messages[-1].content,
                        ),
                    )
                }
            )
        if self.budget is not None:
            from core.agent.context import ContextOverflow, Counter, input_limit

            if request.sampling.max_tokens is None:
                request = request.model_copy(
                    update={
                        "sampling": request.sampling.model_copy(
                            update={"max_tokens": self.budget.output_tokens}
                        )
                    }
                )
            counter = Counter(self.budget)
            limit = input_limit(self.budget, request)
            count = counter.request(request)
            if count > limit:
                raise ContextOverflow(
                    f"Input budget exceeded: {count} > {limit} ({counter.method})"
                )
        partial = LLMPartial()
        stream = getattr(self.client, "complete_stream", None)
        try:
            response = await (stream(request, partial) if stream else self.client.complete(request))
            continuation.messages = (
                *request.messages,
                Message(
                    role="assistant", content=response.text, reasoning_content=response.reasoning
                ),
            )
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                partial.text = response.text
                partial.reasoning = response.reasoning or ""
                raise asyncio.CancelledError
            return response
        except asyncio.CancelledError:
            continuation.messages = (
                *request.messages,
                Message(
                    role="assistant",
                    content=partial.text,
                    reasoning_content=partial.reasoning or None,
                ),
            )
            continuation._commit = None
            continuation.notes.clear()
            raise
