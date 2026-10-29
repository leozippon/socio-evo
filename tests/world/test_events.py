"""The events table: what each event offers, how it is entered and left, and the percepts and
interruptions that come with the transitions."""

from __future__ import annotations

import asyncio
from typing import get_args

import pytest

from tests.support.towns import at, awake_at
from world.events import (
    BEDRIDDEN_TOOLS,
    CONVERSATION_TOOLS,
    IDLE_TOOLS,
    SLEEP_TOOLS,
    TALK,
    WORK_TOOLS,
    Bedridden,
    Conversation,
    Idle,
    Movement,
    Sleep,
    Work,
)
from world.occupations import OCCUPATIONS, WORK_DONE, OccupationId

ARCHITECTURE_TABLE = {
    "idle": {
        "help",
        "look_around",
        "go",
        "start_work",
        "view_board",
        "read_task",
        "claim_task",
        "shell",
        "read_repo_file",
        "write_repo_file",
        "edit_repo_file",
        "submit",
        "abandon_task",
        "assign",
        "cook",
        "order",
        "set_price",
        "examine",
        "treat",
        "report",
        "announce",
        "grant",
        "say",
        "message",
        "buy",
        "get",
        "put",
        "pass",
        "eat",
        "move_in",
        "sleep",
        "wait",
    },
    "movement": set(),
    "work": {
        "look_around",
        "go",
        "view_board",
        "read_task",
        "claim_task",
        "shell",
        "read_repo_file",
        "write_repo_file",
        "edit_repo_file",
        "submit",
        "abandon_task",
        "assign",
        "cook",
        "order",
        "set_price",
        "examine",
        "treat",
        "report",
        "announce",
        "grant",
        "say",
        "message",
        "buy",
        "get",
        "put",
        "pass",
        "eat",
        "wait",
        "leave_work",
    },
    "conversation": {
        "look_around",
        "go",
        "wait",
        "say",
        "buy",
        "get",
        "put",
        "pass",
        "eat",
        "leave_conversation",
    },
    "sleep": {"look_around", "review_day", "sleep"},
    "bedridden": {"look_around", "say", "sleep"},
}
for _event, _tools in ARCHITECTURE_TABLE.items():
    if _event != "movement":  # taking stock and asking: every waking event
        _tools |= {"how_am_i", "help"}
    if _event not in ("movement", "sleep"):  # seeing what one has: every waking event out of bed
        _tools.add("inventory")


def test_every_occupation_has_its_workplace_its_work_and_its_words():
    assert set(OCCUPATIONS) == set(get_args(OccupationId))
    assert WORK_DONE <= IDLE_TOOLS and WORK_DONE <= WORK_TOOLS  # done at rest or at work
    # What a conversation offers of its own is what idling and working offer, and talk.
    assert CONVERSATION_TOOLS <= (IDLE_TOOLS | TALK) and CONVERSATION_TOOLS <= (WORK_TOOLS | TALK)


def test_the_tool_sets_are_the_architecture_table():
    assert IDLE_TOOLS == ARCHITECTURE_TABLE["idle"] == Idle.tools
    assert Movement.tools == ARCHITECTURE_TABLE["movement"]
    assert WORK_TOOLS == ARCHITECTURE_TABLE["work"] == Work.tools
    assert CONVERSATION_TOOLS == ARCHITECTURE_TABLE["conversation"] == Conversation.tools
    assert SLEEP_TOOLS == ARCHITECTURE_TABLE["sleep"] == Sleep.tools
    assert BEDRIDDEN_TOOLS == ARCHITECTURE_TABLE["bedridden"] == Bedridden.tools


async def _refusals(town, name: str) -> dict[str, str]:
    """The refusal of every declared tool the resident's event does not offer."""
    resident = town.world.residents[name]
    offered = resident.tools
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
    assert idle["leave_work"] == "You are not at work."
    assert idle["leave_conversation"] == "You are not in a conversation."
    assert idle["review_day"] == "You can do that only once you have gone to bed."
    assert set(idle) == {spec.name for spec in world.tool_specs} - IDLE_TOOLS

    go = await town.call("Mei", "go", place="workshop")
    assert go.ends_turn and go.text == "You set off for the workshop and will arrive at 07:10."
    moving = await _refusals(town, "Mei")
    assert set(moving) == {spec.name for spec in world.tool_specs}
    assert (
        moving["say"] == "You are on your way to the workshop; you can do nothing until you arrive."
    )
    assert (await town.call("Mei", "look_around")).ends_turn

    await town.until("08:00")
    assert isinstance(mei.base, Idle) and mei.place == "workshop"
    claimed = await town.call("Mei", "claim_task", task=1)
    assert claimed.text.startswith("You sat down to work and claimed task 1, in org/repo1;")
    assert isinstance(mei.base, Work)
    working = await _refusals(town, "Mei")
    assert working["move_in"] == "You are at work; leave work first."
    assert working["review_day"] == "You can do that only once you have gone to bed."
    assert set(working) == {spec.name for spec in world.tool_specs} - WORK_TOOLS


