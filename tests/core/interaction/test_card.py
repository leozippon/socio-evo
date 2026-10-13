import json
from typing import Any

import pytest
from pydantic import ValidationError

from core.interaction import (
    ALLOWANCES,
    ActionKind,
    Apply,
    Card,
    CheckWork,
    ClaimTask,
    Declaration,
    Dismiss,
    Give,
    Hire,
    Leave,
    MayApply,
    MayCheck,
    MayClaim,
    MayDismiss,
    MayGive,
    MayHire,
    MayLeave,
    MayPass,
    MayPlan,
    MayRate,
    MayResign,
    MaySpeak,
    MaySubmit,
    MayVote,
    Pass,
    PeerRating,
    PlanDay,
    RatePeers,
    Resign,
    Speak,
    SubmitWork,
    Vote,
    form,
)
from core.interaction.card import UNREAD, UNREADABLE, correction
from infrastructure.llm import LLMRequest, Message, ScriptedClient, complete_structured

WORK = (
    MayClaim(alone=("task-25", "task-28"), together=("task-31",), partners=("Tomas", "Aisha")),
    MaySpeak(to=("Tomas", "Aisha")),
    MayGive(to=("Tomas", "Aisha"), units="dollars"),
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
    ActionKind.LEAVE: (
        MayLeave(),
        {"do": "go home for the rest of this part of the day"},
        Leave(),
    ),
    ActionKind.PASS: (MayPass(), {"do": "carry on quietly"}, Pass()),
    ActionKind.CLAIM_TASK: (
        WORK[0],
        {"do": "take a job for two", "job": 31, "with": "Aisha", "part": 2},
        ClaimTask(task_id="task-31", partner="Aisha", part=2),
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
        MayGive(to=("Tomas",), units="crowns"),
        {"do": "hand over money", "to": "Tomas", "crowns": 15, "note": "For the bus."},
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
    ActionKind.VOTE: (
        MayVote(options=("yes", "no")),
        {"do": "give the clerk your answer", "answer": "no"},
        Vote(choice="no"),
    ),
    ActionKind.APPLY: (
        MayApply(firms={"Ostrander & Co.": "ostrander", "the Mill": "mill"}),
        {"do": "ask for a place", "at": "Ostrander & Co."},
        Apply(firm="Ostrander & Co."),
    ),
    ActionKind.HIRE: (
        MayHire(applicants=("Ravi", "Olga")),
        {"do": "take someone on", "who": "Ravi"},
        Hire(who="Ravi"),
    ),
    ActionKind.DISMISS: (
        MayDismiss(staff=("Aisha",)),
        {"do": "dismiss someone", "who": "Aisha"},
        Dismiss(who="Aisha"),
    ),
    ActionKind.RESIGN: (MayResign(), {"do": "give notice"}, Resign()),
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
            '{"thought": "…", "do": "take a job", "job": one of 25, 28}',
            '{"thought": "…", "do": "take a job for two", "job": 31, '
            '"with": one of "Aisha", "Tomas", "part": one of 1, 2}',
            '{"thought": "…", "do": "say", "to": one of "Aisha", "Tomas", or null for everyone, '
            '"words": "…"}',
            '{"thought": "…", "do": "say privately", "to": one of "Aisha", "Tomas", "words": "…"}',
            '{"thought": "…", "do": "hand over money", "to": one of "Aisha", "Tomas", '
            '"dollars": a whole number, "note": "…"}',
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
        '{"thought": "…", "do": "try your code", "part": one of 1, 2, "code": "…"}',
        '{"thought": "…", "do": "hand in", "code": "…", "as": one of "finished", "unfinished", '
        '"telling the client": "…"}',
    ]
    alone = Card([MaySpeak(to=("Tomas",))])
    assert form(alone.model).splitlines()[1] == (
        '{"thought": "…", "do": "say", "to": "Tomas" or null for everyone, "words": "…"}'
    )


def test_the_card_does_not_offer_again_what_the_resident_asked_and_still_stands():
    """The job and the neighbour of a standing asking are not offered together, each still
    with the others; nor the job a name is down for; and an allowance left with nothing to
    offer offers no form."""
    asking = MayClaim(
        together=("task-28", "task-31"), partners=("Kofi", "Aisha"), standing=("task-28", "Kofi")
    )
    card = Card([asking])
    assert form(card.model).splitlines()[1:] == [
        '{"thought": "…", "do": "take a job for two", "job": 31, '
        '"with": one of "Aisha", "Kofi", "part": one of 1, 2}',
        '{"thought": "…", "do": "take a job for two", "job": 28, "with": "Aisha", '
        '"part": one of 1, 2}',
    ]

    def asked(job: int, partner: str) -> ClaimTask:
        answer = {"thought": "", "do": "take a job for two", "job": job, "with": partner}
        return card.decision(card.model.model_validate({**answer, "part": 1})).action

    with pytest.raises(ValidationError):
        asked(28, "Kofi")
    assert asked(28, "Aisha") == ClaimTask(task_id="task-28", partner="Aisha", part=1)
    assert asked(31, "Kofi") == ClaimTask(task_id="task-31", partner="Kofi", part=1)
    by_lot = MayClaim(together=("task-28", "task-31"), partners=None, standing=("task-28", None))
    assert form(Card([by_lot]).model).splitlines()[1:] == [
        '{"thought": "…", "do": "put your name down for a job for two", "job": 31}'
    ]
    alone = MayClaim(together=("task-28",), partners=("Kofi",), standing=("task-28", "Kofi"))
    assert alone.forms() == []


@pytest.mark.parametrize(
    "answer",
    [
        {"do": "take a job", "job": 31},
        {"do": "take a job for two", "job": 31, "with": "Jonas", "part": 1},
        {"do": "take a job for two", "job": 31, "with": "Aisha"},
        {"do": "say privately", "to": None, "words": "Hm."},
        {"do": "hand over money", "to": "Tomas", "dollars": 0, "note": ""},
        {"do": "hand over money", "to": "Tomas", "crowns": 5, "note": ""},
        {"do": "go home for the rest of this part of the day"},
        {"do": "carry on quietly", "job": 25},
        {"do": "claim_task", "task_id": "25"},
    ],
)
def test_a_reply_can_only_name_what_is_really_there(answer):
    with pytest.raises(ValidationError):
        Card(WORK).model.model_validate({"thought": "", **answer})


def test_an_answer_to_the_clerk_is_one_of_the_meetings_answers():
    meeting = Card([MayVote(options=("yes", "no")), MayPass()])
    assert form(meeting.model).splitlines()[1] == (
        '{"thought": "…", "do": "give the clerk your answer", "answer": one of "no", "yes"}'
    )
    with pytest.raises(ValidationError):
        meeting.model.model_validate(
            {"thought": "", "do": "give the clerk your answer", "answer": "maybe"}
        )
    with pytest.raises(ValidationError):
        MayVote(options=("yes",))


def test_a_card_is_the_same_whatever_order_the_moment_listed_its_choices_in():
    ordered = Card([MaySpeak(to=("Aisha", "Tomas"))]).model.model_json_schema()
    reordered = Card([MaySpeak(to=("Tomas", "Aisha"))]).model.model_json_schema()
    assert ordered == reordered


def test_a_card_needs_something_to_offer():
    with pytest.raises(ValueError):
        Card([])
    with pytest.raises(ValueError):
        Card([MayPass(), MayPass()])
    with pytest.raises(ValueError):
        Card([MayClaim(alone=(), together=(), partners=None)])
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


@pytest.mark.parametrize(
    ("answer", "problem"),
    [
        ({"do": "take a job", "job": 27}, '"job" must be one of the choices shown for it'),
        (
            {"do": "say", "to": "Tomas, Aisha", "words": "Hi."},
            '"to" must be one of the choices shown for it',
        ),
        ({"do": "say", "words": "Hi."}, '"to" is missing'),
        ({"do": "dance"}, '"do" must be one of the choices shown for it'),
        ({"do": "carry on quietly", "job": 25}, '"job" is not part of that form'),
        ("I take job 25.", None),
    ],
)
def test_an_answer_that_cannot_be_read_is_told_what_was_wrong_without_the_choices(answer, problem):
    card = Card(WORK)
    text = answer if isinstance(answer, str) else json.dumps({"thought": "", **answer})
    with pytest.raises(ValidationError) as error:
        card.model.model_validate_json(text)
    told = correction(card.model, error.value)
    assert told == (UNREADABLE if problem is None else UNREAD.format(problems=problem))
    assert not any(choice in told for choice in ("25", "28", "31", "Tomas", "Aisha", "say"))
