import asyncio
import itertools
import json
import re
import shutil
import tempfile
from datetime import date

import pytest
import yaml
from pydantic import ValidationError

from core.agent import CognitionConfig
from core.agent.evolution import History, Level, Trigger
from core.environment import EnvironmentState, Trade
from core.interaction import card, day_of, time_at
from evaluation import (
    DEFAULT_CONFIG,
    FAMILIES,
    AgentResult,
    Dimension,
    EvaluationConfig,
    Outcome,
    ProbeResult,
    Variant,
    estimate,
    evaluate,
    read_results,
    read_scores,
)
from evaluation.probes import Played, Unit
from experiments.config import ExperimentConfig
from infrastructure.config import ConfigError, load_config
from infrastructure.git import Repository
from infrastructure.llm import LLMRequest, ScriptedClient
from infrastructure.storage import RunDirectory
from runtime.simulation import Checkpoint
from tasks import BUILT_IN
from tests.core.agent.test_prompts import choices, offered
from tests.evaluation.conftest import HERE, SOLUTIONS, judge_client, make_run, town

ALL = list(FAMILIES)
FIRM = HERE.parents[1] / "experiments" / "configs" / "firm.yaml"


class Anyone:
    """A scripted resident for any moment: it carries on quietly, and plans a day at the
    first places its card offers; every request is kept."""

    def __init__(self, words=None) -> None:
        self.requests: list[LLMRequest] = []
        self.words = words

    def __call__(self, request: LLMRequest):
        self.requests.append(request)
        forms = offered(request)
        if card.DECIDE in forms:
            parts = {
                key: values[0] for key, values in choices(request, card.DECIDE).items() if values
            }
            return {"thought": "A day.", "do": card.DECIDE, **parts, card.PLAN: "A day."}
        if self.words and card.SAY in forms:
            return {"thought": "Hm.", "do": card.SAY, card.TO: None, card.WORDS: self.words()}
        return {"thought": "Quiet.", "do": card.CARRY_ON}


def _files(run: RunDirectory) -> dict[str, bytes]:
    """Every file of the run outside its evaluation results, agent repositories included."""
    return {
        str(path.relative_to(run.root)): path.read_bytes()
        for path in sorted(run.root.rglob("*"))
        if path.is_file() and run.evaluation_dir not in path.parents
    }


def _evaluate(run, days, config, resident, **options):
    experiment = town()
    return evaluate(
        run,
        days,
        config,
        client=ScriptedClient(resident),
        judge=judge_client(),
        cognition=CognitionConfig(),
        environment=experiment.environment,
        simulation=experiment.simulation,
        **options,
    )


async def test_evaluation_writes_one_result_per_resident_day_and_variant_and_nothing_else(
    run, config, tmp_path, monkeypatch
):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    before = _files(run)
    names = sorted(path.name for path in run.agents_dir.iterdir())
    heads = {name: History(run.agent_dir(name)).head() for name in names}
    resident = Anyone()
    chosen = config(levels=[1], repetitions=1, variants=["full", "no-policy-no-insights"])

    paths = await _evaluate(run, [2, 0, 2], chosen, resident)
    expected = {
        run.evaluation_path(f"day-{day:04d}{suffix}", name)
        for day in (0, 2)
        for name in names
        for suffix in ("", "-no-policy-no-insights")
    }
    assert set(paths) == expected and len(paths) == len(expected)
    assert _files(run) == before
    for name, head in heads.items():
        assert History(run.agent_dir(name)).head() == head
        assert not Repository(run.agent_dir(name)).has_changes()
    assert list(scratch.iterdir()) == []

    results = {(r.agent, r.day, r.variant): r for r in read_results(run)}
    mei = results[("Mei", 2, Variant.FULL)]
    versions = History(run.agent_dir("Mei")).log()
    assert (mei.format, mei.commit, list(mei.probes)) == (2, versions[0].commit, ALL)
    assert results[("Mei", 0, Variant.FULL)].commit == versions[-1].commit
    for name, probe in mei.probes.items():
        family = FAMILIES[name]
        [outcome] = probe.repetitions
        assert (probe.dimension, probe.unit, list(probe.curve)) == (family.trait, family.unit, [1])
        assert (outcome.level, outcome.repetition, outcome.surface) == (1, 0, 0)
        assert outcome.stake == family.stake(1, 20) and outcome.outcome is not None
        assert all(isinstance(step["observation"], dict) for step in outcome.transcript)

    policy = "resolves to keep a tidy desk"
    for request in resident.requests:
        agent, day = request.metadata["agent"], day_of(request.metadata["time"])
        remembered = re.findall(r"\w+ worked on Day \d", request.messages[-1].content)
        if remembered:
            assert day in (3, 4) and remembered == [f"{agent} worked on Day {d}" for d in (1, 2)]
        else:
            assert day in (1, 2)
    full = [r for r in resident.requests if policy in r.messages[0].content]
    assert full and len(full) * 2 == len(resident.requests)

    rows = read_scores(run)
    assert len(rows) == len(names) * 2 * 2 * len(ALL)
    row = next(
        r
        for r in rows
        if (r.agent, r.day, r.variant, r.probe) == ("Mei", 2, "full", "short_of_living")
    )
    assert (row.dimension, row.level, row.stake, row.unit, row.repetition) == (
        "cooperation",
        1,
        10,
        "money",
        0,
    )
    assert (row.surface, row.outcome, row.score) == (0, "gave_nothing", 0.0)


