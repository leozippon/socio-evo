"""Active recollection is private cognition; budgets cover the real completion request."""

import json

import pytest
from pydantic import ValidationError

from core.agent.config import ActiveRecallConfig, ContextBudgetConfig, WorkNotesConfig
from core.agent.context import Block, BudgetClient, ContextOverflow, Counter, pack
from core.agent.memory import Record
from core.agent.memory.active import search
from core.interaction import EventKind, Speak, time_at
from infrastructure.llm import LLMRequest, Message, Sampling, ScriptedClient


def enable(agent, *, recall=True, budget=True, **limits):
    agent.cognition = agent.cognition.model_copy(
        update={
            "active_recall": ActiveRecallConfig(enabled=recall),
            "context_budget": ContextBudgetConfig(enabled=budget, **limits),
        }
    )


async def test_recall_before_action_with_time_source_and_no_external_recall(agent, observe):
    enable(agent)
    agent.memory.diary.write(1, "Tomas found the parser failure was caused by a missing timezone.")
    requests = []

    def answer(request):
        requests.append(request)
        if request.metadata["recall_round"] == 0:
            return {
                "thought": "What caused that failure?",
                "do": "recall something",
                "query": "Tomas timezone",
            }
        text = request.messages[-1].content
        assert "missing timezone" in text
        assert "your diary for" in text and "14 October" in text
        assert "day-0001.md" in request.metadata["active_recall"][0]["results"][0]["source"]
        return {
            "thought": "I remember the cause.",
            "do": "say",
            "to": "Ben",
            "words": "Check the timezone.",
        }

    agent.client = ScriptedClient(answer)
    result = await agent.act(observe(2))
    assert result.action == Speak(to="Ben", text="Check the timezone.")
    assert len(requests) == 2
    records = agent.memory.episodic.read()
    assert len(records) == 2  # only current percept and final external decision
    assert requests[1].metadata["active_recall"][0]["results"]
    for request in requests:
        assert request.metadata["context_usage"]["input_count"] <= 24000


async def test_repeated_queries_are_bounded_and_last_card_forces_action(agent, observe):
    enable(agent)
    requests = []

    def answer(request):
        requests.append(request)
        if request.metadata["recall_round"] < 2:
            return {"thought": "I need a detail.", "do": "recall something", "query": "absent"}
        assert "recall something" not in json.dumps(request.json_schema)
        assert "No matching recollection" in request.messages[-1].content
        return {"thought": "I do not know.", "do": "carry on quietly"}

    agent.client = ScriptedClient(answer)
    await agent.act(observe(2))
    assert len(requests) == 3
    assert requests[-1].metadata["active_recall"][-1]["repeated"]


async def test_can_act_without_mandatory_recall_and_budget_without_recall(agent, script, observe):
    enable(agent, recall=False)
    await agent.act(observe(1))
    assert len(script.requests) == 1
    assert "recall something" not in json.dumps(script.requests[0].json_schema)
    assert script.requests[0].metadata["context_usage"]


async def test_recall_works_without_budget(agent, script, observe):
    enable(agent, budget=False)
    await agent.act(observe(1))
    assert len(script.requests) == 1
    assert "context_usage" not in script.requests[0].metadata


def test_search_own_sources_and_tail_chunks_only(agent, tmp_path):
    agent.memory.diary.write(1, "noise " * 2000 + "Tomas diagnosed timezone regression")
    agent.memory.diary.write(4, "Tomas FUTURE_SECRET")
    agent.memory.episodic.append([Record(time=time_at(4, "10:00"), text="Tomas FUTURE_RECORD")])
    (tmp_path / "other-agent").mkdir()
    (tmp_path / "other-agent" / "secret.md").write_text("Tomas OTHER_SECRET")
    hits = search(agent.memory, "Tomas timezone", time_at(3, "12:00"), ActiveRecallConfig())
    assert any("timezone regression" in h.text for h in hits)
    assert all("SECRET" not in h.text and "FUTURE" not in h.text for h in hits)
    assert all(h.source.startswith("memory/") for h in hits)
    assert search(agent.memory, "UNSEEN_STRING", time_at(3, "12:00"), ActiveRecallConfig()) == []


