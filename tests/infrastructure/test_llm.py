import json

import pytest

from infrastructure.config import StrictModel
from infrastructure.llm import (
    LLMCallError,
    LLMConfig,
    LLMConfigError,
    LLMRequest,
    Message,
    RecordingClient,
    ScriptedClient,
    StructuredOutputError,
    complete_structured,
    create_client,
)
from infrastructure.storage import read_jsonl


class Verdict(StrictModel):
    answer: int


def _request() -> LLMRequest:
    return LLMRequest(
        messages=(Message(role="user", content="How many?"),),
        metadata={"agent": "ana", "purpose": "act"},
    )


async def test_structured_completion_feeds_errors_back_until_valid():
    replies = iter(["not json", '{"answer": "many"}', '{"answer": 42}'])
    requests: list[LLMRequest] = []

    def responder(request: LLMRequest) -> str:
        requests.append(request)
        return next(replies)

    assert await complete_structured(ScriptedClient(responder), _request(), Verdict) == Verdict(
        answer=42
    )
    assert [request.metadata for request in requests] == [
        {"agent": "ana", "purpose": "act", "attempt": attempt} for attempt in (1, 2, 3)
    ]
    assert all(request.json_schema == Verdict.model_json_schema() for request in requests)
    assert requests[0].messages == _request().messages
    final = requests[2].messages
    assert [message.role for message in final] == ["user", "assistant", "user", "assistant", "user"]
    assert final[3].content == '{"answer": "many"}' and "answer" in final[4].content


async def test_structured_completion_gives_up_after_bounded_attempts():
    requests: list[LLMRequest] = []
    client = ScriptedClient(lambda request: requests.append(request) or {"answer": "never"})
    with pytest.raises(StructuredOutputError) as failure:
        await complete_structured(client, _request(), Verdict, attempts=2)
    assert len(requests) == 2
    assert failure.value.attempts == 2 and "answer" in failure.value.error


async def test_scripted_client_reports_no_usage_and_encodes_dicts():
    response = await ScriptedClient(lambda request: {"answer": "ünïcode"}).complete(_request())
    assert json.loads(response.text) == {"answer": "ünïcode"}
    assert response.usage is None and response.reasoning is None


async def test_recording_client_logs_successes_and_failures(tmp_path):
    path = tmp_path / "llm_calls.jsonl"
    await RecordingClient(ScriptedClient(lambda request: "fine"), path).complete(_request())

    def fail(request: LLMRequest) -> str:
        raise LLMCallError("server down")

    with pytest.raises(LLMCallError):
        await RecordingClient(ScriptedClient(fail), path).complete(_request())

    success, failure = read_jsonl(path)
    assert success["metadata"] == {"agent": "ana", "purpose": "act"}
    assert "metadata" not in success["request"]
    assert success["request"]["messages"] == [{"role": "user", "content": "How many?"}]
    assert success["response"]["text"] == "fine" and success["error"] is None
    assert failure["response"] is None
    assert failure["error"] == {"type": "LLMCallError", "message": "server down"}


def test_factory_requires_a_responder_exactly_for_the_scripted_backend():
    scripted = LLMConfig(
        backend="scripted", base_url="http://llm.test/v1", api_key_env="K", model="m"
    )
    assert isinstance(create_client(scripted, lambda request: "ok"), ScriptedClient)
    with pytest.raises(LLMConfigError):
        create_client(scripted)
    with pytest.raises(LLMConfigError):
        create_client(scripted.model_copy(update={"backend": "openai_compatible"}), lambda r: "ok")
