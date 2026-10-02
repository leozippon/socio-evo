from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from core.agent.evolution import Level
from experiments.config import ExperimentConfig
from experiments.run import main
from infrastructure.config import load_config
from infrastructure.llm import LLMConfigError
from infrastructure.storage import RunDirectory, RunStatus
from tests.core.agent.test_prompts import STEERING

CONFIGS = Path(__file__).parents[2] / "experiments" / "configs"


def test_experiment_configs_load_and_profiles_describe_circumstances_only():
    configs = {path.stem: load_config(path, ExperimentConfig) for path in CONFIGS.glob("*.yaml")}
    assert set(configs) == {"smoke", "pilot"}
    for config in configs.values():
        for seed in config.agents:
            profile = seed.profile
            assert seed.policy == ""
            assert not STEERING.search(f"{profile.occupation} {profile.backstory}"), profile.name
    pilot = configs["pilot"]
    assert (len(pilot.agents), pilot.simulation.days) == (8, 28)
    assert set(pilot.evolution.levels) == {Level.L0, Level.L1, Level.L2}


def test_an_inconsistent_experiment_is_rejected():
    data = yaml.safe_load((CONFIGS / "smoke.yaml").read_text(encoding="utf-8"))
    ExperimentConfig.model_validate(data)
    places = data["environment"]["places"]
    closes_mid_slot = [
        {**place, "hours": ["09:00-11:00"]} if place.get("hours") else place for place in places
    ]
    for broken in (
        {**data, "environment": {**data["environment"], "places": closes_mid_slot}},
        {**data, "agents": data["agents"][:2]},
        {**data, "agents": [*data["agents"], data["agents"][0]]},
        {
            **data,
            "simulation": {
                **data["simulation"],
                "interventions": [{"day": 2, "conditions": {"weather": "rain"}}],
            },
        },
    ):
        with pytest.raises(ValidationError):
            ExperimentConfig.model_validate(broken)


def test_a_configuration_error_leaves_no_run_behind(tmp_path, monkeypatch):
    monkeypatch.delenv("VLLM_API_KEY", raising=False)
    with pytest.raises(LLMConfigError):
        main([str(CONFIGS / "smoke.yaml"), "--seeds", "0", "--runs-root", str(tmp_path)])
    assert not any(tmp_path.iterdir())


def test_a_dry_run_stops_resumes_and_completes(tmp_path, capsys):
    command = [str(CONFIGS / "smoke.yaml"), "--seeds", "3", "--runs-root", str(tmp_path)]
    command.append("--dry-run")
    root = tmp_path / "smoke-dry-run" / "seed-0003"

    main([*command, "--until-day", "1"])
    run = RunDirectory.open(root)
    assert run.read_manifest().status is RunStatus.INTERRUPTED
    with pytest.raises(FileExistsError):
        main(command)
    main([*command, "--resume"])
    manifest = run.read_manifest()
    assert (manifest.status, manifest.seed) == (RunStatus.COMPLETED, 3)
    assert manifest.code_revision
    assert run.latest_checkpoint() == run.checkpoint_path(3)
    assert f"{root}: completed" in capsys.readouterr().out
    with pytest.raises(ValueError):
        main([*command, "--resume"])
