"""Conversation invitations report replies and visible alternatives without forcing a move."""

import asyncio

import pytest

from runtime.activities.model import ConversationActivity
from tests.runtime.activities import test_engine as base
from tests.runtime.activities.test_activity_context import invite
from tests.runtime.activities.test_open_local_chat import co_present, start
from tests.runtime.realtime import test_engine as realtime_tests
from tests.runtime.realtime.test_interruptions import Resident

engine = base.engine
rt = realtime_tests.rt


@pytest.fixture(params=["engine", "rt"])
def scheduler(request):
    return request.getfixturevalue(request.param)


def latest_notice(e, who):
    return next(
        event
        for event in reversed(base.events(e))
        if event["payload"].get("invitation_update_for") == who
    )


def assert_wait_woken(e, who):
    if hasattr(e, "running"):
        assert e.running[who].task.cancelling()
    else:
        assert who not in e.pending


@pytest.mark.parametrize("response", ["accept", "decline", "defer"])
async def test_conversation_owner_gets_reply_and_wait_wakes_immediately(scheduler, response):
    e = scheduler
    co_present(e)
    chat = start(e)
    invitation = invite(e)
    e.env.perceive("Mei")
    e.schedule("Mei", base.use("wait", seconds=600))
    await asyncio.sleep(0)
    args = {"invitation": invitation.id, "at": "08:30"}
    e.invitation_action("Tomas", response, args)
    assert e.current["Mei"] == chat.id
    assert_wait_woken(e, "Mei")
    assert not e.deferred_invitation_replies.get("Mei")
    notices = e.env.log.pending_events("Mei")
    assert any(p.payload.get("response") == response for p in notices)
    assert f"Tomas {response}:" in e.observation("Mei").situation
    assert latest_notice(e, "Mei")["payload"]["response"] == response
    if hasattr(e, "close_running"):
        await e.close_running()


async def test_invitation_reply_does_not_cancel_a_started_nonwait_tool(scheduler):
    e = scheduler
    co_present(e)
    start(e)
    invitation = invite(e)
    e.schedule("Mei", base.use("invite_here", people=["Aisha"]))
    await asyncio.sleep(0)
    operation = getattr(e, "running", e.pending)["Mei"]
    e.invitation_action("Tomas", "accept", {"invitation": invitation.id})
    assert getattr(e, "running", e.pending)["Mei"] is operation
    if hasattr(operation, "task"):
        assert not operation.task.cancelling()
    if hasattr(e, "close_running"):
        await e.close_running()


