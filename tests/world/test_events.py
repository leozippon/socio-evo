"""The events table: what each event offers, how it is entered and left, and the percepts and
interruptions that come with the transitions."""

from __future__ import annotations

import asyncio

import pytest

from tests.world.conftest import at, awake_at
from world.events import (
    CONVERSATION_TOOLS,
    IDLE_TOOLS,
    SLEEP_TOOLS,
    WORK_TOOLS,
    Conversation,
    Idle,
    Movement,
    Sleep,
    Work,
)

ARCHITECTURE_TABLE = {
    "idle": {
        "help",
        "look_around",
        "go",
        "start_work",
        "say",
        "message",
        "buy",
        "move_in",
        "sleep",
        "wait",
    },
    "movement": set(),
    "work": {
        "look_around",
        "go",
        "sleep",
        "view_board",
        "claim_task",
        "shell",
        "read_repo_file",
        "write_repo_file",
        "edit_repo_file",
        "submit",
        "abandon_task",
        "say",
        "message",
        "leave_work",
    },
    "conversation": {
        "say",
        "message",
        "give_money",
        "share_skill",
        "buy",
        "look_around",
        "go",
        "wait",
        "sleep",
        "start_work",
        "leave_conversation",
    },
    "sleep": {"look_around", "review_day", "rate"},
}


def test_the_tool_sets_are_the_architecture_table():
    assert IDLE_TOOLS == ARCHITECTURE_TABLE["idle"] == Idle.tools
    assert Movement.tools == ARCHITECTURE_TABLE["movement"]
    assert WORK_TOOLS == ARCHITECTURE_TABLE["work"] == Work.tools
    assert CONVERSATION_TOOLS == ARCHITECTURE_TABLE["conversation"] == Conversation.tools
    assert SLEEP_TOOLS == ARCHITECTURE_TABLE["sleep"] == Sleep.tools


async def _refusals(town, name: str) -> dict[str, str]:
    """The refusal of every declared tool the resident's event does not offer."""
    resident = town.world.residents[name]
    offered = resident.event.tools
    refused = {}
    for spec in town.world.tool_specs:
        if spec.name not in offered:
            result = await town.call(name, spec.name)
            assert "\n" not in result.text
            refused[spec.name] = result.text
    return refused


async def test_each_event_refuses_what_it_does_not_offer_naming_the_condition(make_town):
    town = make_town()
    await awake_at(town)
    world, mei = town.world, town.world.residents["Mei"]

    idle = await _refusals(town, "Mei")
    assert idle["shell"] == "You are not at work; start work at the workshop first."
    assert idle["give_money"] == "You are not in a conversation."
    assert idle["rate"] == "You can do that only once you have gone to bed."
    assert set(idle) == {spec.name for spec in world.tool_specs} - IDLE_TOOLS

    go = await town.call("Mei", "go", place="workshop")
    assert go.ends_turn and go.text == "You set off for the workshop and will arrive at 07:10."
    moving = await _refusals(town, "Mei")
    assert set(moving) == {spec.name for spec in world.tool_specs}
    assert (
        moving["say"] == "You are on your way to the workshop; you can do nothing until you arrive."
    )
    assert (await town.call("Mei", "look_around")).ends_turn

    await town.until("07:10")
    assert isinstance(mei.base, Idle) and mei.place == "workshop"
    started = await town.call("Mei", "start_work")
    assert started.text.startswith("You started work.") and isinstance(mei.base, Work)
    working = await _refusals(town, "Mei")
    assert working["wait"] == "You are at work; leave work first."
    assert working["start_work"] == "You are already at work."
    assert set(working) == {spec.name for spec in world.tool_specs} - WORK_TOOLS


