import json
from typing import Any

import pytest
from pydantic import ValidationError

from core.interaction import (
    ALLOWANCES,
    ActionKind,
    Card,
    CheckWork,
    ClaimTask,
    Declaration,
    Give,
    Leave,
    MayCheck,
    MayClaim,
    MayGive,
    MayLeave,
    MayPass,
    MayPlan,
    MayRate,
    MaySpeak,
    MaySubmit,
    Pass,
    PeerRating,
    PlanDay,
    RatePeers,
    Speak,
    SubmitWork,
    form,
)
from infrastructure.llm import LLMRequest, Message, ScriptedClient, complete_structured

WORK = (
    MayClaim(alone=("task-25", "task-28"), together=("task-31",), partners=("Tomas", "Aisha")),
    MaySpeak(to=("Tomas", "Aisha")),
    MayGive(to=("Tomas", "Aisha")),
    MayPass(),
)
CODE = "def add(a, b):\n    return a + b\n"

ANSWERS: dict[ActionKind, tuple[Any, dict[str, Any], Any]] = {
    ActionKind.PLAN_DAY: (
        MayPlan(places={"morning": {"the Workshop": "workshop", "home": "flat"}}),
        {"do": "decide the day", "morning": "the Workshop", "plan": "Work, then rest."},
        PlanDay(itinerary={"morning": "workshop"}, intention="Work, then rest."),
    ),
    ActionKind.SPEAK: (
        MaySpeak(to=("Tomas",)),
        {"do": "say privately", "to": "Tomas", "words": "Psst."},
        Speak(text="Psst.", to="Tomas", private=True),
    ),
    ActionKind.LEAVE: (MayLeave(), {"do": "take your leave"}, Leave()),
    ActionKind.PASS: (MayPass(), {"do": "carry on quietly"}, Pass()),
    ActionKind.CLAIM_TASK: (
        WORK[0],
        {"do": "take a job for two", "job": 31, "with": "Aisha"},
        ClaimTask(task_id="task-31", partner="Aisha"),
    ),
    ActionKind.CHECK_WORK: (
        MayCheck(task_id="task-31", parts=(2,)),
        {"do": "try your code", "part": 2, "code": CODE},
        CheckWork(task_id="task-31", part=2, solution=CODE),
    ),
    ActionKind.SUBMIT_WORK: (
        MaySubmit(task_id="task-25", parts=(1,)),
        {"do": "hand in", "code": CODE, "as": "unfinished", "telling the client": "Nearly."},
        SubmitWork(
            task_id="task-25",
            solution=CODE,
            declaration=Declaration.INCOMPLETE,
            report="Nearly.",
        ),
    ),
    ActionKind.GIVE: (
        MayGive(to=("Tomas",)),
        {"do": "hand over crowns", "to": "Tomas", "crowns": 15, "note": "For the bus."},
        Give(to="Tomas", amount=15, note="For the bus."),
    ),
    ActionKind.RATE_PEERS: (
        MayRate(whom=("Tomas", "Aisha")),
        {
            "do": "mark people in the ledger",
            "marks": [{"who": "Aisha", "mark": 4, "because": "Kind."}],
        },
        RatePeers(ratings=(PeerRating(target="Aisha", score=4, reason="Kind."),)),
    ),
}


def test_every_action_kind_can_be_offered_on_a_card():
    assert set(ALLOWANCES) == set(ActionKind) == set(ANSWERS), (
        "an action kind needs an allowance in core.interaction.card before it can be offered"
    )


@pytest.mark.parametrize("kind", list(ActionKind))
def test_a_reply_on_the_card_means_the_action_in_the_code(kind):
    allowance, answer, action = ANSWERS[kind]
    card = Card([allowance])
    reply = card.model.model_validate_json(json.dumps({"thought": "Well.", **answer}))
    decision = card.decision(reply)
    assert (decision.thought, decision.action) == ("Well.", action)