async def test_repetitions_run_on_separate_exports_and_never_see_one_another(run, config):
    notes = itertools.count()
    resident = Anyone(words=lambda: f"Note {next(notes)}.")
    chosen = config(families=["short_of_living"], levels=[2], repetitions=3)
    await _evaluate(run, [2], chosen, resident)
    prompts = [r.messages[-1].content for r in resident.requests if r.metadata["agent"] == "Mei"]
    second = [prompt for prompt in prompts if "Even part of it" in prompt]
    first = [prompt for prompt in prompts if prompt not in second]
    assert len(first) == len(second) == 3
    assert not any("Note" in prompt for prompt in first)
    seen = [re.findall(r"Note \d+", prompt) for prompt in second]
    assert all(len(found) == 1 for found in seen) and len({found[0] for found in seen}) == 3
    [result] = [r for r in read_results(run) if r.agent == "Mei"]
    surfaces = [outcome.surface for outcome in result.probes["short_of_living"].repetitions]
    assert surfaces == [0, 1, 2]


async def test_a_probe_puts_up_its_job_alone_on_the_board_whatever_trades_and_firms_a_town_has(
    config, tmp_path
):
    """In a town of three trades with a firm, every family plays on every surface it is given:
    each probe puts up its own job alone, on the board of a work place that is no firm's, told
    as the programming job it is; and the firm's foreman and staff hold their places there in
    every status they are shown, as they remember them."""
    data = yaml.safe_load(FIRM.read_text(encoding="utf-8"))
    data["environment"]["conditions"]["trade_mix"] = dict.fromkeys(map(str, Trade), 1)
    data["tasks"]["banks"] = {str(trade): str(path) for trade, path in BUILT_IN.items()}
    experiment = ExperimentConfig.model_validate(data)
    run = make_run(tmp_path, experiment)
    resident = Anyone()
    await evaluate(
        run,
        [2],
        config(levels=[1], repetitions=2),
        client=ScriptedClient(resident),
        judge=judge_client(),
        cognition=CognitionConfig(),
        environment=experiment.environment,
        simulation=experiment.simulation,
    )
    results = read_results(run)
    assert sorted(result.agent for result in results) == ["Aisha", "Mei", "Tomas"]
    assert all(list(result.probes) == ALL for result in results)
    prompts = {result.agent: [] for result in results}
    for request in resident.requests:
        prompts[request.metadata["agent"]].append(request.messages[-1].content)
    texts = [text for told in prompts.values() for text in told]
    boards = [re.findall(r"^- Job .*$", text, re.M) for text in texts if "On the board:" in text]
    assert any(boards)
    for jobs in boards:
        assert len(jobs) <= 1 and all('": a programming job for ' in job for job in jobs), jobs
    assert not any("You are at Ostrander & Co." in text for text in texts)
    held = {
        "Mei": "You are the foreman of Ostrander & Co.; its staff are Tomas",
        "Tomas": "You work at Ostrander & Co. (Mei is the foreman); $30 a day",
    }
    for name, position in held.items():
        shown = [
            text
            for text in prompts[name]
            if "You are not working on any job." in text or "You are working on " in text
        ]
        assert shown and all(position in text for text in shown), name


async def test_existing_results_are_kept_unless_replacing_them_is_asked_for(run, config):
    resident = Anyone()
    chosen = config(families=["shared_notice"], levels=[1])

    async def day_1(**options):
        return await _evaluate(run, [1], chosen, resident, **options)

    paths = await day_1()
    written, calls = [path.read_bytes() for path in paths], len(resident.requests)
    with pytest.raises(FileExistsError):
        await day_1()
    assert [path.read_bytes() for path in paths] == written and len(resident.requests) == calls
    assert await day_1(overwrite=True) == paths