async def test_a_conversation_covers_work_and_gives_it_back_when_it_ends(make_town):
    town = make_town()
    await awake_at(town)
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="workshop")
    await town.until("09:00")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="a.py", content="x = 1\n")
    for name in ("Mei", "Tomas"):
        town.take(name)
    world, port = town.world, town.world.ports["Mei"]
    mei, tomas = world.residents["Mei"], world.residents["Tomas"]

    said = await town.call("Tomas", "say", text="How is it going?", to=["Mei"])
    assert said.text == "You said to Mei: “How is it going?”"
    assert isinstance(mei.event, Conversation) and isinstance(mei.base, Work)
    assert port.interrupt.is_set()
    assert town.take("Mei") == ["Tomas said to you: “How is it going?”"]
    assert not port.interrupt.is_set()
    assert mei.tools == WORK_TOOLS | TALK and world.activity(mei) == "work"  # the hours run on
    offered = [spec.name for spec in port.tool_specs()]
    assert {"shell", "submit", "buy", "get", "put", "pass", "eat", "say"} <= set(offered)
    assert offered[-1] == "leave_conversation"
    refused = await _refusals(town, "Mei")
    assert refused["move_in"] == "You are at work; leave work first."
    assert set(refused) == {spec.name for spec in world.tool_specs} - WORK_TOOLS - TALK
    assert "You are at work at the workshop, in a conversation with Tomas." in port.situation()
    assert "Also here: Mei (working, in a conversation)." in world.ports["Tomas"].situation()

    left = await town.call("Mei", "leave_conversation")
    assert left.text == "You left the conversation. You are back at work."
    assert isinstance(mei.event, Work) and world.board.claims["Mei"].task == 1
    assert (await town.call("Mei", "read_repo_file", path="a.py")).text == "x = 1\n"
    kinds = [e["kind"] for e in world.log.entries() if e["actor"] == "Mei"]
    assert kinds.count("start_work") == 1 and "leave_work" not in kinds  # one stretch of work
    assert tomas.conversation is None
    assert town.take("Tomas") == [
        "At 09:00 Mei went back to work.",
        "At 09:00 the conversation ended.",
    ]

    # Doing her work while talking leaves the conversation first: one thing at a time.
    await town.call("Tomas", "say", text="And the tests?", to=["Mei"])
    town.take("Mei")
    worked = await town.call("Mei", "shell", command="pytest")
    assert worked.text == "You went back to work. ran pytest\nExit code 0."
    assert mei.conversation is None and tomas.conversation is None
    assert town.take("Tomas") == [
        "At 09:00 Mei went back to work.",
        "At 09:00 the conversation ended.",
    ]

    # A conversation that ends by itself gives the work back the same way.
    await town.call("Tomas", "say", text="Lunch?", to=["Mei"])
    town.take("Mei")
    assert isinstance(mei.event, Conversation)
    await town.until("09:10")  # silence
    assert isinstance(mei.event, Work) and mei.conversation is None
    assert town.take("Mei") == ["Nobody spoke for 10 minutes; at 09:10 the conversation ended."]
    assert (await town.call("Mei", "shell", command="pytest")).text == "ran pytest\nExit code 0."


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
    assert [p.text for p in listening.result()] == [
        "Aisha said: “Like a log.”",
        "That ended the wait you began at 07:00; it is now 07:02.",
    ]
    assert mei.conversation is town.world.residents["Aisha"].conversation is not None
    # What is told as the wait begins, or before, ends it with no word of a wait.
    await town.call("Mei", "wait", minutes=30)
    await town.call("Aisha", "say", text="And you?")
    assert [p.text for p in await port.wait()] == ["Aisha said: “And you?”"]

    await town.call("Mei", "wait", minutes=30)
    listening = asyncio.create_task(port.wait())
    await town.until("07:12")
    assert [p.text for p in listening.result()] == [
        "Nobody spoke for 10 minutes; at 07:12 the conversation ended.",
        "That ended the wait you began at 07:02; it is now 07:12.",
    ]
    assert "leave_conversation" not in town.kinds()


