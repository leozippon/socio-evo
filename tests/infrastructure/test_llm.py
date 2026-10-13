import json

import pytest

from infrastructure.config import StrictModel
from infrastructure.llm import (
    LLMBusyError,
    LLMCallError,
    LLMConfig,
    LLMConfigError,
    LLMRequest,
    LLMResponse,
    Message,
    RecordingClient,
    ScriptedClient,
    StructuredOutputError,
    complete_structured,
    complete_text,
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
    assert [request.after_invalid for request in requests] == [False, True, True]
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
    assert all(failure.startswith("invalid: answer") for failure in failure.value.failures)


async def test_the_correction_of_an_invalid_reply_is_the_callers():
    replies = iter(['{"answer": "many"}', '{"answer": 3}'])
    requests: list[LLMRequest] = []

    def responder(request: LLMRequest) -> str:
        requests.append(request)
        return next(replies)

    def plainly(model: type, error: Exception) -> str:
        return f"Once more, as a {model.__name__}."

    client = ScriptedClient(responder)
    assert await complete_structured(client, _request(), Verdict, correction=plainly) == Verdict(
        answer=3
    )
    assert requests[1].messages[-1].content == "Once more, as a Verdict."


class Sequenced:
    """A client that answers with `outcomes` in turn: an exception is raised, text returned."""

    def __init__(self, *outcomes: str | Exception) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return LLMResponse(text=outcome, latency=0)


async def test_a_reply_not_given_in_time_is_a_failed_attempt_but_a_failed_backend_is_final():
    busy = LLMBusyError("no reply in time after 9 call(s); last: rate-limited")
    client = Sequenced(busy, '{"answer": 1}')
    assert await complete_structured(client, _request(), Verdict) == Verdict(answer=1)
    assert [request.messages for request in client.requests] == [_request().messages] * 2

    with pytest.raises(StructuredOutputError) as failure:
        await complete_structured(Sequenced(busy, "", busy), _request(), Verdict)
    assert failure.value.failures[0] == failure.value.failures[2] == str(busy)
    assert failure.value.failures[1].startswith("invalid:")

    down = Sequenced(LLMCallError("APIConnectionError: Connection error."), '{"answer": 1}')
    with pytest.raises(LLMCallError):
        await complete_structured(down, _request(), Verdict)
    assert len(down.requests) == 1
    with pytest.raises(LLMCallError):
        await complete_text(Sequenced(LLMCallError("AuthenticationError")), _request())


class Note(StrictModel):
    text: str


async def test_a_backslash_that_begins_no_escape_a_reply_means_is_read_as_itself():
    client = Sequenced(r'{"text": "r\"\d+\" and \\d, \n"}')
    assert await complete_structured(client, _request(), Note) == Note(text='r"\\d+" and \\d, \n')
    assert len(client.requests) == 1
    latex = Sequenced(r'{"text": "$\frac{1}{2} \beta \right)$ at \bword\b"}')
    assert await complete_structured(latex, _request(), Note) == Note(
        text="$\\frac{1}{2} \\beta \\right)$ at \\bword\\b"
    )


LIMIT = 16384
"""The token limit of the fake server, where a request sets none."""


class Server:
    """A client that answers with `replies` in turn, None standing for a reply cut off by the
    token limit, and reports the limit each call was made with."""

    def __init__(self, *replies: str | None) -> None:
        self.replies = list(replies)
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        reply = self.replies.pop(0)
        return LLMResponse(
            text='{"answer' if reply is None else reply,
            truncated=reply is None,
            max_tokens=request.sampling.max_tokens or LIMIT,
            latency=0,
        )


async def test_a_reply_cut_off_is_asked_for_again_with_half_the_limit():
    client = Server(None, None, '{"answer": 7}')
    assert await complete_structured(client, _request(), Verdict) == Verdict(answer=7)
    assert [request.messages for request in client.requests] == [_request().messages] * 3
    assert [request.metadata["attempt"] for request in client.requests] == [1, 2, 3]
    limits = [request.sampling.max_tokens for request in client.requests]
    assert limits == [None, LIMIT // 2, LIMIT // 2]
    assert not any(request.after_invalid for request in client.requests)
    with pytest.raises(StructuredOutputError) as failure:
        await complete_structured(Server(None, None, None), _request(), Verdict)
    assert failure.value.failures == ("cut off by the token limit",) * 3

    text = Server(None, "A whole entry.")
    assert await complete_text(text, _request()) == "A whole entry."
    assert [request.json_schema for request in text.requests] == [None, None]
    assert [request.sampling.max_tokens for request in text.requests] == [None, LIMIT // 2]
    with pytest.raises(StructuredOutputError, match="cut off"):
        await complete_text(Server(None, None), _request(), attempts=2)


async def test_every_attempt_is_logged_with_how_it_failed(tmp_path):
    path = tmp_path / "llm_calls.jsonl"
    replies = Server(None, '{"answer": "many"}', '{"answer": 3}')
    assert await complete_structured(RecordingClient(replies, path), _request(), Verdict) == (
        Verdict(answer=3)
    )
    with pytest.raises(StructuredOutputError) as failure:
        await complete_text(RecordingClient(Server(" ", None, None), path), _request())

    records = list(read_jsonl(path))
    cut, invalid, valid = (record["failure"] for record in records[:3])
    assert cut == "cut off by the token limit" and valid is None
    assert invalid.startswith("invalid: answer: ")
    assert [record["failure"] for record in records[3:]] == list(failure.value.failures)
    assert [record["response"]["max_tokens"] for record in records[:3]] == [
        LIMIT,
        LIMIT // 2,
        LIMIT // 2,
    ]
    assert all("verdict" not in record["request"] for record in records)


async def test_an_empty_text_is_asked_for_again_within_the_bounded_attempts():
    assert await complete_text(Sequenced(" \n", "An entry."), _request()) == "An entry."
    with pytest.raises(StructuredOutputError) as failure:
        await complete_text(Sequenced("", "", ""), _request())
    assert failure.value.failures == ("empty",) * 3


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
