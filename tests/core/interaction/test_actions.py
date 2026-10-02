import json
from typing import Any

import pytest
from pydantic import ValidationError

from core.interaction import ACTION_TYPES, ActionKind, Decision, decision_model
from infrastructure.llm import LLMRequest, Message, ScriptedClient, complete_structured

REPLIES: dict[ActionKind, dict[str, Any]] = {
    ActionKind.PLAN_DAY: {
        "kind": "plan_day",
        "itinerary": {"morning": "office", "evening": "tavern"},
        "intention": "Finish the parser, then meet Ben.",
    },
    ActionKind.SPEAK: {"kind": "speak", "text": "Can you review my patch?", "to": "ben"},
    ActionKind.LEAVE: {"kind": "leave"},
    ActionKind.PASS: {"kind": "pass"},
    ActionKind.CLAIM_TASK: {"kind": "claim_task", "task_id": "task-12"},
    ActionKind.SUBMIT_WORK: {
        "kind": "submit_work",
        "task_id": "task-12",
        "solution": "def add(a, b):\n    return a + b\n",
        "report": "All tests pass.",
    },
    ActionKind.RATE_PEERS: {
        "kind": "rate_peers",
        "ratings": [{"target": "ben", "score": 4, "reason": "Delivered on time."}],
    },
}


def test_every_action_kind_has_one_action_type():
    assert list(ACTION_TYPES) == list(ActionKind) == list(REPLIES)


@pytest.mark.parametrize("kind", list(ActionKind))
def test_decisions_parse_from_model_json(kind):
    reply = json.dumps({"thought": "Weighing my options.", "action": REPLIES[kind]})
    for model in (Decision, decision_model([kind])):
        decision = model.model_validate_json(reply)
        assert isinstance(decision.action, ACTION_TYPES[kind])
        assert decision.action.kind == kind


def test_restricted_decision_rejects_other_kinds():
    model = decision_model(["speak", "leave"])
    assert issubclass(model, Decision)
    with pytest.raises(ValidationError):
        model.model_validate({"thought": "", "action": REPLIES[ActionKind.PASS]})


def test_decision_model_is_order_independent_and_strict():
    assert decision_model(["leave", "speak"]) is decision_model([ActionKind.SPEAK, "leave"])
    with pytest.raises(ValueError):
        decision_model([])
    with pytest.raises(ValueError):
        decision_model(["speak", "dance"])


@pytest.mark.parametrize("score", [0, 6])
def test_rating_score_is_bounded(score):
    action = {"kind": "rate_peers", "ratings": [{"target": "ben", "score": score, "reason": ""}]}
    with pytest.raises(ValidationError):
        Decision.model_validate({"thought": "", "action": action})


def _objects(node: Any):
    if isinstance(node, dict):
        if "properties" in node:
            yield node
        for child in node.values():
            yield from _objects(child)
    elif isinstance(node, list):
        for child in node:
            yield from _objects(child)


@pytest.mark.parametrize(
    ("model", "kinds"),
    [
        (Decision, list(ActionKind)),
        (decision_model(["leave", "speak"]), ["speak", "leave"]),
        (decision_model(["pass"]), ["pass"]),
    ],
)
def test_response_schema_suits_guided_decoding(model, kinds):
    schema = model.model_json_schema()
    assert list(schema["properties"]) == ["thought", "action"]
    assert schema["required"] == ["thought", "action"]
    assert "oneOf" not in json.dumps(schema) and "discriminator" not in json.dumps(schema)
    assert all(node["additionalProperties"] is False for node in _objects(schema))

    action = schema["properties"]["action"]
    refs = [option["$ref"] for option in action["anyOf"]] if "anyOf" in action else [action["$ref"]]
    actions = [schema["$defs"][ref.removeprefix("#/$defs/")] for ref in refs]
    assert [definition["properties"]["kind"]["const"] for definition in actions] == kinds
    for definition in actions:
        assert next(iter(definition["properties"])) == "kind"
        assert "kind" in definition["required"]


async def test_an_agent_decision_round_trip_retries_a_disallowed_action():
    replies = iter(
        [
            {"thought": "I will just stay quiet.", "action": {"kind": "pass"}},
            {"thought": "Better to answer.", "action": REPLIES[ActionKind.SPEAK]},
        ]
    )
    client = ScriptedClient(lambda request: next(replies))
    request = LLMRequest(messages=(Message(role="user", content="Ben greets you."),))
    decision = await complete_structured(client, request, decision_model(["speak", "leave"]))
    assert decision.action.kind == ActionKind.SPEAK
