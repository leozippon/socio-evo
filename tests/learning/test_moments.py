"""A life cut into moments from what the real runtime writes: scripted days, a real morning of the
run of 29 October replayed, and a trace that is not as its checkpoints committed it."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from agent import texts as runtime_texts
from agent.port import ToolResult
from agent.runtime import RuntimeConfig
from infrastructure.llm import LLMCallError
from infrastructure.llm.scripted import reply, tool_call
from learning.moments import digest, life, rendering
from tests.support.lives import Step, Turn, a_day, at, checkpoint, live, resident

START = date(2026, 3, 2)


async def test_a_life_is_its_waking_turns_numbered_once_and_for_all(tmp_path):
    ana = resident(tmp_path / "Ana")
    await live(
        ana,
        [
            Turn(
                at(1, 7),
                ["You woke up at home."],
                [
                    Step(reply("", tool_call("look_around")), [ToolResult("You are at home.")]),
                    Step(
                        reply("Off to work.", tool_call("go", place="the bakery")),
                        [ToolResult("You set off.", ends_turn=True)],
                    ),
                ],
            ),
            Turn(
                at(1, 8),
                ["You arrived at the bakery."],
                [
                    Step(
                        reply("", tool_call("say", text="Morning!")),
                        [ToolResult("You said it.")],
                        meanwhile=["Ben came in."],
                    ),
                    Step(reply("Nothing more for now.")),
                ],
            ),
            Turn(at(1, 23), ["You fell asleep."], asleep=True),
        ],
    )
    checkpoint(ana.root, 1)
    # The next day a request lapses: what it was told falling asleep and waking, and the knock
    # that followed, all open the one moment in which it next replied.
    await live(
        ana,
        [
            Turn(at(2, 7), ["You woke up at home."], [Step(LLMCallError("down"))]),
            Turn(at(2, 7, 5), ["Ben knocked."], [Step(reply("I will see who it is."))]),
        ],
        RuntimeConfig(model_attempts=1),
    )
    checkpoint(ana.root, 2)

    first = life(ana.root, 1)
    assert [(m.number, m.day) for m in first.moments] == [(1, 1), (2, 1)]
    morning, bakery = first.moments
    assert [m.role for m in morning.messages] == ["user", "assistant", "tool", "assistant", "tool"]
    assert [m.role for m in bakery.messages] == ["user", "assistant", "tool", "assistant"]
    assert (morning.start, bakery.start, bakery.end) == (at(1, 7), at(1, 8), at(1, 8))
    assert first.actions >= {"read_file", "compact"}
    both = life(ana.root, 2)
    assert both.moments[:2] == first.moments  # a number, once given, names the same moment
    (knock,) = both.of(2)
    told = [m.content.split("\n\n")[0] for m in knock.messages if m.role == "user"]
    assert (knock.number, told) == (3, ["You fell asleep.", "You woke up at home.", "Ben knocked."])
    assert [m.role for m in knock.messages][-1:] == ["assistant"]
    # Looking around and setting off, and speaking, act; a thought alone does not.
    assert [m.acted for m in both.moments] == [True, True, False]

    assert digest(morning) == "1. 07:00 You woke up at home.\n    You: look_around; go the bakery"
    assert digest(bakery, " (kept tonight)") == (
        "2. 08:00 You arrived at the bakery. (kept tonight)\n    You: say Morning!"
    )
    assert digest(knock) == "3. 23:00 You fell asleep.\n    You thought: I will see who it is."
    told = rendering(bakery, START)
    assert told.startswith(
        "Moment 2, Monday 2 March, 08:00 to 08:00.\n\nYou arrived at the bakery."
    )
    news = runtime_texts.NEWS_AHEAD.format(news="08:00 — Ben came in.", result="You said it.")
    assert 'You did: say(text: "Morning!")\n→ ' + news.replace("\n", "\n  ") in told
    assert told.endswith("You thought: Nothing more for now.")


async def test_a_real_morning_replayed_is_its_six_waking_turns(tmp_path):
    """The first six waking turns of Mei's first day in the run of 29 October, as its trace
    recorded them, replayed through today's runtime: the same news, replies and results."""
    fixture = json.loads((Path(__file__).parent / "morning.json").read_text(encoding="utf-8"))
    mei = resident(tmp_path / "Mei", background="I am Mei, 34, the team leader at the Office.")
    turns = [
        Turn(turn["at"], turn["told"], [_step(step) for step in turn["steps"]])
        for turn in fixture["turns"]
    ]
    await live(mei, turns)
    checkpoint(mei.root, 1)

    lived = life(mei.root, 1)
    assert len(lived.moments) == 6 and {moment.day for moment in lived.moments} == {1}
    replies = [[m.role for m in moment.messages].count("assistant") for moment in lived.moments]
    assert replies == [len(turn.steps) for turn in turns] == [3, 2, 2, 4, 2, 1]
    # Setting off for the Office and speaking act; reading the board and waiting do not.
    assert [moment.acted for moment in lived.moments] == [True, False, False, True, False, False]
    lines = [digest(moment).splitlines() for moment in lived.moments]
    assert lines[0] == [
        "1. 07:00 You woke up at home. It is Thursday 29 October, 07:00. You are well fed. You "
        "are fresh. You are in good…",
        "    You: list_files; how_am_i; look_around; go office",
    ]
    assert lines[1] == [
        "2. 07:18 You arrived at the Office. Nobody else is here.",
        "    You: view_board; wait 45",
    ]
    assert lines[3][0].startswith("4. 07:41 Kofi said to you: “Good morning, Mei. Board's bare")
    assert lines[3][1].startswith('    You: say ["Kofi"] Nothing I can point at — clients…; say ')
    assert len(lines[3][1]) <= 4 + 160 and lines[3][1].endswith("…")
    # The conversation interrupted its first two replies, whose calls were not carried out, and
    # what was said meanwhile opened the next request: all one moment, until it waited again.
    talk = rendering(lived.moments[3], START)
    assert talk.count(runtime_texts.NOT_CARRIED_OUT) == 2
    assert "Tomas said: “Good morning, Mei. Good morning, Kofi" in talk
    assert talk.rstrip().endswith("→ You wait for up to 90 minutes.")