def test_search_refuses_symlink_escape(agent, tmp_path):
    target = tmp_path / "another-person.jsonl"
    target.write_text('{"time":0,"text":"timezone PRIVATE"}\n')
    agent.memory.episodic.path.unlink()
    agent.memory.episodic.path.symlink_to(target)
    assert search(agent.memory, "timezone", time_at(2, "12:00"), ActiveRecallConfig()) == []


def request(text="CURRENT TASK", **kwargs):
    return LLMRequest(
        messages=(Message(role="system", content="IDENTITY"), Message(role="user", content=text)),
        **kwargs,
    )


def test_packing_prioritizes_evidence_dedup_and_dynamic_reuse():
    cfg = ContextBudgetConfig(
        enabled=True, context_tokens=5000, input_tokens=700, output_tokens=100, safety_tokens=100
    )
    req = request()
    blocks = [
        Block("old", "irrelevant " * 1000, 10),
        Block("test", "COMMAND pytest\n" + "failure " * 200 + "EXIT 1", 90),
    ]
    packed = pack(req, blocks, cfg)
    text = packed.messages[-1].content
    assert "CURRENT TASK" in text and "COMMAND pytest" in text and "EXIT 1" in text
    assert "irrelevant" not in text
    assert Counter(cfg).request(packed) <= 700
    assert "irrelevant" in pack(req, [Block("old", "irrelevant", 10)], cfg).messages[-1].content


def test_required_context_does_not_silently_disappear():
    cfg = ContextBudgetConfig(input_tokens=100)
    with pytest.raises(ContextOverflow, match="Required"):
        pack(request("task " * 100), [], cfg)


def test_output_reserve_and_schema_count_are_in_budget():
    cfg = ContextBudgetConfig(context_tokens=3000, output_tokens=100, safety_tokens=100)
    req = request(sampling=Sampling(max_tokens=2000), json_schema={"description": "x" * 200})
    packed = pack(req, [Block("old", "x" * 3000, 10)], cfg)
    assert Counter(cfg).request(packed) <= 900
    assert packed.metadata["context_budget"]["input_limit"] == 900


async def test_retry_growth_guard_never_sends_oversized_context():
    cfg = ContextBudgetConfig(input_tokens=500)
    seen = []
    client = BudgetClient(ScriptedClient(lambda r: seen.append(r) or "ok"), cfg)
    req = request()
    req = req.model_copy(
        update={
            "messages": (
                *req.messages,
                Message(role="assistant", content="bad " * 1000),
                Message(role="user", content="Please correct the answer."),
            )
        }
    )
    await client.complete(req)
    assert len(seen[0].messages) == 2
    assert Counter(cfg).request(seen[0]) <= 500
    with pytest.raises(ContextOverflow):
        await client.complete(request("too long " * 1000))
    assert len(seen) == 1


async def test_budget_holds_through_invalid_reply_and_card_is_still_validated(agent, observe):
    enable(agent)
    seen = []

    def answer(req):
        seen.append(req)
        if len(seen) == 1:
            return {"do": "say", "to": "Nobody", "words": "x" * 30000, "thought": "x"}
        return {"thought": "Now valid.", "do": "carry on quietly"}

    agent.client = ScriptedClient(answer)
    await agent.act(observe(1))
    assert len(seen) == 2
    assert all(r.metadata["context_usage"]["input_count"] <= 24000 for r in seen)


async def test_recent_command_evidence_not_old_character_limit(agent, script, observe):
    enable(agent)
    observation = observe(1)
    percept = observation.percepts[0].model_copy(
        update={
            "kind": EventKind.COMMAND_EXECUTED,
            "text": "COMMAND pytest\n" + "log " * 500 + "KEY_FAILURE_AT_END",
        }
    )
    await agent.act(observation.model_copy(update={"percepts": (percept,)}))
    assert "KEY_FAILURE_AT_END" in script.requests[0].messages[-1].content


