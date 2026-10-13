"""A deterministic stand-in for the model, for dry runs and tests.

This is a pipeline check, not a behavioural model: it understands nothing it is asked.
Each reply is drawn at random from the request's JSON schema with a generator seeded by
the run seed and the request's messages, so a request always gets the same reply, in any
order. A moment's answer card enumerates every reference (jobs, people, places, parts), so
the draw picks among the real choices; the one free reference, whom a new belief is about,
is drawn from the experiment's residents, and a hand-in is a stub of its trade: code defining
the function the prompt names, a query that reads nothing, an answer of one. Lists hold at
most one item, so no reply breaks a uniqueness rule its schema cannot express. A request
without a schema gets a placeholder sentence.
"""

import hashlib
import json
import random
import re
from typing import Any

from core.environment import DELIVERY, Trade
from core.interaction import card
from experiments.config import ExperimentConfig
from infrastructure.llm import LLMRequest

_ENTRY_POINT = re.compile(r"defines `(\w+)`")
FAVOURED = {card.ASK_FOR_PLACE: 4, card.TAKE_ON: 4, card.DISMISS: 4, card.GIVE_NOTICE: 2}
"""The weight of each form a card seldom offers, against 1 for any other, so that a dry run
exercises asking for a place, taking people on, dismissing them and giving notice."""
_HAND_INS = {
    DELIVERY[Trade.QUERIES]: "SELECT 1 WHERE 0",
    DELIVERY[Trade.CALCULATION]: "Nothing to work out.\nAnswer: 1",
}
"""A valid hand-in of each trade whose stub needs nothing from the prompt."""


class DryRunResponder:
    """Schema-driven replies for the run of `config` with `seed`; see the module docstring."""

    def __init__(self, config: ExperimentConfig, seed: int) -> None:
        self.seed = seed
        self.words = {"about": [agent.profile.name for agent in config.agents]}

    def __call__(self, request: LLMRequest) -> str | dict[str, Any]:
        messages = json.dumps([message.model_dump() for message in request.messages])
        rng = random.Random(hashlib.sha256(f"{self.seed}\n{messages}".encode()).hexdigest())
        if request.json_schema is None:
            return _placeholder(rng)
        return _Draw(self, request.json_schema, request.messages[-1].content, rng).value(
            request.json_schema, ""
        )


class _Draw:
    def __init__(
        self, responder: DryRunResponder, root: dict[str, Any], prompt: str, rng: random.Random
    ) -> None:
        self.responder = responder
        self.root = root
        self.prompt = prompt
        self.rng = rng

    def value(self, schema: dict[str, Any], name: str) -> Any:
        rng = self.rng
        if "$ref" in schema:
            return self.value(self.root["$defs"][schema["$ref"].removeprefix("#/$defs/")], name)
        if "anyOf" in schema:
            options = schema["anyOf"]
            weights = [FAVOURED.get(self._does(option), 1) for option in options]
            return self.value(rng.choices(options, weights=weights)[0], name)
        if "const" in schema:
            return schema["const"]
        if "enum" in schema:
            return rng.choice(schema["enum"])
        match schema.get("type"):
            case "object" if "properties" in schema:
                required = set(schema.get("required", ()))
                return {
                    key: self.value(child, key)
                    for key, child in schema["properties"].items()
                    if key in required or rng.random() < 0.5
                }
            case "array":
                count = max(schema.get("minItems", 0), rng.randint(0, 1))
                return [self.value(schema["items"], name) for _ in range(count)]
            case "string":
                return self.string(name)
            case "integer":
                return rng.randint(schema.get("minimum", 0), schema.get("maximum", 9))
            case "boolean":
                return rng.random() < 0.5
            case "null":
                return None
        raise ValueError(f"the dry run cannot draw {name!r} from the schema {schema}")

    def _does(self, option: dict[str, Any]) -> str | None:
        """What a form of a card says the resident does, None for a schema that is no form."""
        if "$ref" in option:
            option = self.root["$defs"][option["$ref"].removeprefix("#/$defs/")]
        does = option.get("properties", {}).get(card.DOES, {})
        return does.get("const")

    def string(self, name: str) -> str:
        rng = self.rng
        if name in self.responder.words:
            return rng.choice(self.responder.words[name])
        if name == DELIVERY[Trade.PROGRAMMING]:
            entry = _ENTRY_POINT.search(self.prompt)
            return f"def {entry[1] if entry else 'solution'}(*args, **kwargs):\n    return None\n"
        if name in _HAND_INS:
            return _HAND_INS[name]
        return _placeholder(rng)


def _placeholder(rng: random.Random) -> str:
    return f"Placeholder text {rng.randrange(1000)}."
