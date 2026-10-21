"""The real Activity menus retain free choices while personal context stays scoped."""

import json

import pytest

from core.agent import Agent, CognitionConfig
from core.agent.memory import Record, Skill
from core.interaction import EventKind
from infrastructure.llm import ScriptedClient
from tests.core.agent.conftest import SEED, TOWN
from tests.runtime.activities import test_engine as base
from tests.runtime.realtime.test_engine import finish as finish_realtime
from tests.runtime.realtime.test_engine import rt as realtime_fixture

rt = realtime_fixture

engine = base.engine


@pytest.fixture(params=["engine", "rt"])
def scheduler(request):
    return request.getfixturevalue(request.param)


@pytest.mark.parametrize("choice", ["rest", "join conversation"])
@pytest.mark.parametrize("use_method", [False, True])
async def test_aisha_can_rest_or_join_without_compulsory_skill_calls(
    scheduler, tmp_path, choice, use_method
):
    e = scheduler
    chat = base.conversation(e, public=True)
    e.env.move("Aisha", "workshop", time=e.now // 60)
    seed = SEED.model_copy(update={"profile": SEED.profile.model_copy(update={"name": "Aisha"})})
    requests = []

    def answer(request):
        requests.append(request)
        schema = json.dumps(request.json_schema)
        assert "join conversation" in schema and '"rest"' in schema
        if use_method and len(requests) == 1:
            return {"thought": "Consider my method.", "do": "use skill", "name": "ask-first"}
        if choice == "rest":
            return {
                "thought": "I prefer a break.",
                "do": "rest",
                "day": "today",
                "until": "10:00",
                "wake for invitations": False,
            }
        return {
            "thought": "I want to talk.",
            "do": "join conversation",
            "conversation": chat.id,
            **({} if hasattr(e, "running") else {"minutes": 15}),
        }

    agent = Agent.create(tmp_path / "Aisha", seed, ScriptedClient(answer), CognitionConfig(), TOWN)
    agent.memory.skills.write(
        Skill(
            name="ask-first",
            title="Ask first",
            description="Conversation",
            body="Consider whether you want company; you can also rest.",
        )
    )
    agent.memory.episodic.append(
        [
            Record(
                time=e.now // 60,
                kind=EventKind.COMMAND_EXECUTED,
                task_id="task-1",
                text="OLD_CODE_SHOULD_NOT_APPEAR",
            ),
            Record(time=e.now // 60, text="OLD_REASON_SHOULD_NOT_APPEAR"),
        ]
    )
    observation = e.observation("Aisha")
    assert observation.activity_kind == "selection"
    assert "Open conversations here" in observation.situation and chat.id in observation.situation
    decision = await agent.choose_activity(observation)
    e.select("Aisha", decision.action)
    active = e.activities[e.current["Aisha"]]
    assert active.kind == ("rest" if choice == "rest" else "conversation")
    if choice == "rest":
        assert active.wake_invitations is False
    assert len(requests) == 1 + use_method
    text = "\n".join(m.content for r in requests for m in r.messages)
    assert "OLD_CODE_SHOULD_NOT_APPEAR" not in text
    assert "OLD_REASON_SHOULD_NOT_APPEAR" not in text
    assert all(r.metadata["purpose"] == "choose_activity" for r in requests)


async def test_task_specification_is_only_automatic_in_work(scheduler):
    e = scheduler
    base.work(e)
    await base.perform(e, "Mei", "claim", job="task-1", partner=None)
    claim = e.env.board.claim_of("Mei")
    specification = claim.task.parts[0].specification
    work = e.observation("Mei")
    assert work.activity_kind == "work" and work.activity_task_id == "task-1"
    assert specification in work.situation
    e.leave("Mei", "Take a break")
    selection = e.observation("Mei")
    assert selection.own_task_id == "task-1" and selection.activity_task_id is None
    assert specification not in selection.situation
    chat = base.conversation(e)
    conversation = e.observation("Mei")
    assert conversation.activity_id == chat.id and conversation.activity_kind == "conversation"
    assert specification not in conversation.situation
    chat.task_id = "task-1"
    related = e.observation("Mei")
    assert related.activity_task_id == "task-1"
    assert specification not in related.situation


async def test_executed_work_receipt_supports_daytime_revision(scheduler, tmp_path):
    e = scheduler
    work = base.work(e)
    await base.perform(e, "Mei", "claim", job="task-1", partner=None)
    requests = []
    phase = "work"

    def answer(request):
        requests.append(request)
        if phase == "work":
            if len(requests) == 1:
                return {"thought": "Try my method.", "do": "use skill", "name": "inspect"}
            return {
                "thought": "Inspect the current file.",
                "do": "run a command",
                "command": "cat current.py",
            }
        if len(requests) == 3:
            assert "repository evidence" in request.messages[-1].content
            return {
                "thought": "Include the caller next time.",
                "do": "revise skill",
                "sources": [receipt.seq],
                "change": {
                    "change": "write",
                    "title": "Inspect",
                    "summary": "Before editing",
                    "text": "Read the current file and its caller.",
                },
            }
        return {
            "thought": "I want a break.",
            "do": "rest",
            "day": "today",
            "until": "10:00",
            "wake for invitations": True,
        }

    agent = Agent.create(tmp_path / "Mei", SEED, ScriptedClient(answer), CognitionConfig(), TOWN)
    original = Skill(
        name="inspect", title="Inspect", description="Before editing", body="Read the current file."
    )
    agent.memory.skills.write(original)
    decision = await agent.choose_tool(e.observation("Mei"))
    e.schedule("Mei", decision.action)
    if hasattr(e, "running"):
        await finish_realtime(e, "Mei")
    else:
        await base.complete(e, e.pending["Mei"].end)
    provider = next(iter(e.env.providers.values()))
    assert ("Mei", "cat current.py") in provider.commands
    observation = e.observation("Mei")
    receipt = next(p for p in observation.percepts if p.kind == EventKind.COMMAND_EXECUTED)
    phase = "revise"
    decision = await agent.choose_tool(observation)
    e.schedule("Mei", decision.action)
    assert e.activities[e.current["Mei"]].kind == "rest"
    assert agent.memory.skills.read()[0].version != original.version
    records = agent.memory.episodic.read()
    action = next(r for r in records if r.action and r.action.get("tool") == "command")
    observed = next(r for r in records if r.seq == receipt.seq)
    assert action.decision_id in observed.related_decisions
    assert action.activity_id == work.id
    assert action.skill_trace["skill"]["version"] == original.version
    assert len(requests) == 4  # Two voluntary internal operations, two external decisions.


async def test_realtime_body_inherits_method_without_editing_it(rt, tmp_path):
    chat = base.conversation(rt)
    phase = "intent"
    requests = []

    def answer(request):
        requests.append(request)
        schema = json.dumps(request.json_schema)
        if phase == "intent" and len(requests) == 1:
            assert "revise skill" in schema
            return {"thought": "Listen first.", "do": "use skill", "name": "listen"}
        if phase == "intent":
            return {"thought": "Address Tomas.", "do": "reply", "targets": ["Tomas"]}
        assert "revise skill" not in schema and "use skill" not in schema
        assert "LISTEN_METHOD" in request.messages[-1].content
        return {"thought": "Clarify.", "text": "What did you mean?"}

    agent = Agent.create(tmp_path / "Mei", SEED, ScriptedClient(answer), CognitionConfig(), TOWN)
    agent.memory.skills.write(
        Skill(
            name="listen",
            title="Listen",
            description="For conversations",
            body="LISTEN_METHOD: ask before assuming.",
        )
    )
    observation = rt.observation("Mei")
    await agent.choose_tool(observation)
    phase = "body"
    allowance = observation.allowed[0].model_copy(
        update={
            "menu": {
                **observation.allowed[0].menu,
                "reply_phase": "body",
                "reply_targets": ["Tomas"],
            }
        }
    )
    await agent.choose_tool(
        observation.model_copy(update={"allowed": (allowance,), "percepts": ()})
    )
    assert agent.personal_skills.activity == chat.id
    assert len(requests) == 3