async def test_a_failing_repetition_cancels_the_others(run, config, monkeypatch):
    cancelled = asyncio.Event()

    class Waiting(type(FAMILIES["shared_notice"])):
        async def play(self, town, level, surface, judge):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    class Failing(type(FAMILIES["short_of_living"])):
        async def play(self, town, level, surface, judge) -> Played:
            await asyncio.sleep(0)
            raise RuntimeError("the probe failed")

    monkeypatch.setitem(FAMILIES, "shared_notice", Waiting())
    monkeypatch.setitem(FAMILIES, "short_of_living", Failing())
    chosen = config(families=["shared_notice", "short_of_living"], levels=[1])
    with pytest.raises(ExceptionGroup) as raised:
        await _evaluate(run, [2], chosen, Anyone())
    assert raised.group_contains(RuntimeError, match="the probe failed") and cancelled.is_set()


async def test_nothing_runs_unless_every_resident_day_and_family_can_be_evaluated(
    run, config, tmp_path
):
    resident = Anyone()

    def attempt(days, chosen=None):
        return _evaluate(run, days, chosen or config(levels=[1]), resident)

    for days in ([], [-1], [0, 3]):
        with pytest.raises(ValueError):
            await attempt(days)
    run.checkpoint_path(1).unlink()
    with pytest.raises(ValueError, match="no checkpoint"):
        await attempt([1])
    broken = tmp_path / "work.yaml"
    work = yaml.safe_load(config().work.read_text(encoding="utf-8"))
    work["families"]["handed_back"][0]["draft"] = SOLUTIONS["slugify"]["reference"]
    broken.write_text(yaml.safe_dump(work), encoding="utf-8")
    with pytest.raises(ValueError, match="handed_back"):
        await attempt([2], config(levels=[1], work=broken))
    # Mei evolved on day 3 before the run failed, so the day has no checkpoint.
    History(run.agent_dir("Mei"), date(2001, 1, 1)).commit_step(
        Level.L0, Trigger.DAILY, time_at(3, "22:00"), "Reflect"
    )
    with pytest.raises(ValueError, match="latest checkpoint, day 2"):
        await attempt([3])
    assert resident.requests == [] and list(run.evaluation_dir.iterdir()) == []


def test_the_estimate_bounds_the_calls_of_a_selection(config):
    default = config()
    cost = estimate(default, residents=8, days=7)
    per = 8 * 7 * 4 * 3
    assert cost.scenes == per * len(FAMILIES)
    assert cost.fewest == per * sum(family.calls[0] for family in FAMILIES.values())
    assert cost.most == per * sum(family.calls[1] for family in FAMILIES.values())
    assert cost.judged == per * sum(family.calls[2] for family in FAMILIES.values())
    narrow = config(
        families=["shared_notice"], levels=[1, 4], repetitions=2, variants=list(Variant)
    )
    assert estimate(narrow, residents=3, days=2) == type(cost)(
        scenes=3 * 2 * 2 * 2 * 4, fewest=96, most=96, judged=0
    )


def test_the_default_config_plays_every_family_with_a_judge_of_another_family(tmp_path):
    default = load_config(DEFAULT_CONFIG, EvaluationConfig)
    assert (default.families, default.levels, default.repetitions) == (
        tuple(FAMILIES),
        (1, 2, 3, 4),
        3,
    )
    assert all(family.surfaces == default.repetitions for family in FAMILIES.values())
    assert default.variants == (Variant.FULL,)
    judge = default.judge
    assert (judge.base_url, judge.model, judge.sampling.temperature) == (
        "https://api.deepseek.com/v1",
        "deepseek-v4-pro",
        0.0,
    )
    assert judge.structured_output == "json_object" and "qwen" not in judge.model
    path = tmp_path / "evaluation.yaml"
    for bad in (
        {"families": ["mind_reading"]},
        {"families": ["shared_notice"] * 2},
        {"levels": [5]},
        {"variants": ["no-memory"]},
        {"colour": 1},
    ):
        path.write_text(yaml.safe_dump({**default.model_dump(mode="json"), **bad}))
        with pytest.raises(ConfigError):
            load_config(path, EvaluationConfig)


def test_aggregates_give_a_curve_a_switching_level_and_leave_out_the_unscored():
    def outcome(level, score):
        return Outcome(score=score, measures={"given": score}, transcript=(), level=level)

    played = [outcome(1, 1.0), outcome(1, None), outcome(2, 1.0), outcome(2, 0.0), outcome(3, 0.0)]
    played += [outcome(4, None)]
    result = ProbeResult.of(Dimension.COOPERATION, played, Unit.MONEY)
    assert result.curve == {1: 1.0, 2: 0.5, 3: 0.0, 4: None}
    assert (result.score, result.switch, result.unit) == (0.5, 3, Unit.MONEY)
    held = ProbeResult.of(Dimension.COOPERATION, [outcome(1, 1.0), outcome(2, 1.0)])
    assert (held.score, held.switch) == (1.0, None)
    unscored = ProbeResult.of(Dimension.COOPERATION, [outcome(1, None)])
    assert (unscored.score, unscored.switch, unscored.curve) == (None, None, {1: None})


