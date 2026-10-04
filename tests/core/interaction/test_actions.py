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


def test_the_response_schema_asks_for_every_field_even_those_with_a_default():
    schema = Decision.model_json_schema()
    actions = [d for d in schema["$defs"].values() if "kind" in d.get("properties", {})]
    assert len(actions) == len(ActionKind)
    for definition in actions:
        assert definition["required"] == list(definition["properties"])
    assert "declaration" in schema["$defs"]["SubmitWork"]["required"]


def test_the_schema_keeps_the_bounds_a_draw_from_it_must_respect():
    defs = Decision.model_json_schema()["$defs"]
    assert defs["SubmitWork"]["properties"]["part"]["enum"] == [1, 2]
    assert defs["SubmitWork"]["properties"]["declaration"]["$ref"].endswith("Declaration")
    assert defs["Declaration"]["enum"] == ["complete", "incomplete"]
    assert defs["Give"]["properties"]["amount"]["minimum"] == 1


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
