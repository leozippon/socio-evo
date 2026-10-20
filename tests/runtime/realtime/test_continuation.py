# ruff: noqa: F811
"""Interruptions through the actual scheduler and agent streaming path."""

import asyncio
import json
from pathlib import Path

import pytest

from core.agent import Agent
from experiments.config import ExperimentConfig
from infrastructure.config import load_config
from infrastructure.llm import LLMResponse
from tests.runtime.activities.test_engine import conversation
from tests.runtime.realtime.test_engine import engine, rt  # noqa: F401


async def until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), 2)


@pytest.mark.parametrize("retry", [None, "truncated", "invalid"])
@pytest.mark.parametrize("late_result", [False, True, "invalid"])
@pytest.mark.parametrize("change", ["speech", "membership"])
async def test_driver_restarts_latest_observation_after_stream_cleanup(
    rt, tmp_path, monkeypatch, late_result, change, retry
):
    started, cancelled, cleanup, resumed, final = (asyncio.Event() for _ in range(5))
    requests = []

    class Client:
        async def complete_stream(self, request, partial):
            requests.append(request)
            if len(requests) == 1:
                partial.text = '{"thought":"unfinished'
                partial.reasoning = "draft reasoning"
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    await cleanup.wait()
                    if not late_result:
                        raise
                    if late_result == "invalid":
                        return LLMResponse(text="invalid old action", latency=1)
                    return LLMResponse(
                        text=json.dumps(
                            {"thought": "obsolete", "do": "reply", "text": "Stale answer"}
                        ),
                        latency=1,
                    )
            if len(requests) == 2:
                resumed.set()
                await final.wait()
                if retry:
                    return LLMResponse(
                        text="" if retry == "truncated" else "invalid new action",
                        reasoning="resumed draft",
                        truncated=retry == "truncated",
                        latency=1,
                    )
            if len(requests) == (3 if retry else 2):
                return LLMResponse(
                    text=json.dumps({"thought": "latest", "do": "reply", "text": "Current answer"}),
                    latency=1,
                )
            await asyncio.Event().wait()

    config = load_config(Path("experiments/configs/community/realtime.yaml"), ExperimentConfig)
    seed = next(a for a in config.agents if a.profile.name == "Tomas")
    listener = Agent.create(
        tmp_path / "Tomas", seed, Client(), config.cognition, config.environment.setting
    )
    activity = conversation(rt)
    # A third resident can leave without ending the conversation.
    rt.enter(activity, "Aisha", rt.end)
    rt.sim.agents = {"Tomas": listener}
    monkeypatch.setattr(rt, "prepare_day", lambda start: None)
    driver = asyncio.create_task(rt.run(rt.now // 60))
    try:
        await asyncio.wait_for(started.wait(), 2)
        logical_start = rt.running["Tomas"].start
        rt.wall.value += 4
        rt.now = rt.clock.now()
        # Plain time and somebody else's private bookkeeping do not restart.
        rt.emit("tool_started", "Private operation", actor="Aisha", audience=["Aisha"])
        await asyncio.sleep(0.04)
        assert len(requests) == 1
        if change == "speech":
            rt.speak("Mei", "New evidence", activity)
        else:
            rt.leave("Aisha", "Going home")
        await asyncio.wait_for(cancelled.wait(), 2)
        if change == "speech":
            rt.speak("Mei", "Newest evidence", activity)
            rt.leave("Aisha", "Going home")
        assert len(requests) == 1  # The previous stream must finish cleanup first.
        cleanup.set()
        await asyncio.wait_for(resumed.wait(), 2)
        assert rt.running["Tomas"].start == logical_start
        history = requests[1].messages
        if late_result:
            expected = "invalid old action" if late_result == "invalid" else "obsolete"
            assert any(expected in m.content for m in history)
        else:
            assert all(m.reasoning_content is None for m in history)
            assert any("unfinished" in m.content for m in history)
        latest = history[-1].content
        if change == "speech":
            assert "New evidence" in latest and "Newest evidence" in latest
        assert '"participants": ["Mei", "Tomas"]' in latest
        final.set()
        await until(lambda: any(m.text == "Current answer" for m in activity.messages))
        if retry:
            retried = requests[2]
            assert (
                sum('"participants": ["Mei", "Tomas"]' in m.content for m in retried.messages) >= 1
            )
            assert sum(m.role == "assistant" for m in retried.messages) == 1
            assert all(m.reasoning_content is None for m in retried.messages)
            assert retried.after_invalid is (retry == "invalid")
            if retry == "invalid":
                assert "could not be read" in retried.messages[-1].content.lower()
        assert sum(m.text == "Current answer" for m in activity.messages) == 1
        assert not any(m.text == "Stale answer" for m in activity.messages)
        rows = [json.loads(line) for line in rt.env.log.path.read_text().splitlines()]
        assert not any(
            r["kind"] == "tool_started"
            and r["actor"] == "Tomas"
            and r["payload"].get("tool") == "wait"
            for r in rows
        )
        records = listener.memory.episodic.read()
        assert [r.time for r in records] == sorted(r.time for r in records)
        assert not any("obsolete" in r.text for r in records)
        assert sum("latest" in r.text for r in records) == 1
    finally:
        cleanup.set()
        driver.cancel()
        await asyncio.gather(driver, return_exceptions=True)


async def test_completed_wait_decision_is_discarded_if_speech_arrives_before_acceptance(rt):
    from core.interaction import Decision
    from tests.runtime.activities.test_engine import use
    from tests.runtime.realtime.test_engine import finish

    activity = conversation(rt)
    observations = []

    class Listener:
        async def choose_tool(self, observation):
            observations.append(observation)
            return Decision(
                thought="Listen" if len(observations) == 1 else "Answer",
                action=use("wait", seconds=300)
                if len(observations) == 1
                else use("reply", text="Heard it"),
            )

    rt.sim.agents["Tomas"] = Listener()
    rt.start_decision("Tomas")
    await rt.running["Tomas"].task
    rt.speak("Mei", "Arrived just before the wait was accepted", activity)
    await finish(rt, "Tomas")
    await finish(rt, "Tomas")
    await finish(rt, "Tomas")
    assert len(observations) == 2
    assert any("just before" in p.text for p in observations[-1].percepts)
    assert sum(m.text == "Heard it" for m in activity.messages) == 1
    rows = [json.loads(line) for line in rt.env.log.path.read_text().splitlines()]
    assert not any(
        r["kind"] == "tool_started" and r["actor"] == "Tomas" and r["payload"].get("tool") == "wait"
        for r in rows
    )


async def test_cancel_before_first_task_turn_keeps_unconsumed_speech(rt):
    from core.interaction import Decision
    from tests.runtime.activities.test_engine import use
    from tests.runtime.realtime.test_engine import finish

    activity = conversation(rt)
    seen = []

    class Listener:
        async def choose_tool(self, observation):
            seen.extend(p.text for p in observation.percepts)
            return Decision(thought="Answer", action=use("reply", text="Both heard"))

    rt.sim.agents["Tomas"] = Listener()
    rt.speak("Mei", "First message", activity)
    rt.start_decision("Tomas")
    rt.speak("Mei", "Second message", activity)
    await rt.refresh_decisions()
    await finish(rt, "Tomas")
    await finish(rt, "Tomas")
    assert any("First message" in text for text in seen)
    assert any("Second message" in text for text in seen)
