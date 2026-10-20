import asyncio

import pytest

from core.agent import DecisionContinuation
from core.agent.continuation import ContinuationClient
from infrastructure.llm.base import LLMRequest, LLMResponse, Message
from infrastructure.llm.recording import RecordingClient
from infrastructure.storage.jsonl import read_jsonl


async def test_cancel_retains_only_answer_draft_and_logs_original_reasoning(tmp_path):
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
    assert requests[1].messages[0].content == '{"thought":'
    assert requests[1].messages[0].reasoning_content is None
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
    assert continuation.messages[-1].reasoning_content is None


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


async def test_truncated_then_invalid_preserves_drafts_and_correction_once():
    from pydantic import BaseModel

    from infrastructure.llm.base import Sampling
    from infrastructure.llm.structured import complete_structured

    class Reply(BaseModel):
        answer: int

    requests = []

    class Replies:
        async def complete(self, request):
            requests.append(request)
            return [
                LLMResponse(text="", reasoning="partial plan", truncated=True, latency=0),
                LLMResponse(text='{"answer":"bad"}', reasoning="continued plan", latency=0),
                LLMResponse(text='{"answer":7}', latency=0),
            ][len(requests) - 1]

    continuation = DecisionContinuation()
    client = ContinuationClient(Replies(), continuation)
    result = await complete_structured(
        client,
        LLMRequest(
            messages=(Message(role="user", content="unique scene"),),
            sampling=Sampling(max_tokens=4096),
        ),
        Reply,
    )
    assert result.answer == 7
    assert [r.sampling.max_tokens for r in requests] == [4096] * 3
    assert [r.after_invalid for r in requests] == [False, False, True]
    final = requests[-1].messages
    assert sum("unique scene" in m.content for m in final) == 1
    assert [m.content for m in final if m.role == "assistant"] == ['{"answer":"bad"}']
    assert all(m.reasoning_content is None for m in final)
    assert sum(m.content == '{"answer":"bad"}' for m in final) == 1
    assert "invalid" in final[-1].content


