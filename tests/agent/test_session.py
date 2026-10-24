import pytest

from agent import texts
from agent.compaction import exchanges, kept
from agent.session import Session, estimate
from infrastructure.llm import Message, ToolCall


def _user(text: str) -> Message:
    return Message(role="user", content=text)


def _calls(*ids: str) -> Message:
    calls = tuple(ToolCall(id=i, name="look_around", arguments={"far": i}) for i in ids)
    return Message(role="assistant", content="", tool_calls=calls)


def _result(call_id: str) -> Message:
    return Message(role="tool", content=f"Seen {call_id}.", tool_call_id=call_id)


def _fill(session: Session) -> list[int]:
    return [
        session.append(message)
        for message in (
            _user("09:00. You are at home."),
            _calls("a"),
            _result("a"),
            _calls("b", "c"),
            _result("b"),
            _result("c"),
            Message(role="assistant", content="Nothing more for now."),
            _user("Ben says hello."),
            _user("09:30. You are at home."),
            _calls("d"),
            _result("d"),
        )
    ]


def test_the_session_persists_every_message_and_reloads_the_same(tmp_path):
    path = tmp_path / "session.jsonl"
    session = Session(path)
    ids = _fill(session)
    assert ids == list(range(1, 12))
    reloaded = Session(path)
    assert reloaded.context() == session.context()
    assert reloaded.append(_user("10:00.")) == 12

    path.write_text(path.read_text() + '{"type": "message", "id": 3, "message": {}}\n')
    with pytest.raises(ValueError, match="session.jsonl:13"):
        Session(path)


def test_compaction_keeps_tool_calls_with_their_results_and_records_what_it_replaced(tmp_path):
    path = tmp_path / "session.jsonl"
    session = Session(path)
    _fill(session)
    cut = exchanges(session.context())
    assert [[entry.id for entry in exchange] for exchange in cut] == [
        [1, 2, 3],
        [4, 5, 6],
        [7],
        [8, 9, 10, 11],
    ]
    keep = kept(session.context(), 2)
    assert keep == [7, 8, 9, 10, 11]

    record = session.compact("I looked around twice.", keep)
    assert record.id == 12 and record.replaced == (1, 2, 3, 4, 5, 6)
    context = session.context()
    assert context[0].message == _user(texts.SUMMARY.format(summary="I looked around twice."))
    assert [entry.id for entry in context] == [12, 7, 8, 9, 10, 11]
    assert Session(path).context() == context

    later = session.compact("Still at home.", kept(session.context(), 1))
    assert later.replaced == (12, 7) and [e.id for e in session.context()] == [13, 8, 9, 10, 11]
    with pytest.raises(ValueError, match="outside the context"):
        session.compact("Lost.", [1])


def test_the_context_size_is_the_last_report_plus_an_estimate_since(tmp_path):
    session = Session(tmp_path / "session.jsonl")
    prefix = "You are Ana." * 100
    session.append(_user("09:00."))
    unmeasured = session.size(prefix)
    assert unmeasured > estimate(prefix)
    session.append(Message(role="assistant", content="Hello."), prompt_tokens=5000)
    measured = session.size(prefix)
    assert 5000 < measured < 5010
    session.append(_user("x" * 300))
    assert session.size(prefix) >= measured + 100
    assert Session(tmp_path / "session.jsonl").size(prefix) == session.size(prefix)
    session.compact("Morning.", [])
    assert session.size(prefix) < 5000
