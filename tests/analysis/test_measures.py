import json
import shutil
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from analysis import evaluation_usage, measure, read_run, results, run_usage, scores
from core.interaction import Decision, day_of


def lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def truncate_mid_day(root: Path, day: int) -> None:
    """Make the run at `root` look stopped in the middle of `day`: its checkpoints end the
    day before, and its event log ends with half of a line still being written."""
    log = root / "events.jsonl"
    events = log.read_bytes().split(b"\n")[:-1]
    first = next(i for i, line in enumerate(events) if day_of(json.loads(line)["time"]) == day)
    cut = first + 40
    log.write_bytes(b"\n".join(events[:cut]) + b"\n" + events[cut][: len(events[cut]) // 2])
    for checkpoint in (root / "checkpoints").glob("day-*.json"):
        if int(checkpoint.stem.removeprefix("day-")) >= day:
            checkpoint.unlink()


def test_measures_agree_with_the_log_and_the_final_checkpoint(town):
    run = read_run(town)
    measured = measure(run)
    log = lines(town / "events.jsonl")
    final = json.loads((town / "checkpoints" / "day-0003.json").read_text())["environment"]
    agents = ["Ana", "Ben", "Cai"]
    rows = {(row.agent, row.day): row for row in measured.agents}
    assert sorted(rows) == sorted((agent, day) for agent in agents for day in (1, 2, 3))

    # Balances: each day's changes add up, and the last day ends where the checkpoint does.
    for agent in agents:
        balance = 100
        for day in (1, 2, 3):
            row = rows[agent, day]
            balance += row.income - row.living_cost - row.clawed_back
            assert row.balance == balance
        assert balance == final["balances"][agent]

    # Deliveries, defects and their discovery, counted from the raw log.
    def count(kind, who, test=lambda event: True):
        return Counter(who(e) for e in log if e["kind"] == kind and test(e))

    accepted = count("work_submitted", lambda e: e["actor"], lambda e: e["payload"]["accepted"])
    defective = count(
        "work_assessed",
        lambda e: e["actor"],
        lambda e: e["payload"]["accepted"] and e["payload"]["quality"] < 1,
    )
    found = count("defect_discovered", lambda e: e["payload"]["worker"])
    latent = Counter(delivery["worker"] for delivery in final["latent_defects"])
    for agent in agents:
        days = [rows[agent, day] for day in (1, 2, 3)]
        assert sum(row.delivered for row in days) == accepted[agent]
        assert sum(row.defective for row in days) == defective[agent]
        assert sum(row.defects_discovered for row in days) == found[agent]
        assert defective[agent] - found[agent] == latent[agent]
    assert defective["Ben"] and found["Ben"] and sum(r.clawbacks for r in measured.agents)

    # Esteem as the checkpoint holds it, and the conditions the intervention changed.
    for agent in agents:
        mean = final["esteem"][agent]
        assert rows[agent, 3].esteem == pytest.approx(mean["total"] / mean["weight"])
    assert [day.conditions["living_cost"] for day in measured.society] == [5, 9, 9]
    assert [day.tasks_posted for day in measured.society] == [3, 3, 3]

    # Where everyone was: the plans of the script, with refused moves sent home.
    assert rows["Ana", 1].slots == {"morning": "office", "afternoon": "flat", "evening": "cafe"}
    assert rows["Ben", 1].slots == {"morning": "office", "afternoon": "house", "evening": "cafe"}

    # The graph, edge by edge: ratings, speech, and minutes in shared scenes enumerated turn
    # by turn.
    expected = defaultdict(Counter)
    turn = 5
    scenes = {e["scene"]: e for e in log if e["kind"] == "scene_started"}
    ended = {e["scene"]: e for e in log if e["kind"] == "scene_ended"}
    left = {(e["scene"], e["actor"]): e["time"] for e in log if e["kind"] == "left"}
    assert left
    for scene, started in scenes.items():
        if started["payload"]["kind"] not in ("work", "conversation"):
            continue
        day, people = day_of(started["time"]), started["payload"]["participants"]
        for k in range(ended[scene]["payload"]["turns"]):
            at = started["time"] + k * turn
            here = [p for p in people if left.get((scene, p), at) >= at]
            for source in here:
                for target in here:
                    if source != target:
                        expected[day, source, target]["minutes"] += turn
        for source in people:
            for target in people:
                if source != target:
                    expected[day, source, target]["scenes"] += 1
    for e in log:
        if e["kind"] == "rating":
            key = (day_of(e["time"]), e["payload"]["rater"], e["payload"]["target"])
            expected[key]["ratings"] += 1
            expected[key]["ratings_sum"] += e["payload"]["score"]
        elif e["kind"] == "speech":
            for listener in e["audience"]:
                expected[day_of(e["time"]), e["actor"], listener]["heard"] += 1
            if e["payload"]["to"]:
                expected[day_of(e["time"]), e["actor"], e["payload"]["to"]]["addressed"] += 1
    fields = ("minutes", "scenes", "addressed", "heard", "ratings", "ratings_sum")
    assert {
        (edge.day, edge.source, edge.target): Counter(
            {name: getattr(edge, name) for name in fields if getattr(edge, name)}
        )
        for edge in measured.graph
    } == expected

    # Model usage counts every call, and the scripted model reports no tokens.
    calls = lines(town / "llm_calls.jsonl")
    usage = run_usage(run)
    assert sum(row["calls"] for row in usage) == sum(row["unmetered"] for row in usage)
    assert sum(row["calls"] for row in usage) == len(calls)
    assert {(row["agent"], row["purpose"]) for row in usage} == {
        (call["metadata"]["agent"], call["metadata"]["purpose"]) for call in calls
    }
    assert evaluation_usage(run) == []

    rows = scores(results(run.directory))
    assert [(row.agent, row.day, row.score) for row in rows] == [
        (agent, day, day / 3) for agent in agents for day in (0, 3)
    ]
    assert rows[-1].measures == {"disclosed": 1.0}


def test_a_run_in_progress_is_read_up_to_its_last_complete_line(town, tmp_path):
    root = tmp_path / "town" / "seed-0007"
    shutil.copytree(town, root)
    truncate_mid_day(root, 2)
    run = read_run(root)
    assert (run.settled_day, run.last_day) == (1, 2)
    complete = read_run(town)
    assert run.events == complete.events[: len(run.events)]
    day = [row for row in measure(run).society if row.day == 2]
    assert day and day[0].living_cost == 0  # the day has not ended


def test_malformed_settled_data_is_an_error(town, tmp_path):
    root = tmp_path / "town" / "seed-0007"
    shutil.copytree(town, root)
    log = root / "events.jsonl"
    events = log.read_bytes().split(b"\n")
    events[5] = events[5][:-3]
    log.write_bytes(b"\n".join(events))
    with pytest.raises(ValueError, match="events.jsonl:6"):
        read_run(root)

    shutil.copy(town / "events.jsonl", log)
    with log.open("ab") as file:  # an event the latest checkpoint does not account for
        file.write(log.read_bytes().split(b"\n")[-2] + b"\n")
    with pytest.raises(ValueError, match="out of sequence"):
        read_run(root)

    log.write_bytes(b"\n".join(log.read_bytes().split(b"\n")[:100]) + b"\n")
    with pytest.raises(ValueError, match="checkpoint of day 3 counts"):
        read_run(root)


def old_shape(record: dict) -> dict:
    """`record`, an event of the town, as the protocol before tasks had parts recorded it."""
    payload = dict(record["payload"])
    match record["kind"]:
        case "task_posted":
            task = payload["task"]
            payload = {"task": {"id": task["id"], **task["parts"][0]}}
        case "task_claimed":
            payload = {"task_id": payload["task_id"], "due_day": payload["due_day"]}
        case "task_expired":
            payload = {"task_id": payload["task_id"], "agent": payload["workers"][0]}
        case "work_submitted":
            kept = {key: payload[key] for key in ("task_id", "solution", "report")}
            payload = {**kept, "passed": payload["accepted"], "feedback": ""}
        case "work_assessed":
            kept = {key: payload[key] for key in ("task_id", "quality")}
            payload = {**kept, "passed": payload["accepted"]}
        case "defect_discovered":
            payload = {key: payload[key] for key in ("task_id", "worker", "quality")}
        case "clawback":
            payload = {key: payload[key] for key in ("agent", "task_id", "amount", "balance")}
        case "living_cost":
            del payload["obligation"]
        case "speech":
            del payload["private"]
        case "decision":
            new = ("part", "declaration", "partner", "private")
            payload["action"] = {k: v for k, v in payload["action"].items() if k not in new}
    return {**record, "payload": payload}


def test_a_log_recorded_before_tasks_had_parts_measures_as_it_meant(town, tmp_path):
    root = tmp_path / "town" / "seed-0007"
    shutil.copytree(town, root)
    old = [old_shape(record) for record in lines(town / "events.jsonl")]
    log = "".join(json.dumps(record) + "\n" for record in old)
    (root / "events.jsonl").write_text(log, encoding="utf-8")
    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    environment = config["environment"]
    del environment["circumstances"]
    conditions = environment["conditions"]
    conditions["tasks_per_day"] = conditions.pop("one_part_tasks")
    for key in ("two_part_tasks", "trusting_client_prob", "two_part_premium"):
        del conditions[key]
    for key in ("incomplete_share", "partner_choice"):
        del conditions[key]
    (root / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")

    then, now = measure(read_run(root)), measure(read_run(town))
    assert then.agents == now.agents and then.graph == now.graph
    assert [replace(day, conditions={}) for day in then.society] == [
        replace(day, conditions={}) for day in now.society
    ]
    assert sum(row.delivered for row in then.agents) and sum(row.claimed for row in then.agents)
    decided = [record["payload"]["action"] for record in old if record["kind"] == "decision"]
    deliveries = [
        Decision.model_validate({"thought": "", "action": action}).action
        for action in decided
        if action["kind"] == "submit_work"
    ]
    assert deliveries and {(action.part, action.declaration) for action in deliveries} == {
        (1, "complete")
    }
