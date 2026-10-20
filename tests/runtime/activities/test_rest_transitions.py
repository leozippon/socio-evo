"""Waiting uses a resident's reusable Rest activity, including direct activity exits."""

import json

import pytest

from core.environment.rejection import Rejected
from core.interaction import Card
from runtime.activities.engine import ActivityEngine
from runtime.activities.model import RestActivity, at
from runtime.realtime.engine import RealtimeEngine
from tests.runtime.activities import test_engine as base
from tests.runtime.activities.test_engine import choose, conversation, use, work
from tests.runtime.realtime.test_engine import finish

engine = base.engine


@pytest.fixture(params=[ActivityEngine, RealtimeEngine])
def scheduler(engine, request):
    result = request.param(engine.sim)
    result.now, result.end = at(1, "07:00"), at(1, "22:00")
    return result


def rest(scheduler, who="Mei", until="08:00", **kwargs):
    scheduler.schedule(
        who,
        choose(
            "select_rest",
            arguments={
                "day": "today",
                "until": until,
                "wake": True,
                **kwargs,
            },
        ),
    )


@pytest.mark.parametrize("kind", ["work", "conversation"])
def test_activity_card_can_switch_directly_to_rest(scheduler, kind):
    active = work(scheduler) if kind == "work" else conversation(scheduler)
    card = Card(scheduler.observation("Mei").allowed)
    reply = card.model.model_validate(
        {
            **(
                {}
                if isinstance(scheduler, RealtimeEngine) and kind == "conversation"
                else {"thought": "Wait here"}
            ),
            "do": "rest",
            "day": "today",
            "until": "08:00",
            "wake for invitations": True,
        }
    )
    scheduler.schedule("Mei", card.decision(reply).action)
    current = scheduler.activities[scheduler.current["Mei"]]
    assert isinstance(current, RestActivity)
    assert current.members["Mei"].end == at(1, "08:00")
    assert not active.members["Mei"].active
    rows = base.events(scheduler)
    assert any(r["kind"] == "activity_left" and r["payload"]["activity"] == active.id for r in rows)
    assert not any(
        r["actor"] == "Mei" and r["payload"].get("phase") == "choosing_next_activity" for r in rows
    )


def test_expired_rest_does_not_exit_work(scheduler):
    active = work(scheduler)
    with pytest.raises(Rejected, match="has passed"):
        rest(scheduler, until="06:59")
    assert scheduler.current["Mei"] == active.id
    assert active.members["Mei"].active
    assert not scheduler.rest_requests


async def test_rest_reuses_instance_resets_state_and_ignores_old_end_timer(scheduler):
    rest(scheduler, until="08:00", wake=False)
    first = scheduler.activities[scheduler.current["Mei"]]
    first.waiting_for = "old-invitation"
    first.feedback["Mei"] = ["old feedback"]
    first.result["Mei"] = "old result"
    scheduler.now = at(1, "07:01")
    scheduler.leave("Mei", "Choose again")
    rest(scheduler, until="09:00", wake=True)
    current = scheduler.activities[scheduler.current["Mei"]]
    assert current is first
    assert current.start == at(1, "07:01")
    assert current.latest_end == at(1, "09:00")
    assert current.members["Mei"].start == scheduler.now
    assert current.waiting_for is None
    assert current.feedback == current.result == {}
    assert current.wake_invitations is True
    scheduler.now = at(1, "08:00")
    for event in scheduler.queue.pop_at(scheduler.now):
        await scheduler.process(event)
    assert scheduler.current["Mei"] == first.id
    entered = [
        r
        for r in base.events(scheduler)
        if r["kind"] == "activity_entered" and r["payload"]["activity"] == first.id
    ]
    assert len(entered) == 2
    assert entered[0]["payload"]["start"] != entered[1]["payload"]["start"]
    state = json.loads(json.dumps(scheduler.state()))
    restored = type(scheduler)(scheduler.sim, state)
    restored.prepare_day(1440 + 7 * 60)
    rest(restored, until="08:00")
    assert restored.current["Mei"] == first.id


async def test_rest_transition_keeps_claim_and_private_workspace(scheduler):
    active = work(scheduler)
    scheduler.schedule("Mei", use("claim", job="task-1", partner=None))
    if isinstance(scheduler, RealtimeEngine):
        await finish(scheduler, "Mei")
    else:
        await base.complete(scheduler, scheduler.pending["Mei"].end)
    claim = scheduler.env.board.claim_of("Mei")
    active.history.append({"repair": "preserved"})
    rest(scheduler)
    assert scheduler.env.board.claim_of("Mei") == claim
    assert active.history == [{"repair": "preserved"}]
    assert active.status == "paused"


@pytest.mark.parametrize("crosses_closing", [False, True])
async def test_conversation_rest_waits_for_started_speech_before_transition(
    engine, crosses_closing
):
    rt = RealtimeEngine(engine.sim)
    rt.now, rt.end = at(1, "08:00"), at(1, "22:00")
    rt.clock.rebase(rt.now)
    active = conversation(rt)
    rt.schedule("Mei", use("reply", text="Finish this speech"))
    if crosses_closing:
        rt.now = at(1, "21:59")
        rt.clock.rebase(rt.now)
    rest(
        rt,
        who="Tomas",
        until="07:45" if crosses_closing else "09:00",
        day="tomorrow" if crosses_closing else "today",
    )
    assert rt.current["Tomas"] == active.id
    assert "Tomas" in rt.rest_requests
    assert not any(
        r["kind"] == "activity_entered"
        and r["payload"].get("activity_type") == "rest"
        and r["actor"] == "Tomas"
        for r in base.events(rt)
    )
    await finish(rt, "Mei")
    if crosses_closing:
        rt.now = at(1, "22:01")
    rt.flush_leaves()
    if crosses_closing:
        assert "Tomas" not in rt.current
        assert rt.rest_intents["Tomas"]["until"] == at(2, "07:45")
        rt.prepare_day(1440 + 7 * 60)
    assert isinstance(rt.activities[rt.current["Tomas"]], RestActivity)
    assert "Tomas" not in rt.rest_requests
    rows = base.events(rt)
    speech = next(r["seq"] for r in rows if r["kind"] == "speech")
    rested = next(
        r["seq"]
        for r in rows
        if r["kind"] == "activity_entered"
        and r["actor"] == "Tomas"
        and r["payload"].get("activity_type") == "rest"
    )
    assert speech < rested
