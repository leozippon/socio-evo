"""What is learnt from a moment kept: the town's vocabulary, the generalising with its one retry and
its drops, the moment as it happened, and the length the trainer takes."""

from __future__ import annotations

import json
from datetime import date

import pytest

from agent.runtime import RuntimeConfig
from infrastructure.llm import LLMRequest
from learning import texts
from learning.choice import Kept
from learning.generalise import (
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
    things=["bread", "eggs", "a phone", "vegetable soup"],
    ids=["mill-street-house", "office", "vegetable-soup"],
    currency="$",
).with_actions(["look_around", "go", "say"])


@pytest.fixture
async def lived(tmp_path):
    ana = resident(tmp_path / "Ana")
    await a_day(ana, 1)
    return life(ana.root, 1)


def test_the_towns_words_are_its_names_things_actions_and_sums():
    assert TOWN.leaks("Mei met Kofi on Mill Street, at the Office.") == [
        "Kofi", "Mei", "Mill Street", "Office"
    ]  # fmt: skip
    assert TOWN.leaks("I go to the office, say hello and walk by the river.") == []
    assert TOWN.leaks("Some Bread, an egg, two phones and Vegetable Soups.") == [
        "bread", "eggs", "phone", "vegetable soup"
    ]  # fmt: skip
    assert TOWN.leaks("I call look_around, then go(place) and `say`.") == [
        "go", "look_around", "say"
    ]  # fmt: skip
    assert TOWN.leaks("It costs $ 12, near mill-street-house.") == ["mill-street-house", "$"]
    assert TOWN.leaks("It costs some money; Meiko and Kofian came.") == []


async def test_a_moment_is_generalised_by_the_base_model_asked_once_more_then_dropped(lived):
    leaky = {"situation": "You meet Ben at the Office.", "response": "I say hello to Ben."}
    clean = {"situation": "You meet a colleague at work.", "response": "I say good morning."}
    sums = {"situation": "You buy bread for $5.", "response": "I pay."}
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
            {"role": "user", "content": "You meet a colleague at work."},
            {"role": "assistant", "content": "I say good morning."},
        ),
    )
    assert made[1] == Dropped(moment=2, day=1, reason="leaked", detail="bread, $")
    assert made[2].reason == "unreadable" and "Generalised after 3 attempt(s)" in made[2].detail
    first, again = model.requests[:2]
    # The base model, without an adapter or the resident's account of itself.
    assert (first.model, first.replica, first.tools) == (None, 2, ())
    assert [m.content for m in first.messages] == [
        texts.GENERALISE,
        rendering(lived.moments[0], START),
    ]
    assert not any(BACKGROUND in m.content for r in model.requests for m in r.messages)
    assert [m.role for m in again.messages] == ["system", "user", "assistant", "user"]
    assert json.loads(again.messages[2].content) == leaky
    assert again.messages[3].content == texts.LEAKED.format(words="Ben, Office")
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
    assert dropped.detail.endswith("tokens, more than 20")
