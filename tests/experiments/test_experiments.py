import json
import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from core.agent.evolution import Level
from core.interaction import Setting
from experiments.config import ExperimentConfig
from experiments.run import main
from infrastructure.config import ConfigError, load_config
from infrastructure.git import Repository
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


def written(run: RunDirectory) -> list[str]:
    """Every reply the residents of `run` wrote, structured or free."""
    return [call["response"]["text"] for call in read_jsonl(run.llm_calls_path)]


def test_experiment_configs_load_and_profiles_tell_circumstances_only():
    configs = {path.stem: load_config(path, ExperimentConfig) for path in CONFIGS.glob("*.yaml")}
    assert set(configs) == {"smoke", "pilot", "town"}
    for config in configs.values():
        assert not unguarded([config.environment.setting.backdrop]), config.name
        for meeting in config.simulation.meetings:
            assert not unguarded([meeting.question, *meeting.options]), meeting.id
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
    smoke = configs["smoke"]  # the town in small, against the model on the built-in bank
    assert (len(smoke.agents), smoke.simulation.days) == (3, 3)
    assert smoke.environment.conditions == town.environment.conditions.model_copy(
        update={"one_part_tasks": 2, "defect_discovery_prob": 0.3}
    )
    assert sum(place.kind == "social" for place in smoke.environment.places) == 2
    assert smoke.simulation.postings == town.simulation.postings
    assert (smoke.llm, smoke.tasks.isolation) == (town.llm, town.tasks.isolation)
    dollars = town.environment.setting.currency
    assert (dollars.tell(20), smoke.environment.setting.currency) == ("$20", dollars)
    assert pilot.environment.setting == Setting()  # the first pilot's rules: crowns, from a Monday
    for config in (town, smoke):  # the day ends when the last place closes; evenings are social
        places, calendar = config.environment.places, config.simulation.calendar
        social = [place for place in places if place.kind == "social"]
        assert all(place.hours for place in social)
        assert calendar.day_end == max(closes for p in places for _, closes in p.spans())
        assert all(place.is_open(calendar.slots[-1].start) for place in social)


def test_a_configuration_frozen_before_towns_had_a_setting_loads_as_the_town_it_was():
    """A run frozen before the setting existed, such as the first smoke run of the second town,
    has no `setting`: it loads as a nameless town of crowns whose day 1 is a Monday."""
    data = yaml.safe_load((CONFIGS / "smoke.yaml").read_text(encoding="utf-8"))
    del data["environment"]["setting"]
    setting = ExperimentConfig.model_validate(data).environment.setting
    assert (setting.name, setting.backdrop, setting.currency.tell(2)) == (None, "", "2 crowns")
    assert setting.start_date == date(2001, 1, 1) and setting.start_date.weekday() == 0


def test_an_inconsistent_experiment_is_rejected():
    data = yaml.safe_load((CONFIGS / "smoke.yaml").read_text(encoding="utf-8"))
    ExperimentConfig.model_validate(data)
    places = data["environment"]["places"]
    with_hours = [place["id"] for place in places if place.get("hours")]
    assert with_hours == ["workshop", "cafe", "tavern"]
    closes_late = [
        {**place, "hours": ["18:00-23:45"]} if place["id"] == "tavern" else place
        for place in places
    ]
    late = {**data, "environment": {**data["environment"], "places": closes_late}}
    with pytest.raises(ValidationError, match="tavern closes at 23:45, after the day ends at"):
        ExperimentConfig.model_validate(late)
    for broken in (
        late,
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


@pytest.mark.parametrize(
    ("changes", "refusal"),
    [
        ({"enacts": {"maybe": {"esteem_public": False}}}, "enacts answers it lacks: ['maybe']"),
        ({"options": ["yes"]}, "at least 2 items"),
        ({"options": ["yes", "yes"]}, "repeats an answer"),
        ({"options": ["yes", "not now"]}, "should match pattern"),
        ({"at": "midday"}, "tavern is not open from 12:00 until after 12:40"),
        ({"at": "night"}, "not a slot"),
        ({"place": "workshop"}, "no social place workshop"),
        ({"enacts": {"no": {"esteem_public": "never"}}}, "esteem_public"),
        ({"day": 4}, "after the last day 3"),
    ],
)
def test_a_meeting_is_refused_unless_it_can_be_held_and_its_answers_enacted(changes, refusal):
    data = yaml.safe_load((CONFIGS / "smoke.yaml").read_text(encoding="utf-8"))
    planned = data["simulation"]["interventions"]
    [meeting] = [index for index, plan in enumerate(planned) if plan.get("kind") == "meeting"]
    ExperimentConfig.model_validate(data)
    planned[meeting] |= changes
    with pytest.raises(ValidationError, match=re.escape(refusal)):
        ExperimentConfig.model_validate(data)


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


def test_a_run_needs_its_bank_and_isolation_and_a_dry_run_works_on_the_built_in_bank(
    tmp_path, monkeypatch
):
    runs = tmp_path / "runs"
    data = yaml.safe_load((CONFIGS / "town.yaml").read_text(encoding="utf-8"))
    data["tasks"]["bank"] = str(tmp_path / "absent")
    data["simulation"] |= {"days": 1, "interventions": []}
    config = tmp_path / "town.yaml"
    config.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="python -m tasks.coding.fetch"):
        main([str(config), "--seeds", "0", "--runs-root", str(runs)])
    with monkeypatch.context() as patch:
        patch.setattr(shutil, "which", lambda name: None)
        with pytest.raises(RuntimeError, match="bubblewrap"):
            main([str(config), "--seeds", "0", "--runs-root", str(runs), "--dry-run"])
    assert not runs.exists()

    main([str(config), "--seeds", "0", "--runs-root", str(runs), "--dry-run"])
    frozen = RunDirectory.open(runs / "town-dry-run" / "seed-0000").config_path
    tasks = yaml.safe_load(frozen.read_text(encoding="utf-8"))["tasks"]
    assert (tasks["bank"], tasks["isolation"]) == ("tasks/coding/bank", "bubblewrap")


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


