"""Activity contracts, appointment readiness and authoritative time facts."""

import pytest
from pydantic import ValidationError

from core.interaction import Card
from runtime.activities.model import RestActivity, at
from tests.runtime.activities import test_engine as base

engine = base.engine


def invite(engine, at_time="08:10"):
    for who in ("Mei", "Tomas"):
        engine.env.move(who, "workshop", time=engine.now // 60)
    engine.invitation_action(
        "Mei",
        "invite",
        {
            "people": ["Tomas"],
            "place": "the Workshop",
            "at": at_time,
            "minutes": 20,
            "topic": "Review the repair",
            "public": False,
        },
    )
    return next(iter(engine.invitations.values()))


def test_confirmation_is_visible_but_accept_is_no_longer_offered(engine):
    invitation = invite(engine)
    assert engine.invitation_views("Tomas")[0]["status"] == "awaiting_response"
    engine.invitation_action("Tomas", "accept", {"invitation": invitation.id})
    view = engine.invitation_views("Tomas")[0]
    assert view["status"] == "confirmed_waiting" and view["your_confirmed"]
    assert "Tomas" in view["confirmed"]
    assert view["start_clock"] == "08:10:00" and "depart_by" in view
    card = Card(engine.observation("Tomas").allowed)
    with pytest.raises(ValidationError):
        card.model.model_validate(
            {"thought": "Again", "do": "accept invitation", "invitation": invitation.id}
        )
    card.model.model_validate(
        {"thought": "Cancel", "do": "decline invitation", "invitation": invitation.id}
    )
    before = engine.env.log.count
    engine.invitation_action("Tomas", "accept", {"invitation": invitation.id})
    assert engine.env.log.count == before, "replayed accepts cannot spam other participants"


def test_duplicate_pending_invite_reuses_existing_commitment(engine):
    first = invite(engine, None)
    engine.invitation_action("Tomas", "accept", {"invitation": first.id})
    engine.invitation_action(
        "Mei",
        "invite",
        {
            "people": ["Tomas"],
            "place": "the Workshop",
            "at": None,
            "minutes": 20,
            "topic": "review THE repair",
            "public": False,
        },
    )
    assert len(engine.invitations) == 1
    assert first.confirmed == ["Mei", "Tomas"]


def test_busy_owner_is_explained_and_confirmed_wait_is_explicit(engine):
    invitation = invite(engine)
    engine.invitation_action("Tomas", "accept", {"invitation": invitation.id})
    base.work(engine, who="Mei")
    assert "busy" in engine.invitation_views("Tomas")[0]["readiness"]["Mei"]
    card = Card(engine.observation("Tomas").allowed)
    reply = card.model.model_validate(
        {
            "thought": "Be ready",
            "do": "wait for confirmed conversation",
            "invitation": invitation.id,
        }
    )
    engine.select("Tomas", card.decision(reply).action)
    rest = engine.activities[engine.current["Tomas"]]
    assert isinstance(rest, RestActivity) and rest.waiting_for == invitation.id
    engine.now = invitation.start
    engine.start_ready_conversations()
    assert invitation.status == "pending", "working owner must not be interrupted"
    engine.leave("Mei", "Attend my confirmed meeting")
    engine.start_ready_conversations()
    assert invitation.status == "started"
    assert set(engine.activities[invitation.conversation].participants) == {"Mei", "Tomas"}
    assert engine.invitation_views("Tomas")[0]["status"] == "started"


def test_conversation_contract_routes_submit_via_work(engine):
    activity = base.conversation(engine)
    observation = engine.observation("Mei")
    assert "No code edits, tests or submissions happen here" in observation.situation
    assert "pause or leave" in observation.setting and "resume Work" in observation.setting
    card = Card(observation.allowed)
    with pytest.raises(ValidationError):
        card.model.model_validate(
            {"thought": "Submit", "do": "submit your repair", "report": "WORKTREE"}
        )
    assert activity.kind == "conversation"


@pytest.mark.parametrize(
    "when,expected",
    [
        ("11:59", "OPEN, closes at 12:00:00, 60"),
        ("12:00", "CLOSED; next opens at 14:00:00"),
        ("16:00", "OPEN, closes at 18:00:00, 7200"),
        ("18:00", "CLOSED; next opens tomorrow at 08:00"),
    ],
)
def test_clock_and_open_state_are_computed_not_inferred(engine, when, expected):
    engine.now = at(1, when)
    facts = engine.current_facts("Mei")
    assert expected in facts
    assert "Current location permits code work now: False" in facts
    assert "Repository tools still require a Work activity" in facts


def test_cancelled_confirmed_wait_releases_resident(engine):
    invitation = invite(engine)
    engine.select("Mei", base.choose("select_rest", arguments={"invitation": invitation.id}))
    invitation.status = "cancelled"
    engine.wake_rests()
    assert "Mei" not in engine.current


def test_future_appointment_does_not_absorb_a_new_immediate_invite(engine):
    future = invite(engine, "09:00")
    engine.invitation_action(
        "Mei",
        "invite",
        {
            "people": ["Tomas"],
            "place": "the Workshop",
            "at": None,
            "minutes": 20,
            "topic": future.topic,
            "public": False,
        },
    )
    assert len(engine.invitations) == 2


def test_waiting_for_one_meeting_cannot_start_a_different_pending_meeting(engine):
    first = invite(engine, None)
    engine.invitation_action("Tomas", "accept", {"invitation": first.id})
    engine.invitation_action(
        "Mei",
        "invite",
        {
            "people": ["Tomas"],
            "place": "the Workshop",
            "at": None,
            "minutes": 20,
            "topic": "A different meeting",
            "public": False,
        },
    )
    second = list(engine.invitations.values())[-1]
    engine.invitation_action("Tomas", "accept", {"invitation": second.id})
    engine.select("Tomas", base.choose("select_rest", arguments={"invitation": second.id}))
    engine.start_ready_conversations()
    assert first.status == "pending"
    assert second.status == "started"
