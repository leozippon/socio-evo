import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.agent import prompts
from core.agent.evolution import History, Level, Mode, Trigger
from core.interaction import day_of
from experiments.config import ExperimentConfig
from experiments.run import as_dry_run
from experiments.run import run as run_experiment
from experiments.study import load_study, main
from infrastructure.config import ConfigError, load_config
from infrastructure.git import Repository
from infrastructure.storage import RunDirectory, RunStatus, read_jsonl
from tests.experiments.test_experiments import sent, unguarded, written

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
    # The base town's meetings are for the town on its own; the study is the controlled design.
    assert len(load_config(TOWN, ExperimentConfig).simulation.meetings) == 2
    assert not any(config.simulation.meetings for config in arms.values())

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
            "short": {"simulation": {"days": 2, "interventions": []}},
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


LEVEL_OF = {
    "memory/diary/": Level.L0,
    "memory/insights.jsonl": Level.L0,
    "memory/skills/": Level.L1,
    "parameters/self.md": Level.L2,
    "parameters/policy.md": Level.L2,
}
"""The level at which each of the files a resident writes about itself and its ways changes."""


async def test_a_free_resident_reads_its_own_account_from_its_second_day(tmp_path):
    """The free arm of the smoke study, answered by the scripted model: on day 1 a resident
    reads its profile, on the first night it writes an account of itself, from day 2 it reads
    that account and never its profile, and every night it is asked what it would change in
    what it has written. Every change to that writing is a commit at its level, triggered
    daily; and nothing sent or written steers traits or shows the machinery."""
    _, arms = load_study(STUDIES / "smoke.yaml")
    config = as_dry_run(arms["free"])
    assert (config.name, config.evolution.mode) == ("smoke-free-dry-run", Mode.FREE)
    root, status = await run_experiment(config, 0, tmp_path, resume=False, until_day=None)
    assert status is RunStatus.COMPLETED
    directory = RunDirectory.open(root)
    assert not unguarded(sent(directory)) and not unguarded(written(directory))

    calls = list(read_jsonl(directory.llm_calls_path))
    for seed in config.agents:
        name, backstory = seed.profile.name, seed.profile.backstory
        mine = [call for call in calls if call["metadata"]["agent"] == name]
        for call in mine:
            shown = any(backstory in message["content"] for message in call["request"]["messages"])
            assert shown == (day_of(call["metadata"]["time"]) == 1), call["metadata"]
        revise = [call for call in mine if call["metadata"]["purpose"] == "revise"]
        assert [day_of(call["metadata"]["time"]) for call in revise] == [1, 2, 3]
        required = [
            "about yourself" in call["request"]["json_schema"]["required"] for call in revise
        ]
        assert required == [True, False, False]

        path = directory.agent_dir(name)
        repository, steps = Repository(path), History(path).log()[::-1]
        changes = repository.changes()
        for version in steps[1:]:
            for change in changes[version.commit]:
                level = next((v for k, v in LEVEL_OF.items() if change.path.startswith(k)), None)
                if level is None:
                    assert change.path == "memory/episodic.jsonl", change
                    assert version.level in (None, Level.L0), version
                else:
                    assert version.level is level, (change, version)
        assert {v.trigger for v in steps if v.level} == {Trigger.DAILY}
        assert {day_of(v.time) for v in steps if v.level is Level.L0} == {1, 2, 3}
        [first] = [v for v in steps if v.level is Level.L2 and day_of(v.time) == 1]
        assert "parameters/self.md" in {change.path for change in changes[first.commit]}
        account = repository.read_file(first.commit, "parameters/self.md").strip()
        first_act = next(
            call["request"]["messages"][0]["content"]
            for call in mine
            if call["metadata"]["purpose"] == "act" and day_of(call["metadata"]["time"]) == 2
        )
        assert first_act.startswith(prompts.OWN_ACCOUNT.format(name=name, account=f'"{account}"'))
