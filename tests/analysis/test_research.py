"""Reports follow committed milestones and distinguish missing usage from measured zero."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from analysis.research import compare, main, summarize
from experiments.config import load_experiment
from infrastructure.git import Repository
from infrastructure.storage import RunDirectory


def make_run(tmp_path, arm, score):
    config = load_experiment(
        Path(__file__).resolve().parents[2] / f"experiments/configs/autoresearch-{arm}.yaml"
    )
    run = RunDirectory.create(tmp_path, arm, config=config, code_revision="test")
    root = run.root / "research"
    records = root / "records"
    records.mkdir(parents=True)
    repo = Repository.init(root, user_name="Test", user_email="test@town.invalid")
    record = {
        "stage": "proposal",
        "day": 7,
        "status": "reviewed",
        "score": score,
        "reward_per_resident": 100,
        "reward_total": 100 * len(config.residents),
        "audit": "research_reviews/proposal/hash",
    }
    (records / "milestone-proposal.json").write_text(json.dumps(record))
    revision = repo.commit("Checkpoint milestone", date=datetime.now(UTC))
    run.checkpoint_path(7).write_text(
        json.dumps(
            {
                "research": revision,
                "residents": {r.name: {"inventory": {"money": 100}} for r in config.residents},
            }
        )
    )
    # The current tree differs: report must still read the checkpoint's exact revision.
    (records / "milestone-proposal.json").write_text(json.dumps(record | {"score": 100}))
    repo.commit("Uncheckpointed change", date=datetime.now(UTC))
    for resident in config.residents:
        path = run.agent_dir(resident.name)
        path.mkdir()
        (path / "trace.jsonl").write_text(
            json.dumps({"kind": "request"})
            + "\n"
            + json.dumps({"kind": "reply", "usage": {"prompt_tokens": 10, "completion_tokens": 2}})
            + "\n"
            + json.dumps({"kind": "reply", "usage": None})
            + "\n"
        )
    attempts = run.root / "research_reviews" / "proposal" / "hash"
    attempts.mkdir(parents=True)
    (attempts / "input.json").write_text(json.dumps({"rubric": "Same four anchored dimensions."}))
    (attempts / "attempts.jsonl").write_text(
        json.dumps({"response": None, "error": {"message": "failed"}})
        + "\n"
        + json.dumps({"response": {"usage": {"prompt_tokens": 30, "completion_tokens": 5}}})
        + "\n"
    )
    return run.root


def test_report_uses_checkpoint_grants_and_counts_every_actors_usage(tmp_path):
    town, academy = make_run(tmp_path, "town", 75), make_run(tmp_path, "academy", 50)
    out = tmp_path / "reports" / "comparison.json"
    main(["--town", str(town), "--academy", str(academy), "--out", str(out)])
    report = json.loads(out.read_text())
    assert report["score_differences"] == [
        {"stage": "proposal", "day": 7, "town_minus_academy": 25}
    ]
    for arm, population in (("town", 8), ("academy", 4)):
        result = report["arms"][arm]
        assert result["completed_day"] == 7
        assert result["population"] == population
        assert result["milestone_rewards"] == 100 * population
        assert result["actor_usage"]["prompt_tokens"] == 10 * population
        assert result["actor_usage"]["replies_missing_usage"] == population
        assert result["actor_usage"]["cached_prompt_tokens"] is None
        assert result["judge_usage"]["requests"] == 2
        assert result["judge_usage"]["prompt_tokens"] == 30
        assert result["milestones"][1]["status"] == "pending"


def test_swapped_arms_and_missing_committed_review_fail_explicitly(tmp_path):
    town, academy = make_run(tmp_path, "town", 75), make_run(tmp_path, "academy", 50)
    with pytest.raises(ValueError, match="service conditions"):
        compare(academy, town)
    checkpoint = town / "checkpoints/day-07.json"
    checkpoint.write_text(checkpoint.read_text().replace('"research": "', '"research": "invalid'))
    with pytest.raises(RuntimeError):
        compare(town, academy)


@pytest.mark.parametrize("changed", ["actor", "judge", "seed", "milestones", "rubric"])
def test_mismatched_paired_protocol_cannot_produce_score_differences(tmp_path, changed):
    town, academy = make_run(tmp_path, "town", 75), make_run(tmp_path, "academy", 50)
    path = academy / "config.yaml"
    config = yaml.safe_load(path.read_text())
    if changed == "actor":
        config["llm"]["sampling"]["temperature"] = 0.9
    elif changed == "judge":
        config["town"]["research"]["judge"]["base_url"] = "https://different.invalid/v1"
    elif changed == "seed":
        config["town"]["seed"] += 1
    elif changed == "milestones":
        config["town"]["research"]["milestones"][0]["max_reward_per_resident"] += 1
    else:
        (academy / "research_reviews/proposal/hash/input.json").write_text(
            json.dumps({"rubric": "Different standards."})
        )
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError, match="protocol|rubrics"):
        compare(town, academy)


def test_distinct_physical_gpu_assignments_preserve_paired_protocol(tmp_path):
    town, academy = make_run(tmp_path, "town", 75), make_run(tmp_path, "academy", 50)
    for root, device in ((town, "device=0"), (academy, "device=1")):
        path = root / "config.yaml"
        config = yaml.safe_load(path.read_text())
        config["town"]["research"]["gpus"] = device
        path.write_text(yaml.safe_dump(config))
    report = compare(town, academy)
    assert report["score_differences"][0]["town_minus_academy"] == 25
    assert report["arms"]["town"]["gpu_assignment"] == "device=0"
    assert report["arms"]["academy"]["gpu_assignment"] == "device=1"


def test_cycle_report_schedules_unreviewed_papers_without_inventing_scores(tmp_path):
    config = load_experiment(
        Path(__file__).resolve().parents[2] / "experiments/configs/ai-lab.yaml"
    )
    run = RunDirectory.create(tmp_path, config.name, config=config, code_revision="test")
    report = summarize(run.root)
    assert report["milestones"] == [
        {"stage": f"cycle-{index:03d}", "day": day, "status": "pending"}
        for index, day in enumerate((28, 49, 70), 1)
    ]
    assert report["milestone_rewards"] == 0
    assert report["completed_day"] is None