async def test_cancel_then_changed_observation_then_retry_shares_context():
    from pydantic import BaseModel

    from infrastructure.llm.structured import complete_structured

    class Reply(BaseModel):
        answer: int

    entered = asyncio.Event()
    requests = []

    class Stream:
        async def complete_stream(self, request, partial):
            requests.append(request)
            if len(requests) == 1:
                partial.reasoning = "cancelled draft"
                partial.text = '{"answer":'
                entered.set()
                await asyncio.Event().wait()
            if len(requests) == 2:
                return LLMResponse(text="", reasoning="new draft", truncated=True, latency=0)
            return LLMResponse(text='{"answer":9}', latency=0)

    continuation = DecisionContinuation()
    client = ContinuationClient(Stream(), continuation)
    task = asyncio.create_task(
        complete_structured(
            client, LLMRequest(messages=(Message(role="user", content="old scene"),)), Reply
        )
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    result = await complete_structured(
        client, LLMRequest(messages=(Message(role="user", content="new scene"),)), Reply
    )
    assert result.answer == 9
    final = requests[-1].messages
    assert sum("new scene" in m.content for m in final) == 1
    assert [m.content for m in final if m.role == "assistant"] == ['{"answer":']
    assert all(m.reasoning_content is None for m in final)
    assert not any("old scene" in m.content for m in final)
    with pytest.raises(RuntimeError, match="no completed decision"):
        continuation.commit()


async def test_busy_retry_keeps_the_pending_json_correction():
    from pydantic import BaseModel

    from infrastructure.llm.base import LLMBusyError
    from infrastructure.llm.structured import complete_structured

    class Reply(BaseModel):
        answer: int

    requests = []

    class Replies:
        async def complete(self, request):
            requests.append(request)
            if len(requests) == 1:
                return LLMResponse(text="bad answer", reasoning="retained draft", latency=0)
            if len(requests) == 2:
                raise LLMBusyError("busy")
            return LLMResponse(text='{"answer":1}', latency=0)

    result = await complete_structured(
        ContinuationClient(Replies(), DecisionContinuation()),
        LLMRequest(messages=(Message(role="user", content="scene"),)),
        Reply,
    )
    assert result.answer == 1
    assert requests[2].messages == requests[1].messages
    assert "invalid" in requests[2].messages[-1].content


async def test_fourteen_environment_changes_keep_one_scene_and_latest_nonempty_draft():
    requests = []

    class Cancel:
        async def complete_stream(self, request, partial):
            requests.append(request)
            # Several cancelled streams receive no output at all.
            if len(requests) % 3:
                partial.text = f"draft-{len(requests):02}"
            partial.reasoning = "not retained" * 100
            raise asyncio.CancelledError

    continuation = DecisionContinuation()
    client = ContinuationClient(Cancel(), continuation)
    latest = None
    for i in range(14):
        with pytest.raises(asyncio.CancelledError):
            await client.complete(
                LLMRequest(
                    messages=(
                        Message(role="system", content="stable"),
                        Message(role="user", content=f"scene-{i:02}" + "x" * 1000),
                    )
                )
            )
        request = requests[-1]
        assert request.messages[0].content == "stable"
        assert sum(f"scene-{i:02}" in m.content for m in request.messages) == 1
        assert all(f"scene-{j:02}" not in m.content for j in range(i) for m in request.messages)
        drafts = [m for m in request.messages if m.role == "assistant"]
        assert [m.content for m in drafts] == ([latest] if latest else [])
        assert all(m.reasoning_content is None for m in request.messages)
        assert sum(len(m.content) for m in request.messages) < 1200
        if (i + 1) % 3:
            latest = f"draft-{i + 1:02}"
        assert continuation.messages[-1].content == latest


async def test_cancel_environment_invalid_busy_success_retains_latest_draft_and_commits_once():
    from pydantic import BaseModel

    from infrastructure.llm.base import LLMBusyError
    from infrastructure.llm.structured import complete_structured

    class Reply(BaseModel):
        answer: int

    requests = []

    class Stream:
        async def complete_stream(self, request, partial):
            requests.append(request)
            if len(requests) == 1:
                partial.text = "old partial answer"
                raise asyncio.CancelledError
            if len(requests) == 2:
                return LLMResponse(text="invalid new answer", latency=0)
            if len(requests) == 3:
                raise LLMBusyError("busy")
            return LLMResponse(text='{"answer":3}', latency=0)

    continuation = DecisionContinuation()
    client = ContinuationClient(Stream(), continuation)
    with pytest.raises(asyncio.CancelledError):
        await complete_structured(
            client, LLMRequest(messages=(Message(role="user", content="old scene"),)), Reply
        )
    reply = await complete_structured(
        client, LLMRequest(messages=(Message(role="user", content="latest scene"),)), Reply
    )
    assert "old partial answer" in requests[1].messages[0].content
    assert requests[2].messages == requests[3].messages
    assert sum("latest scene" in m.content for m in requests[3].messages) == 1
    assert all("old scene" not in m.content for m in requests[3].messages)
    assert [m.content for m in requests[3].messages if m.role == "assistant"] == [
        "invalid new answer"
    ]
    assert "invalid" in requests[3].messages[-1].content
    commits = []
    continuation.stage(lambda: commits.append(reply.answer))
    continuation.commit()
    continuation.commit()
    assert commits == [3]


async def test_packed_input_near_limit_rejects_added_draft_without_discarding_it():
    from core.agent.config import ContextBudgetConfig
    from core.agent.context import ContextOverflow, Counter, pack

    budget = ContextBudgetConfig(
        enabled=True, context_tokens=1500, input_tokens=1000, output_tokens=400, safety_tokens=100
    )
    request = pack(
        LLMRequest(
            messages=(
                Message(role="system", content="identity"),
                Message(role="user", content="current scene" + "x" * 870),
            )
        ),
        [],
        budget,
    )
    assert Counter(budget).request(request) < budget.input_tokens
    continuation = DecisionContinuation()
    continuation.messages = (Message(role="assistant", content="draft" * 100),)

    class NeverCalled:
        async def complete(self, request):
            raise AssertionError("overflow must fail before the backend")

    with pytest.raises(ContextOverflow, match="Input budget exceeded"):
        await ContinuationClient(NeverCalled(), continuation, budget=budget).complete(request)
    assert continuation.messages[0].content == "draft" * 100
    with pytest.raises(RuntimeError, match="no completed decision"):
        continuation.commit()