async def test_going_elsewhere_leaves_a_conversation_and_work_on_its_own(make_town):
    town = make_town()
    await awake_at(town)
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="workshop")
    await town.until("08:00")
    mei = town.world.residents["Mei"]
    await town.call("Mei", "claim_task", task=1)
    await town.call("Tomas", "say", text="Coffee?", to=["Mei"])
    town.take("Tomas")
    assert isinstance(mei.base, Work) and mei.conversation is not None
    assert (await town.call("Mei", "claim_task", task=2)).text == (  # her work: she goes back
        "You went back to work. You already hold task 1; submit it or give it up first."
    )
    assert mei.conversation is None

    await town.call("Tomas", "say", text="Coffee, really?", to=["Mei"])
    went = await town.call("Mei", "go", place="cafe")
    assert went.ends_turn and went.text == (
        "You left the conversation and stopped work. You set off for the café on the square "
        "and will arrive at 08:05."
    )
    assert isinstance(mei.base, Movement) and mei.conversation is None
    assert town.take("Tomas")[-1] == "Mei left the workshop for the café on the square."
    kinds = [e["kind"] for e in town.world.log.entries() if e["actor"] == "Mei"]
    assert kinds[-3:] == ["leave_work", "leave_conversation", "depart"]


async def test_going_to_bed_leaves_a_conversation_and_is_refused_away_from_home(make_town):
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

    await town.until("08:00")
    await town.call("Tomas", "claim_task", task=1)
    refused = await town.call("Tomas", "sleep", until="12:00", journal="Tired.")
    assert refused.text == "You can sleep only at home." and not refused.ends_turn
    assert isinstance(town.world.residents["Tomas"].base, Work)


async def test_looking_around_tells_the_hour_at_work_and_in_bed(make_town):
    town = make_town()
    await awake_at(town)
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="workshop")
    await town.until("08:14")
    for task, name in enumerate(("Mei", "Tomas"), start=1):
        await town.call(name, "claim_task", task=task)
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
    await town.until("08:10")
    await town.call("Mei", "claim_task", task=1)
    town.take("Mei")

    said = await town.call("Tomas", "say", text="Morning, all.")
    assert said.text == "You said: “Morning, all.”"
    assert not ports["Mei"].interrupt.is_set() and isinstance(mei.event, Work)
    assert town.world.residents["Tomas"].conversation is None  # nobody was drawn in
    assert (await town.call("Mei", "shell", command="pytest")).text == "ran pytest\nExit code 0."
    assert town.take("Mei") == ["Tomas said: “Morning, all.”"]  # waiting for her next step

    await town.call("Tomas", "say", text="Mei, a minute?", to=["Mei"])
    assert ports["Mei"].interrupt.is_set() and isinstance(mei.event, Conversation)


async def test_bed_at_any_hour_and_waking_at_the_next_time_the_hour_comes(make_town, tmp_path):
    town = make_town()
    await awake_at(town)
    mei = town.world.residents["Mei"]
    await town.until("10:00")
    await town.call("Mei", "sleep", until="15:00", journal="Up all night with the bug.")
    assert town.take("Mei")[0].startswith(
        "You are in bed and will wake at 15:00; your journal entry for today is kept. Before "
        "you fall asleep"
    )
    assert mei.base.wake == at("15:00")  # the same day
    town.rest("Mei")
    await town.until("15:00")
    assert isinstance(mei.base, Idle)
    assert town.heard["Mei"][-1].text == (
        "You woke up at home. It is Monday 1 January, 15:00. You are a little hungry. You are "
        "fresh. You are in good health."
    )
    await town.until("23:00")
    await town.call("Mei", "sleep", until="09:00", journal="A short afternoon after the nap.")
    assert mei.base.wake == at("09:00", day=2)  # an hour already past: tomorrow
    told = [p.text for p in town.heard["Mei"] if p.kind == "sleep"][-1]
    assert told.startswith("You are in bed and will wake at 09:00; your journal entry for today")
    journal = tmp_path / "agents" / "Mei" / "memory" / "journal" / "2001-01-01.md"
    assert journal.read_text() == (
        "Up all night with the bug.\n\nA short afternoon after the nap.\n"
    )  # one file for the day, an entry per bedtime
    sleeps = [e for e in town.world.log.entries() if e["kind"] == "sleep"]
    assert [e["payload"]["day"] for e in sleeps] == [1, 1]


