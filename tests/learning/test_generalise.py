"""What is learnt from a moment kept: the town's vocabulary, the generalising with its one retry and
its drops, the moment as it happened, and the length the trainer takes, with its margin."""

from __future__ import annotations

import json
import math
from datetime import date

import pytest

import learning.generalise as generalise_module
from agent.runtime import RuntimeConfig
from infrastructure.llm import LLMRequest, Message
from infrastructure.llm.scripted import tool_call
from learning import texts
from learning.choice import Kept
from learning.generalise import (
    ACCOUNT_CHARS,
    LENGTH_MARGIN,
    Dropped,
    Example,
    Generalised,
    Vocabulary,
    as_it_happened,
    faults,
    generalise,
    too_long,
)
from learning.moments import Moment, life, rendering
from tests.support.doubles import ScriptedModel
from tests.support.lives import BACKGROUND, a_day, resident

START = date(2026, 3, 2)
TOWN = Vocabulary.of_town(
    residents=["Mei", "Kofi", "Ben"],
    places=["the shared house on Mill Street", "the Office", "the river walk"],
    ids=["mill-street-house", "office", "vegetable-soup"],
).with_actions(["look_around", "go", "say"])


@pytest.fixture
async def lived(tmp_path):
    ana = resident(tmp_path / "Ana")
    await a_day(ana, 1)
    return life(ana.root, 1)


def test_the_towns_words_are_its_names_ids_and_actions_not_the_names_of_things_nor_sums():
    assert TOWN.leaks("Mei met Kofi on Mill Street, at the Office.") == [
        "Kofi", "Mei", "Mill Street", "Office"
    ]  # fmt: skip
    assert TOWN.leaks("I go to the office, say hello and walk by the river.") == []
    assert TOWN.leaks("Some bread, an egg, two phones and a bowl of vegetable soup.") == []
    assert TOWN.leaks("Two of vegetable-soup, from Mill-Street-House.") == [
        "mill-street-house", "vegetable-soup"
    ]  # fmt: skip
    assert TOWN.leaks("I call look_around, then go(place) and `say`.") == [
        "go", "look_around", "say"
    ]  # fmt: skip
    assert TOWN.leaks("It costs $12, or $ 12.50, near mill-street-house.") == ["mill-street-house"]
    assert TOWN.leaks("It costs some money; Meiko and Kofian came.") == []


async def test_a_moment_is_generalised_by_the_base_model_asked_once_more_then_dropped(lived):
    # An exchange, as it was spoken to the resident and as it answered; then a moment alone.
    leaky = {"situation": "Ben here. Lend me some bread till Friday?", "response": "Take it, Ben."}
    asked = "Could you lend me something to eat till Friday? I'll pay you back then."
    clean = {"situation": asked, "response": "Take it, and pay me when you can."}
    found = {"situation": "You find $5 by the mill-street-house.", "response": "I take it."}
    model = ScriptedModel(leaky, clean, found, found, "not an answer", "{}", '{"situation": ""}')
    made = [
        await generalise(
            moment,
            Kept(moment=moment.number, day=1, why="It mattered."),
            client=model,
            vocabulary=TOWN,
            start_date=START,
            runtime=RuntimeConfig(),
            replica=2,
        )
        for moment in lived.moments
    ]

    assert made[0] == Example(
        moment=1,
        day=1,
        why="It mattered.",
        messages=(
            {"role": "user", "content": asked},
            {"role": "assistant", "content": "Take it, and pay me when you can."},
        ),
    )
    assert made[1] == Dropped(moment=2, day=1, reason="leaked", detail="mill-street-house")
    assert made[2].reason == "unreadable" and "Generalised after 3 attempt(s)" in made[2].detail
    first, again = model.requests[:2]
    # The base model, without an adapter or the resident's account of itself.
    assert (first.model, first.replica, first.tools) == (None, 2, ())
    account = rendering(lived.moments[0], START)
    assert [m.content for m in first.messages] == [
        texts.GENERALISE,
        f"<account>\n{account}\n</account>",  # between the marks the instructions name
    ]
    assert not any(BACKGROUND in m.content for r in model.requests for m in r.messages)
    assert [m.role for m in again.messages] == ["system", "user", "assistant", "user"]
    assert json.loads(again.messages[2].content) == leaky
    assert again.messages[3].content == texts.LEAKED.format(words="Ben")
    assert all(isinstance(r, LLMRequest) and r.json_schema for r in model.requests)