def test_results_of_the_first_pilot_still_load_and_read_as_rows(tmp_path):
    run = RunDirectory.create(tmp_path, "pilot", 0, config=town(), code_revision="x")
    target = run.evaluation_path("day-0007", "Kofi")
    target.parent.mkdir(parents=True)
    shutil.copy(HERE / "pilot_result.json", target)
    [result] = read_results(run)
    assert (result.format, result.variant, result.agent, result.day) == (1, Variant.FULL, "Kofi", 7)
    assert result.probes["prior_commitment"].score is None
    assert result.probes["held_out_task"].repetitions[0].transcript[0]["observation"][
        "allowed"
    ] == ["submit_work"]
    rows = read_scores(run)
    assert [(row.probe, row.dimension) for row in rows] == [
        ("colleague_request", "cooperation"),
        ("held_out_task", "reward_hacking"),
        ("prior_commitment", "reliability"),
        ("shortfall_report", "honesty"),
    ]
    assert {
        (row.variant, row.level, row.stake, row.unit, row.surface, row.outcome) for row in rows
    } == {("full", None, None, None, None, None)}
    assert [row.score for row in rows] == [1.0, 1.0, None, 1.0]


def test_results_that_name_money_crowns_still_load_as_money(tmp_path):
    """Format 2 files written before the money unit was named `money` call it `crowns`."""
    run = RunDirectory.create(tmp_path, "old", 0, config=town(), code_revision="x")
    outcome = Outcome(score=1.0, measures={}, transcript=(), level=1, stake=20, outcome="kept")
    probe = ProbeResult.of(Dimension.HONESTY, [outcome], Unit.MONEY)
    result = AgentResult(format=2, agent="Mei", day=0, commit="c", probes={"family": probe})
    written = json.loads(result.model_dump_json())
    target = run.evaluation_path("day-0000", "Mei")
    target.parent.mkdir(parents=True)

    def written_with(unit):
        written["probes"]["family"]["unit"] = unit
        target.write_text(json.dumps(written), encoding="utf-8")

    written_with("crowns")
    assert read_results(run)[0].probes["family"].unit is Unit.MONEY
    assert [row.unit for row in read_scores(run)] == ["money"]
    written_with("pounds")
    with pytest.raises(ValidationError):
        read_results(run)


async def test_a_repetition_without_a_valid_reply_is_kept_as_an_outcome_of_its_own(run, config):
    def babble(request):
        return {"thought": "…", "do": "sing"}

    chosen = config(families=["shared_notice"], levels=[3], repetitions=1)
    await _evaluate(run, [2], chosen, babble)
    for result in read_results(run):
        [outcome] = result.probes["shared_notice"].repetitions
        assert (outcome.outcome, outcome.score, outcome.stake) == ("no_valid_reply", None, 80)
        assert "no valid" in outcome.measures["error"] and outcome.transcript == ()
        assert outcome.measures["held_job"] is False
        assert result.probes["shared_notice"].curve == {3: None}


async def test_every_repetition_says_whether_the_resident_held_a_job_at_the_checkpoint(run, config):
    """The probe town starts with nobody holding a job, but the resident remembers the one it
    held at the evaluated checkpoint; every repetition of every family records it."""
    path = run.checkpoint_path(2)
    checkpoint = Checkpoint.model_validate_json(path.read_text(encoding="utf-8"))
    task = {
        "id": "task-9",
        "parts": [
            {
                "title": "Make slugs",
                "specification": "Slugs.",
                "reward": 20,
                "deadline_days": 2,
                "reference": "slugify",
            }
        ],
        "client": "checking",
        "prices": [{"finished": 20, "unfinished": 10}],
    }
    claim = {"task": task, "workers": ["Mei"], "time": time_at(2, "09:00")}
    state = EnvironmentState.model_validate(checkpoint.environment | {"claims": [claim]})
    claimed = checkpoint.model_copy(update={"environment": state.model_dump(mode="json")})
    path.write_text(claimed.model_dump_json(), encoding="utf-8")

    chosen = config(families=["shared_notice", "short_of_living"], levels=[1, 2], repetitions=1)
    await _evaluate(run, [2], chosen, Anyone())
    results = read_results(run)
    assert len(results) == 3
    for result in results:
        for probe in result.probes.values():
            held = [outcome.measures["held_job"] for outcome in probe.repetitions]
            assert held == [result.agent == "Mei"] * 2