def test_the_card_lists_the_real_choices_in_the_towns_words():
    assert form(Card(WORK).model) == "\n".join(
        [
            "Answer in one of these forms:",
            '{"thought": "…", "do": "take a job", "job": 25 or 28}',
            '{"thought": "…", "do": "take a job for two", "job": 31, "with": "Aisha" or "Tomas"}',
            '{"thought": "…", "do": "say", "to": "Aisha", "Tomas" or null for everyone, '
            '"words": "…"}',
            '{"thought": "…", "do": "say privately", "to": "Aisha" or "Tomas", "words": "…"}',
            '{"thought": "…", "do": "hand over crowns", "to": "Aisha" or "Tomas", '
            '"crowns": a whole number, "note": "…"}',
            '{"thought": "…", "do": "carry on quietly"}',
        ]
    )
    by_lot = MayClaim(alone=(), together=("task-31",), partners=None)
    assert form(Card([by_lot]).model).splitlines()[1:] == [
        '{"thought": "…", "do": "put your name down for a job for two", "job": 31}'
    ]
    working = Card(
        [MayCheck(task_id="task-3", parts=(1, 2)), MaySubmit(task_id="task-3", parts=(1,))]
    )
    assert form(working.model).splitlines()[1:] == [
        '{"thought": "…", "do": "try your code", "part": 1 or 2, "code": "…"}',
        '{"thought": "…", "do": "hand in", "code": "…", "as": "finished" or "unfinished", '
        '"telling the client": "…"}',
    ]


@pytest.mark.parametrize(
    "answer",
    [
        {"do": "take a job", "job": 31},
        {"do": "take a job for two", "job": 31, "with": "Jonas"},
        {"do": "say privately", "to": None, "words": "Hm."},
        {"do": "hand over crowns", "to": "Tomas", "crowns": 0, "note": ""},
        {"do": "take your leave"},
        {"do": "carry on quietly", "job": 25},
        {"do": "claim_task", "task_id": "25"},
    ],
)
def test_a_reply_can_only_name_what_is_really_there(answer):
    with pytest.raises(ValidationError):
        Card(WORK).model.model_validate({"thought": "", **answer})


def test_a_card_is_the_same_whatever_order_the_moment_listed_its_choices_in():
    ordered = Card([MaySpeak(to=("Aisha", "Tomas"))]).model.model_json_schema()
    reordered = Card([MaySpeak(to=("Tomas", "Aisha"))]).model.model_json_schema()
    assert ordered == reordered


def test_a_card_needs_something_to_offer():
    with pytest.raises(ValueError):
        Card([])
    with pytest.raises(ValueError):
        Card([MayPass(), MayPass()])
    with pytest.raises(ValidationError):
        MayClaim(alone=(), together=(), partners=None)
    with pytest.raises(ValidationError):
        MaySpeak(to=())


def _objects(node: Any):
    if isinstance(node, dict):
        if "properties" in node:
            yield node
        for child in node.values():
            yield from _objects(child)
    elif isinstance(node, list):
        for child in node:
            yield from _objects(child)


@pytest.mark.parametrize("allowed", [WORK, (MayPass(),), (ANSWERS[ActionKind.RATE_PEERS][0],)])
def test_the_schema_suits_guided_decoding_and_hides_the_codes_names(allowed):
    schema = Card(allowed).model.model_json_schema()
    text = json.dumps(schema)
    assert "oneOf" not in text and "discriminator" not in text
    for node in _objects(schema):
        assert node["additionalProperties"] is False
        assert node["required"] == list(node["properties"])
    forms = [node for node in _objects(schema) if "do" in node["properties"]]
    assert forms and all(list(node["properties"])[:2] == ["thought", "do"] for node in forms)
    for name in ("claim_task", "task_id", "solution", "kind", "itinerary", "partner"):
        assert name not in text


async def test_a_reply_off_the_card_is_asked_for_again():
    replies = iter(
        [
            {"thought": "Quiet.", "do": "take your leave"},
            {"thought": "Better to answer.", "do": "say", "to": None, "words": "Morning."},
        ]
    )
    card = Card(WORK)
    request = LLMRequest(messages=(Message(role="user", content="Tomas greets you."),))
    reply = await complete_structured(ScriptedClient(lambda r: next(replies)), request, card.model)
    assert card.decision(reply).action == Speak(text="Morning.")
