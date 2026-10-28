"""A town run dry, end to end: the run directory a day writes, stopping after a day and resuming,
and the ways a run refuses to start or fails."""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
from datetime import UTC, datetime

import pytest
import yaml

import simulation.run as simulation
from agent.runtime import Runtime, RuntimeConfig
from experiments.config import PROJECT_ROOT, load_experiment
from infrastructure.git import Repository
from infrastructure.llm import (
    LLMCallError,
    LLMConfigError,
    LLMRequest,
    LLMResponse,
    ScriptedClient,
)
from infrastructure.storage import RunDirectory, read_jsonl


def smoke(**changes):
    config = load_experiment(PROJECT_ROOT / "experiments" / "configs" / "smoke.yaml")
    return config.model_copy(update=changes)


@pytest.fixture(scope="module")
def smoke_run(tmp_path_factory):
    """The smoke town's day, run dry once for the tests that only read it."""
    runs = tmp_path_factory.mktemp("runs")
    root, status = asyncio.run(simulation.run(smoke(), runs, dry_run=True))
    return runs, root, status


def kinds(root) -> list[str]:
    return [entry["kind"] for entry in read_jsonl(root / "world.jsonl")]


def frozen_as_before(root) -> None:
    """Rewrite the configuration frozen in the run at `root` as a run frozen before the settings
    added since (`simulation.ADDED`) existed would have frozen it."""
    path = RunDirectory(root).config_path
    frozen = yaml.safe_load(path.read_text(encoding="utf-8"))
    del frozen["llm"]["context_window"], frozen["runtime"]["kept_tokens"]
    frozen["runtime"]["kept_exchanges"] = 6  # the count kept_tokens replaced
    path.write_text(yaml.safe_dump(frozen, sort_keys=False), encoding="utf-8")


def test_a_dry_day_writes_the_whole_run_directory(smoke_run):
    runs, root, status = smoke_run
    assert root == runs / "smoke-dry-run" and status == "completed"
    run = RunDirectory.open(root)
    manifest = run.read_manifest()
    assert manifest.status == "completed" and manifest.ended_at is not None
    assert manifest.pid is None
    assert load_experiment(run.config_path) == simulation.as_dry_run(smoke())
    assert sorted(path.name for path in run.checkpoints_dir.iterdir()) == [
        "day-00.json",
        "day-01.json",
    ]
    saved = json.loads(run.checkpoint_path(1).read_text())
    assert set(saved["residents"]) == {"Mei", "Olga", "Jonas"}
    entries = list(read_jsonl(root / "world.jsonl"))
    # Mei worked at the Office from about 08:15 to 17:00, Olga kept the Store's counter from
    # 07:15 to 19:00, and Jonas cooked at the Linde until 20:00, his time buying for the kitchen
    # at the Store not counted; each was paid its wages at midnight, its rent taken out of them.
    wages = {e["actor"]: e["payload"] for e in entries if e["kind"] == "wage"}
    for name, rent, wage, hours in (
        ("Mei", 30, 9, (8, 9)),
        ("Olga", 35, 7, (11.5, 12)),
        ("Jonas", 50, 7, (11.5, 12.5)),
    ):
        paid = wages[name]
        assert hours[0] < paid["hours"] < hours[1], name
        assert abs(paid["wages"] - paid["hours"] * wage) < 1
        assert (paid["rent"], paid["paid"]) == (rent, paid["wages"] - rent)
    # The shopkeeper opened the Store and ordered bread and what the kitchen takes, which arrive
    # the next morning; the chef bought for the kitchen there, cooked and served; Mei bought
    # bread and had a dish.
    sold = [
        (e["actor"], e["payload"]["item"], e["payload"]["kitchen"])
        for e in entries
        if e["kind"] == "sale"
    ]
    assert ("Mei", "bread", False) in sold and ("Jonas", "vegetables", True) in sold
    served = [e for e in entries if e["kind"] == "served"]
    assert [(e["actor"], e["payload"]["chef"]) for e in served] == [
        ("Mei", "Jonas"),
        ("Olga", "Jonas"),
    ]
    orders = [e["payload"] for e in entries if e["kind"] == "order"]
    assert saved["store"]["pending"] == [[o["item"], o["quantity"], o["arrives"]] for o in orders]
    assert {o["item"] for o in orders} == {"bread", "vegetables", "eggs"}
    assert saved["kitchen"]["portions"] == {} and saved["kitchen"]["stock"] == {}
    fund = saved["fund"]
    money = sum(r["inventory"]["money"] for r in saved["residents"].values())
    # Only the client's money came in and only the supplier's went out.
    supplier = sum(o["amount"] for o in orders)
    assert fund["balance"] + money == 1500 + 240 + 230 + 210 + 150 - supplier
    assert fund["yesterday"]["client"] == 150 and fund["yesterday"]["supplier"] == supplier
    assert fund["owed"] == fund["arrears"] == {} and fund["ledger"] == {}
    living = saved["residents"]["Mei"]["living"]
    # Fed by a dish and a helping of bread in the evening, rested, in good health.
    assert living["eaten"] == {}
    assert living["health"] == 100 and living["satiety"] > 35 and living["energy"] > 65
    assert living["night"] == {"poor_home": -2, "recovery": 5}
    log = kinds(root)
    lived = (
        "wake", "start_work", "claim", "verdict", "service", "order", "price", "sale", "cook",
        "served", "speech", "sleep", "wage",
    )  # fmt: skip
    for kind in lived:
        assert kind in log, kind
    assert log[-1] == "checkpoint" and "forced_sleep" not in log and "bedridden" not in log
    for name in ("Mei", "Olga", "Jonas"):
        agent = run.agent_dir(name)
        repository = Repository(agent)
        assert [c.subject for c in repository.log()] == [
            "day-01: Tuesday 3 March, 04:30",
            "day-00: Monday 2 March, 04:30",
        ]
        assert repository.tree("day-01") and not repository.has_changes()
        assert (agent / "memory" / "journal" / "2026-03-02.md").read_text().strip()
        assert set(repository.tree("day-00")) == {"background.md"}  # memory and skills empty
        assert repository.read_file("day-00", "background.md").startswith(f"I am {name}, ")
        assert "session.jsonl" in repository.tree("day-01")
    assert re.search(  # the saved day names the fund
        rf"saved day 1 after .*\. The fund holds \${fund['balance']}\. Yesterday it took in",
        run.run_log_path.read_text(),
    )


