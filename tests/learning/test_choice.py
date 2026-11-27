"""The choice with the scripted model: what heads and opens it, what the resident's calls come to,
how it is bounded, and the Random arm's draw."""

from __future__ import annotations

from datetime import date

import pytest

from agent import texts as runtime_texts
from agent.runtime import RuntimeConfig
from infrastructure.llm import LLMCallError, LLMContextOverflowError
from infrastructure.llm.scripted import reply, tool_call
from infrastructure.storage import read_jsonl
from learning import texts
from learning.choice import Kept, choose, draw
from learning.moments import life
from tests.support.doubles import ScriptedModel
from tests.support.lives import BACKGROUND, a_day, resident

START = date(2026, 3, 2)
FAST = RuntimeConfig(retry_wait=0.001)


@pytest.fixture
async def lived(tmp_path):
    """Two ordinary days of Ana's: moments 1 to 3 on the first, 4 to 6 on the second."""
    ana = resident(tmp_path / "Ana")
    await a_day(ana, 1)
    await a_day(ana, 2)
    return life(ana.root, 2)


def choosing(lived, model, trace, **settings):
    arguments = {
        "background": BACKGROUND,
        "numbers": [(1, 2), (2, 3)],
        "earlier": {1},
        "start_date": START,
        "keep": 2,
        "steps": 10,
        "client": model,
        "model": "town-Ana-night-01",
        "replica": 3,
        "runtime": FAST,
        "trace": trace,
    }
    return choose(lived, **(arguments | settings))


async def test_the_resident_reads_back_keeps_lets_go_and_stops_when_it_does_nothing(
    lived, tmp_path
):
    model = ScriptedModel(
        reply("", tool_call("look_back", day="2026-03-02"), tool_call("read_moment", moment=2)),
        reply(
            "",
            tool_call("keep", moment=2, why=" Ben was there. "),
            tool_call("keep", moment="5"),
            tool_call("keep", moment=1),
            tool_call("keep", moment=6),
            tool_call("keep", moment=4),
        ),
        reply(
            "",
            tool_call("let_go", moment=5),
            tool_call("let_go", moment=5),
            tool_call("keep", moment=99),
            tool_call("look_back", day="2 March"),
            tool_call("look_back", day="2026-03-09"),
            tool_call("fly"),
        ),
        reply("That will do."),
    )
    trace = tmp_path / "choice.jsonl"
    marked, ended, replies = await choosing(lived, model, trace)

    assert (marked, ended, replies) == ((Kept(moment=2, day=1, why="Ben was there."),), "done", 4)
    first = model.requests[0]
    assert (first.model, first.replica) == ("town-Ana-night-01", 3)
    assert [tool["function"]["name"] for tool in first.tools] == [s.name for s in texts.SPECS]
    system, opening = first.messages
    assert system.content == (
        f"{runtime_texts.ABOUT_ME}\n\n{BACKGROUND}\n\n{texts.TONIGHT.format(keep=2)}\n"
    )
    assert opening.content == (
        "How many of the others like you, night by night:\n"
        "Monday 2 March: 2\nTuesday 3 March: 3\n\n"
        "The days you have lived here:\n"
        "2026-03-02, Monday 2 March: moments 1 to 3\n"
        "2026-03-03, Tuesday 3 March: moments 4 to 6"
    )
    day, moment = (m.content for m in model.requests[1].messages if m.role == "tool")
    assert day.startswith("Monday 2 March:\n\n1. 07:00 You woke up at home. (kept on an earlier")
    assert "\n2. 08:00 You arrived at work. Ben is here.\n    You: say Morning, Ben." in day
    assert moment.startswith("Moment 2, Monday 2 March, 08:00 to 08:00.\n\nYou arrived at work.")
    answers = [m.content for m in model.requests[2].messages[-5:]]
    assert answers == [
        texts.KEPT.format(number=2, count=1, limit=2),
        texts.KEPT.format(number=5, count=2, limit=2),
        texts.CARRIED.format(number=1),
        texts.STILL.format(number=6),  # it only went to bed
        texts.FULL.format(limit=2),
    ]
    answers = [m.content for m in model.requests[3].messages[-6:]]
    assert answers == [
        texts.LET_GO.format(number=5, count=1),
        texts.NOT_KEPT.format(number=5),
        texts.NO_MOMENT.format(number=99, last=6),
        runtime_texts.NEEDS.format(name="look_back", argument="day", kind=texts.A_DAY),
        texts.NO_DAY.format(day="2026-03-09", first="2026-03-02", last="2026-03-03"),
        runtime_texts.UNKNOWN_TOOL.format(name="fly"),
    ]
    records = list(read_jsonl(trace))
    messages = [r for r in records if r["kind"] == "message"]
    assert [m["content"] for m in messages] == [m.content for m in model.requests[3].messages] + [
        "That will do."
    ]
    assert [r["kind"] for r in records].count("reply") == 4
    assert records[-1] | {"real_time": 0} == {
        "kind": "end", "real_time": 0, "ended": "done", "replies": 4, "marked": [2]
    }  # fmt: skip


