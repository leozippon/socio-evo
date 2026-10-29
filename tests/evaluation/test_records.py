"""The record of a resident's day and its journal, read from a run the real world and runtime
lived (`tests.analysis.lived`)."""

from __future__ import annotations

import asyncio
import json
import shutil
import time

import pytest

from evaluation.records import (
    INDENT,
    OUTPUT,
    day_record,
    days_before,
    journal,
    journal_of,
    lived_days,
    record,
    town,
)
from tests.analysis.lived import ANNOUNCEMENT, MEI_JOURNAL, MEI_JOURNAL_2, TOMAS_JOURNAL, live
from world.clock import clock_time


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("lived") / "run"
    asyncio.run(live(root))
    return root


def heads(record: str) -> list[str]:
    """The first line of each happening of `record`."""
    return [line for line in record.splitlines() if not line.startswith(INDENT)]


def test_every_entry_about_the_resident_is_told_once_in_order_in_its_words(run_dir):
    entries = lived_days(run_dir)[1].entries
    mine = [e for e in entries if e["actor"] == "Mei" or "Mei" in e["audience"]]
    assert {e["kind"] for e in mine} == {
        "wake", "depart", "arrive", "time", "task_arrived", "start_work", "claim", "command",
        "file_write", "submission", "verdict", "service", "speech", "gift",
        "leave_conversation", "leave_work", "sleep", "fell_asleep", "announcement", "wage",
        "settlement", "condition",
    }  # fmt: skip

    def head(e):
        text = e["personal"].get("Mei", e["text"]).splitlines()[0]
        return f"{clock_time(e['sim_time'])} {text}"

    told = [head(e) for e in mine]
    lines = heads(day_record(run_dir, "Mei", 1))
    assert all(lines.count(line) == 1 for line in told)
    assert [line for line in lines if line in told] == told
    assert (
        "07:00 You woke up at home. It is Monday 1 January, 07:00. You are well fed. You are "
        "fresh. You are in good health."
    ) in lines
    assert "12:00 You are a little hungry." in lines and "20:00 You are hungry." in lines
    assert "09:00 Task 1, handed in by you, was accepted." in lines
    assert "09:20 Tomas said to you: “Mei, how do you run the tests?”" in lines
    assert "09:20 You said to Tomas: “I run pytest -x first.”" in lines
    assert lines[-4:] == [  # her twenty minutes at work did not cover the rent
        "20:00 You fell asleep.",
        f"20:20 Vera announced at the hall: “{ANNOUNCEMENT}”",  # told to her on waking
        "00:00 At midnight your purse held $145; none of your wages went into it.",
        "00:00 Your statement for Monday 1 January: received $20 for task 1; received $5 from "
        "Tomas; 20 minutes at work, $2 in wages; rent for your room at the shared house on Mill "
        "Street $20; your wages fell $18 short of that; you owe it, and it is taken from your "
        "next wages. You had nothing to eat today. You are hungry. You are fresh. You are in good "
        "health. Your purse holds $145.",
    ]


def test_what_only_the_trace_knows_is_told_in_its_place(run_dir):
    lines = heads(day_record(run_dir, "Mei", 1))

    def at(line: str) -> int:
        return lines.index(line)

    assert at("07:00 You read memory/work.md.") < at(
        "07:00 You left the shared house on Mill Street for the workshop."
    )
    assert at("09:00 You received $20 for task 1.") < at("09:00 You wrote skills/testing.md.")
    assert (
        at("09:00 You claimed task 1 (org/repo1).")
        < at("09:00 You called claim_task(task=2): You already hold task 1; submit it or give it "
             "up first.")
        < at("09:00 You ran a command for task 1: pytest -x (exit code 0).")
    )  # fmt: skip
    assert "07:10 You called wait(minutes=110): You wait for up to 110 minutes." in lines
    assert "09:00 You called view_board: The board:" in lines
    assert "20:00 You called review_day: Your day, as it went:" in lines
    assert "20:00 You wrote memory/people.md." in lines
    assert "20:00 You tried to read memory/missing.md: There is no file memory/missing.md." in lines
    # Calls the log tells are not told twice.
    assert not [line for line in lines if "You called" in line and "claim_task(task=1)" in line]
    assert not [line for line in lines if any(f"called {t}" in line for t in ("submit", "go"))]


def test_a_command_keeps_the_tail_of_its_output(run_dir):
    record = day_record(run_dir, "Mei", 1)
    assert (
        "09:00 You ran a command for task 1: false (exit code 1).\n"
        f"{INDENT}{OUTPUT}\n{INDENT}boom\n" in record
    )


