"""Local conversations need no invitation and preserve physical/access boundaries."""

import asyncio

import pytest

from core.interaction import Card, ClaimTask
from runtime.activities.model import ConversationActivity, RestActivity, at
from tests.runtime.activities import test_engine as base
from tests.runtime.realtime import test_engine as realtime_tests
from tests.runtime.realtime.test_engine import finish

engine = base.engine
rt = realtime_tests.rt


@pytest.fixture(params=["engine", "rt"])
def scheduler(request):
    return request.getfixturevalue(request.param)


def co_present(e):
    for who in ("Mei", "Tomas", "Aisha"):
        e.arrive(who, "workshop")


def start(e):
    card = Card(e.observation("Mei").allowed)
    reply = card.model.model_validate(
        {
            "thought": "Chat while waiting",
            "do": "start a local conversation",
            "topic": "How was your morning?",
        }
    )
    e.select("Mei", card.decision(reply).action)
    return e.activities[e.current["Mei"]]


def test_arriving_before_opening_does_not_select_rest(scheduler):
    e = scheduler
    e.now = at(1, "07:30")
    e.arrive("Mei", "workshop")
    assert "Mei" not in e.current and "Mei" not in e.outside
    assert not any(
        x["kind"] == "activity_entered"
        and x["payload"].get("activity_type") == "rest"
        and not x["payload"].get("phase")
        for x in base.events(e)
    )


@pytest.mark.parametrize("when", ["07:30", "08:00", "12:30", "18:30"])
def test_start_and_join_without_invitation_or_forced_membership(scheduler, when):
    e = scheduler
    e.now = at(1, when)
    co_present(e)
    chat = start(e)
    assert chat.public and chat.spontaneous and not chat.outside
    assert chat.participants == ("Mei",) and not e.invitations
    assert chat.id in e.menu("Tomas")["conversations"]
    card = Card(e.observation("Tomas").allowed)
    reply = {"thought": "Join freely", "do": "join conversation", "conversation": chat.id}
    if not e.menu("Tomas").get("realtime"):
        reply["minutes"] = 10
    e.select("Tomas", card.decision(card.model.model_validate(reply)).action)
    assert set(chat.participants) == {"Mei", "Tomas"} and "Aisha" not in e.current
    assert chat.had_company
    e.leave("Tomas", "Done")
    assert chat.status == "ended" and "Mei" not in e.current


def test_resting_listener_wakes_to_choose_and_can_decline(scheduler):
    e = scheduler
    co_present(e)
    e.select("Tomas", base.choose("select_rest", arguments={"until": "10:00", "wake": True}))
    e.select("Aisha", base.choose("select_rest", arguments={"until": "10:00", "wake": False}))
    chat = start(e)
    e.wake_rests()
    assert "Tomas" not in e.current
    assert isinstance(e.activities[e.current["Aisha"]], RestActivity)
    # Considering the opportunity never silently makes a resident a participant.
    assert chat.participants == ("Mei",)
    e.select("Tomas", base.choose("select_rest", arguments={"until": "10:00", "wake": True}))
    e.wake_rests()
    assert isinstance(e.activities[e.current["Tomas"]], RestActivity), (
        "same announcement cannot wake repeatedly"
    )


def test_working_listener_is_not_interrupted(scheduler):
    e = scheduler
    co_present(e)
    working = base.work(e, "Tomas")
    chat = start(e)
    e.wake_rests()
    assert e.current["Tomas"] == working.id and "Tomas" not in chat.participants
    assert chat.id in [
        a.id
        for a in e.activities.values()
        if isinstance(a, ConversationActivity) and e.conversation_access("Tomas", a)
    ]
    e.leave("Tomas", "Finish work before joining")
    e.select("Tomas", base.choose("select_conversation", target=chat.id, seconds=600))
    assert "Tomas" in chat.participants


def test_early_chat_continues_at_eight_and_code_permission_opens(scheduler):
    e = scheduler
    e.now = at(1, "07:30")
    co_present(e)
    chat = start(e)
    e.select("Tomas", base.choose("select_conversation", target=chat.id, seconds=3600))
    assert not e.can_code("Mei")
    e.now = at(1, "08:00")
    e.boundary()
    assert not e.outside and not chat.outside
    assert e.can_code("Mei") and e.current["Mei"] == chat.id
    assert "command" not in e.menu("Mei")["tools"], "coding still requires switching to Work"


def test_old_workplace_doorstep_checkpoint_migrates_to_indoor(scheduler):
    e = scheduler
    e.now = at(1, "07:30")
    co_present(e)
    chat = start(e)
    state = e.state()
    state["outside"] = {"Mei": "workshop", "Tomas": "workshop"}
    state["activities"][chat.id]["outside"] = True
    restored = type(e)(e.sim, state=state)
    assert not restored.outside and not restored.activities[chat.id].outside


async def test_public_speech_reaches_listener_without_joining_or_interrupting_command(
    rt, monkeypatch
):
    co_present(rt)
    chat = start(rt)
    working = base.work(rt, "Tomas")
    await rt.env.execute(
        "Tomas",
        ClaimTask(task_id="task-1"),
        time=rt.now // 60,
        scene="activities",
        witnesses=["Tomas"],
    )
    gate = asyncio.Event()

    async def slow(*args):
        await gate.wait()
        return {"exit_code": 0, "output": "done"}

    monkeypatch.setattr(next(iter(rt.env.providers.values())), "run_command", slow)
    rt.schedule("Tomas", base.use("command", command="slow"))
    rt.speak("Mei", "Hello everyone here", chat)
    assert "Tomas" in rt.running and rt.current["Tomas"] == working.id
    assert "Tomas" not in chat.participants
    assert any("Hello everyone here" in p.text for p in rt.env.log.pending_events("Tomas"))
    assert set(chat.messages[-1].audience) == {"Mei", "Tomas", "Aisha"}
    gate.set()
    await finish(rt, "Tomas")
    await rt.close()


def test_indoor_chat_survives_noon_but_ends_at_day_end(scheduler):
    e = scheduler
    co_present(e)
    chat = start(e)
    e.now = at(1, "12:00")
    e.boundary()
    assert e.current["Mei"] == chat.id
    e.now = e.end
    e.boundary()
    assert "Mei" not in e.current and chat.status == "ended"


def test_public_chat_can_interrupt_waiting_for_a_different_appointment_to_offer_choice(scheduler):
    from tests.runtime.activities.test_activity_context import invite

    e = scheduler
    invitation = invite(e, None)
    e.invitation_action("Tomas", "accept", {"invitation": invitation.id})
    e.select(
        "Tomas", base.choose("select_rest", arguments={"invitation": invitation.id, "wake": True})
    )
    chat = start(e)
    e.wake_rests()
    assert "Tomas" not in e.current
    assert invitation.status == "pending" and chat.participants == ("Mei",)