def test_an_existing_run_is_not_created_again_nor_resumed_with_another_configuration(smoke_run):
    runs, root, _ = smoke_run
    with pytest.raises(FileExistsError):
        asyncio.run(simulation.run(smoke(), runs, dry_run=True))
    with pytest.raises(ValueError, match="differs from the one frozen"):
        asyncio.run(simulation.run(smoke(days=2), runs, resume=True, dry_run=True))
    with pytest.raises(ValueError, match="already saved day 1"):
        asyncio.run(simulation.run(smoke(), runs, resume=True, dry_run=True))
    assert RunDirectory.open(root).read_manifest().status == "completed"


async def test_a_run_stopped_after_a_day_resumes_where_it_stopped(tmp_path, monkeypatch):
    config = smoke(days=2)
    root, status = await simulation.run(config, tmp_path, until_day=1, dry_run=True)
    assert status == "interrupted"
    assert RunDirectory.open(root).read_manifest().status == "interrupted"
    first = len(kinds(root))
    log = (root / "run.log").read_text()

    with monkeypatch.context() as patched:  # no resumption while the model does not answer
        patched.setattr(simulation, "_client", lambda c, dry_run: ScriptedClient(unanswered))
        with pytest.raises(LLMCallError, match="did not answer"):
            await simulation.run(config, tmp_path, resume=True, dry_run=True)
    assert RunDirectory.open(root).read_manifest().status == "interrupted"
    assert (root / "run.log").read_text() == log
    lost = {}  # a save of day 2 killed after its tags and before its checkpoint
    for name in ("Mei", "Olga", "Jonas"):
        repository = Repository(RunDirectory(root).agent_dir(name))
        lost[name] = repository.commit("day-02", date=datetime.now(UTC), allow_empty=True)
        repository.tag("day-02")

    frozen_as_before(root)  # a run frozen before the settings added since resumes with them
    root, status = await simulation.run(config, tmp_path, resume=True, dry_run=True)
    assert status == "completed"
    adopted = "frozen before llm.context_window, runtime.kept_tokens existed"
    assert adopted in (root / "run.log").read_text()
    entries = list(read_jsonl(root / "world.jsonl"))
    assert [entry["seq"] for entry in entries] == list(range(1, len(entries) + 1))
    resume = entries[first]
    assert resume["kind"] == "resume" and resume["payload"]["day"] == 1
    assert [entry["kind"] for entry in entries].count("checkpoint") == 2
    for name in ("Mei", "Olga", "Jonas"):
        agent = RunDirectory(root).agent_dir(name)
        repository = Repository(agent)
        assert repository.tree("day-02") and lost[name] not in {c.id for c in repository.log()}
        assert repository.log("day-02")[0].id == repository.head() != lost[name]
        assert sorted(path.name for path in (agent / "memory" / "journal").iterdir()) == [
            "2026-03-02.md",
            "2026-03-03.md",
        ]


