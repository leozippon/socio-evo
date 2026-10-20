"""A real team claim requires a local dialogue and one shared, mutually agreed plan."""

import asyncio

import pytest

from core.environment.rejection import Rejected
from core.interaction import ClaimTask, EventKind
from runtime.activities.engine import ActivityEngine, PendingTool
from runtime.activities.model import ConversationActivity, MoveActivity
from tests.runtime.activities import test_engine as base
from tests.runtime.realtime import test_engine as realtime

engine = base.engine
rt = realtime.rt


@pytest.fixture(params=["engine", "rt"])
def scheduler(request):
    return request.getfixturevalue(request.param)


async def pair(e):
    base.work(e, "Mei")
    base.work(e, "Tomas")
    await base.perform(e, "Mei", "claim", job="task-7", partner="Tomas")
    assert not e.teams
    await base.perform(e, "Tomas", "claim", job="task-7", partner="Mei")
    return e.teams["task-7"]


async def proposal(e, mode="parallel", first=None):
    await base.perform(
        e,
        "Mei",
        "propose_work_plan",
        mode=mode,
        your_role="Implement",
        partner_role="Test",
        relay_first=first,
    )
    return e.team_of("Mei").proposal


async def dialogue(e):
    for who in ("Mei", "Tomas"):
        await base.perform(e, who, "reply", text=f"Here is {who}'s contribution.")


async def test_actual_claim_event_is_consumed_once_and_bootstrap_is_not_permission(scheduler):
    e = scheduler
    team = await pair(e)
    rows = [r for r in e.env.log.pending_events("Mei") if r.kind == EventKind.TASK_CLAIMED]
    e.consume_claim_events(rows + rows)
    assert e.teams["task-7"] is team
    e.advance_team_discussions()
    discussion = e.activities[team.conversation]
    e.advance_team_discussions()
    assert e.activities[team.conversation] is discussion
    assert isinstance(discussion, ConversationActivity)
    assert discussion.task_id == "task-7" and not discussion.public
    assert set(discussion.participants) == {"Mei", "Tomas"}
    assert not discussion.messages and not e.work_ready("Mei")
    for who in team.workers:
        with pytest.raises(Rejected):
            e.schedule(who, base.use("command", command="touch should-not-run"))
    state = e.state()
    state.pop("teams")
    restored = ActivityEngine(e.sim, state)
    restored.reconcile_teams()
    assert "task-7" in restored.teams and not restored.work_ready("Mei")


async def test_solo_claim_does_not_create_a_team(scheduler):
    e = scheduler
    base.work(e)
    await base.perform(e, "Mei", "claim", job="task-1", partner=None)
    assert not e.teams and "command" in e.menu("Mei")["tools"]


