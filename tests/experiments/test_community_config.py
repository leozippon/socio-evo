from pathlib import Path

import pytest

from experiments.config import ExperimentConfig
from infrastructure.config import load_config
from tasks.swebench.fetch import save_bank


@pytest.mark.parametrize("variant,days", [("lite", 3), ("verified", 42)])
def test_community_configuration(variant, days):
    cfg = load_config(Path(f"experiments/configs/community/{variant}.yaml"), ExperimentConfig)
    assert len(cfg.agents) == 8 and cfg.simulation.days == days
    assert cfg.environment.posting_mode == "replenish"
    assert cfg.environment.task_shelf_life_days is None and cfg.environment.strict_acceptance
    assert cfg.simulation.postings == ("morning",)
    assert cfg.environment.conditions.one_part_tasks == 6
    assert cfg.environment.conditions.two_part_tasks == 1
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