async def test_a_response_that_tells_a_you_what_it_did_or_a_situation_with_nothing_is_refused(
    lived,
):
    narrated = {
        "situation": "Could you lend me some bread till Friday?",
        "response": "You say, “Take it.” You then hand it over.",
    }
    spoken = {"situation": narrated["situation"], "response": "Take it. I hand it over."}
    lead_in = {"situation": "A neighbour says to you: “", "response": "Morning."}
    model = ScriptedModel(narrated, spoken, lead_in, {**lead_in, "situation": "  "})

    async def made(moment):
        kept = Kept(moment=moment.number, day=1)
        return await generalise(
            moment, kept, client=model, vocabulary=TOWN, start_date=START,
            runtime=RuntimeConfig(), replica=None,
        )  # fmt: skip

    assert (await made(lived.moments[0])).messages[1]["content"] == "Take it. I hand it over."
    assert model.requests[1].messages[-1].content == texts.NARRATED
    dropped = await made(lived.moments[1])
    assert (dropped.reason, dropped.detail) == ("empty", "'  '")
    assert model.requests[3].messages[-1].content == texts.EMPTY

    # An answer may open with "you" when those are the person's own words: it was speaking to
    # someone. What it says inside its answer is not looked at.
    answer = tool_call("say", text="You're right, take the next one. I'll point it your way.")
    asked = Message(role="user", content="Ben said to you: “Can I take the next task?”")
    own = Moment(
        1, 1, 0, 0, (asked, Message(role="assistant", content="", tool_calls=(answer,))), True
    )
    right = {
        "situation": "Can I take the next one?",
        "response": "You're right, take the next one.",
    }
    inside = {"situation": right["situation"], "response": "Fine. Your turn next, then."}
    assert faults(Generalised(**right), TOWN, own) == []
    assert faults(Generalised(**inside), TOWN, own) == []
    told = Generalised(situation=right["situation"], response="You're glad, and you say so.")
    assert [fault[0] for fault in faults(told, TOWN, own)] == ["narrated"]
    for empty in ("", "A neighbour says to you:", 'He says, "', "She says, '"):
        assert [
            f[0]
            for f in faults(
                Generalised.model_construct(situation=empty, response="I go."), TOWN, own
            )
        ] == ["empty"]
    for full in ('He says: "Lend me some."', "She says: 'Lend me some.'", "You find a purse."):
        assert faults(Generalised(situation=full, response="I go."), TOWN, own) == []


SPOKEN = (
    # What the resident said, and the response of the first night of the restarted Social arm
    # (runs/social/learning/night-01), the names taken out of it as the layer is told to.
    ("You're kind, Marek, but $280 is more than I've got on me and I don't want to over-commit.",
     "You're kind, but $280 is more than I've got on me and I don't want to over-commit. Maybe "
     "one day! I went back to work on the code."),
    ("Marek, you're perfectly well — no treatment needed, just keep moving.",
     "You're perfectly well — no treatment needed, just keep moving. And I'll pass on the "
     "bicycle for now; my walks go far enough."),
    ("Jonas, you're too good. This is exactly what my back needed. Thank you — on you it really "
     "is, then.",
     "You're too good. This is exactly what my back needed. Thank you — on you it really is, "
     "then. I'll be back to work in a moment."),
)  # fmt: skip
NARRATED = (
    # What the resident said, and the response, of the first night of the pilot Social arm
    # (runs/social-pilot1/learning/night-01), which narrated a "you".
    ("Thanks, Mei — that's fair. I'll be ready the moment it lands.",
     "You say, “Thanks — that's fair. I'll be ready the moment it lands.” You then stay at your "
     "desk, waiting for the next task to come your way."),
    ("Jonas, you're not working thin tomorrow — I've got a full restock coming in at 08:00.",
     "You say: 'You're not working thin tomorrow — I've got a full restock coming in at 08:00 "
     "tomorrow morning.'"),
    ("Fair, Selin — and sorry I moved 717 while you were mid-way in.",
     "You said: 'Fair — and sorry I moved that one while you were mid-way in.'"),
)  # fmt: skip
PEOPLE = Vocabulary.of_town(residents=["Mei", "Selin", "Jonas", "Marek"], places=[], ids=[])