async def test_clerk_pairing_uses_the_same_actual_claim_entry(scheduler):
    e = scheduler
    e.env.conditions = e.env.conditions.model_copy(update={"partner_choice": False})
    for who in ("Mei", "Tomas"):
        events = await e.env.execute(
            who, ClaimTask(task_id="task-7"), time=e.now // 60, scene="activities", witnesses=[]
        )
        e.consume_claim_events(events)
    assert not e.teams
    events = e.env.pair_applicants(e.now // 60, e.sim.rng)
    e.consume_claim_events(events)
    assert len(e.teams["task-7"].workers) == 2
    e.advance_team_discussions()
    assert all(isinstance(e.activities[e.current[p]], MoveActivity) for p in ("Mei", "Tomas"))


async def test_plan_requires_actual_dialogue_partner_confirmation_and_current_id(scheduler):
    e = scheduler
    team = await pair(e)
    e.advance_team_discussions()
    plan = await proposal(e)
    with pytest.raises(Rejected, match="Both partners must speak"):
        e.work_plan_action("Tomas", "confirm_work_plan", {"proposal": plan.id})
    with pytest.raises(Rejected, match="not your own"):
        e.work_plan_action("Mei", "confirm_work_plan", {"proposal": plan.id})
    for args in (
        {"mode": "parallel", "your_role": " ", "partner_role": "Test", "relay_first": None},
        {
            "mode": "parallel",
            "your_role": "Implement",
            "partner_role": "Test",
            "relay_first": "Mei",
        },
        {"mode": "relay", "your_role": "Implement", "partner_role": "Test", "relay_first": "Olga"},
    ):
        with pytest.raises(Rejected):
            e.work_plan_action("Mei", "propose_work_plan", args)
    old_id = plan.id
    await dialogue(e)
    plan = await proposal(e, "relay", "Mei")
    with pytest.raises(Rejected, match="old one"):
        e.work_plan_action("Tomas", "confirm_work_plan", {"proposal": old_id})
    await base.perform(e, "Tomas", "confirm_work_plan", proposal=plan.id)
    assert plan.accepted_at is not None and not e.work_ready("Mei")
    e.advance_team_discussions()
    if hasattr(e, "flush_leaves"):
        e.flush_leaves()
    assert e.activities[team.conversation].status == "ended" and e.work_ready("Mei")
    for who in team.workers:
        e.select(
            who,
            base.choose(
                "select_work", seconds=1800, arguments={"mode": "parallel", "public": False}
            ),
        )
    assert "edit" in e.menu("Mei")["tools"] and "edit" not in e.menu("Tomas")["tools"]
    for a in e.activities.values():
        if a.kind == "work":
            a.mode, a.relay_owner = "parallel", "Tomas"
    assert "edit" not in e.menu("Tomas")["tools"]
    assert "Implement" in e.observation("Mei").situation
    with pytest.raises(Rejected):
        e.work_plan_action("Tomas", "confirm_work_plan", {"proposal": plan.id})


async def test_unfinished_leave_does_not_loop_or_release_gate_and_restarts_next_day(scheduler):
    e = scheduler
    team = await pair(e)
    e.advance_team_discussions()
    old = team.conversation
    e.leave("Mei", "Discuss later")
    e.advance_team_discussions()
    assert team.conversation == old and not team.assembling and not e.work_ready("Mei")
    e.select("Mei", base.choose("select_work", seconds=600))
    assert team.conversation != old and not e.work_ready("Mei")
    e.leave("Mei", "Tomorrow")
    restored = ActivityEngine(e.sim, e.state())
    restored.prepare_day(24 * 60 + 8 * 60)
    restored.advance_team_discussions()
    assert restored.teams["task-7"].conversation != team.conversation
    assert not restored.work_ready("Mei")


async def test_different_locations_and_existing_move_finish_before_discussion(scheduler):
    e = scheduler
    team = await pair(e)
    e.leave("Tomas", "Travel")
    e.select("Tomas", base.choose("select_move", target="library"))
    original = e.current["Tomas"]
    e.advance_team_discussions()
    assert e.current["Tomas"] == original and team.conversation is None
    move = e.activities[original]
    await base.complete(e, move.latest_end)
    e.advance_team_discussions()
    returning = e.activities[e.current["Tomas"]]
    assert isinstance(returning, MoveActivity) and returning.destination == team.place
    assert team.conversation is None and e.env.world.locations["Tomas"] == "library"
    await base.complete(e, returning.latest_end)
    e.advance_team_discussions()
    assert set(e.activities[team.conversation].participants) == set(team.workers)
    assert all(e.env.world.locations[p] == team.place for p in team.workers)


async def test_new_claim_instance_cannot_reuse_the_old_agreement(scheduler):
    e = scheduler
    listing = e.env.board.listings["task-7"]
    await pair(e)
    old = await base.agree_team(e)
    del e.env.board.claims["task-7"]
    e.env.board.listings["task-7"] = listing
    for who, partner in (("Mei", "Tomas"), ("Tomas", "Mei")):
        await base.perform(e, who, "claim", job="task-7", partner=partner)
    new = e.teams["task-7"]
    assert new.claim_event_id > old.claim_event_id
    assert new.proposal is None and not e.work_ready("Mei")
    for who in new.workers:
        assert not ({"read_code", "command", "submit", "handoff"} & set(e.menu(who)["tools"]))


async def test_base_confirmation_drains_started_reply_before_ending(engine):
    e = engine
    team = await pair(e)
    e.advance_team_discussions()
    await dialogue(e)
    plan = await proposal(e)
    e.schedule("Mei", base.use("reply", text="More detail " * 100))
    end = e.pending["Mei"].end
    await base.perform(e, "Tomas", "confirm_work_plan", proposal=plan.id)
    e.advance_team_discussions()
    assert len(e.activities[team.conversation].participants) == 2
    assert not e.work_ready("Mei")
    await base.complete(e, end)
    e.advance_team_discussions()
    assert e.work_ready("Mei")
    assert len(e.activities[team.conversation].messages) == 3


async def test_realtime_confirmation_drains_started_body_and_skips_task_auto_wait(rt):
    team = await pair(rt)
    rt.advance_team_discussions()
    await dialogue(rt)
    plan = await proposal(rt)
    gate = asyncio.Event()

    class Speaker:
        async def choose_tool(self, observation):
            await gate.wait()
            return base.Decision(
                thought="Finish speaking",
                action=base.use("reply", targets=["Tomas"], text="Final detail before we begin."),
            )

    rt.sim.agents["Mei"] = Speaker()
    rt.start_decision("Mei", targets=("Tomas",))
    await asyncio.sleep(0)
    await base.perform(rt, "Tomas", "confirm_work_plan", proposal=plan.id)
    rt.advance_team_discussions()
    assert not rt.work_ready("Mei") and team.conversation in rt.closing
    gate.set()
    await realtime.finish(rt, "Mei")
    rt.flush_leaves()
    assert rt.work_ready("Mei") and not rt.running
    assert rt.activities[team.conversation].messages[-1].text == "Final detail before we begin."


async def test_repository_commit_rechecks_unfinished_team_gate(engine):
    e = engine
    await pair(e)
    activity = e.activities[e.current["Mei"]]
    forged = PendingTool(
        activity.id, base.use("command", command="touch forbidden"), e.now, e.now, {}
    )
    outcome = await e.complete_tool("Mei", forged)
    assert outcome["success"] is False
    assert not next(iter(e.env.providers.values())).commands


async def claim_from_conversation(e):
    for who, partner in (("Mei", "Tomas"), ("Tomas", "Mei")):
        events = await e.env.execute(
            who,
            ClaimTask(task_id="task-7", partner=partner),
            time=e.now // 60,
            scene="activities",
            witnesses=[],
        )
        e.consume_claim_events(events)
    return e.team_of("Mei")


async def test_assembly_preserves_a_started_reply_in_the_previous_conversation(engine):
    old = base.conversation(engine)
    engine.schedule("Mei", base.use("reply", text="Finish this earlier conversation first."))
    end = engine.pending["Mei"].end
    team = await claim_from_conversation(engine)
    engine.advance_team_discussions()
    assert team.conversation is None and set(old.participants) == {"Mei", "Tomas"}
    await base.complete(engine, end)
    engine.advance_team_discussions()
    assert old.status == "ended" and len(old.messages) == 1
    assert team.conversation is not None and not engine.work_ready("Mei")


async def test_assembly_preserves_a_started_realtime_body_in_the_previous_conversation(rt):
    old = base.conversation(rt)
    gate = asyncio.Event()

    class Speaker:
        async def choose_tool(self, observation):
            await gate.wait()
            return base.Decision(
                thought="Finish speaking",
                action=base.use(
                    "reply", targets=["Tomas"], text="Finish this earlier conversation first."
                ),
            )

    rt.sim.agents["Mei"] = Speaker()
    rt.start_decision("Mei", targets=("Tomas",))
    await asyncio.sleep(0)
    team = await claim_from_conversation(rt)
    rt.advance_team_discussions()
    assert team.conversation is None and set(old.participants) == {"Mei", "Tomas"}
    gate.set()
    await realtime.finish(rt, "Mei")
    await realtime.finish(rt, "Mei")
    assert "Mei" not in rt.running  # No fresh Wait or model request delays required assembly.
    rt.advance_team_discussions()
    assert old.status == "ended" and len(old.messages) == 1
    assert team.conversation is not None and not rt.work_ready("Mei")


async def test_relay_decline_returns_the_same_task_write_permission(scheduler):
    e = scheduler
    await pair(e)
    team = await base.agree_team(e, mode="relay", first="Mei")
    await base.perform(e, "Mei", "handoff", to="Tomas", description="Please continue")
    handoff = next(iter(e.handoffs.values()))
    assert team.relay_owner is None
    assert "edit" not in e.menu("Mei")["tools"]
    await base.perform(e, "Tomas", "decline_handoff", handoff=handoff.id)
    assert handoff.status == "declined" and team.relay_owner == "Mei"
    assert "edit" in e.menu("Mei")["tools"] and "edit" not in e.menu("Tomas")["tools"]


async def test_old_claim_handoff_cannot_override_a_new_relay_first_writer(scheduler):
    e = scheduler
    listing = e.env.board.listings["task-7"]
    await pair(e)
    await base.agree_team(e)
    await base.perform(e, "Mei", "handoff", to="Tomas", description="Previous claim's repair")
    old_handoff = next(iter(e.handoffs.values()))
    assert old_handoff.status == "offered"
    del e.env.board.claims["task-7"]
    e.env.board.listings["task-7"] = listing
    for who, partner in (("Mei", "Tomas"), ("Tomas", "Mei")):
        await base.perform(e, who, "claim", job="task-7", partner=partner)
    assert old_handoff.status == "declined"
    team = await base.agree_team(e, mode="relay", first="Mei")
    with pytest.raises(Rejected):
        e.schedule("Tomas", base.use("apply_handoff", handoff=old_handoff.id))
    assert team.relay_owner == "Mei" and "edit" not in e.menu("Tomas")["tools"]
