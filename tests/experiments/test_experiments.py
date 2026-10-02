import re
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from core.agent.evolution import Level
from experiments.config import ExperimentConfig
from experiments.run import main
from infrastructure.config import ConfigError, load_config
from infrastructure.llm import LLMConfigError
from infrastructure.storage import RunDirectory, RunStatus, read_jsonl
from tests.core.agent.test_prompts import STEERING

CONFIGS = Path(__file__).parents[2] / "experiments" / "configs"
# "Esteem" is the name of a mechanism of the town, the published mean of the peer ratings an
# agent received, not an instruction about a trait. Only that name is allowed, where the
# esteem board introduces it; any other use of the word still fails the scan below.
# ("Reputation" reaches no agent, so it needs no allowance.)
MECHANISM = re.compile(r"\bEsteem(?=, the mean peer rating\b)")


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
    runs = tmp_path / "runs"
    monkeypatch.delenv("VLLM_API_KEY", raising=False)
    with pytest.raises(LLMConfigError):
        main([str(CONFIGS / "smoke.yaml"), "--seeds", "0", "--runs-root", str(runs)])
    data = yaml.safe_load((CONFIGS / "smoke.yaml").read_text(encoding="utf-8"))
    data["evolution"]["levels"] = ["L0", "L3"]
    unimplemented = tmp_path / "l3.yaml"
    unimplemented.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="L3"):
        main([str(unimplemented), "--seeds", "0", "--runs-root", str(runs), "--dry-run"])
    assert not runs.exists()


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


def test_no_request_in_the_pilot_town_steers_traits(tmp_path):
    """Invariant 1 end to end: no text the model is sent in a dry run of the pilot steers
    traits, whatever its source: situations, events, views, rejections, task specifications,
    place descriptions, announcements, and sandbox feedback when a delivery is made. The
    pilot is compressed in time so that three days reach every evolution level and
    intervention."""
    data = yaml.safe_load((CONFIGS / "pilot.yaml").read_text(encoding="utf-8"))
    simulation = data["simulation"]
    simulation["days"] = 3
    simulation["calendar"] |= {"weekly_days": 2, "monthly_days": 3}
    for day, intervention in zip((2, 3), simulation["interventions"], strict=True):
        intervention["day"] = day
    config = tmp_path / "pilot.yaml"
    config.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    main([str(config), "--seeds", "0", "--runs-root", str(tmp_path), "--dry-run"])

    run = RunDirectory.open(tmp_path / "pilot-dry-run" / "seed-0000")
    calls = list(read_jsonl(run.llm_calls_path))
    purposes = {call["metadata"]["purpose"] for call in calls}
    assert purposes == {"act", "diary", "reflect", "skills", "policy"}
    sent = [message["content"] for call in calls for message in call["request"]["messages"]]
    assert any(simulation["interventions"][0]["announcement"] in text for text in sent)
    lines = {line for text in sent for line in MECHANISM.sub("", text).splitlines()}
    assert not {line for line in lines if STEERING.search(line)}
