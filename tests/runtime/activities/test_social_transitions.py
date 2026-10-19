"""Closing frees activity choice; invitation replies preserve explicit consent."""

import pytest
from pydantic import ValidationError

from core.environment.rejection import Rejected
from core.interaction import Card
from runtime.activities.model import Invitation, at
from tests.runtime.activities import test_engine as base
from tests.runtime.activities.test_activity_context import invite
from tests.runtime.realtime.test_engine import rt as rt

engine = base.engine


@pytest.fixture(params=["engine", "rt"])
def scheduler(request):
    return request.getfixturevalue(request.param)


@pytest.mark.parametrize("closing", ["12:00", "18:00"])
def test_coding_closes_without_evicting_residents(scheduler, closing):
    e = scheduler
    e.now = at(1, "11:55" if closing == "12:00" else "17:55")
    old = base.work(e)
    e.now = at(1, closing)
    e.boundary()
    assert old.status == "paused"
    assert "Mei" not in e.current
    assert e.env.world.locations["Mei"] == "workshop"
    assert "Mei" not in e.outside
    count = e.env.log.count
    e.boundary()
    assert e.env.log.count == count, "closing is idempotent for a resident inside"
    assert not e.can_code("Mei")
    e.select(
        "Mei",
        base.choose("select_rest", arguments={"until": "14:00" if closing == "12:00" else "20:00"}),
    )
    e.leave("Mei", "Go somewhere open instead")
    # Residents can choose any permitted open venue, without a forced homeward trip.
    destination = next(
        p.id
        for p in e.env.world.places.values()
        if p.kind.value != "home" and p.id != "workshop" and p.is_open(closing)
    )
    e.select("Mei", base.choose("select_move", target=destination))
    assert e.activities[e.current["Mei"]].destination == destination


def test_rest_inside_is_not_interrupted_when_code_hours_resume(scheduler):
    e = scheduler
    base.work(e)
    e.now = at(1, "12:00")
    e.boundary()
    e.select("Mei", base.choose("select_rest", arguments={"until": "15:00"}))
    e.now = at(1, "14:00")
    e.boundary()
    assert "Mei" not in e.outside and "Mei" in e.current
    assert e.env.world.locations["Mei"] == "workshop"


def test_day_end_returns_outside_and_open_venue_residents_home(scheduler):
    e = scheduler
    base.work(e)
    e.now = at(1, "18:00")
    e.boundary()
    e.now = at(1, "22:00")
    e.boundary()
    assert e.env.world.locations["Mei"] == e.env.config.homes["Mei"]
    assert "Mei" not in e.outside and "Mei" not in e.current


def test_defer_is_counterproposal_requires_new_confirmation(scheduler):
    e = scheduler
    first = invite(e)
    e.invitation_action("Tomas", "accept", {"invitation": first.id})
    card = Card(e.observation("Tomas").allowed)
    parsed = card.model.model_validate(
        {
            "thought": "Need more time",
            "do": "defer invitation",
            "invitation": first.id,
            "at": "09:00",
        }
    )
    e.select("Tomas", card.decision(parsed).action)
    new = e.invitations[first.superseded_by]
    assert first.status == "cancelled"
    assert new.supersedes == first.id and new.confirmed == ["Tomas"]
    assert new.invited == ("Mei",) and new.start == at(1, "09:00")
    e.now = first.grace_end
    # Old expiry and appointment events cannot cancel/start the replacement.
    for event in e.queue.pop_at(e.now):
        assert event.data.get("invitation") != new.id
    e.start_ready_conversations()
    assert new.status == "pending"
    e.now = new.start
    e.start_ready_conversations()
    assert new.status == "pending", "earlier acceptance is not consent to the new time"
    e.invitation_action("Mei", "accept", {"invitation": new.id})
    e.start_ready_conversations()
    assert new.status == "started"
    assert set(e.activities[new.conversation].participants) == {"Mei", "Tomas"}
    assert Invitation.model_validate(new.model_dump()).supersedes == first.id


def test_decline_keeps_history_and_notifies_declining_resident(scheduler):
    e = scheduler
    first = invite(e)
    e.invitation_action("Tomas", "decline", {"invitation": first.id})
    assert first.status == "cancelled" and first.declined == ["Tomas"]
    assert "Tomas" in first.invited
    assert first.id not in e.invitation_ids("Tomas")
    event = base.events(e)[-1]
    assert event["payload"]["response"] == "decline"
    assert "Tomas" in event["audience"] and "Mei" in event["audience"]
    e.start_ready_conversations()
    assert not first.conversation