async def test_going_to_bed_again_from_bed_adds_to_the_journal_and_sets_the_hour(
    make_town, tmp_path
):
    town = make_town()
    await awake_at(town)
    mei = town.world.residents["Mei"]
    await town.until("21:00")
    await town.call("Mei", "sleep", until="07:00", journal="A quiet day.")
    assert (await town.call("Mei", "review_day")).text.startswith("Your day, as it went:")
    town.take("Mei")
    added = await town.call("Mei", "sleep", until="08:00", journal="Looking back: no shopping.")
    assert added.ends_turn and added.text == (  # its result alone, without the bedtime again
        "You are in bed and will wake at 08:00; your journal entry for today is kept."
    )
    assert town.take("Mei") == []
    journal = tmp_path / "agents" / "Mei" / "memory" / "journal" / "2001-01-01.md"
    assert journal.read_text() == "A quiet day.\n\nLooking back: no shopping.\n"
    assert mei.base.wake == at("08:00", day=2) and not mei.base.suspended
    again = await town.call("Mei", "sleep", until="08:00")
    assert again.text == "You are in bed and will wake at 08:00."
    assert journal.read_text() == "A quiet day.\n\nLooking back: no shopping.\n"
    town.rest()
    await town.until("21:01")
    assert mei.suspended  # nothing left to read: asleep at her next wait
    await town.until("08:00", day=2)
    entries = town.world.log.entries()
    wakes = [e["sim_time"] for e in entries if e["kind"] == "wake" and e["actor"] == "Mei"]
    assert wakes == [at("07:00"), at("08:00", day=2)]  # the hour first given wakes her no more