async def test_conversation_sits_on_top_of_work_and_returns_to_it(make_town):
    town = make_town()
    await awake_at(town)
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="workshop")
    await town.until("09:00")
    await town.call("Mei", "start_work")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="a.py", content="x = 1\n")
    for name in ("Mei", "Tomas"):
        town.take(name)
    mei, tomas = town.world.residents["Mei"], town.world.residents["Tomas"]

    said = await town.call("Tomas", "say", text="How is it going?", to=["Mei"])
    assert said.text == "You said to Mei: “How is it going?”"
    assert isinstance(mei.event, Conversation) and isinstance(mei.base, Work)
    assert town.world.ports["Mei"].interrupt.is_set()
    assert town.take("Mei") == ["Tomas said to you: “How is it going?”"]
    assert not town.world.ports["Mei"].interrupt.is_set()
    refused = await _refusals(town, "Mei")
    assert refused["shell"] == "You are in a conversation; leave it first."
    assert set(refused) == {spec.name for spec in town.world.tool_specs} - CONVERSATION_TOOLS

    left = await town.call("Mei", "leave_conversation")
    assert left.text == "You left the conversation. You are back at work."
    assert isinstance(mei.event, Work)
    assert town.world.board.claims["Mei"].task == 1
    assert (await town.call("Mei", "read_repo_file", path="a.py")).text == "x = 1\n"
    assert tomas.conversation is None
    assert town.take("Tomas") == [
        "At 09:00 Mei left the conversation.",
        "At 09:00 the conversation ended.",
    ]


async def test_conversations_end_on_silence(make_town):
    town = make_town()
    await awake_at(town)
    await town.call("Mei", "say", text="Good morning.")
    aisha = town.world.residents["Aisha"]
    assert isinstance(aisha.event, Conversation)
    await town.until("07:09")
    assert aisha.conversation is not None
    await town.call("Aisha", "say", text="Morning.")
    await town.until("07:18")
    assert aisha.conversation is not None
    await town.until("07:19")
    assert aisha.conversation is None and town.world.residents["Mei"].conversation is None
    assert town.take("Mei")[-1] == "Nobody spoke for 10 minutes; at 07:19 the conversation ended."


async def test_silence_is_not_counted_while_someone_is_still_thinking(make_town):
    town = make_town()
    await awake_at(town)
    await town.call("Mei", "say", text="Good morning.")
    aisha = town.world.residents["Aisha"]
    town.world.clock.set_busy("Aisha", True)  # composing her answer
    await town.until("07:25")
    assert aisha.conversation is not None
    town.world.clock.set_busy("Aisha", False)
    await town.until("07:27")
    assert aisha.conversation is None
    assert town.take("Mei")[-1].startswith("Nobody spoke for 10 minutes; at 07:2")


async def test_speech_interrupts_only_those_it_reaches(make_town):
    town = make_town()
    await awake_at(town)
    ports = town.world.ports
    said = await town.call("Mei", "say", text="Can you keep a secret?", to=["Aisha"])
    assert said.text == "You said to Aisha: “Can you keep a secret?”"
    assert ports["Aisha"].interrupt.is_set()
    assert town.take("Aisha") == ["Mei said to you: “Can you keep a secret?”"]
    assert not ports["Tomas"].pending()  # in another place

    await town.call("Tomas", "go", place="mill-street-house")
    assert (await town.call("Mei", "say", text="Tomas?", to=["Tomas"])).text == "Tomas is not here."
    await town.until("07:10")
    assert not ports["Mei"].interrupt.is_set()
    arrival = [percept.text for percept in ports["Mei"].pending()]
    assert arrival == [
        "Nobody spoke for 10 minutes; at 07:10 the conversation ended.",
        "Tomas arrived at the shared house on Mill Street.",
    ]
    await town.call("Mei", "say", text="Shh.", to=["Aisha"])
    assert not ports["Tomas"].interrupt.is_set()
    assert town.take("Tomas")[-1] == "Mei said something to Aisha that you could not hear."
    assert "Tomas" not in town.world.residents["Mei"].conversation.members