@pytest.mark.parametrize(("said", "response"), SPOKEN)
def test_a_response_opening_with_you_that_the_person_said_to_someone_is_speech(said, response):
    """The person's words opened with a name the layer rightly took out, or held one: what
    remains is still the opening of what it said."""
    answer = Generalised(situation="I could get you one for $280. Want it?", response=response)
    assert faults(answer, PEOPLE, _saying(said)) == []
    # Nor when the layer puts a vocative of its own where the name was.
    elsewhere = response.replace("You're kind, but", "You're kind, neighbour, but", 1)
    assert faults(answer.model_copy(update={"response": elsewhere}), PEOPLE, _saying(said)) == []


@pytest.mark.parametrize(("said", "response"), NARRATED)
def test_a_response_that_tells_a_you_what_it_said_is_narration_even_quoting_its_words(
    said, response
):
    answer = Generalised(situation="Fair enough, take the next one.", response=response)
    assert [fault[0] for fault in faults(answer, PEOPLE, _saying(said))] == ["narrated"]


def _saying(said: str) -> Moment:
    call = tool_call("say", text=said)
    told = Message(role="user", content="Someone speaks to you.")
    return Moment(
        1, 1, 0, 0, (told, Message(role="assistant", content="", tool_calls=(call,))), True
    )


async def test_the_generalising_is_given_the_whole_moment_and_a_cut_is_marked_and_counted(
    monkeypatch,
):
    """The resident reads a moment cut to 12,000 characters; the generalising is given it whole,
    up to `ACCOUNT_CHARS`, and beyond that cut in the middle with the cut marked and counted."""
    log = "\n".join(f"line {n}: the build went on" for n in range(1_500))  # about 40,000
    call = tool_call("shell", command="make")
    long = Moment(1, 1, 0, 0, (
        Message(role="user", content="The client asked for the build."),
        Message(role="assistant", content="", tool_calls=(call,)),
        Message(role="tool", content=log, tool_call_id=call.id),
        Message(role="assistant", content="It builds; I tell the client."),
    ), True)  # fmt: skip
    assert len(log) > 40_000 and len(rendering(long, START)) <= 12_000
    answer = {"situation": "Is the build done?", "response": "It is."}
    model = ScriptedModel(answer, answer)

    async def made():
        return await generalise(
            long, Kept(moment=1, day=1), client=model, vocabulary=TOWN, start_date=START,
            runtime=RuntimeConfig(), replica=None,
        )  # fmt: skip

    whole = rendering(long, START, results=None, most=None)
    assert ACCOUNT_CHARS >= 300_000 and (await made()).cut == 0
    assert model.requests[0].messages[1].content == f"<account>\n{whole}\n</account>"
    assert "line 1499: the build went on" in whole and "left out" not in whole
    monkeypatch.setattr(generalise_module, "ACCOUNT_CHARS", 10_000)
    example = await made()
    assert example.cut == len(whole) - 10_000
    account = model.requests[1].messages[1].content
    assert f"[... {example.cut} characters left out here ...]" in account


async def test_a_raw_example_is_the_moment_as_it_happened_without_the_system_prompt(lived):
    work = lived.moments[1]
    example = as_it_happened(work, Kept(moment=2, day=1, why=None))
    situation = "It is 08:00 on Monday. You are at home."  # the fake port's
    assert example.messages == (
        {"role": "user", "content": f"You arrived at work. Ben is here.\n\n{situation}"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {"name": "say", "arguments": {"text": "Morning, Ben."}},
                }
            ],
        },
        {"role": "tool", "content": "You said to Ben: “Morning, Ben.”"},
        {"role": "assistant", "content": "Back to the ovens."},
    )
    assert too_long(example, 1_000) is None
    dropped = too_long(example, 20)
    assert (dropped.moment, dropped.reason) == (2, "too long")
    assert dropped.detail.endswith("tokens by the estimate, more than 20 / 1.25")


def test_an_example_is_kept_only_with_room_for_the_tokens_to_run_past_their_estimate():
    """Real tokens ran to 1.02 times the estimate on real moments: one estimated just under the
    trainer's limit may be over it, and the trainer then refuses every job of the night."""
    said = Example(moment=4, day=1, messages=({"role": "user", "content": "x" * 2_997},))
    estimate = (len(json.dumps(said.messages[0], ensure_ascii=False)) // 3) + 1
    assert estimate == 1_010
    assert too_long(said, estimate) is not None  # under the limit, but with no room
    assert too_long(said, int(estimate * 1.2)) is not None
    assert too_long(said, math.ceil(estimate * LENGTH_MARGIN)) is None
    assert LENGTH_MARGIN >= 1.02 * 1.2  # the highest ratio seen, and a fifth more
