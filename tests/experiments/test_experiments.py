import json
import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from core.agent.evolution import Level
from core.environment import Trade
from core.interaction import Card, MaySubmit, Setting
from experiments.config import PROJECT_ROOT, ExperimentConfig
from experiments.dry_run import DryRunResponder
from experiments.run import main
from infrastructure.config import ConfigError, load_config
from infrastructure.git import Repository
from infrastructure.llm import LLMConfigError, LLMRequest, Message
from infrastructure.storage import RunDirectory, RunStatus, read_jsonl
from tasks import BUILT_IN
from tasks.calculation.answers import extract
from tasks.queries import sql
from tests.core.agent.test_prompts import MACHINERY, SIMULATOR_TERMS, STEERING
from tests.runtime.test_simulation import told_twice

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
    assert set(configs) == {"smoke", "pilot", "town", "firm"}
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


def test_a_configuration_frozen_before_towns_had_trades_names_the_programming_bank_alone():
    """A run frozen before trades names one `bank`, the programming trade's; it loads as the
    banks of that trade alone, and the mix must post only trades the town has a bank of."""
    data = yaml.safe_load((CONFIGS / "smoke.yaml").read_text(encoding="utf-8"))
    assert data["tasks"] == {"bank": "tasks/coding/bank", "timeout": 5.0, "isolation": "bubblewrap"}
    tasks = ExperimentConfig.model_validate(data).tasks
    assert tasks.banks == {Trade.PROGRAMMING: "tasks/coding/bank"}
    assert tasks.model_dump(mode="json")["banks"] == {"programming": "tasks/coding/bank"}
    assert "bank" not in tasks.model_dump()
    both = {**data, "tasks": {**data["tasks"], "banks": {"queries": "q"}}}
    with pytest.raises(ValidationError, match="under `banks`, or one `bank` alone"):
        ExperimentConfig.model_validate(both)
    conditions = data["environment"]["conditions"]
    mixed = {
        **data,
        "environment": {
            **data["environment"],
            "conditions": {**conditions, "trade_mix": {"programming": 1, "queries": 1}},
        },
    }
    with pytest.raises(
        ValidationError, match="the trade mix posts \\['queries'\\], of which the town has no bank"
    ):
        ExperimentConfig.model_validate(mixed)
    later = {
        **data,
        "simulation": {
            **data["simulation"],
            "interventions": [{"day": 2, "conditions": {"trade_mix": {"calculation": 1}}}],
        },
    }
    with pytest.raises(ValidationError, match="no bank"):
        ExperimentConfig.model_validate(later)
    banks = {**data, "tasks": {"banks": {"programming": "tasks/coding/bank", "queries": "q"}}}
    with_queries = ExperimentConfig.model_validate(banks)
    assert with_queries.tasks.banks[Trade.QUERIES] == "q"


def test_the_dry_run_hands_in_a_valid_stub_of_every_trade():
    responder = DryRunResponder(
        ExperimentConfig.model_validate(
            yaml.safe_load((CONFIGS / "smoke.yaml").read_text(encoding="utf-8"))
        ),
        0,
    )
    for delivery in ("query", "answer"):
        card = Card([MaySubmit(task_id="task-1", parts=(1,), delivery=delivery)])
        request = LLMRequest(
            messages=(Message(role="user", content="The client asks: how many?"),),
            json_schema=card.model.model_json_schema(),
        )
        reply = card.model.model_validate(responder(request))
        handed_in = card.decision(reply).action.solution
        if delivery == "query":
            assert sql.reads_only(handed_in)
        else:
            assert extract(handed_in) is not None


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
    assert tasks["banks"] == {"programming": "tasks/coding/bank"}
    assert tasks["isolation"] == "bubblewrap"


def test_a_dry_run_of_a_town_of_three_trades_works_on_their_built_in_banks(tmp_path):
    """Each bank a town names, wherever it is, is replaced in a dry run by the built-in bank of
    its trade, so a town posting all three trades runs to its end without a fetched bank, and
    nothing its residents read steers traits or shows the machinery."""
    data = yaml.safe_load((CONFIGS / "smoke.yaml").read_text(encoding="utf-8"))
    absent = {trade.value: str(tmp_path / "absent" / trade.value) for trade in Trade}
    data["tasks"] = {"banks": absent, "isolation": "bubblewrap"}
    data["environment"]["conditions"]["trade_mix"] = {trade.value: 1 for trade in Trade}
    config = tmp_path / "three.yaml"
    config.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    main([str(config), "--seeds", "0", "--runs-root", str(tmp_path), "--dry-run"])

    run = RunDirectory.open(tmp_path / "smoke-dry-run" / "seed-0000")
    assert run.read_manifest().status is RunStatus.COMPLETED
    frozen = yaml.safe_load(run.config_path.read_text(encoding="utf-8"))["tasks"]["banks"]
    assert frozen == {
        trade.value: BUILT_IN[trade].relative_to(PROJECT_ROOT).as_posix() for trade in Trade
    }
    log = [json.loads(line) for line in run.events_path.read_text(encoding="utf-8").splitlines()]
    posted = {e["payload"]["task"]["trade"] for e in log if e["kind"] == "task_posted"}
    assert posted == {trade.value for trade in Trade}
    assert not unguarded(sent(run))


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
    calendar and by the dates of every resident's history, nothing sent or written steers
    traits or shows the machinery, and no moment tells a notice, a hand-in or the standings
    twice."""
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
    twice, checked = told_twice(run)
    assert checked and not twice, twice
    assert any("tonight's standings" in text for text in texts)


def test_a_dry_run_of_the_firm_town_pays_wages_and_posts_its_place(tmp_path):
    """The firm town dry-run: the firm's sheet is posted to and its people paid their wages,
    the board says the firm has a place to fill, the scripted model favours asking for it,
    taking people on, dismissing and giving notice, and nothing read steers or shows the
    machinery."""
    main([str(CONFIGS / "firm.yaml"), "--seeds", "0", "--runs-root", str(tmp_path), "--dry-run"])
    run = RunDirectory.open(tmp_path / "firm-dry-run" / "seed-0000")
    log = [json.loads(line) for line in run.events_path.read_text(encoding="utf-8").splitlines()]
    kinds = {event["kind"] for event in log}
    assert {"wage_paid", "task_posted"} <= kinds
    assert any(e["payload"].get("task", {}).get("sheet") == "ostrander" for e in log)
    texts = sent(run)
    assert any("Ostrander & Co. has a place for a programmer at $30 a day" in t for t in texts)
    assert any("You work at Ostrander & Co. (Mei is the foreman); $30 a day" in t for t in texts)
    assert any('"do": "ask for a place", "at": "Ostrander & Co."' in t for t in texts)
    assert not unguarded(texts)
    assert not unguarded(written(run))


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
