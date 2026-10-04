import json
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
from tests.core.agent.test_prompts import MACHINERY, SIMULATOR_TERMS, STEERING

CONFIGS = Path(__file__).parents[2] / "experiments" / "configs"
GUARDS = (STEERING, MACHINERY, SIMULATOR_TERMS)
"""What no text a resident reads may contain: trait words, and the machinery's terms."""


def unguarded(texts: list[str]) -> set[str]:
    """The lines of `texts` that a guard catches."""
    lines = {line for text in texts for line in text.splitlines()}
    return {line for line in lines if any(guard.search(line) for guard in GUARDS)}


def sent(run: RunDirectory) -> list[str]:
    """Every message the residents of `run` were sent."""
    calls = read_jsonl(run.llm_calls_path)
    return [message["content"] for call in calls for message in call["request"]["messages"]]


def test_experiment_configs_load_and_profiles_tell_circumstances_only():
    configs = {path.stem: load_config(path, ExperimentConfig) for path in CONFIGS.glob("*.yaml")}
    assert set(configs) == {"smoke", "pilot", "town"}
    for config in configs.values():
        for seed in config.agents:
            profile = seed.profile
            assert seed.policy == ""
            assert profile.backstory.startswith("You "), profile.name
            assert not STEERING.search(f"{profile.occupation} {profile.backstory}"), profile.name
            assert not unguarded([profile.backstory]), profile.name
    pilot = configs["pilot"]
    assert (len(pilot.agents), pilot.simulation.days) == (8, 28)
    assert set(pilot.evolution.levels) == {Level.L0, Level.L1, Level.L2}
    town = configs["town"]
    conditions, own = town.environment.conditions, town.environment.circumstances
    assert (len(town.agents), town.simulation.days) == (8, 42)
    assert conditions.one_part_tasks and conditions.two_part_tasks
    assert 0 < conditions.trusting_client_prob < 1 and conditions.partner_choice
    assert len({town.environment.starting_balance(seed.profile.name) for seed in town.agents}) > 4
    assert own["Ravi"].obligation and "send money home" in town.agents[5].profile.backstory
    assert set(town.evolution.levels) == {Level.L0, Level.L1, Level.L2}
    assert town.simulation.postings == ("morning", "afternoon")


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


def test_no_request_in_the_pilot_town_steers_traits_or_shows_machinery(tmp_path):
    """Invariant 1 and the immersion guide end to end: no text the model is sent in a dry run
    of the pilot steers traits or speaks of the machinery, whatever its source: the setting,
    situations, events, views, refusals, task specifications, place descriptions,
    announcements, and sandbox feedback when work is handed in. The pilot is compressed in
    time so that three days reach every evolution level and intervention."""
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
    texts = sent(run)
    assert any(simulation["interventions"][0]["announcement"] in text for text in texts)
    assert not unguarded(texts)


def test_nothing_a_resident_reads_tells_how_long_the_run_lasts(tmp_path):
    """Two runs of one town that differ only in their length send their residents the very
    same requests on the days both have."""
    data = yaml.safe_load((CONFIGS / "town.yaml").read_text(encoding="utf-8"))
    requests = {}
    for days in (2, 3):
        data["simulation"]["days"] = days
        config = tmp_path / f"{days}.yaml"
        config.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        runs = tmp_path / f"runs-{days}"
        main(
            [str(config), "--seeds", "0", "--runs-root", str(runs), "--until-day", "2", "--dry-run"]
        )
        run = RunDirectory.open(runs / "town-dry-run" / "seed-0000")
        requests[days] = sorted(
            json.dumps(call["request"], sort_keys=True) for call in read_jsonl(run.llm_calls_path)
        )
    assert requests[2] == requests[3]
    for moment in ("the day is ahead of you", "You could take a job"):
        assert any(moment in request for request in requests[2]), moment
