"""The record of a resident's day and its journal, read from a run the real world and runtime
lived (`tests.analysis.lived`)."""

from __future__ import annotations

import asyncio
import json
import shutil
import time

import pytest

from evaluation.records import INDENT, OUTPUT, day_record, journal, lived_days
from tests.analysis.lived import MEI_JOURNAL, MEI_JOURNAL_2, TOMAS_JOURNAL, live
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
        "wake", "depart", "arrive", "time", "board_posted", "start_work", "claim", "command",
        "file_write", "submission", "verdict", "payment", "speech", "skill_shared", "gift",
        "leave_conversation", "leave_work", "sleep", "rating", "fell_asleep", "settlement",
    }  # fmt: skip
    told = [
        f"{clock_time(e['sim_time'])} {e['personal'].get('Mei', e['text']).splitlines()[0]}"
        for e in mine
    ]
    lines = heads(day_record(run_dir, "Mei", 1))
    assert all(lines.count(line) == 1 for line in told)
    assert [line for line in lines if line in told] == told
    assert "07:00 You woke up at home. It is Monday 1 January, 07:00." in lines
    assert "09:00 Task 1, handed in by you, was accepted." in lines
    assert "09:20 Tomas said to you: “Mei, how do you run the tests?”" in lines
    assert "09:20 You said to Tomas: “I run pytest -x first.”" in lines
    assert "20:00 You rated Tomas 4 of 5: “He asked good questions.”" in lines
    assert lines[-1] == (
        "00:00 Your statement for Monday 1 January: paid $20 for task 1; received $5 from Tomas; "
        "living cost $40. Your purse holds $105."
    )


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
    assert "20:00 You called review_day: The town's record of your day:" in lines
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


def test_others_private_speech_their_days_and_the_journal_stay_out(run_dir):
    record = day_record(run_dir, "Mei", 1)
    assert "09:20 Tomas said something to Aisha that you could not hear." in record
    assert "Do not tell Mei" not in record
    assert "Tomas claimed" not in record and "Tomas ran" not in record
    assert "Tomas rated" not in record and "18:00" not in record
    assert not any(f"Mei {verb}" in record for verb in ("claimed", "said", "ran", "rated"))
    assert MEI_JOURNAL not in record and "I fixed task 1" not in record
    tomas = day_record(run_dir, "Tomas", 1)
    assert "You said to Aisha: “Do not tell Mei about task 2.”" in tomas
    assert TOMAS_JOURNAL not in tomas and "You read" not in tomas  # an empty trace


def test_days_are_cut_at_their_checkpoints(run_dir):
    first, second = day_record(run_dir, "Mei", 1), day_record(run_dir, "Mei", 2)
    assert "Tuesday" not in first and "Monday" not in second
    assert heads(second) == [
        "07:00 You woke up at home. It is Tuesday 2 January, 07:00.",
        "07:00 You called wait(minutes=600): You wait for up to 600 minutes.",
        "17:00 You waited 600 minutes; it is now 17:00.",
        "17:00 You called wait(minutes=180): You wait for up to 180 minutes.",
        "20:00 You waited 180 minutes; it is now 20:00.",
        "20:00 You are in bed and will wake at 07:00; your journal entry for today is kept. Last "
        "night others rated you, without their names: 5 of 5, saying “She shared her testing "
        "skill.”. Before you fall asleep you can look over your day, rate the people you spent "
        "time with today (Aisha), and see to your files; you fall asleep once you have nothing "
        "more to do.",
        "20:00 You fell asleep.",
        "00:00 Your statement for Tuesday 2 January: living cost $40. Your purse holds $65.",
    ]
    with pytest.raises(ValueError, match="day 3 is not a day the world log closed"):
        day_record(run_dir, "Mei", 3)
    with pytest.raises(ValueError, match="no resident Olga"):
        day_record(run_dir, "Olga", 1)


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
