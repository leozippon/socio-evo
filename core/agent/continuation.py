"""One interruptible decision, retaining received drafts until it is accepted."""

import asyncio
from contextvars import ContextVar

from infrastructure.llm.base import LLMPartial, Message


class DecisionContinuation:
    def __init__(self):
        self.reply_draft = ()
        self.metadata = {}
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
        if self.budget is not None:
            from core.agent.context import unpack

            request = unpack(request)
        request = request.model_copy(
            update={"metadata": {**request.metadata, **continuation.metadata}}
        )
        incoming = request.messages
        # Structured retries carry previous replies/corrections in their incoming
        # messages. Keep the original base and only the latest correction; the
        # latest draft lives here, independently of those retry exchanges.
        split = next((i for i, m in enumerate(incoming) if m.role == "assistant"), len(incoming))
        base = incoming[:split]
        correction = incoming[-1].content if split < len(incoming) else None
        if continuation.messages:
            latest = base[-1]
            instruction = correction or (
                "Your draft has not been acted on. "
                "Use the current situation and give your complete reply."
            )
            request = request.model_copy(
                update={
                    "messages": (
                        *base[:-1],
                        continuation.messages[-1],
                        Message(role="user", content=latest.content + "\n\n" + instruction),
                    )
                }
            )
        if self.budget is not None:
            from core.agent.context import ContextOverflow, Counter, input_limit, repack

            if request.sampling.max_tokens is None:
                request = request.model_copy(
                    update={
                        "sampling": request.sampling.model_copy(
                            update={"max_tokens": self.budget.output_tokens}
                        )
                    }
                )
            request = repack(request, self.budget)
            counter = Counter(self.budget)
            limit = input_limit(self.budget, request)
            count = counter.request(request)
            if count > limit:
                raise ContextOverflow(
                    f"Input budget exceeded: {count} > {limit} ({counter.method})"
                )
            usage = {
                "method": counter.method,
                "input_count": count,
                "input_limit": limit,
                "output_reserve": request.sampling.max_tokens,
            }
            request = request.model_copy(
                update={
                    "metadata": {
                        **request.metadata,
                        "context_usage": usage,
                    }
                }
            )
        partial = LLMPartial()
        stream = getattr(self.client, "complete_stream", None)
        try:
            response = await (stream(request, partial) if stream else self.client.complete(request))
            if response.text:
                continuation.messages = (Message(role="assistant", content=response.text),)
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                partial.text = response.text
                partial.reasoning = response.reasoning or ""
                raise asyncio.CancelledError
            return response
        except asyncio.CancelledError:
            if partial.text:
                continuation.messages = (Message(role="assistant", content=partial.text),)
            continuation._commit = None
            continuation.notes.clear()
            raise
