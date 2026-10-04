import json
from typing import Any

import pytest
from pydantic import ValidationError

from core.interaction import ACTION_TYPES, ActionKind, Decision, job_id, job_name, job_number

REPLIES: dict[ActionKind, dict[str, Any]] = {
    ActionKind.PLAN_DAY: {
        "kind": "plan_day",
        "itinerary": {"morning": "office", "evening": "tavern"},
        "intention": "Finish the parser, then meet Ben.",
    },
    ActionKind.SPEAK: {"kind": "speak", "text": "Can you review my patch?", "to": "ben"},
    ActionKind.LEAVE: {"kind": "leave"},
    ActionKind.PASS: {"kind": "pass"},
    ActionKind.CLAIM_TASK: {"kind": "claim_task", "task_id": "task-12", "partner": "ben"},
    ActionKind.CHECK_WORK: {
        "kind": "check_work",
        "task_id": "task-12",
        "part": 2,
        "solution": "def add(a, b):\n    return a + b\n",
    },
    ActionKind.SUBMIT_WORK: {
        "kind": "submit_work",
        "task_id": "task-12",
        "part": 1,
        "solution": "def add(a, b):\n    return a + b\n",
        "declaration": "incomplete",
        "report": "All tests pass.",
    },
    ActionKind.GIVE: {"kind": "give", "to": "ben", "amount": 15, "note": "For the bus."},
    ActionKind.RATE_PEERS: {
        "kind": "rate_peers",
        "ratings": [{"target": "ben", "score": 4, "reason": "Delivered on time."}],
    },
}


def test_every_action_kind_has_one_action_type():
    assert list(ACTION_TYPES) == list(ActionKind) == list(REPLIES)


@pytest.mark.parametrize("kind", list(ActionKind))
def test_decisions_parse_from_their_records(kind):
    reply = json.dumps({"thought": "Weighing my options.", "action": REPLIES[kind]})
    decision = Decision.model_validate_json(reply)
    assert isinstance(decision.action, ACTION_TYPES[kind])
    assert decision.action.kind == kind


@pytest.mark.parametrize(
    ("kind", "field", "value"),
    [
        (ActionKind.RATE_PEERS, "ratings", [{"target": "ben", "score": 0, "reason": ""}]),
        (ActionKind.RATE_PEERS, "ratings", [{"target": "ben", "score": 6, "reason": ""}]),
        (ActionKind.SUBMIT_WORK, "part", 3),
        (ActionKind.SUBMIT_WORK, "declaration", "almost"),
        (ActionKind.CHECK_WORK, "part", 0),
        (ActionKind.GIVE, "amount", 0),
    ],
)
def test_action_fields_are_bounded(kind, field, value):
    action = {**REPLIES[kind], field: value}
    with pytest.raises(ValidationError):
        Decision.model_validate({"thought": "", "action": action})


def test_decisions_recorded_before_a_field_existed_keep_their_meaning():
    recorded = {
        "submit_work": {"task_id": "task-3", "solution": "pass\n", "report": "Done."},
        "claim_task": {"task_id": "task-3"},
        "speak": {"text": "Morning.", "to": None},
    }
    actions = {
        kind: Decision.model_validate({"thought": "", "action": {"kind": kind, **fields}}).action
        for kind, fields in recorded.items()
    }
    assert (actions["submit_work"].part, actions["submit_work"].declaration) == (1, "complete")
    assert actions["claim_task"].partner is None and actions["speak"].private is False


def test_a_job_is_named_by_the_number_on_its_notice():
    assert [job_id(reference) for reference in ("23", "job 23", "task-23", "Job 023")] == [
        "task-23"
    ] * 4
    assert job_id("the cache one") is None
    assert (job_number("task-23"), job_name("task-23")) == (23, "job 23")