async def test_a_run_records_its_process_until_sigterm_to_it_interrupts_the_run(tmp_path):
    """What stopping a run relies on: while the run runs, its manifest names the process, and
    SIGTERM to that process ends the run interrupted, with the id cleared."""
    living = asyncio.create_task(simulation.run(smoke(), tmp_path, dry_run=True))
    manifest = tmp_path / "smoke-dry-run" / "manifest.json"
    async with asyncio.timeout(60):
        while not manifest.exists() or json.loads(manifest.read_text())["pid"] is None:
            await asyncio.sleep(0.01)
    assert json.loads(manifest.read_text())["pid"] == os.getpid()
    os.kill(os.getpid(), signal.SIGTERM)
    root, status = await living
    ended = RunDirectory.open(root).read_manifest()
    assert (status, ended.status, ended.pid) == ("interrupted", "interrupted", None)


async def test_a_runtime_that_ends_fails_the_run_instead_of_hanging_it(tmp_path, monkeypatch):
    class SecondDies(Runtime):
        built = 0

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            SecondDies.built += 1
            self.dies = SecondDies.built == 2

        async def run(self) -> None:
            if self.dies:
                await asyncio.sleep(0.5)
                raise OSError("the disk is gone")
            await super().run()

    monkeypatch.setattr(simulation, "Runtime", SecondDies)
    async with asyncio.timeout(60):
        with pytest.raises(RuntimeError, match="the runtime of Olga ended") as raised:
            await simulation.run(smoke(), tmp_path, dry_run=True)
    assert isinstance(raised.value.__cause__, OSError)
    run = RunDirectory.open(tmp_path / "smoke-dry-run")
    assert (run.read_manifest().status, run.read_manifest().pid) == ("failed", None)
    assert "the run failed" in run.run_log_path.read_text()


def unanswered(request: LLMRequest) -> LLMResponse:
    raise LLMCallError("APIConnectionError: Connection error.")


async def test_a_model_that_stops_answering_fails_the_run(tmp_path, monkeypatch):
    replicas: dict[str, set[int | None]] = {}

    def down(request: LLMRequest) -> LLMResponse | str:
        if not request.tools:  # the check before the run, at the last replica
            replicas["check"] = {request.replica}
            return "Yes."
        name = re.search(r"\bI am (\w+)", request.messages[0].content)[1]
        replicas.setdefault(name, set()).add(request.replica)
        return unanswered(request)

    monkeypatch.setattr(simulation, "_client", lambda config, dry_run: ScriptedClient(down))
    config = smoke(
        llm=smoke().llm.model_copy(update={"replicas": 3}),
        runtime=RuntimeConfig(model_attempts=1, max_consecutive_lapses=2),
    )
    async with asyncio.timeout(60):
        with pytest.raises(RuntimeError, match="the runtime of (Mei|Olga|Jonas) ended") as raised:
            await simulation.run(config, tmp_path, dry_run=True)
    assert "2 requests in a row lapsed" in str(raised.value.__cause__)
    run = RunDirectory.open(tmp_path / "smoke-dry-run")
    assert run.read_manifest().status == "failed"
    log = run.run_log_path.read_text()
    assert "WARNING" in log and "a step request lapsed" in log and "Connection error" in log
    assert replicas == {"check": {2}, "Mei": {0}, "Olga": {1}, "Jonas": {2}}  # its place


async def test_nothing_is_written_when_a_background_or_the_model_is_missing_or_silent(
    tmp_path, monkeypatch
):
    config = smoke()
    lost = config.residents[0].model_copy(update={"background": "experiments/residents/x.md"})
    with pytest.raises(FileNotFoundError):
        await simulation.run(
            config.model_copy(update={"residents": (lost, *config.residents[1:])}),
            tmp_path,
            dry_run=True,
        )
    monkeypatch.delenv("VLLM_BASE_URL", raising=False)
    llm = config.llm.model_copy(update={"base_url": "${VLLM_BASE_URL}"})
    with pytest.raises(LLMConfigError, match="unset environment variable"):
        await simulation.run(config.model_copy(update={"llm": llm}), tmp_path)
    llm = llm.model_copy(
        update={"base_url": "http://127.0.0.1:9/v1", "api_key_env": "SOCIO_EVO_NO_SUCH_KEY"}
    )
    with pytest.raises(LLMConfigError, match="SOCIO_EVO_NO_SUCH_KEY is not set"):
        await simulation.run(config.model_copy(update={"llm": llm}), tmp_path)
    monkeypatch.setattr(simulation, "_client", lambda config, dry_run: ScriptedClient(unanswered))
    with pytest.raises(LLMCallError, match="did not answer a test request: .*Connection error"):
        await simulation.run(config, tmp_path, dry_run=True)
    assert list(tmp_path.iterdir()) == []