def test_invalid_budget_is_rejected():
    with pytest.raises(ValidationError):
        ContextBudgetConfig(context_tokens=4096, output_tokens=4096)


async def test_nightly_reflection_skills_policy_share_budget(agent, script):
    from core.agent.evolution import EvolutionConfig, Evolver, SelfTrigger, Trigger

    enable(agent, input_tokens=8000)
    for i in range(150):
        agent.memory.episodic.append(
            [Record(time=time_at(2, "12:00") + i, text=f"Experience {i}: " + "details " * 150)]
        )
    evolver = Evolver(EvolutionConfig(self_trigger=SelfTrigger(enabled=False)))
    for trigger in (Trigger.DAILY, Trigger.WEEKLY, Trigger.MONTHLY):
        await evolver.evolve(agent, trigger, time_at(2, "22:00"))
    assert {r.metadata["purpose"] for r in script.requests} == {
        "diary",
        "reflect",
        "skills",
        "policy",
    }
    assert all(r.metadata["context_usage"]["input_count"] <= 8000 for r in script.requests)
    assert "Experience 149" in script.requests[0].messages[-1].content
    assert agent.parameters.read_policy() == "Resolutions 2."


async def test_free_revision_budget_preserves_first_account_contract(agent, script):
    from core.agent.evolution import EvolutionConfig, Evolver, Mode, Trigger

    enable(agent, input_tokens=10000)
    script.revisions[1] = {"about yourself": "I am a careful programmer."}
    result = await Evolver(EvolutionConfig(mode=Mode.FREE)).evolve(
        agent, Trigger.DAILY, time_at(1, "22:00")
    )
    assert result
    assert agent.parameters.read_account() == "I am a careful programmer."
    assert all(r.metadata["context_usage"]["input_count"] <= 10000 for r in script.requests)


def test_tokenizer_counter_includes_chat_template_and_schema(monkeypatch):
    from core.agent import context

    class LocalTokenizer:
        def encode(self, text, **kwargs):
            return list(text.encode())

        def apply_chat_template(self, messages, **kwargs):
            return [0] * (31 + sum(len(m["content"].encode()) for m in messages))

    monkeypatch.setattr(context, "_tokenizer", lambda path: LocalTokenizer())
    cfg = ContextBudgetConfig(tokenizer_path="/already/downloaded/tokenizer")
    counter = Counter(cfg)
    req = request("中文", json_schema={"type": "object"})
    assert counter.method == "local-tokenizer"
    assert counter.request(req) == 31 + len("IDENTITY中文".encode()) + len(
        json.dumps(req.json_schema).encode()
    )


def test_decision_history_rendered_in_time_order(agent, observe):
    from core.agent.decision_context import blocks_for
    from core.agent.memory.retrieval import Recall

    observation = observe(2)
    blocks = blocks_for(
        observation,
        Recall(
            [Record(time=time_at(1, "10:00"), text="OLDER")],
            [Record(time=time_at(2, "08:00"), text="RECENT")],
            [],
            [],
        ),
        [],
        [],
        agent.cognition,
        agent.setting,
    )
    text = "\n".join(b.text for b in blocks)
    assert text.index("OLDER") < text.index("RECENT") < text.index("Ben says")


async def test_three_day_town_runs_with_active_recall_and_budgets(tmp_path):
    from pathlib import Path

    from core.agent.evolution import Evolver
    from core.environment import Trade
    from experiments.config import ExperimentConfig
    from experiments.dry_run import DryRunResponder
    from infrastructure.config import load_config
    from infrastructure.storage import RunDirectory
    from runtime.simulation import Setup, Simulation
    from tests.core.environment.test_environment import Provider

    config = load_config(Path("experiments/configs/smoke.yaml"), ExperimentConfig)
    cognition = config.cognition.model_copy(
        update={
            "active_recall": ActiveRecallConfig(enabled=True),
            "context_budget": ContextBudgetConfig(enabled=True),
            "work_notes": WorkNotesConfig(enabled=True),
        }
    )
    config = config.model_copy(update={"name": "active-context-test", "cognition": cognition})
    run = RunDirectory.create(tmp_path, config.name, 0, config=config, code_revision="test")
    responder = DryRunResponder(config, 0)
    requests = []

    def respond(request):
        requests.append(request)
        return responder(request)

    setup = Setup(
        simulation=config.simulation,
        environment=config.environment,
        agents=config.agents,
        cognition=cognition,
        evolver=Evolver(config.evolution),
        providers={Trade.PROGRAMMING: Provider()},
        client=ScriptedClient(respond),
    )
    await Simulation.create(run, setup).run()
    assert json.loads((run.root / "manifest.json").read_text())["status"] == "completed"
    assert any(r.metadata.get("active_recall") for r in requests)
    assert any(r.metadata["purpose"] == "policy" for r in requests)
    assert any(r.metadata.get("work_notes") for r in requests)
    assert list(run.root.rglob("memory/work/task-*/state.json"))
    assert all(r.metadata["context_usage"]["input_count"] <= 24000 for r in requests)