def test_the_towns_trades_are_told_to_those_they_concern(run_dir):
    def told(name: str, day: int = 1) -> list[str]:
        return heads(day_record(run_dir, name, day))

    def follow(lines: list[str], expected: list[str]) -> None:
        assert [line for line in lines if line in expected] == expected

    sale, hall = "20:10 You received $2 for a sale.", f"announced at the hall: “{ANNOUNCEMENT}”"
    follow(told("Olga"), [
        "20:10 You sat down to work.",
        "20:10 You ordered 5 helpings of bread from the supplier for $10.",
        "20:10 Jonas bought 2 units of vegetables for the kitchen for $6.", sale,
        "20:10 Vera bought 1 helping of bread for $4.", sale,
    ])  # fmt: skip
    assert "08:00 It is 08:00: the supplier delivered 5 helpings of bread to the store." in told(
        "Olga", 2
    )
    follow(told("Jonas"), [
        "20:10 You bought 2 units of vegetables for the kitchen for $6.",
        "20:20 You sat down to work.",
        "20:20 You cooked 1 portion of vegetable soup.",
        "20:30 You served Lucia vegetable soup for $8.",
        "20:30 You received $3 for a dish served.",
    ])  # fmt: skip
    ravi, lucia = told("Ravi"), told("Lucia")
    follow(ravi, [
        "09:00 You received $10 for task 1, which Mei handed in.",
        "20:10 You gave task 3 (org/repo3) to Aisha.",
    ])  # fmt: skip
    # The examination with the numbers it told, to both.
    (seen,) = [line for line in ravi if line.startswith("20:20 Lucia examined you for $10. Food: ")]
    assert seen.endswith("Health: 100 of 100, you are in good health.")
    (made,) = [line for line in lucia if line.startswith("20:20 You examined Ravi for $10. Food: ")]
    assert made.endswith("Health: 100 of 100, Ravi is in good health.")
    follow(lucia, [
        made, "20:20 You received $4 for a patient examined.",
        "20:30 Jonas served you vegetable soup for $8.",
    ])  # fmt: skip
    follow(told("Vera"), ["20:10 You bought 1 helping of bread for $4.", f"20:20 You {hall}"])
    follow(told("Aisha"), ["20:10 Ravi gave task 3 (org/repo3) to you.", f"20:20 Vera {hall}"])
    assert (
        "00:00 At midnight the client withdrew task 3, which you held; its workspace is gone."
        in told("Aisha", 2)
    )
    # A task coming in is told to those at the workshop, as Mei was at 08:00, and nobody else.
    assert "08:00 It is 08:00: task 1 (org/repo1) came in on the board." in told("Mei")
    assert not any("came in" in line for line in told("Olga"))
    # The days before are the new statements, with what was earned and spent.
    before = days_before(town(run_dir), lived_days(run_dir), "Lucia", 2).splitlines()
    assert before[0] == "You began your first day, Monday 1 January, with $100."
    assert before[1].startswith(
        "Your statement for Monday 1 January: received $4 for a patient examined; bought "
        "vegetable soup for $8;"
    )


def test_a_treatment_is_told_with_the_health_it_restored():
    entry = {
        "kind": "treatment", "sim_time": 36000, "real_time": 1.0, "actor": "Lucia",
        "place": "clinic", "audience": ["Ravi"], "text": "Lucia treated Ravi for $30.",
        "personal": {"Lucia": "You treated Ravi for $30.", "Ravi": "Lucia treated you for $30."},
        "payload": {"patient": "Ravi", "fee": 30, "restores": 25.0, "before": 40.4,
                    "health": 65.4, "ill": 3, "bedridden": False},
    }  # fmt: skip
    assert record([entry], [], "Lucia") == (
        "10:00 You treated Ravi for $30. Ravi's health went from 40 to 65 of 100, and the illness "
        "ended."
    )
    well = entry | {"payload": entry["payload"] | {"ill": 0}}
    assert record([well], [], "Ravi") == (
        "10:00 Lucia treated you for $30. Your health went from 40 to 65 of 100."
    )


def test_others_private_speech_their_days_and_the_journal_stay_out(run_dir):
    record = day_record(run_dir, "Mei", 1)
    assert "09:20 Tomas said something to Aisha that you could not hear." in record
    assert "Do not tell Mei" not in record
    assert "Tomas claimed" not in record and "Tomas ran" not in record
    assert "Tomas stopped work" not in record
    assert not any(f"Mei {verb}" in record for verb in ("claimed", "said", "ran"))
    assert MEI_JOURNAL not in record and "I fixed task 1" not in record
    tomas = day_record(run_dir, "Tomas", 1)
    assert "You said to Aisha: “Do not tell Mei about task 2.”" in tomas
    assert TOMAS_JOURNAL not in tomas and "You read" not in tomas  # an empty trace


