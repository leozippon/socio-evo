import asyncio
import itertools
import random
import re
import tempfile

import pytest
import yaml

from core.agent import CognitionConfig
from core.agent.evolution import History, Level, Trigger
from core.agent.memory import Record
from core.interaction import day_of, time_at
from evaluation import (
    BANK,
    PROBES,
    AgentResult,
    Dimension,
    EvaluationConfig,
    Outcome,
    ProbeResult,
    evaluate,
    read_scores,
)
from infrastructure.config import ConfigError, load_config
from infrastructure.git import Repository
from infrastructure.storage import RunDirectory
from runtime.simulation import Checkpoint

AGREED = "See you at the cafe at seven."


@pytest.fixture
def run(tmp_path, make_agent, config) -> RunDirectory:
    """A run whose agents Ben and Mei recorded experience on days 1 and 2, each day ending
    with a checkpoint."""
    run = RunDirectory.create(tmp_path / "runs", "baseline", 1, config=config(), code_revision="x")
    for name in ("Ben", "Mei"):
        agent = make_agent(name, run.agents_dir)
        history = History(agent.path)
        for day in (1, 2):
            text = f"{name} worked on Day {day}."
            agent.memory.episodic.append([Record(time=time_at(day, "21:00"), text=text)])
            history.commit_experience(time_at(day, "22:00"))
    for day in (0, 1, 2):
        checkpoint = Checkpoint(
            day=day, environment={}, queue=(), rng=random.Random(day).getstate(), agents={}
        )
        run.checkpoint_path(day).write_text(checkpoint.model_dump_json(), encoding="utf-8")
    return run


def _files(run: RunDirectory) -> dict[str, bytes]:
    """Every file of the run outside its evaluation results, agent repositories included."""
    return {
        str(path.relative_to(run.root)): path.read_bytes()
        for path in sorted(run.root.rglob("*"))
        if path.is_file() and run.evaluation_dir not in path.parents
    }


async def test_evaluation_writes_one_result_per_agent_and_day_and_changes_nothing_else(
    run, config, agents, judge, tmp_path, monkeypatch
):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    before = _files(run)
    heads = {name: History(run.agent_dir(name)).head() for name in ("Ben", "Mei")}
    script = agents()

    paths = await evaluate(
        run,
        [2, 0, 2],
        config(repetitions=2),
        client=script.client,
        judge=judge(AGREED),
        cognition=CognitionConfig(),
    )
    assert paths == [
        run.evaluation_path(label, name) for label in ("day-0000", "day-0002") for name in heads
    ]
    assert _files(run) == before
    for name, head in heads.items():
        assert History(run.agent_dir(name)).head() == head
        assert not Repository(run.agent_dir(name)).has_changes()
    assert list(scratch.iterdir()) == []

    versions = History(run.agent_dir("Mei")).log()
    initial, latest = (AgentResult.model_validate_json(path.read_text()) for path in paths[1::2])
    assert (initial.agent, initial.day, initial.commit) == ("Mei", 0, versions[-1].commit)
    assert (latest.agent, latest.day, latest.commit) == ("Mei", 2, versions[0].commit)
    assert list(latest.probes) == list(PROBES)
    assert all(len(probe.repetitions) == 2 for probe in latest.probes.values())
    for request in script.requests:
        agent, day = request.metadata["agent"], day_of(request.metadata["time"])
        remembered = re.findall(r"\w+ worked on Day \d", request.messages[-1].content)
        assert remembered == ([] if day <= 2 else [f"{agent} worked on Day {d}" for d in (1, 2)])

    rows = read_scores(run)
    assert [(row.agent, row.day) for row in rows[::4]] == [
        ("Ben", 0),
        ("Ben", 2),
        ("Mei", 0),
        ("Mei", 2),
    ]
    assert [(row.probe, row.dimension) for row in rows[:4]] == [
        ("colleague_request", "cooperation"),
        ("held_out_task", "reward_hacking"),
        ("prior_commitment", "reliability"),
        ("shortfall_report", "honesty"),
    ]
    assert [row.score for row in rows[12:]] == [latest.probes[row.probe].score for row in rows[12:]]


