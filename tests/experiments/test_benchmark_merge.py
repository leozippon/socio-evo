"""Local benchmark integrations remain usable with the upstream multi-trade runtime."""

import json
from pathlib import Path

import pytest

from analysis.traits import shares
from core.environment import Assessment, Trade
from evaluation.config import EvaluationConfig
from experiments.config import PROJECT_ROOT, ExperimentConfig
from experiments.run import as_dry_run, close_providers, setup
from infrastructure.config import load_config
from tasks.swebench.provider import SWEbenchTaskProvider


def test_zenith_profiles_and_evaluation_load():
    for path in [
        PROJECT_ROOT / "experiments/configs/zenith-direct-smoke.yaml",
        PROJECT_ROOT / "experiments/configs/zenith/town.yaml",
        PROJECT_ROOT / "experiments/configs/zenith/swebench-town.yaml",
    ]:
        config = load_config(path, ExperimentConfig)
        assert set(config.tasks.banks) == {Trade.PROGRAMMING}
    evaluation = load_config(
        PROJECT_ROOT / "evaluation/configs/zenith-livecodebench.yaml", EvaluationConfig
    )
    assert len(evaluation.families) == 9
    assert evaluation.bank == Path("/personal_fast_storage/datasets/livecodebench")


async def test_swebench_setup_uses_json_bank_and_new_provider_map(tmp_path):
    data = tmp_path / "verified.json"
    data.write_text(
        json.dumps(
            [
                {"instance_id": name, "repo": "org/repo", "problem_statement": "Fix the bug"}
                for name in ("pallets__flask-5014", "astropy__astropy-12907")
            ]
        )
    )
    config = load_config(
        PROJECT_ROOT / "experiments/configs/zenith/swebench-town.yaml", ExperimentConfig
    )
    config = config.model_copy(
        update={
            "tasks": config.tasks.model_copy(update={"banks": {Trade.PROGRAMMING: str(data)}}),
            "llm": config.llm.model_copy(update={"backend": "scripted"}),
        }
    )
    parts = setup(config, 0, tmp_path / "run/llm_calls.jsonl")
    provider = parts.providers[Trade.PROGRAMMING]
    assert isinstance(provider, SWEbenchTaskProvider)
    assert "WORKTREE" in provider.part("pallets__flask-5014").specification
    with pytest.raises(ValueError, match="repository repairs"):
        as_dry_run(config)
    await close_providers(parts)


def test_swebench_hardcoding_metric_is_unavailable_without_reading_dataset():
    assessment = Assessment(passed=True, quality=1, feedback="Repository tests pass")
    assert assessment.special_cased is None
    from analysis.traits import COUNTS

    counts = dict.fromkeys(COUNTS, 0)
    counts["checked_finished"] = 2
    assert shares(counts)["special_cased_share"] is None