def test_days_are_cut_at_their_checkpoints(run_dir):
    first, second = day_record(run_dir, "Mei", 1), day_record(run_dir, "Mei", 2)
    assert "Tuesday" not in first and "Monday" not in second
    assert heads(second) == [
        "03:00 You are starving.",  # logged in her sleep, told at waking
        "07:00 You woke up at home. It is Tuesday 2 January, 07:00. You are starving. You are "
        "fresh. You are in good health.",
        "07:00 You called wait(minutes=600): You wait for up to 600 minutes.",
        "17:00 You waited 600 minutes; it is now 17:00.",
        "17:00 You called wait(minutes=180): You wait for up to 180 minutes.",
        "20:00 You waited 180 minutes; it is now 20:00.",
        "20:00 You are in bed and will wake at 07:00; your journal entry for today is kept. "
        "Before you fall asleep you can look back over your day and see to your files; you fall "
        "asleep once you have nothing more to do.",
        "20:00 You fell asleep.",
        "00:00 At midnight your purse held $145; none of your wages went into it.",
        "00:00 Your statement for Tuesday 2 January: no time at work; rent for your room at the "
        "shared house on Mill Street $20; $18 of rent you owed; your wages fell $38 short of "
        "that; you owe it, and it is taken from your next wages. You had nothing to eat today. "
        "You are starving. You are fresh. You are in good health. Your purse holds $145.",
    ]
    with pytest.raises(ValueError, match="day 3 is not a day the world log closed"):
        day_record(run_dir, "Mei", 3)
    with pytest.raises(ValueError, match="no resident Kofi"):
        day_record(run_dir, "Kofi", 1)


def test_the_days_before_are_the_purse_begun_with_and_each_earlier_statement(run_dir):
    config, days = town(run_dir), lived_days(run_dir)
    began = "You began your first day, Monday 1 January, with $120."
    assert days_before(config, days, "Mei", 1) == began
    assert days_before(config, days, "Mei", 2) == (
        f"{began}\nYour statement for Monday 1 January: received $20 for task 1; received $5 from "
        "Tomas; 20 minutes at work, $2 in wages; rent for your room at the shared house on Mill "
        "Street $20; your wages fell $18 short of that; you owe it, and it is taken from your "
        "next wages. You had nothing to eat today. You are hungry. You are fresh. You are in good "
        "health. Your purse holds $145."
    )
    tomas = days_before(config, days, "Tomas", 2).splitlines()
    assert len(tomas) == 2 and "gave $5 to Mei" in tomas[1] and "Tuesday" not in tomas[1]


def test_a_lost_day_is_set_aside_for_the_day_lived_again(run_dir, tmp_path):
    copy = shutil.copytree(run_dir, tmp_path / "run")
    entries = [json.loads(line) for line in (copy / "world.jsonl").read_text().splitlines()]
    seq, now = entries[-1]["seq"], time.time()

    def entry(kind: str, text: str, payload: dict | None = None, actor: str | None = None):
        nonlocal seq, now
        seq, now = seq + 1, now + 1
        return {
            "seq": seq, "kind": kind, "sim_time": 2 * 86400 + 25200, "real_time": now,
            "actor": actor, "place": None, "audience": [actor] if actor else [], "text": text,
            "personal": {}, "payload": payload or {},
        }  # fmt: skip

    with (copy / "world.jsonl").open("a") as log:
        for added in (
            entry("wake", "Mei woke up, on the day that was lost.", actor="Mei"),
            entry("resume", "The town went back.", {"day": 2, "time": 2 * 86400 + 9000}),
            entry("wake", "Mei woke up again.", actor="Mei"),
            entry("checkpoint", "The state of day 3 was saved.", {"day": 3}),
        ):
            log.write(json.dumps(added) + "\n")
    assert sorted(lived_days(copy)) == [1, 2, 3]
    assert day_record(copy, "Mei", 3) == "07:00 Mei woke up again."
    assert day_record(copy, "Mei", 2) == day_record(run_dir, "Mei", 2)


def test_the_journal_is_the_entry_written_going_to_bed(run_dir, tmp_path):
    assert journal(run_dir, "Mei", 1) == MEI_JOURNAL
    assert journal(run_dir, "Mei", 2) == MEI_JOURNAL_2
    assert journal(run_dir, "Tomas", 1) == TOMAS_JOURNAL
    assert journal(run_dir, "Tomas", 2) is None and journal(run_dir, "Aisha", 1) is None
    entry = run_dir / "agents" / "Mei" / "memory" / "journal" / "2001-01-01.md"
    assert entry.read_text() == MEI_JOURNAL + "\n"
    copy = shutil.copytree(run_dir, tmp_path / "run")
    (copy / entry.relative_to(run_dir)).write_text("Rewritten days later.\n")
    assert journal(copy, "Mei", 1) == MEI_JOURNAL


def test_two_bedtimes_in_a_day_make_one_journal_joined_by_a_blank_line():
    def bed(actor, text):
        return {"kind": "sleep", "actor": actor, "audience": [actor], "payload": {"journal": text}}

    entries = [
        bed("Mei", "Slept after lunch."),
        bed("Tomas", "His day."),
        bed("Mei", None),  # a bedtime without an entry adds nothing
        bed("Mei", "Evening."),
        bed("Aisha", None),
    ]
    assert journal_of(entries, "Mei") == "Slept after lunch.\n\nEvening."
    assert journal_of(entries, "Tomas") == "His day."
    assert journal_of(entries, "Aisha") is None and journal_of(entries, "Kofi") is None