async def test_waiting_in_a_conversation_listens_until_the_reply_or_the_silence(make_town):
    town = make_town()
    await awake_at(town)
    port, mei = town.world.ports["Mei"], town.world.residents["Mei"]
    await town.call("Mei", "say", text="Did you sleep well?", to=["Aisha"])
    waited = await town.call("Mei", "wait", minutes=30)
    assert waited.ends_turn and waited.text == "You wait for up to 30 minutes."
    listening = asyncio.create_task(port.wait())
    await town.until("07:02")
    assert not listening.done() and mei.conversation is not None
    await town.call("Aisha", "say", text="Like a log.")
    assert [p.text for p in listening.result()] == ["Aisha said: “Like a log.”"]
    assert mei.conversation is town.world.residents["Aisha"].conversation is not None

    await town.call("Mei", "wait", minutes=30)
    listening = asyncio.create_task(port.wait())
    await town.until("07:12")
    assert [p.text for p in listening.result()] == [
        "Nobody spoke for 10 minutes; at 07:12 the conversation ended."
    ]
    assert "leave_conversation" not in town.kinds()


async def test_going_elsewhere_or_back_to_work_leaves_a_conversation_on_its_own(make_town):
    town = make_town()
    await awake_at(town)
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="workshop")
    await town.until("07:10")
    await town.call("Mei", "start_work")
    mei = town.world.residents["Mei"]
    await town.call("Tomas", "say", text="Coffee?", to=["Mei"])
    town.take("Tomas")
    back = await town.call("Mei", "start_work")
    assert back.text == "You left the conversation. You are back at work. It is 07:10."
    assert isinstance(mei.event, Work)
    assert town.take("Tomas") == [
        "At 07:10 Mei left the conversation.",
        "At 07:10 the conversation ended.",
    ]

    await town.call("Tomas", "say", text="Coffee, really?", to=["Mei"])
    went = await town.call("Mei", "go", place="cafe")
    assert went.ends_turn and went.text == (
        "You left the conversation and stopped work. You set off for the café on the square "
        "and will arrive at 07:15."
    )
    assert isinstance(mei.base, Movement) and mei.conversation is None
    assert town.take("Tomas")[-1] == "Mei left the workshop for the café on the square."
    kinds = [e["kind"] for e in town.world.log.entries() if e["actor"] == "Mei"]
    assert kinds[-3:] == ["leave_conversation", "leave_work", "depart"]


async def test_going_to_bed_leaves_a_conversation_and_is_refused_at_work(make_town):
    town = make_town()
    await awake_at(town)
    await town.call("Tomas", "go", place="workshop")
    await town.call("Aisha", "say", text="Tired already?", to=["Mei"])
    slept = await town.call("Mei", "sleep", until="12:00", journal="Back to bed.")
    assert slept.ends_turn and slept.text == "You left the conversation. You went to bed."
    assert town.take("Aisha") == [
        "At 07:00 Mei left the conversation.",
        "At 07:00 the conversation ended.",
    ]
    mei = [e["kind"] for e in town.world.log.entries() if e["actor"] == "Mei"]
    assert mei[-2:] == ["leave_conversation", "sleep"]

    await town.until("07:10")
    await town.call("Tomas", "start_work")
    refused = await town.call("Tomas", "sleep", until="12:00", journal="Tired.")
    assert refused.text == "You can sleep only at home." and not refused.ends_turn
    assert isinstance(town.world.residents["Tomas"].base, Work)


async def test_looking_around_tells_the_hour_at_work_and_in_bed(make_town):
    town = make_town()
    await awake_at(town)
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="workshop")
    await town.until("08:14")
    for name in ("Mei", "Tomas"):
        await town.call(name, "start_work")
    looked = await town.call("Mei", "look_around")
    assert looked.text == "It is 08:14. You are at the workshop. Also here: Tomas (working)."
    assert not looked.ends_turn and isinstance(town.world.residents["Mei"].event, Work)
    await town.call("Aisha", "sleep", until="12:00", journal="A slow morning.")
    assert (await town.call("Aisha", "look_around")).text == (
        "It is 08:14. You are at the shared house on Mill Street. It is your home, which you "
        "share with Mei. Nobody else is here."
    )