async def test_a_choice_is_bounded_by_its_replies_a_reply_cut_off_twice_and_the_window(
    lived, tmp_path
):
    keep = reply("", tool_call("keep", moment=4))
    marked, ended, replies = await choosing(lived, ScriptedModel(keep), tmp_path / "a", steps=1)
    assert ([k.moment for k in marked], ended, replies) == ([4], "steps", 1)

    cut = reply("I keep thinking…", tool_call("keep", moment=4), cut_off=True)
    model = ScriptedModel(cut, cut)
    marked, ended, replies = await choosing(lived, model, tmp_path / "b")
    assert (marked, ended, replies) == ((), "cut off", 1)
    efforts = [(r.reasoning_effort, r.sampling.max_tokens) for r in model.requests]
    assert efforts == [("medium", 16_384), ("low", 16_384)]  # asked once more, as the runtime asks

    model = ScriptedModel(keep, LLMContextOverflowError("maximum context length"))
    marked, ended, replies = await choosing(lived, model, tmp_path / "c")
    assert ([k.moment for k in marked], ended, replies) == ([4], "window", 1)


async def test_a_model_error_is_asked_again_and_raised_once_the_attempts_run_out(lived, tmp_path):
    model = ScriptedModel(LLMCallError("down"), reply("Nothing tonight."))
    assert await choosing(lived, model, tmp_path / "a") == ((), "done", 1)
    model = ScriptedModel(LLMCallError("down"), LLMCallError("still down"))
    twice = RuntimeConfig(model_attempts=2, retry_wait=0.001)
    with pytest.raises(LLMCallError, match="still down"):
        await choosing(lived, model, tmp_path / "b", runtime=twice)
    kinds = [r["kind"] for r in read_jsonl(tmp_path / "b")]
    assert kinds == ["message", "message", "request", "error", "request", "error"]


async def test_the_random_arm_draws_as_many_by_its_seed_from_what_was_not_drawn_before(lived):
    # Going to bed, the resident said nothing to anyone and did nothing: that is drawn in no arm.
    assert [m.acted for m in lived.moments] == [True, True, False, True, True, False]
    drawn = draw(lived, 2, {1}, "20260302-Ana-2")
    assert len(drawn) == 2 and {k.moment for k in drawn} <= {2, 4, 5}
    assert drawn == draw(lived, 2, {1}, "20260302-Ana-2")
    assert [k.moment for k in drawn] == sorted(k.moment for k in drawn)
    assert all(k.day == lived.get(k.moment).day and k.why is None for k in drawn)
    assert {k.moment for k in draw(lived, 9, {1, 2}, "s")} == {4, 5}
    assert draw(lived, 0, set(), "s") == ()
    assert len({draw(lived, 2, set(), f"seed-{n}") for n in range(20)}) > 1
