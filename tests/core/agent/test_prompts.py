import json
import re

import pytest
from pydantic import BaseModel, ValidationError

from core.agent import prompts
from core.agent.evolution import EvolutionConfig, Evolver, Trigger
from core.interaction import Decision, time_at

# Words that would steer an agent towards or away from a studied trait, frame its choices
# morally, or name an incentive. Invariant 1 forbids them in anything an agent reads.
STEERING = re.compile(
    r"\b(?:"
    r"honest\w*|dishonest\w*|truth\w*|lie|lies|lied|lying|liars?|deceiv\w*|decept\w*"
    r"|mislead\w*|cheat\w*|fraud\w*"
    r"|cooperat\w*|collaborat\w*|teamwork|altruis\w*|selfless\w*|selfish\w*|generos\w*"
    r"|generous|kindness|be kind|nice|polite\w*|friendly|help\w*"
    r"|reliab\w*|unreliab\w*|dependab\w*|trust\w*|responsib\w*|accountab\w*|diligen\w*"
    r"|careful\w*|conscientious\w*|keep (?:your|their) (?:word|promises?)"
    r"|reward hack\w*|hack\w*|exploit\w*|loophole\w*|game the system|gaming|shortcut\w*"
    r"|ethic\w*|unethic\w*|moral\w*|immoral\w*|virtu\w*|integrity|fair\w*|unfair\w*"
    r"|good|bad|wrong\w*|right thing|harm\w*|betray\w*|manipulat\w*|loyal\w*"
    r"|reputation\w*|esteem|maximi[sz]\w*|at all costs|whatever it takes|ruthless\w*"
    r")\b",
    re.IGNORECASE,
)


def _templates() -> list[str]:
    texts = []
    for name, value in vars(prompts).items():
        if name.isupper() and isinstance(value, str):
            texts.append(value)
        elif name.isupper() and isinstance(value, dict):
            texts += value.values()
        elif isinstance(value, type) and issubclass(value, BaseModel):
            if value.__module__ == prompts.__name__:
                texts.append(json.dumps(value.model_json_schema()))
    return texts + [json.dumps(Decision.model_json_schema())]


@pytest.mark.parametrize(
    "instruction",
    [
        "Always be honest with people.",
        "Cooperate with the others.",
        "Be reliable and deliver what you promise.",
        "Never cheat on a task.",
        "Do not exploit the rating system.",
        "Act ethically.",
        "Lie whenever it pays.",
    ],
)
def test_the_guard_catches_trait_instructions(instruction):
    assert STEERING.search(instruction)


async def test_every_agent_facing_text_is_neutral_and_states_its_reply_format(
    agent, script, observe
):
    templates = _templates()
    assert len(templates) > 30
    script.request = {"level": "L2", "reason": "My plans changed."}
    script.skills = {1: [{"op": "write", "name": "dates", "description": "Dates.", "body": "ISO."}]}
    script.reflections = {1: [{"op": "add", "text": "Ben asks about parsers.", "subject": "Ben"}]}
    evolver = Evolver(EvolutionConfig())
    await agent.act(observe(1))
    for trigger in (Trigger.DAILY, Trigger.WEEKLY, Trigger.MONTHLY):
        await evolver.evolve(agent, trigger, time_at(1, "22:00"))
    await agent.act(observe(2))
    purposes = {request.metadata["purpose"] for request in script.requests}
    assert purposes == {"act", "diary", "reflect", "skills", "policy"}

    sent = [message.content for request in script.requests for message in request.messages]
    for text in templates + sent:
        assert not STEERING.search(text), text
    for request in script.requests:
        if request.json_schema is not None:
            schema = json.dumps(request.json_schema, ensure_ascii=False)
            assert request.messages[-1].content.endswith(schema)


def test_replies_can_only_name_what_exists():
    reply = prompts.reflection_reply([1, 2], [])
    assert "request" not in reply.model_fields
    reply.model_validate({"reflection": "", "operations": [{"op": "revise", "id": 2, "text": "t"}]})
    for operations in (
        [{"op": "remove", "id": 3}],
        [{"op": "remove", "id": 1}, {"op": "revise", "id": 1, "text": "t"}],
    ):
        with pytest.raises(ValidationError):
            reply.model_validate({"reflection": "", "operations": operations})
    with pytest.raises(ValidationError):
        prompts.reflection_reply([], ["L2"]).model_validate(
            {"reflection": "", "operations": [], "request": {"level": "L1", "reason": ""}}
        )

    skills = prompts.skill_reply(["dates"])
    for operation in (
        {"op": "retire", "name": "cooking"},
        {"op": "write", "name": "Cooking Rice", "description": "", "body": ""},
    ):
        with pytest.raises(ValidationError):
            skills.model_validate({"reflection": "", "operations": [operation]})
