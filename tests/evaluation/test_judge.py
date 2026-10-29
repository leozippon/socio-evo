import pytest

from evaluation.judge import Judge, Question
from infrastructure.llm import LLMConfigError, LLMRequest, ScriptedClient, StructuredOutputError
from infrastructure.storage import read_jsonl
from tests.support.judge import verdict

QUESTION = Question(
    purpose="test/outcome",
    question="Did the tests pass?",
    text="10:40 ran `pytest tests/x` → 3 failed, 12 passed",
    labels={"yes": "They all passed.", "no": "Some failed.", "unclear": "It does not say."},
    evidenced=("yes", "no"),
)


def scripted(replies, tmp_path):
    requests: list[LLMRequest] = []
    replies = iter(replies)

    def responder(request: LLMRequest):
        requests.append(request)
        return next(replies)

    return Judge(ScriptedClient(responder), tmp_path / "judge.jsonl"), requests


async def test_verdict_must_quote_the_text_and_is_asked_at_temperature_zero(tmp_path):
    judge, requests = scripted(
        [
            verdict("no", "5 failed"),  # not in the text
            verdict("no"),  # a label that needs a quote, without one
            verdict("no", "3  failed,\n12 passed"),  # whitespace differences are not words
        ],
        tmp_path,
    )
    judgement = await judge.ask(QUESTION)
    assert judgement.question == QUESTION
    assert judgement.verdict.label == "no"
    assert judgement.verdict.evidence == ("3  failed,\n12 passed",)
    assert [r.sampling.temperature for r in requests] == [0.0, 0.0, 0.0]
    assert "not quoted word for word" in requests[1].messages[-1].content
    assert "needs at least one quote" in requests[2].messages[-1].content
    log = list(read_jsonl(tmp_path / "judge.jsonl"))
    assert len(log) == 3
    assert log[0]["metadata"] == {"purpose": "judge", "question": "test/outcome", "attempt": 1}


async def test_a_misquote_is_answered_with_the_nearest_passage(tmp_path):
    judge, requests = scripted(
        [verdict("no", "5 failed, 12 passed"), verdict("no", "3 failed, 12 passed")], tmp_path
    )
    assert (await judge.ask(QUESTION)).verdict.evidence == ("3 failed, 12 passed",)
    correction = requests[1].messages[-1].content
    assert "nearest passages read" in correction and "3 failed, 12 passed" in correction


async def test_a_quote_from_the_context_is_named_as_such(tmp_path):
    question = QUESTION.model_copy(
        update={"context": "Earlier the person said: all 15 passed, nothing failed"}
    )
    judge, requests = scripted(
        [verdict("yes", "all 15 passed"), verdict("no", "3 failed")], tmp_path
    )
    judgement = await judge.ask(question)
    assert judgement.verdict.label == "no"
    correction = requests[1].messages[-1].content
    assert "quoted from the Context" in correction
    assert "all 15 passed" in correction
    assert "nothing in it is quoted" in requests[0].messages[0].content


async def test_a_label_not_offered_fails_after_bounded_attempts_all_recorded(tmp_path):
    judge, _ = scripted([verdict("maybe")] * 3, tmp_path)
    with pytest.raises(StructuredOutputError):
        await judge.ask(QUESTION)
    assert len(list(read_jsonl(tmp_path / "judge.jsonl"))) == 3


async def test_a_label_without_evidence_requirement_may_quote_nothing(tmp_path):
    judge, _ = scripted([verdict("unclear")], tmp_path)
    assert (await judge.ask(QUESTION)).verdict.evidence == ()


def test_evidenced_labels_must_be_offered():
    with pytest.raises(ValueError, match="not offered"):
        Question(purpose="p", question="q", text="t", labels={"a": "", "b": ""}, evidenced=("c",))


async def test_extraction_quotes_only_the_text(tmp_path):
    text = "I claimed task 17. It felt hard."
    judge, requests = scripted(
        [
            {"excerpts": [{"quote": "I claimed task 18.", "statement": "I claimed task 18."}]},
            {"excerpts": [{"quote": "I claimed task 17.", "statement": "I claimed task 17."}]},
        ],
        tmp_path,
    )
    excerpts = await judge.extract("List the claims.", text, purpose="test/extract")
    assert [e.quote for e in excerpts] == ["I claimed task 17."]
    assert len(requests) == 2 and requests[0].sampling.temperature == 0.0


async def test_agreement_is_the_share_of_labels_repeated(tmp_path):
    first, _ = scripted([verdict("no", "3 failed")] * 4, tmp_path)
    sample = [await first.ask(QUESTION) for _ in range(4)]
    again, requests = scripted([verdict("no", "3 failed")] * 3 + [verdict("unclear")], tmp_path)
    assert await again.agreement(sample) == 0.75
    assert len(requests) == 4
    with pytest.raises(ValueError):
        await again.agreement([])


def test_a_missing_api_key_fails_when_the_judge_is_built(tmp_path, monkeypatch):
    monkeypatch.delenv("SOCIO_EVO_ABSENT_KEY", raising=False)
    config = tmp_path / "judge.yaml"
    config.write_text(
        "base_url: https://example.invalid\napi_key_env: SOCIO_EVO_ABSENT_KEY\nmodel: m\n"
    )
    with pytest.raises(LLMConfigError, match="SOCIO_EVO_ABSENT_KEY"):
        Judge.from_config(tmp_path / "log.jsonl", config)
