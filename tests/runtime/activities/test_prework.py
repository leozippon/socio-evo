"""The free preparation hour reuses Work/Conversation/Move/Rest without unlocking code."""

import pytest

from core.environment.rejection import Rejected
from runtime.activities.model import at
from runtime.realtime.engine import RealtimeEngine
from tests.runtime.activities import test_early_arrival as arrival_tests
from tests.runtime.activities import test_engine as activity_tests
from tests.runtime.realtime.test_engine import finish

engine = activity_tests.engine
gate = arrival_tests.gate
choose, use, complete = activity_tests.choose, activity_tests.use, activity_tests.complete


@pytest.fixture
def morning(gate):
    gate.now = at(1, "07:00")
    if isinstance(gate, RealtimeEngine):
        gate.clock.rebase(gate.now)
    return gate


async def tool(driver, action, who="Mei"):
    driver.schedule(who, action)
    if isinstance(driver, RealtimeEngine):
        await finish(driver, who)
    else:
        await complete(driver, driver.pending[who].end)


def test_morning_shows_current_facts_and_activity_choices(morning):
    from core.interaction import Card

    observation = morning.observation("Mei")
    assert "07:00:00" in observation.situation
    assert "Current location permits code work now: False" in observation.situation
    card = Card(observation.allowed)
    card.model.model_validate(
        {"thought": "Wait", "do": "rest", "until": "08:00", "wake for invitations": True}
    )
    assert not morning.current
    assert "07:00–22:00" in observation.setting
    assert "repository work guide" in observation.setting


async def test_home_work_preparation_can_claim_and_review_but_not_execute_code(morning):
    morning.select("Mei", choose("select_work", seconds=3600))
    home = morning.env.config.homes["Mei"]
    assert morning.activities[morning.current["Mei"]].place == home
    assert {"board", "claim", "feedback", "invite"} <= set(morning.menu("Mei")["tools"])
    await tool(morning, use("board"))
    await tool(morning, use("claim", job="task-1", partner=None))
    assert morning.env.board.claim_of("Mei").task.id == "task-1"
    await tool(morning, use("feedback"))
    tools = morning.menu("Mei")["tools"]
    assert not set(tools) & {
        "read_code",
        "search",
        "diff",
        "edit",
        "command",
        "test",
        "submit",
        "handoff",
    }
    with pytest.raises(Rejected):
        morning.schedule("Mei", use("command", command="python --version"))
    assert not next(iter(morning.env.providers.values())).commands
    await morning.close()


async def test_morning_claim_survives_commute_and_code_opens_at_eight(morning):
    morning.select("Mei", choose("select_work", seconds=3600))
    await tool(morning, use("claim", job="task-1", partner=None))
    morning.leave("Mei", "Travel after preparation")
    morning.select("Mei", choose("select_move", target="workshop"))
    arrival = morning.activities[morning.current["Mei"]].latest_end
    await complete(morning, arrival)
    assert "Mei" not in morning.outside and not morning.can_code("Mei")
    morning.now = at(1, "08:00")
    if isinstance(morning, RealtimeEngine):
        morning.clock.rebase(morning.now)
    morning.boundary()
    assert "Mei" not in morning.outside
    morning.select("Mei", choose("select_work", seconds=3600))
    assert morning.env.board.claim_of("Mei").task.id == "task-1"
    assert {"read_code", "edit", "command", "test", "submit"} <= set(morning.menu("Mei")["tools"])
    await morning.close()


def test_rest_is_optional_and_not_converted_to_work_at_opening(morning):
    morning.select("Mei", choose("select_rest", arguments={"until": "09:00", "wake": False}))
    activity = morning.current["Mei"]
    morning.now = at(1, "08:00")
    morning.boundary()
    assert morning.current["Mei"] == activity
    assert morning.activities[activity].kind == "rest"


def test_shared_home_conversation_and_remote_partner_invitation_are_available(morning):
    home = morning.env.config.homes["Mei"]
    assert morning.env.world.locations["Aisha"] == home
    morning.invitation_action(
        "Mei",
        "invite",
        dict(
            people=["Aisha"],
            place=morning.env.world.places[home].name,
            at="07:05",
            minutes=15,
            topic="Morning preparation",
            public=False,
        ),
    )
    invitation = list(morning.invitations.values())[-1]
    morning.invitation_action("Aisha", "accept", {"invitation": invitation.id})
    morning.now = at(1, "07:05")
    morning.start_ready_conversations()
    assert invitation.status == "started"
    assert morning.current["Mei"] == morning.current["Aisha"]
    assert morning.activities[morning.current["Mei"]].kind == "conversation"
    morning.invitation_action(
        "Jonas",
        "invite",
        dict(
            people=["Tomas"],
            place=morning.env.world.places["workshop"].name,
            at="08:10",
            minutes=15,
            topic="Find a partner",
            public=False,
        ),
    )
    appointment = list(morning.invitations.values())[-1]
    assert appointment.status == "pending"
    assert morning.env.world.locations["Tomas"] == morning.env.config.homes["Tomas"]
