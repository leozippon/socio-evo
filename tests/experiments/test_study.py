import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest
import yaml

from experiments.study import load_study, main
from infrastructure.config import ConfigError
from infrastructure.storage import RunDirectory, RunStatus, read_jsonl
from tests.experiments.test_experiments import sent, unguarded

STUDIES = Path(__file__).parents[2] / "experiments" / "studies"
TOWN = Path(__file__).parents[2] / "experiments" / "configs" / "town.yaml"


def differences(a: Any, b: Any, path: str = "") -> set[str]:
    """The dotted paths at which `a` and `b`, plain data, differ."""
    if isinstance(a, dict) and isinstance(b, dict):
        return {
            d
            for key in a.keys() | b.keys()
            for d in differences(a.get(key), b.get(key), f"{path}.{key}")
        }
    return set() if a == b else {path.lstrip(".")}


def test_the_study_derives_every_arm_from_the_town_by_its_overlays():
    study, arms = load_study(STUDIES / "trust.yaml")
    assert study.seeds == (0, 1, 2, 3, 4)
    dumps = {arm: config.model_dump(mode="json") for arm, config in arms.items()}
    assert set(arms) == {
        "selection-comfortable",
        "selection-scarce",
        "assignment-comfortable",
        "assignment-scarce",
        "solo",
        "no-evolution",
    }
    assert {config.name for config in arms.values()} == {f"trust-{arm}" for arm in arms}

    selection = dumps["selection-comfortable"]
    [late] = arms["selection-comfortable"].simulation.interventions
    assert (late.day, late.conditions) == (
        29,
        {"partner_choice": False, "defect_discovery_prob": 0.0},
    )
    assert differences(selection, dumps["assignment-comfortable"]) == {
        "name",
        "environment.conditions.partner_choice",
        "simulation.interventions",
    }
    assert differences(selection, dumps["selection-scarce"]) == {
        "name",
        "environment.conditions.living_cost",
        "environment.conditions.one_part_tasks",
    }
    assert differences(dumps["selection-scarce"], dumps["assignment-scarce"]) == differences(
        selection, dumps["assignment-comfortable"]
    )
    assert differences(selection, dumps["no-evolution"]) == {"name", "evolution.levels"}
    solo = arms["solo"]
    assert [seed.profile.name for seed in solo.agents] == ["Mei"]
    assert solo.environment.homes == {"Mei": "mill-street-house"}
    assert set(solo.environment.circumstances) == {"Mei"}
    assert solo.environment.conditions.two_part_tasks == 0 and not solo.simulation.interventions
    assert (
        solo.environment.conditions.one_part_tasks
        == arms["selection-comfortable"].environment.conditions.one_part_tasks
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"arms": {"x": ["missing"]}}, "unknown overlays"),
        ({"overlays": {"o": {"residents": ["Zed"]}}, "arms": {"x": ["o"]}}, "Zed"),
        ({"overlays": {"o": {"simulation": {"days": 0}}}, "arms": {"x": ["o"]}}, "arm x"),
    ],
)
def test_a_study_whose_arm_is_invalid_is_refused(tmp_path, changes, message):
    study = {"name": "s", "base": str(TOWN), "seeds": [0], "overlays": {}, "arms": {}} | changes
    path = tmp_path / "s.yaml"
    path.write_text(yaml.safe_dump(study), encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_study(path)


def rows(out: str) -> dict[str, tuple[str, str]]:
    """The status table printed in `out`: each arm's status and days."""
    lines = out[out.index("arm ") :].splitlines()[1:]
    return {arm: (status, days) for arm, _, status, days in (line.split() for line in lines)}


def posted(run: RunDirectory) -> dict[tuple[int, int], list[tuple[list[str], str]]]:
    """The jobs `run` posted, by moment and size, each its parts' sources and its client."""
    jobs = defaultdict(list)
    for event in read_jsonl(run.events_path):
        if event["kind"] == "task_posted":
            task = event["payload"]["task"]
            parts = [part["reference"] for part in task["parts"]]
            jobs[event["time"], len(parts)].append((parts, task["client"]))
    return dict(jobs)


def test_a_study_runs_its_grid_resumes_skips_and_matches_its_seeds(tmp_path, capsys):
    study = {
        "name": "short",
        "base": str(TOWN),
        "seeds": [0],
        "overlays": {
            "short": {"simulation": {"days": 2}},
            "assignment": {"environment": {"conditions": {"partner_choice": False}}},
            "scarce": {"environment": {"conditions": {"living_cost": 30, "one_part_tasks": 1}}},
            "solo": {"residents": ["Mei"], "environment": {"conditions": {"two_part_tasks": 0}}},
        },
        "arms": {
            "selection": ["short"],
            "assignment": ["short", "assignment"],
            "scarce": ["short", "scarce"],
            "solo": ["short", "solo"],
        },
    }
    path = tmp_path / "short.yaml"
    path.write_text(yaml.safe_dump(study), encoding="utf-8")
    runs = tmp_path / "runs"
    command = [str(path), "--dry-run", "--workers", "4", "--runs-root", str(runs)]

    main([*command, "--until-day", "1"])
    out = capsys.readouterr().out
    assert out.count(": interrupted") == 4
    assert rows(out) == dict.fromkeys(study["arms"], ("interrupted", "1/2"))
    directories = {
        arm: RunDirectory(runs / f"short-{arm}-dry-run" / "seed-0000") for arm in study["arms"]
    }
    main(command)
    assert all(run.read_manifest().status is RunStatus.COMPLETED for run in directories.values())
    logs = {arm: run.events_path.read_bytes() for arm, run in directories.items()}
    capsys.readouterr()
    main(command)
    out = capsys.readouterr().out
    assert ": completed" not in out
    assert rows(out) == dict.fromkeys(study["arms"], ("completed", "2/2"))
    assert {arm: run.events_path.read_bytes() for arm, run in directories.items()} == logs
    main([*command, "--status"])
    assert rows(capsys.readouterr().out) == dict.fromkeys(study["arms"], ("completed", "2/2"))

    jobs = {arm: posted(run) for arm, run in directories.items()}
    assert jobs["selection"] == jobs["assignment"]
    for arm in ("scarce", "solo"):
        assert jobs[arm] and all(
            jobs[arm][moment] == jobs["selection"][moment][: len(jobs[arm][moment])]
            for moment in jobs[arm]
        )
    for run in directories.values():
        assert not unguarded(sent(run))
        config = yaml.safe_load(run.config_path.read_text(encoding="utf-8"))
        assert json.dumps(config).count("dry-run") == 1