def test_a_dry_run_of_the_smoke_town_tells_its_setting_in_every_request(tmp_path):
    """The smoke town on a Wednesday start: what every resident knows opens with the backdrop,
    money is told in dollars and never in crowns, the first day is a Wednesday by the town's
    calendar and by the dates of every resident's history, and nothing sent or written steers
    traits or shows the machinery."""
    data = yaml.safe_load((CONFIGS / "smoke.yaml").read_text(encoding="utf-8"))
    data["environment"]["setting"]["start_date"] = "2001-01-03"
    config = tmp_path / "smoke.yaml"
    config.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    main([str(config), "--seeds", "0", "--runs-root", str(tmp_path), "--dry-run"])

    run = RunDirectory.open(tmp_path / "smoke-dry-run" / "seed-0000")
    calls = list(read_jsonl(run.llm_calls_path))
    acts = [call["request"]["messages"] for call in calls if call["metadata"]["purpose"] == "act"]
    backdrop = " ".join(data["environment"]["setting"]["backdrop"].split())
    assert all(f"town by now:\n{backdrop}\n\nYou live in" in act[0]["content"] for act in acts)
    texts = sent(run)
    assert not [text for text in texts if "crown" in text.lower()]
    assert any("You have $" in text for text in texts) and any("pays $" in text for text in texts)
    assert any("Wednesday, your first day in town" in text for text in texts)
    notice = "The clerk has put up a notice: a meeting at the Anchor at 18:00 today, on the "
    assert any(notice in text for text in texts)
    counted = "The clerk has posted "  # its count, or that nobody came
    assert any(counted in text and "meeting at the Anchor" in text for text in texts)
    assert not any("Monday, your first day" in text for text in texts)
    assert not unguarded(texts)
    assert not unguarded(written(run))
    first = Repository(run.agent_dir("Mei")).log()[-1]
    assert first.date == datetime(2001, 1, 3, tzinfo=UTC)


def test_no_request_in_the_pilot_town_steers_traits_or_shows_machinery(tmp_path):
    """Invariant 1 and the immersion guide end to end: no text the model is sent in a dry run
    of the pilot steers traits or speaks of the machinery, whatever its source: the setting,
    situations, events, views, refusals, task specifications, place descriptions,
    announcements, sandbox feedback when work is handed in, and the answer cards; nor does
    anything a resident writes, whose keys and fixed values come from those cards. The pilot is
    compressed in time so that three days reach every evolution level and intervention."""
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
    assert not unguarded(written(run))


def test_nothing_a_resident_reads_tells_how_long_the_run_lasts(tmp_path):
    """Two runs of one town that differ only in their length send their residents the very
    same requests on the days both have."""
    data = yaml.safe_load((CONFIGS / "town.yaml").read_text(encoding="utf-8"))
    data["simulation"]["interventions"] = []  # the town's meetings come later
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
    for moment in ("the day is ahead of you", "take a job"):
        assert any(moment in request for request in requests[2]), moment