@pytest.mark.parametrize("access", ["public", "invited", "private", "remote"])
def test_other_conversation_details_follow_existing_access_rules(scheduler, access):
    e = scheduler
    co_present(e)
    chat = start(e)
    other = base.conversation(e, people=("Tomas", "Aisha"), public=access != "private")
    other.topic = "Visible alternative" if access in ("public", "invited") else "Hidden topic"
    if access == "invited":
        other.public = False
        other.invited = (*other.invited, "Mei")
    if access == "remote":
        other.place = "library"
        for person in other.participants:
            e.env.move(person, "library", time=e.now // 60)
    sent = e.invitation_action("Mei", "invite_here", {"people": ["Tomas"]})
    context = "\n".join(e.conversation_context("Mei", chat))
    visible = access in ("public", "invited")
    assert (f"visible conversation {other.id}" in context) == visible
    assert (other.topic in context) == visible
    if visible:
        assert "members: Tomas, Aisha" in context
        assert f"visible conversation {other.id}" in e.observation("Mei").situation
    else:
        assert not any(
            event["payload"].get("visible_conversation") == other.id and "Mei" in event["audience"]
            for event in base.events(e)
        )
    e.invitation_action("Tomas", "decline", {"invitation": sent["invitation"]})
    assert e.invitations[sent["invitation"]].status == "cancelled"
    context = "\n".join(e.conversation_context("Mei", chat))
    assert "Tomas: declined" in context
    assert "awaiting response" not in context


async def test_visible_invitee_join_and_leave_wake_wait_without_switching_owner(scheduler):
    e = scheduler
    co_present(e)
    chat = start(e)
    e.invitation_action("Mei", "invite_here", {"people": ["Tomas"]})
    e.schedule("Mei", base.use("wait", seconds=600))
    await asyncio.sleep(0)
    e.select("Tomas", base.choose("start_chat", topic="Another public conversation"))
    other = e.activities[e.current["Tomas"]]
    assert isinstance(other, ConversationActivity)
    assert_wait_woken(e, "Mei")
    assert latest_notice(e, "Mei")["payload"]["visible_conversation"] == other.id
    assert f"currently in visible conversation {other.id}" in e.observation("Mei").situation
    if hasattr(e, "close_running"):
        await e.close_running()
    e.schedule("Mei", base.use("wait", seconds=600))
    await asyncio.sleep(0)
    e.leave("Tomas", "Done")
    assert_wait_woken(e, "Mei")
    assert e.current["Mei"] == chat.id
    assert "left conversation" in latest_notice(e, "Mei")["text"]
    assert "currently in visible conversation" not in "\n".join(e.conversation_context("Mei", chat))
    if hasattr(e, "close_running"):
        await e.close_running()


async def test_invitation_reply_refreshes_realtime_intent_with_explicit_cause(rt):
    co_present(rt)
    start(rt)
    invitation = invite(rt)
    resident = Resident(asyncio.Event())
    rt.sim.agents["Mei"] = resident
    rt.start_decision("Mei")
    await asyncio.sleep(0)
    job = rt.running["Mei"]
    rt.invitation_action("Tomas", "accept", {"invitation": invitation.id})
    assert job.invalidated
    assert job.causes[-1]["changed_fields"] == ["invitation_status"]
    await rt.refresh_decisions()
    await asyncio.sleep(0)
    assert rt.running["Mei"] is not job
    assert "Tomas accept:" in resident.observations[-1].situation
    await rt.close_running()


async def test_invitation_reply_does_not_interrupt_realtime_reply_body(rt):
    base.conversation(rt)
    sent = rt.invitation_action("Tomas", "invite_here", {"people": ["Aisha"]})
    gate = asyncio.Event()
    resident = Resident(gate, body=True)
    rt.sim.agents["Tomas"] = resident
    rt.start_decision("Tomas")
    await realtime_tests.finish(rt, "Tomas")
    await asyncio.sleep(0)
    job = rt.running["Tomas"]
    assert job.targets
    rt.invitation_action("Aisha", "decline", {"invitation": sent["invitation"]})
    assert not job.invalidated and not job.task.cancelling()
    assert job.received_invitation_update
    gate.set()
    await realtime_tests.finish(rt, "Tomas")
    assert rt.running["Tomas"].received_invitation_update
    await realtime_tests.finish(rt, "Tomas")
    assert "Tomas" not in rt.running, "the pending invitation reply must skip automatic wait"
    assert rt.activities[rt.current["Tomas"]].messages[-1].text == "Body accepted"
    assert "Aisha decline:" in rt.observation("Tomas").situation
    assert "Aisha: declined" in rt.observation("Tomas").situation
    await rt.close_running()


async def test_confirmed_invitee_join_wakes_owner_still_waiting_in_target_conversation(scheduler):
    e = scheduler
    co_present(e)
    chat = start(e)
    sent = e.invitation_action("Mei", "invite_here", {"people": ["Tomas"]})
    e.invitation_action("Tomas", "accept", {"invitation": sent["invitation"]})
    e.schedule("Mei", base.use("wait", seconds=600))
    await asyncio.sleep(0)
    e.start_ready_conversations()
    assert e.current["Tomas"] == chat.id
    assert_wait_woken(e, "Mei")
    assert "Current conversation members: Mei, Tomas." in e.observation("Mei").situation
    if hasattr(e, "close_running"):
        await e.close_running()