async def test_a_remark_to_everyone_leaves_those_at_work_to_their_work(make_town):
    town = make_town()
    await awake_at(town)
    ports, mei = town.world.ports, town.world.residents["Mei"]
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="workshop")
    await town.until("07:10")
    await town.call("Mei", "start_work")
    await town.call("Mei", "claim_task", task=1)
    town.take("Mei")

    said = await town.call("Tomas", "say", text="Morning, all.")
    assert said.text == "You said: “Morning, all.”"
    assert not ports["Mei"].interrupt.is_set() and isinstance(mei.event, Work)
    assert town.world.residents["Tomas"].conversation is None  # nobody was drawn in
    assert (await town.call("Mei", "shell", command="pytest")).text == "ran pytest\nExit code 0."
    assert town.take("Mei") == ["Tomas said: “Morning, all.”"]  # waiting for her next step
    assert town.world.ratings.met["Tomas"] == set()

    await town.call("Tomas", "say", text="Mei, a minute?", to=["Mei"])
    assert ports["Mei"].interrupt.is_set() and isinstance(mei.event, Conversation)
    assert town.world.ratings.met["Tomas"] == {"Mei"}


async def test_bed_at_any_hour_and_waking_at_the_next_time_the_hour_comes(make_town, tmp_path):
    town = make_town()
    await awake_at(town)
    mei = town.world.residents["Mei"]
    await town.until("10:00")
    await town.call("Mei", "sleep", until="15:00", journal="Up all night with the bug.")
    assert town.take("Mei")[0].startswith(
        "You are in bed and will wake at 15:00; your journal entry for today is kept. Nobody "
        "rated you last night."
    )
    assert mei.base.wake == at("15:00")  # the same day
    town.rest("Mei")
    await town.until("15:00")
    assert isinstance(mei.base, Idle)
    assert town.heard["Mei"][-1].text == "You woke up at home. It is Monday 1 January, 15:00."
    await town.until("23:00")
    await town.call("Mei", "sleep", until="09:00", journal="A short afternoon after the nap.")
    assert mei.base.wake == at("09:00", day=2)  # an hour already past: tomorrow
    told = [p.text for p in town.heard["Mei"] if p.kind == "sleep"][-1]
    assert "rated you" not in told  # its ratings were read at the first bedtime of the day
    journal = tmp_path / "agents" / "Mei" / "memory" / "journal" / "2001-01-01.md"
    assert journal.read_text() == (
        "Up all night with the bug.\n\nA short afternoon after the nap.\n"
    )  # one file for the day, an entry per bedtime
    sleeps = [e for e in town.world.log.entries() if e["kind"] == "sleep"]
    assert [e["payload"]["day"] for e in sleeps] == [1, 1]


async def test_one_sleep_lasts_at_most_twelve_hours_and_the_forced_sleep_is_unchanged(make_town):
    town = make_town()
    await awake_at(town)
    mei, tomas = town.world.residents["Mei"], town.world.residents["Tomas"]
    await town.until("08:23")
    refused = await town.call("Mei", "sleep", until="07:00", journal="Tired already.")
    assert refused.text == (
        "Nobody sleeps longer than 12 hours at a stretch: give an hour no later than 20:23."
    )
    assert not refused.ends_turn and isinstance(mei.base, Idle) and "sleep" not in town.kinds()
    assert (await town.call("Mei", "sleep", until="20:00", journal="Tired already.")).ends_turn
    assert mei.base.wake == at("20:00")
    await town.until("23:00")
    await town.call("Tomas", "sleep", until="07:00", journal="A long day.")
    assert tomas.base.wake == at("07:00", day=2)
    town.rest()
    await town.until("02:00", day=2)  # Mei, up again, and Aisha, never in bed
    forced = [e for e in town.world.log.entries() if e["kind"] == "forced_sleep"]
    assert sorted(e["actor"] for e in forced) == ["Aisha", "Mei"]
    assert {e["payload"]["wake"] for e in forced} == {at("07:00", day=2)}
    await town.until("07:00", day=2)
    assert all(isinstance(r.base, Idle) for r in town.world.residents.values())