async def test_a_trace_that_is_not_as_its_checkpoints_committed_it_is_refused(tmp_path):
    ana = resident(tmp_path / "Ana")
    await a_day(ana, 1)
    assert len(life(ana.root, 1).moments) == 3
    with pytest.raises(ValueError, match="no trace committed at day-02"):
        life(ana.root, 2)
    # A trace written before its requests named what they offered quietly: every call acts.
    records = [json.loads(line) for line in ana.trace_path.read_text().splitlines()]
    assert [m.acted for m in life(ana.root, 1).moments] == [True, True, False]
    older = [{k: v for k, v in r.items() if k != "quiet"} for r in records]
    ana.trace_path.write_text("".join(json.dumps(r) + "\n" for r in older))
    checkpoint(ana.root, 1)
    assert [m.acted for m in life(ana.root, 1).moments] == [True, True, True]
    ana.trace_path.write_text("".join(json.dumps(r) + "\n" for r in records))
    checkpoint(ana.root, 1)
    committed = ana.trace_path.read_bytes()
    ana.trace_path.write_bytes(committed[:-10])  # cut short after its commit
    with pytest.raises(ValueError, match="shorter than day 1 left it"):
        life(ana.root, 1)
    ana.trace_path.write_bytes(b'{"kind": "percept", "sim_time": 0}\n' + committed)  # another
    with pytest.raises(ValueError, match="does not end where day 1 ended"):
        life(ana.root, 1)


def _step(step: dict) -> Step:
    """A step of the fixture as the runtime is to replay it: a result the runtime itself gave
    (a call not carried out, for news that interrupted) comes from the news, not the world."""
    results = [ToolResult(text, ends) for text, ends in step["results"]]
    interrupting = any(r.text == runtime_texts.NOT_CARRIED_OUT for r in results)
    calls = [tool_call(name, **arguments) for name, arguments in step["calls"]]
    return Step(
        reply(step["text"], *calls),
        [r for r in results if r.text != runtime_texts.NOT_CARRIED_OUT],
        step["meanwhile"],
        interrupting,
    )