@pytest.mark.parametrize("when", ["08:05", "08:10", "22:00"])
def test_invalid_defer_does_not_destroy_original(scheduler, when):
    e = scheduler
    first = invite(e)
    with pytest.raises(Rejected):
        e.invitation_action("Tomas", "defer", {"invitation": first.id, "at": when})
    assert first.status == "pending" and first.superseded_by is None
    assert len(e.invitations) == 1


def test_group_decline_does_not_cancel_other_members(scheduler):
    e = scheduler
    first = invite(e)
    first.invited = ("Tomas", "Aisha")
    e.invitation_action("Tomas", "decline", {"invitation": first.id})
    assert first.status == "pending"
    assert e.invitation_views("Tomas")[0]["status"] == "declined"
    assert e.invitation_views("Mei")[0]["readiness"]["Tomas"] == "declined"
    e.env.move("Aisha", "workshop", time=e.now // 60)
    e.invitation_action("Aisha", "accept", {"invitation": first.id})
    e.now = first.start
    e.start_ready_conversations()
    assert set(e.activities[first.conversation].participants) == {"Mei", "Aisha"}


def test_invitation_responses_offered_in_work_and_prompts(scheduler):
    e = scheduler
    first = invite(e)
    base.work(e, "Tomas")
    card = Card(e.observation("Tomas").allowed)
    for name in ["accept", "decline", "defer"]:
        reply = {"thought": "Respond", "do": name + " invitation", "invitation": first.id}
        if name == "defer":
            reply["at"] = "09:00"
        assert card.decision(card.model.model_validate(reply)).action.tool == name
    assert "explicitly accept, decline" in e.observation("Tomas").situation
    assert "Defer proposes a later time" in e.activity_help("Tomas")
    with pytest.raises(ValidationError):
        card.model.model_validate(
            {"thought": "No time", "do": "defer invitation", "invitation": first.id}
        )


async def test_superseded_expiry_does_not_expire_new_appointment(scheduler):
    e = scheduler
    old = invite(e)
    e.invitation_action("Tomas", "defer", {"invitation": old.id, "at": "09:00"})
    new = e.invitations[old.superseded_by]
    e.now = old.grace_end
    for scheduled in e.queue.pop_at(e.now):
        await e.process(scheduled)
    assert new.status == "pending"
    assert old.status == "cancelled"


def test_invitation_access_and_legacy_checkpoint_defaults(scheduler):
    e = scheduler
    invitation = invite(e)
    for tool in ("accept", "decline", "defer"):
        with pytest.raises(Rejected):
            e.invitation_action("Aisha", tool, {"invitation": invitation.id, "at": "09:00"})
        with pytest.raises(Rejected):
            e.invitation_action("Tomas", tool, {"invitation": "missing", "at": "09:00"})
    legacy = invitation.model_dump(exclude={"declined", "supersedes", "superseded_by"})
    restored = Invitation.model_validate(legacy)
    assert not restored.declined and restored.superseded_by is None


def test_started_conversation_cannot_be_rescheduled(scheduler):
    e = scheduler
    invitation = invite(e, None)
    e.invitation_action("Tomas", "accept", {"invitation": invitation.id})
    e.start_ready_conversations()
    with pytest.raises(Rejected):
        e.invitation_action("Tomas", "defer", {"invitation": invitation.id, "at": "09:00"})
    assert invitation.status == "started"


def test_lunch_appointment_inside_workplace_is_allowed(scheduler):
    e = scheduler
    first = invite(e)
    e.invitation_action("Tomas", "defer", {"invitation": first.id, "at": "12:30"})
    assert e.invitations[first.superseded_by].start == at(1, "12:30")


@pytest.mark.parametrize("when", ["07:30", "12:30", "18:30"])
def test_preparation_session_stays_inside_but_has_no_repository_tools(scheduler, when):
    e = scheduler
    e.now = at(1, when)
    e.arrive("Mei", "workshop")
    e.select("Mei", base.choose("select_work", seconds=1800))
    current = e.current["Mei"]
    e.boundary()
    e.boundary()
    assert e.current["Mei"] == current and not e.outside
    assert not e.can_code("Mei")
    assert not {"command", "edit", "test", "submit"} & set(e.menu("Mei")["tools"])