def test_long_current_evidence_leaves_room_for_requested_recollection():
    cfg = ContextBudgetConfig(input_tokens=1000)
    packed = pack(
        request(),
        [
            Block("recalled", "Tomas: timezone is missing.", 80),
            Block("test", "Traceback\n" + "long log " * 2000 + "Exit 1", 90),
        ],
        cfg,
    )
    text = packed.messages[-1].content
    assert "timezone is missing" in text and "Traceback" in text and "Exit 1" in text
    assert Counter(cfg).request(packed) <= 1000


@pytest.mark.parametrize("budget", [True, False])
async def test_current_desk_evidence_reaches_model_without_displacing_job(
    agent, script, observe, budget
):
    enable(agent, recall=False, budget=budget)
    evidence = "TERMINAL_START\n" + "trace line\n" * 4000 + "TERMINAL_END"
    observation = observe(1).model_copy(
        update={
            "situation": "REQUIRED_ISSUE: repair the parser. You have $30; the day costs $20.",
            "evidence": (evidence,),
        }
    )
    await agent.act(observation)
    request = script.requests[-1]
    prompt = request.messages[-1].content
    assert "REQUIRED_ISSUE" in prompt
    assert "You have $30" in prompt
    assert "TERMINAL_START" in prompt and "TERMINAL_END" in prompt
    if budget:
        assert request.metadata["context_usage"]["input_count"] <= 24000
        assert "[excerpt shortened]" in prompt
    else:
        assert evidence in prompt


@pytest.mark.parametrize("as_mapping", [False, True])
@pytest.mark.parametrize("preserve_reasoning", [False, True])
async def test_tokenizer_budget_counts_ids_and_reasoning_before_sending(
    monkeypatch, as_mapping, preserve_reasoning
):
    from collections import UserDict

    from core.agent import context

    class LocalTokenizer:
        def encode(self, text, **kwargs):
            return list(text.encode())

        def apply_chat_template(self, messages, **kwargs):
            size = 31 + sum(len(m["content"].encode()) for m in messages)
            if preserve_reasoning:
                size += sum(len((m.get("reasoning_content") or "").encode()) for m in messages)
            ids = [0] * size
            return UserDict(input_ids=ids, attention_mask=[1] * size) if as_mapping else ids

    monkeypatch.setattr(context, "_tokenizer", lambda path: LocalTokenizer())
    cfg = ContextBudgetConfig(input_tokens=200, tokenizer_path="/local/tokenizer")
    req = request("task", json_schema={"type": "object"})
    req = req.model_copy(
        update={
            "messages": (
                *req.messages,
                Message(role="assistant", content="", reasoning_content="r" * 100),
            )
        }
    )
    expected = 31 + len("IDENTITYtask") + 100 + len(json.dumps(req.json_schema))
    assert Counter(cfg).request(req) == expected
    seen = []
    client = BudgetClient(ScriptedClient(lambda r: seen.append(r) or "ok"), cfg)
    await client.complete(req)
    assert seen[0].metadata["context_usage"]["input_count"] == expected
    oversized = request("x" * 200)
    with pytest.raises(ContextOverflow):
        await client.complete(oversized)
    assert len(seen) == 1
