from pathlib import Path

import pytest

from experiments.config import ExperimentConfig
from infrastructure.config import load_config
from tasks.swebench.fetch import save_bank


@pytest.mark.parametrize("variant,days", [("lite", 3), ("verified", 42)])
def test_community_configuration(variant, days):
    cfg = load_config(Path(f"experiments/configs/community/{variant}.yaml"), ExperimentConfig)
    assert len(cfg.agents) == 8 and cfg.simulation.days == days
    assert cfg.tasks.repository_guidance
    assert cfg.environment.posting_mode == "replenish"
    assert cfg.environment.task_shelf_life_days is None and cfg.environment.strict_acceptance
    assert cfg.simulation.postings == ("morning",)
    assert cfg.environment.conditions.one_part_tasks == 8
    assert cfg.environment.conditions.two_part_tasks == 0
    assert cfg.environment.starting_balance("Aisha") == 30
    assert cfg.environment.obligation("Jonas") == 8
    assert cfg.environment.obligation("Ravi") == 10
    assert cfg.cognition.work_notes.editable and cfg.cognition.active_recall.enabled
    assert cfg.cognition.context_budget.enabled
    for place in cfg.environment.places:
        if place.kind == "work":
            assert place.is_open("08:00") and place.is_open("14:00")
            assert not place.is_open("13:30")
        if place.kind == "social":
            assert not place.is_open("22:00")


def test_bank_manifest_and_no_accidental_replacement(tmp_path):
    import hashlib
    import json

    rows = [
        {
            "instance_id": "org__repo-1",
            "repo": "org/repo",
            "base_commit": "abc",
            "problem_statement": "Fix it",
            "patch": "private grading data",
        }
    ]
    dest = tmp_path / "verified"
    path = save_bank(rows, dest, variant="verified", revision="pinned-sha")
    manifest = json.loads((dest / "manifest.json").read_text())
    assert manifest["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert manifest["revision"] == "pinned-sha" and manifest["variant"] == "verified"
    with pytest.raises(FileExistsError):
        save_bank(rows, dest, variant="verified", revision="other-sha")


def test_repository_guidance_is_opt_in_for_old_configs():
    from experiments.config import TasksConfig

    assert not TasksConfig().repository_guidance
    assert not TasksConfig(provider="swebench").repository_guidance
    with pytest.raises(ValueError, match="requires the swebench provider"):
        TasksConfig(repository_guidance=True)


@pytest.mark.parametrize("variant", ["lite", "verified", "activities", "realtime"])
async def test_community_posts_and_replenishes_only_solo_jobs(variant, tmp_path):
    from core.environment import Environment
    from core.interaction import ClaimTask, SubmitWork, time_at
    from tests.core.environment.test_environment import act, go
    from tests.core.environment.test_technical_community import RepositoryProvider

    config = load_config(Path(f"experiments/configs/community/{variant}.yaml"), ExperimentConfig)
    env = Environment.create(
        config.environment, list(config.environment.homes), RepositoryProvider(),
        tmp_path / "events.jsonl",
    )
    env.post(time_at(1, "07:00"), 0)
    assert len(env.board.listings) == 8
    assert all(listing.task.worker_count == 1 for listing in env.board.listings.values())
    original = set(env.board.listings)
    task = next(iter(env.board.listings))
    go(env, "workshop", "Mei")
    await act(env, "Mei", ClaimTask(task_id=task))
    await act(env, "Mei", SubmitWork(task_id=task, solution="perfect", report="Ready"))
    assert env.board.claim_of("Mei") is None
    assert len(env.board.listings) == 8
    assert set(env.board.listings) != original
    assert all(listing.task.worker_count == 1 for listing in env.board.listings.values())