async def test_the_body_wakes_one_after_twelve_hours_and_the_forced_sleep_is_unchanged(make_town):
    town = make_town()
    await awake_at(town)
    mei, tomas = town.world.residents["Mei"], town.world.residents["Tomas"]
    await town.until("08:23")
    slept = await town.call("Mei", "sleep", until="07:00", journal="Tired already.")
    assert slept.ends_turn and slept.text == "You went to bed."  # any hour is taken
    assert mei.base.wake == at("20:23") and mei.base.longest
    assert town.take("Mei")[-1].startswith(
        "You are in bed and will wake at 20:23, since you cannot sleep longer than 12 hours; "
        "your journal entry for today is kept."
    )
    town.rest("Mei")
    await town.until("20:23")
    assert isinstance(mei.base, Idle)
    assert town.heard["Mei"][-1].text.startswith(
        "You could sleep no longer and woke up at home. It is Monday 1 January, 20:23."
    )
    await town.until("23:00")
    await town.call("Tomas", "sleep", until="07:00", journal="A long day.")
    assert tomas.base.wake == at("07:00", day=2) and not tomas.base.longest
    town.rest("Tomas", "Aisha")
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
    await town.call("Mei", "go", place="park")
    await town.until("20:10")
    assert (await town.call("Mei", "sleep", until="08:00", journal="x")).text == (
        "You can sleep only at home."
    )
    await town.call("Mei", "go", place="mill-street-house")
    await town.until("20:20")
    await town.call("Mei", "say", text="Good night.", to=["Aisha"])
    await town.call("Mei", "leave_conversation")
    town.take("Mei")

    await town.call("Mei", "sleep", until="08:00", journal="I walked to the park and back.")
    journal = tmp_path / "agents" / "Mei" / "memory" / "journal" / "2001-01-01.md"
    assert journal.read_text() == "I walked to the park and back.\n"
    assert isinstance(mei.base, Sleep) and not mei.base.suspended
    in_bed = town.take("Mei")
    assert len(in_bed) == 1 and in_bed[0].startswith("You are in bed and will wake at 08:00")
    in_bed_refusals = await _refusals(town, "Mei")
    assert set(in_bed_refusals) == {spec.name for spec in town.world.tool_specs} - SLEEP_TOOLS
    assert in_bed_refusals["go"] == (
        "You have gone to bed; before you fall asleep you can only look around, take stock of "
        "how you feel, look back over your day, add to your journal, read how the town works "
        "and see to your own files."
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
    assert woke[-1].text == (
        "You woke up at home. It is Tuesday 2 January, 08:00. You are starving. You are fresh. "
        "You are in good health."
    )
    assert isinstance(mei.base, Idle) and mei.place == "mill-street-house"


async def test_going_to_bed_without_a_journal_entry_writes_none(make_town, tmp_path):
    town = make_town()
    await awake_at(town)
    await town.until("21:00")
    slept = await town.call("Mei", "sleep", until="07:00")
    assert slept.ends_turn and slept.text == "You went to bed."
    assert town.take("Mei")[-1].startswith("You are in bed and will wake at 07:00. Before you")
    assert (await town.call("Aisha", "sleep", until="07:00", journal="  ")).ends_turn
    assert not (tmp_path / "agents" / "Mei" / "memory" / "journal").exists()
    assert not (tmp_path / "agents" / "Aisha" / "memory" / "journal").exists()
    sleeps = [e for e in town.world.log.entries() if e["kind"] == "sleep"]
    assert [(e["text"], e["payload"]["journal"]) for e in sleeps] == [
        ("Mei went to bed.", None),
        ("Aisha went to bed.", None),
    ]


async def test_whoever_is_up_at_the_forced_hour_falls_asleep_without_a_journal(make_town, tmp_path):
    town = make_town()
    await awake_at(town)
    await town.call("Tomas", "go", place="park")
    await town.until("21:00")
    await town.call("Mei", "sleep", until="09:00", journal="Early night.")
    await town.call("Aisha", "sleep", until="23:30", journal="A nap before a late night.")
    await town.until("01:59", day=2)
    town.take("Tomas")
    town.take("Aisha")  # up again since 23:30, her entry for the day written
    await town.until("02:00", day=2)
    tomas, mei = town.world.residents["Tomas"], town.world.residents["Mei"]
    assert tomas.suspended and tomas.place == "college-flat"
    assert town.take("Tomas") == [
        "It is 02:00: you fell asleep without going to bed, and will wake at home at 07:00."
    ]
    assert town.take("Aisha") == [
        "It is 02:00: you fell asleep without going to bed again, and will wake at home at 07:00."
    ]
    assert mei.suspended
    assert town.take("Mei")[-2:] == [
        "Your statement for Monday 1 January: rent for your room at the shared house on Mill "
        "Street $20; your purse paid it. You had nothing to eat today. You are hungry. You are "
        "fresh. You are in good health. Your purse holds $100.",
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
    await town.call("Mei", "claim_task", task=2)
    town.take("Mei")
    await town.until("18:00")
    mei = town.world.residents["Mei"]
    assert isinstance(mei.base, Work)
    assert town.take("Mei") == [  # a long stretch of work: only the body speaks, by the hour
        "You are a little hungry.",
        "You are a little tired.",
    ]
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


async def test_the_port_offers_what_applies_now_and_the_situation_tells_the_rest(make_town):
    town = make_town()
    port = town.world.ports["Mei"]

    def offered() -> list[str]:
        return [spec.name for spec in port.tool_specs()]

    assert port.situation().startswith("Monday 1 January, 02:30. You are asleep.")
    assert offered() == []
    await awake_at(town)
    situation = port.situation()
    assert situation == (
        "Monday 1 January, 07:00. You are at the shared house on Mill Street. Also here: Aisha. "
        "Your purse holds $120. You carry nothing but your money."
    )  # what is for the resident to know; what it can do is offered, not told
    assert offered() == [
        "help", "look_around", "how_am_i", "inventory", "go", "wait", "sleep", "say", "buy",
        "get", "put", "pass", "eat", "move_in",
    ]  # fmt: skip
    # nothing to write with, no board here and no task held: no message, board or task
    town.world.residents["Mei"].inventory.items["phone"] = 1
    assert offered()[-2:] == ["move_in", "message"]
    await town.call("Mei", "go", place="park")
    assert port.situation().endswith(
        "You are on your way to the park and will arrive at 07:10. There is nothing to do until "
        "you arrive. Your purse holds $120."
    )
    assert offered() == [] and port.sim_time() == at("07:00")
