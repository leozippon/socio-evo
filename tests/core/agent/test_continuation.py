import asyncio

import pytest

from core.agent import DecisionContinuation
from core.agent.continuation import ContinuationClient
from infrastructure.llm.base import LLMRequest, LLMResponse, Message
from infrastructure.llm.recording import RecordingClient
from infrastructure.storage.jsonl import read_jsonl


async def test_cancel_retains_draft_and_reasoning_and_logs_interruption(tmp_path):
    entered = asyncio.Event()
    closed = asyncio.Event()
    requests = []

    class Stream:
        async def complete_stream(self, request, partial):
            requests.append(request)
            if len(requests) == 1:
                partial.text = '{"thought":'
                partial.reasoning = "unfinished reasoning"
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    closed.set()
            return LLMResponse(text='{"do":"pass"}', latency=0)

    continuation = DecisionContinuation()
    path = tmp_path / "calls.jsonl"
    client = ContinuationClient(RecordingClient(Stream(), path), continuation)
    task = asyncio.create_task(
        client.complete(LLMRequest(messages=(Message(role="user", content="old"),)))
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    await client.complete(LLMRequest(messages=(Message(role="user", content="new observation"),)))
    assert requests[1].messages[1].content == '{"thought":'
    assert requests[1].messages[1].reasoning_content == "unfinished reasoning"
    assert "new observation" in requests[1].messages[-1].content
    interrupted = list(read_jsonl(path))[0]
    assert interrupted["interrupted"] is True
    assert interrupted["response"]["reasoning"] == "unfinished reasoning"


async def test_decision_staged_until_accepted_and_committed_once(agent, observe):
    continuation = DecisionContinuation()
    await agent.act(observe(1), continuation=continuation)
    assert len(agent.memory.episodic.read()) == 1
    continuation.commit()
    continuation.commit()
    assert len(agent.memory.episodic.read()) == 2


async def test_new_attempt_cannot_commit_previous_completed_decision(agent, observe):
    continuation = DecisionContinuation()
    await agent.act(observe(1), continuation=continuation)

    class Failed:
        async def complete(self, request):
            raise RuntimeError("backend failed")

    agent.client = Failed()
    with pytest.raises(RuntimeError, match="backend failed"):
        await agent.act(observe(2), continuation=continuation)
    with pytest.raises(RuntimeError, match="no completed decision"):
        continuation.commit()
    assert all(record.seq is not None for record in agent.memory.episodic.read())


async def test_reasoning_only_history_cannot_bypass_context_budget():
    from core.agent.config import ContextBudgetConfig
    from core.agent.context import ContextOverflow

    continuation = DecisionContinuation()
    continuation.messages = (Message(role="assistant", content="", reasoning_content="x" * 100000),)

    class NeverCalled:
        async def complete(self, request):
            raise AssertionError("over-budget history reached model")

    client = ContinuationClient(
        NeverCalled(), continuation, budget=ContextBudgetConfig(enabled=True)
    )
    with pytest.raises(ContextOverflow):
        await client.complete(LLMRequest(messages=(Message(role="user", content="new"),)))


async def test_swallowed_cancel_cannot_start_old_structured_correction():
    entered = asyncio.Event()

    class Swallows:
        async def complete(self, request):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return LLMResponse(
                    text="invalid old result", reasoning="received thought", latency=0
                )

    continuation = DecisionContinuation()
    client = ContinuationClient(Swallows(), continuation)
    task = asyncio.create_task(
        client.complete(LLMRequest(messages=(Message(role="user", content="old"),)))
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert continuation.messages[-1].content == "invalid old result"
    assert continuation.messages[-1].reasoning_content == "received thought"


@pytest.mark.parametrize("preserves_reasoning", [True, False])
def test_tokenizer_budget_counts_reasoning_once_even_when_template_omits_it(preserves_reasoning):
    from core.agent.config import ContextBudgetConfig
    from core.agent.context import Counter

    class Tokenizer:
        def encode(self, text, **kwargs):
            return list(text)

        def apply_chat_template(self, messages, **kwargs):
            count = sum(len(message["content"]) for message in messages) + 16
            if preserves_reasoning:
                count += sum(len(message.get("reasoning_content") or "") for message in messages)
            return [0] * count

    counter = Counter(ContextBudgetConfig())
    counter.tokenizer = Tokenizer()
    request = LLMRequest(
        messages=(Message(role="assistant", content="x", reasoning_content="reason"),)
    )
    assert counter.request(request) == 23