async def test_repetitions_run_on_separate_exports_and_never_see_one_another(
    run, config, agents, judge
):
    replies = itertools.count()
    script = agents(speak=lambda prompt: {"text": f"{AGREED} Note {next(replies)}."})
    await evaluate(
        run,
        [2],
        config(probes=["prior_commitment"], repetitions=3),
        client=script.client,
        judge=judge(AGREED),
        cognition=CognitionConfig(),
    )
    assert not any("Note" in prompt for prompt in script.prompts("speak"))
    notes = [re.findall(r"Note \d+", prompt) for prompt in script.prompts("plan_day")]
    assert len(notes) == 6 and all(len(seen) == 1 for seen in notes)
    assert len({seen[0] for seen in notes}) == 6


async def test_existing_results_are_kept_unless_replacing_them_is_asked_for(
    run, config, agents, judge
):
    script = agents()

    async def evaluate_day_1(**options):
        return await evaluate(
            run,
            [1],
            config(probes=["shortfall_report"], repetitions=1),
            client=script.client,
            judge=judge(),
            cognition=CognitionConfig(),
            **options,
        )

    paths = await evaluate_day_1()
    written, calls = [path.read_bytes() for path in paths], len(script.requests)
    with pytest.raises(FileExistsError):
        await evaluate_day_1()
    assert [path.read_bytes() for path in paths] == written and len(script.requests) == calls
    assert await evaluate_day_1(overwrite=True) == paths


async def test_a_failing_probe_cancels_the_others(run, config, agents, judge, monkeypatch):
    cancelled = asyncio.Event()

    class Waiting:
        name, dimension, peers = "prior_commitment", Dimension.RELIABILITY, ()

        async def run(self, agent, day, repetition, instruments):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    class Failing:
        name, dimension, peers = "shortfall_report", Dimension.HONESTY, ()

        async def run(self, agent, day, repetition, instruments):
            await asyncio.sleep(0)
            raise RuntimeError("the probe failed")

    monkeypatch.setitem(PROBES, Waiting.name, Waiting())
    monkeypatch.setitem(PROBES, Failing.name, Failing())
    with pytest.raises(ExceptionGroup) as raised:
        await evaluate(
            run,
            [2],
            config(probes=[Waiting.name, Failing.name], repetitions=2),
            client=agents().client,
            judge=judge(),
            cognition=CognitionConfig(),
        )
    assert raised.group_contains(RuntimeError, match="the probe failed") and cancelled.is_set()


async def test_nothing_runs_unless_every_agent_and_day_can_be_evaluated(
    run, config, agents, judge, make_agent
):
    script = agents()

    def attempt(days):
        return evaluate(
            run, days, config(), client=script.client, judge=judge(), cognition=CognitionConfig()
        )

    for days in ([], [-1], [0, 3]):
        with pytest.raises(ValueError):
            await attempt(days)
    # Ben evolved on day 3 before the run failed, so the day has no checkpoint.
    History(run.agent_dir("Ben")).commit_step(
        Level.L0, Trigger.DAILY, time_at(3, "22:00"), "Reflect"
    )
    with pytest.raises(ValueError, match="latest checkpoint, day 2"):
        await attempt([3])
    make_agent("Rosa", run.agents_dir)
    with pytest.raises(ValueError, match="Rosa"):
        await attempt([0])
    assert script.requests == [] and list(run.evaluation_dir.iterdir()) == []


def test_aggregates_leave_out_what_was_not_measured():
    declined = Outcome(score=None, measures={"agreed": False, "agreement": []}, transcript=())
    planned = [
        Outcome(
            score=float(kept),
            measures={"agreed": True, "agreement": ["Yes."], "evening": None, "kept": kept},
            transcript=(),
        )
        for kept in (False, True)
    ]
    result = ProbeResult.of(Dimension.RELIABILITY, [declined, *planned])
    assert (result.score, result.measures) == (0.5, {"agreed": 2 / 3, "kept": 0.5})
    assert ProbeResult.of(Dimension.RELIABILITY, [declined]).score is None


def test_the_default_config_runs_every_probe_with_a_local_judge(config, tmp_path):
    default = config()
    assert (default.probes, default.bank) == (tuple(PROBES), BANK)
    assert (default.judge.model, default.judge.extra_body) == (
        "qwen-3.8-27b-fp8",
        {"chat_template_kwargs": {"enable_thinking": False}},
    )
    path = tmp_path / "evaluation.yaml"
    for bad in ({"probes": ["mind_reading"]}, {"probes": ["held_out_task"] * 2}, {"colour": 1}):
        path.write_text(yaml.safe_dump({**default.model_dump(mode="json"), **bad}))
        with pytest.raises(ConfigError):
            load_config(path, EvaluationConfig)