async def test_bed_stays_open_after_midnight_and_nobody_wakes_before_the_checkpoint(make_town):
    town = make_town()
    await awake_at(town)
    await town.until("01:00", day=2)
    went = await town.call("Mei", "sleep", until="02:15", journal="A late night.")
    assert went.text == "You went to bed."
    assert town.take("Mei")[-1].startswith("You are in bed and will wake at 02:30;")
    town.rest()
    await town.until("02:30", day=2)
    assert [day for day, _ in town.checkpoints] == [1]
    assert isinstance(town.world.residents["Mei"].base, Idle)  # woken after the checkpoint


async def test_nobody_can_address_a_resident_in_bed_or_asleep(make_town):
    town = make_town()
    await awake_at(town)
    await town.until("20:00")
    slept = await town.call("Aisha", "sleep", until="08:00", journal="Short day.")
    assert slept.ends_turn and slept.text == "You went to bed."
    assert (await town.call("Mei", "say", text="Hi", to=["Aisha"])).text == "Aisha is asleep."
    nobody = await town.call("Mei", "say", text="Anyone?")
    assert nobody.text == "There is nobody here to hear you."
    assert "Aisha (asleep)" in (await town.call("Mei", "look_around")).text


async def test_sleep_ends_the_day_with_a_journal_and_waking_comes_at_the_hour(make_town, tmp_path):
    town = make_town()
    await awake_at(town)
    port, mei = town.world.ports["Mei"], town.world.residents["Mei"]
    await town.until("20:00")
    assert (await town.call("Mei", "sleep", until="7am", journal="x")).text.startswith("Give")
    assert (await town.call("Mei", "sleep", until="08:00", journal=" ")).text.startswith("Write")
    await town.call("Mei", "go", place="park")
    await town.until("20:10")
    assert (await town.call("Mei", "sleep", until="08:00", journal="x")).text == (
        "You can sleep only at home."
    )
    await town.call("Mei", "go", place="mill-street-house")
    await town.until("20:20")
    await town.call("Mei", "say", text="Good night.", to=["Aisha"])
    town.take("Mei")

    await town.call("Mei", "sleep", until="08:00", journal="I walked to the park and back.")
    journal = tmp_path / "agents" / "Mei" / "memory" / "journal" / "2001-01-01.md"
    assert journal.read_text() == "I walked to the park and back.\n"
    assert isinstance(mei.base, Sleep) and not mei.base.suspended
    in_bed = town.take("Mei")
    assert len(in_bed) == 1 and in_bed[0].startswith("You are in bed and will wake at 08:00")
    assert "Aisha" in in_bed[0]  # whom it may rate
    in_bed_refusals = await _refusals(town, "Mei")
    assert set(in_bed_refusals) == {spec.name for spec in town.world.tool_specs} - SLEEP_TOOLS
    assert in_bed_refusals["go"] == (
        "You have gone to bed; before you fall asleep you can only look around, look back over "
        "your day, rate people and see to your own files."
    )
    review = await town.call("Mei", "review_day")
    assert "07:00 You woke up at home." in review.text
    assert "You went to bed" not in review.text  # the actor's own wording is the in-bed text

    waiting = asyncio.create_task(port.wait())
    await town.until("20:21")
    assert mei.suspended and not waiting.done()
    assert (await town.call("Mei", "look_around")).text == "You are asleep."
    town.rest("Tomas", "Aisha")  # the checkpoint waits for every runtime to rest
    await town.until("08:00", day=2)
    assert [day for day, _ in town.checkpoints] == [1]
    woke = waiting.result()
    assert [p.kind for p in woke][-1] == "wake"
    assert woke[-1].text == "You woke up at home. It is Tuesday 2 January, 08:00."
    assert isinstance(mei.base, Idle) and mei.place == "mill-street-house"


