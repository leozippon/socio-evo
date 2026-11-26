"""What is learnt from a moment kept: the town's vocabulary, the generalising with its one retry and
its drops, the moment as it happened, and the length the trainer takes, with its margin."""

from __future__ import annotations

import json
import math
from datetime import date

import pytest

from agent.runtime import RuntimeConfig
from infrastructure.llm import LLMRequest
from learning import texts
from learning.choice import Kept
from learning.generalise import (
    LENGTH_MARGIN,
    Dropped,
    Example,
    Vocabulary,
    as_it_happened,
    generalise,
    too_long,
)
from learning.moments import life, rendering
from tests.support.doubles import ScriptedModel
from tests.support.lives import BACKGROUND, a_day, resident

START = date(2026, 3, 2)
TOWN = Vocabulary.of_town(
    residents=["Mei", "Kofi", "Ben"],
    places=["the shared house on Mill Street", "the Office", "the river walk"],
    ids=["mill-street-house", "office", "vegetable-soup"],
    currency="$",
).with_actions(["look_around", "go", "say"])


@pytest.fixture
async def lived(tmp_path):
    ana = resident(tmp_path / "Ana")
    await a_day(ana, 1)
    return life(ana.root, 1)


def test_the_towns_words_are_its_names_ids_actions_and_sums_and_not_the_names_of_things():
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
    assert TOWN.leaks("It costs $ 12, near mill-street-house.") == ["mill-street-house", "$"]
    assert TOWN.leaks("It costs some money; Meiko and Kofian came.") == []


async def test_a_moment_is_generalised_by_the_base_model_asked_once_more_then_dropped(lived):
    # An exchange, as it was spoken to the resident and as it answered; then a moment alone.
    leaky = {"situation": "Ben here. Lend me some bread till Friday?", "response": "Take it, Ben."}
    asked = "Could you lend me something to eat till Friday? I'll pay you back then."
    clean = {"situation": asked, "response": "Take it, and pay me when you can."}
    sums = {"situation": "You find bread worth $5 left on a bench.", "response": "I take it."}
    model = ScriptedModel(leaky, clean, sums, sums, "not an answer", "{}", '{"situation": ""}')
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
    assert made[1] == Dropped(moment=2, day=1, reason="leaked", detail="$")
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
