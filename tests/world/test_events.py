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
    "idle": {"help", "look_around", "go", "start_work", "say", "sleep", "wait"},
    "movement": set(),
    "work": {
        "view_board",
        "claim_task",
        "shell",
        "read_repo_file",
        "write_repo_file",
        "edit_repo_file",
        "submit",
        "abandon_task",
        "say",
        "leave_work",
    },
    "conversation": {"say", "give_money", "share_skill", "look_around", "leave_conversation"},
    "sleep": {"review_day", "rate"},
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
    closed = await town.call("Mei", "start_work")
    assert closed.text == "The workshop is closed; it is open from 09:00 to 18:00."
    await town.until("09:00")
    assert town.take("Mei")[-1] == "It is 09:00: the workshop opened and the day's board is posted."
    started = await town.call("Mei", "start_work")
    assert started.text.startswith("You started work.") and isinstance(mei.base, Work)
    working = await _refusals(town, "Mei")
    assert working["go"] == working["sleep"] == "You are at work; leave work first."
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

    said = await town.call("Tomas", "say", text="How is it going?")
    assert said.text == "You said: “How is it going?”"
    assert isinstance(mei.event, Conversation) and isinstance(mei.base, Work)
    assert town.world.ports["Mei"].interrupt.is_set()
    assert town.take("Mei") == ["Tomas said: “How is it going?”"]
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
    assert town.take("Tomas") == ["Mei left the conversation.", "The conversation is over."]


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
    assert town.take("Mei")[-1] == "Nobody has spoken for 10 minutes; the conversation is over."


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
        "Nobody has spoken for 10 minutes; the conversation is over.",
        "Tomas arrived at the shared house on Mill Street.",
    ]
    await town.call("Mei", "say", text="Shh.", to=["Aisha"])
    assert not ports["Tomas"].interrupt.is_set()
    assert town.take("Tomas")[-1] == "Mei said something to Aisha that you could not hear."
    assert "Tomas" not in town.world.residents["Mei"].conversation.members


async def test_nobody_can_address_a_resident_in_bed_or_asleep(make_town):
    town = make_town()
    await awake_at(town)
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
    assert (await town.call("Mei", "sleep", until="06:00", journal="x")).text == (
        "You can sleep until 07:00 at the earliest."
    )
    assert (await town.call("Mei", "sleep", until="7am", journal="x")).text.startswith("Give")
    assert (await town.call("Mei", "sleep", until="08:00", journal=" ")).text.startswith("Write")
    await town.call("Mei", "go", place="park")
    await town.until("07:10")
    assert (await town.call("Mei", "sleep", until="08:00", journal="x")).text == (
        "You can sleep only at home."
    )
    await town.call("Mei", "go", place="mill-street-house")
    await town.until("07:20")
    town.take("Mei")

    await town.call("Mei", "sleep", until="08:30", journal="I walked to the park and back.")
    journal = tmp_path / "agents" / "Mei" / "memory" / "journal" / "2001-01-01.md"
    assert journal.read_text() == "I walked to the park and back.\n"
    assert isinstance(mei.base, Sleep) and not mei.base.suspended
    in_bed = town.take("Mei")
    assert len(in_bed) == 1 and in_bed[0].startswith("You are in bed and will wake at 08:30")
    assert "Aisha" in in_bed[0]  # whom it may rate
    in_bed_refusals = await _refusals(town, "Mei")
    assert set(in_bed_refusals) == {spec.name for spec in town.world.tool_specs} - SLEEP_TOOLS
    assert in_bed_refusals["go"] == (
        "You have gone to bed; before you fall asleep you can only review your day, rate "
        "people and see to your own files."
    )
    review = await town.call("Mei", "review_day")
    assert "07:00 You woke up at home." in review.text
    assert "You went to bed" not in review.text  # the actor's own wording is the in-bed text

    waiting = asyncio.create_task(port.wait())
    await town.until("07:21")
    assert mei.suspended and not waiting.done()
    assert (await town.call("Mei", "look_around")).text == "You are asleep."
    town.rest("Tomas", "Aisha")  # the checkpoint waits for every runtime to rest
    await town.until("08:30", day=2)
    assert [day for day, _ in town.checkpoints] == [1]
    woke = waiting.result()
    assert [p.kind for p in woke][-1] == "wake"
    assert woke[-1].text == "You woke up at home. It is Tuesday 2 January, 08:30."
    assert isinstance(mei.base, Idle) and mei.place == "mill-street-house"


async def test_whoever_is_up_at_the_forced_hour_falls_asleep_without_a_journal(make_town, tmp_path):
    town = make_town()
    await awake_at(town)
    await town.call("Tomas", "go", place="park")
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
    assert town.take("Mei")[-2:] == [
        "Your statement for Monday 1 January: living cost $30. Your purse holds $90.",
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


async def test_the_workplace_closing_sends_workers_outside(make_town):
    town = make_town()
    await awake_at(town)
    await town.call("Mei", "go", place="workshop")
    await town.until("09:00")
    await town.call("Mei", "start_work")
    await town.call("Mei", "claim_task", task=2)
    town.take("Mei")
    await town.until("18:00")
    mei = town.world.residents["Mei"]
    assert isinstance(mei.base, Idle) and mei.place == "workshop"
    assert town.take("Mei") == [
        "It is 18:00: the workshop closed, and you stopped work and stepped outside."
    ]
    assert town.world.board.claims["Mei"].task == 2
    assert "It is closed; it opens at 09:00." in (await town.call("Mei", "look_around")).text
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
    assert situation.endswith(
        "Now you can use: help, look_around, go, wait, sleep, start_work, say."
    )
    await town.call("Mei", "go", place="park")
    assert "on your way to the park and will arrive at 07:10" in port.situation()
    assert port.sim_time() == at("07:00")