async def test_whoever_is_up_at_the_forced_hour_falls_asleep_without_a_journal(make_town, tmp_path):
    town = make_town()
    await awake_at(town)
    await town.call("Tomas", "go", place="park")
    await town.until("21:00")
    await town.call("Mei", "sleep", until="09:00", journal="Early night.")
    await town.until("01:59", day=2)
    town.take("Tomas")
    await town.until("02:00", day=2)
    tomas, mei = town.world.residents["Tomas"], town.world.residents["Mei"]
    assert tomas.suspended and tomas.place == "college-flat"
    assert town.take("Tomas") == [
        "It is 02:00: you fell asleep without writing a journal entry, and will wake at home "
        "at 07:00."
    ]
    assert mei.suspended
    assert town.take("Mei")[-3:] == [
        "Your statement for Monday 1 January: rent for your room at the shared house on Mill "
        "Street $20. You had nothing to eat today. Your purse holds $100.",
        "You went hungry today, too hungry to concentrate on work before the next meal.",
        "It is 02:00: you fell asleep.",
    ]
    assert not (tmp_path / "agents" / "Tomas" / "memory" / "journal").exists()
    forced = [e for e in town.world.log.entries() if e["kind"] == "forced_sleep"]
    assert {e["actor"] for e in forced} == {"Tomas", "Aisha"}
    town.rest()
    await town.until("07:00", day=2)
    assert isinstance(tomas.base, Idle) and tomas.place == "college-flat"
    assert isinstance(mei.base, Sleep)
    await town.until("09:00", day=2)
    assert isinstance(mei.base, Idle)


async def test_the_workplace_never_closes_and_a_route_shortens_the_walk(make_town):
    town = make_town()
    await awake_at(town)
    await town.call("Mei", "go", place="workshop")
    await town.until("09:00")
    await town.call("Mei", "start_work")
    await town.call("Mei", "claim_task", task=2)
    town.take("Mei")
    await town.until("18:00")
    mei = town.world.residents["Mei"]
    assert isinstance(mei.base, Work) and town.take("Mei") == []
    await town.call("Mei", "leave_work")
    assert (await town.call("Mei", "look_around")).text == (
        "It is 18:00. You are at the workshop. Nobody else is here."
    )
    assert town.world.board.claims["Mei"].task == 2
    went = await town.call("Mei", "go", place="cafe")  # a route shorter than the default walk
    assert went.text == "You set off for the café on the square and will arrive at 18:05."
    await town.until("18:04")
    assert mei.place is None
    await town.until("18:05")
    assert mei.place == "cafe"


@pytest.mark.parametrize("args", [{}, {"place": 3}, {"place": "moon"}, {"place": "cafe", "x": 1}])
async def test_bad_arguments_are_refused_in_one_line(make_town, args):
    town = make_town()
    await awake_at(town)
    result = await town.call("Mei", "go", **args)
    assert "\n" not in result.text and not result.ends_turn
    assert town.world.residents["Mei"].place == "mill-street-house"


async def test_an_unknown_tool_raises(make_town):
    town = make_town()
    with pytest.raises(KeyError):
        await town.world.ports["Mei"].call("fly", {})


async def test_situation_says_what_applies_now(make_town):
    town = make_town()
    port = town.world.ports["Mei"]
    assert port.situation().startswith("Monday 1 January, 02:30. You are asleep.")
    await awake_at(town)
    situation = port.situation()
    assert situation.startswith("Monday 1 January, 07:00. You are at the shared house")
    assert "Also here: Aisha." in situation and "Your purse holds $120." in situation
    assert "You have nothing of your own yet." in situation  # told at home
    assert situation.endswith(
        "What you can do now: help, look_around, go, wait, sleep, start_work, say, buy, "
        "move_in, message."
    )
    await town.call("Mei", "go", place="park")
    assert "on your way to the park and will arrive at 07:10" in port.situation()
    assert port.sim_time() == at("07:00")
