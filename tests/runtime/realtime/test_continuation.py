# ruff: noqa: F811
"""Two-phase replies through the real Agent, stream cleanup and scheduler."""

import asyncio
import json
from pathlib import Path

import pytest

from core.agent import Agent
from experiments.config import ExperimentConfig
from infrastructure.config import load_config
from infrastructure.llm import LLMResponse
from tests.runtime.activities.test_engine import conversation
from tests.runtime.realtime.test_engine import engine, finish, rt  # noqa: F401


async def until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), 2)


@pytest.mark.parametrize("retry", [None, "truncated", "invalid"])
@pytest.mark.parametrize("late_result", [False, True])
@pytest.mark.parametrize("change", ["speech", "target_left"])
async def test_body_restart_retains_draft_latest_scene_and_commits_once(
    rt, tmp_path, retry, late_result, change
):
    started, cancelled, cleanup, resumed, final = (asyncio.Event() for _ in range(5))
    requests = []
    body_calls = []

    class Client:
        async def complete_stream(self, request, partial):
            requests.append(request)
            if request.metadata["decision_phase"] == "intent":
                target = "Mei" if len(requests) == 1 else "Aisha"
                return LLMResponse(text=json.dumps({"do": "reply", "targets": [target]}), latency=0)
            body_calls.append(request)
            if len(body_calls) == 1:
                partial.text = '{"text":"unfinished'
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    await cleanup.wait()
                    if late_result:
                        return LLMResponse(text='{"text":"Stale answer"}', latency=0)
                    raise
            if len(body_calls) == 2:
                resumed.set()
                await final.wait()
                if retry:
                    return LLMResponse(
                        text="" if retry == "truncated" else "invalid body",
                        truncated=retry == "truncated",
                        latency=0,
                    )
            return LLMResponse(text='{"text":"Current answer"}', latency=0)

    config = load_config(Path("experiments/configs/community/realtime.yaml"), ExperimentConfig)
    seed = next(a for a in config.agents if a.profile.name == "Tomas")
    listener = Agent.create(
        tmp_path / "Tomas", seed, Client(), config.cognition, config.environment.setting
    )
    activity = conversation(rt)
    rt.enter(activity, "Aisha", rt.end)
    rt.sim.agents["Tomas"] = listener
    rt.start_decision("Tomas")
    await finish(rt, "Tomas")  # Intent selects a target; it must not speak or commit yet.
    await asyncio.wait_for(started.wait(), 2)
    logical_start = rt.running["Tomas"].start
    logical_id = rt.running["Tomas"].decision_id
    assert not activity.messages
    if change == "speech":
        rt.speak("Mei", "New evidence", activity)
    else:
        rt.leave("Mei", "Going home")
    refresh = asyncio.create_task(rt.refresh_decisions())
    try:
        await asyncio.wait_for(cancelled.wait(), 2)
        assert len(body_calls) == 1  # Cleanup precedes any replacement request.
        if change == "speech":
            rt.speak("Mei", "Newest evidence", activity)
        cleanup.set()
        await refresh
        if change == "target_left":
            await finish(rt, "Tomas")  # New intent chooses the remaining target.
        await asyncio.wait_for(resumed.wait(), 2)
        assert rt.running["Tomas"].start == logical_start
        assert rt.running["Tomas"].decision_id == logical_id
        history = body_calls[1].messages
        assert sum(m.role == "assistant" for m in history) == 1
        assert any(("Stale answer" if late_result else "unfinished") in m.content for m in history)
        assert all(m.reasoning_content is None for m in history)
        latest = history[-1].content
        if change == "speech":
            assert "New evidence" in latest and "Newest evidence" in latest
        else:
            assert '"participants": ["Tomas", "Aisha"]' in latest
        final.set()
        await finish(rt, "Tomas")
        if "Tomas" in rt.running:
            await finish(rt, "Tomas")
        assert sum(m.text == "Current answer" for m in activity.messages) == 1
        assert not any(m.text == "Stale answer" for m in activity.messages)
        assert '"thought"' not in json.dumps(requests[0].json_schema)
        for request in body_calls:
            assert set(request.json_schema["properties"]) == {"text"}
            usage = request.metadata["context_usage"]
            assert usage["input_count"] <= usage["input_limit"]
            assert request.sampling.max_tokens == 4096
            assert request.metadata["decision_id"] == logical_id
        if retry:
            assert len(body_calls) == 3
            assert body_calls[-1].after_invalid is (retry == "invalid")
        rows = [json.loads(line) for line in rt.env.log.path.read_text().splitlines()]
        cancelled_rows = [
            r for r in rows if r["kind"] == "tool_cancelled" and r["actor"] == "Tomas"
        ]
        assert len(cancelled_rows) == 1
        event_ids = cancelled_rows[0]["payload"]["event_ids"]
        cause_kind = "speech" if change == "speech" else "activity_left"
        assert all(rows[i]["kind"] == cause_kind for i in event_ids)
        if change == "speech":
            assert event_ids == [
                r["seq"] for r in rows if r["kind"] == "speech" and r["actor"] == "Mei"
            ]
        assert cancelled_rows[0]["payload"]["decision_id"] == logical_id
        assert cancelled_rows[0]["payload"]["mode"] == "resume"
        assert body_calls[0].metadata["request_id"] != body_calls[1].metadata["request_id"]
        assert cancelled_rows[0]["payload"]["request_id"] == body_calls[0].metadata["request_id"]
        records = listener.memory.episodic.read()
        assert sum("Current answer" in r.text for r in records if r.kind is None) == 1
    finally:
        cleanup.set()
        final.set()
        refresh.cancel()
        await asyncio.gather(refresh, return_exceptions=True)
        await rt.close_running()


async def test_body_finishing_after_day_close_keeps_memory_chronological(rt, tmp_path):
    started, release = asyncio.Event(), asyncio.Event()

    class Client:
        async def complete_stream(self, request, partial):
            if request.metadata["decision_phase"] == "intent":
                return LLMResponse(text='{"do":"reply","targets":["Mei"]}', latency=0)
            started.set()
            await release.wait()
            return LLMResponse(text='{"text":"Closing answer"}', latency=0)

    config = load_config(Path("experiments/configs/community/realtime.yaml"), ExperimentConfig)
    seed = next(a for a in config.agents if a.profile.name == "Tomas")
    listener = Agent.create(
        tmp_path / "Tomas", seed, Client(), config.cognition, config.environment.setting
    )
    activity = conversation(rt)
    rt.sim.agents["Tomas"] = listener
    rt.start_decision("Tomas")
    await finish(rt, "Tomas")
    await asyncio.wait_for(started.wait(), 2)
    # A started body drains through closing; it still must validate before committing.
    rt.now = rt.end + 60
    rt.clock.rebase(rt.now)
    rt.closing.add(activity.id)
    release.set()
    await finish(rt, "Tomas")
    records = listener.memory.episodic.read()
    assert [r.time for r in records] == sorted(r.time for r in records)
    assert sum("Closing answer" in r.text for r in records if r.kind is None) == 1
    assert sum(m.text == "Closing answer" for m in activity.messages) == 1
    assert "Tomas" not in rt.running
    await rt.close_running()
