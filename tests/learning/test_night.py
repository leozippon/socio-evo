"""The night end to end on residents' real traces, with the scripted model, a fake trainer that
honours the jobs contract, a fake model server and the GPUs' free memory as each test sets it:
each resident from its choice to its own adapter, the three arms, a night broken off between its
steps completed doing only what is missing, a later night resumed on a restarted server, a run
made again under its name, and what is dropped for length; the jobs divided among the GPUs with
room and fitted at once, a night waiting for a GPU and failing when it has waited too long, and a
trainer failing beside another."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import shutil
from datetime import date

import pytest
from pydantic import ValidationError

import learning.fit
import learning.generalise as generalise_module
from agent.directory import AgentDirectory
from agent.runtime import RuntimeConfig
from infrastructure.llm import LLMCallError, LLMConfig, LLMRequest, ScriptedClient
from infrastructure.llm.scripted import reply, tool_call
from infrastructure.storage import RunDirectory, read_jsonl
from learning.adapters import adapter_for, fitted
from learning.choice import draw
from learning.config import LearningConfig, LoraConfig, TrainerConfig
from learning.fit import STEP_COST, Job, TrainerError, divide
from learning.generalise import LENGTH_MARGIN, Vocabulary, as_it_happened
from learning.moments import life
from learning.night import Nights
from tests.support.lives import a_day, resident
from tests.support.server import KEY, FakeServer
from tests.support.trainer import fake_trainer

START = date(2026, 3, 2)
GENERALISED = {"situation": "You meet a colleague at work.", "response": "I say good morning."}


class Model:
    """The scripted model of the nights: each resident's choice from its own list of replies, the
    resident known by the name its account of itself gives, and every generalising answered
    alike. As the server does, it refuses a request for an adapter `server` has not loaded."""

    def __init__(self, server: FakeServer) -> None:
        self.server = server
        self.plans: dict[str, list] = {}
        self.requests: list[LLMRequest] = []
        self.client = ScriptedClient(self._answer)

    def choices(self, name: str) -> list[LLMRequest]:
        return [r for r in self.requests if r.tools and _resident(r) == name]

    def generalising(self) -> list[LLMRequest]:
        return [r for r in self.requests if r.json_schema]

    def _answer(self, request: LLMRequest):
        self.requests.append(request)
        if request.model is not None and request.model not in self.server.loaded:
            raise LLMCallError(f"NotFoundError: The model `{request.model}` does not exist.")
        if request.json_schema:
            return GENERALISED
        planned = self.plans[_resident(request)].pop(0)
        if isinstance(planned, BaseException):
            raise planned
        return planned


@pytest.fixture
def server(monkeypatch):
    with FakeServer() as running:
        monkeypatch.setenv(KEY, running.key)
        yield running


@pytest.fixture
def record(tmp_path, monkeypatch):
    """What the fake trainer was asked, each time it ran."""
    path = tmp_path / "trainer.jsonl"
    monkeypatch.setenv("FAKE_TRAINER_RECORD", str(path))
    return lambda: list(read_jsonl(path)) if path.exists() else []


class Gpus:
    """nvidia-smi as the tests have it: every GPU has 45 GiB free, but for what the next of
    `looks` says, the last again once they run out; `looked` counts the looks."""

    def __init__(self) -> None:
        self.looks: list[dict[str, float]] = []
        self.looked = 0

    def __call__(self) -> dict[str, float]:
        self.looked += 1
        free = {str(gpu): 45.0 for gpu in range(8)}
        return free | (self.looks[min(self.looked, len(self.looks)) - 1] if self.looks else {})


@pytest.fixture(autouse=True)
def gpus(monkeypatch) -> Gpus:
    """The GPUs' free memory as the test sets it, looked at again without waiting."""
    found = Gpus()
    monkeypatch.setattr(learning.fit, "free_memory", found)
    monkeypatch.setattr(learning.fit, "POLL_SECONDS", 0)
    return found


async def town(tmp_path, name: str = "town") -> RunDirectory:
    run = RunDirectory.create(tmp_path / "runs", name, config=LearningConfig(), code_revision="t")
    for resident_name in ("Ana", "Ben"):
        resident(run.agent_dir(resident_name), background=f"I am {resident_name}, the baker.")
    await live_day(run, 1)
    return run


async def live_day(run: RunDirectory, day: int) -> None:
    await a_day(AgentDirectory(run.agent_dir("Ana")), day, friend="Ben")
    await a_day(AgentDirectory(run.agent_dir("Ben")), day, friend="Ana")


def nights(run, server, tmp_path, model, gpus=(5,), patience_minutes=360, **settings) -> Nights:
    trainer = TrainerConfig(
        python=fake_trainer(tmp_path),
        base="/models/base",
        gpus=gpus,
        patience_minutes=patience_minutes,
    )
    learning = LearningConfig(enabled=True, keep_per_night=2, trainer=trainer, **settings)
    return Nights(
        run,
        learning,
        llm=LLMConfig(base_url=server.url, api_key_env=KEY, model="served", replicas=2),
        runtime=RuntimeConfig(model_attempts=1),
        client=model.client,
        residents=("Ana", "Ben"),
        start_date=START,
        seed=7,
        vocabulary=Vocabulary.of_town(residents=["Ana", "Ben"], places=[], ids=[]),
    )


def keeps(*moments: int, why: str | None = None):
    calls = [tool_call("keep", moment=m, **({"why": why} if why else {})) for m in moments]
    return [reply("", *calls), reply("That is all.")] if moments else [reply("Not tonight.")]


def served(run, name, night) -> str:
    """The name on the server of the adapter fitted for `name` on `night`."""
    return fitted(run.root, name, night).name


def read(run, night, name, file):
    return json.loads((run.night_dir(night) / name / file).read_text())


def lines(run, night, name, file):
    return list(read_jsonl(run.night_dir(night) / name / file))


async def test_each_resident_goes_from_its_choice_to_its_own_adapter_night_after_night(
    tmp_path, server, record
):
    run, model = await town(tmp_path), Model(server)
    night = nights(run, server, tmp_path, model, dataset_max=2)
    model.plans = {"Ana": keeps(1, 2, why="Ben was there."), "Ben": keeps()}
    switched: list[dict] = []
    await night.live(1, lambda: {"Ana": 2, "Ben": 0, "Cy": 9}, switched.append)

    assert json.loads((run.night_dir(1) / "liked_by.json").read_text()) == {"Ana": 2, "Ben": 0}
    ana = read(run, 1, "Ana", "kept.json")
    assert (ana["ended"], ana["replies"], ana["drawn"]) == ("done", 2, None)
    assert [k["moment"] for k in ana["marked"]] == [k["moment"] for k in ana["kept"]] == [1, 2]
    assert ana["kept"][0] == {"moment": 1, "day": 1, "why": "Ben was there."}
    assert read(run, 1, "Ben", "kept.json")["marked"] == []
    assert lines(run, 1, "Ana", "dataset.jsonl") == [
        {"messages": [{"role": "user", "content": GENERALISED["situation"]},
                      {"role": "assistant", "content": GENERALISED["response"]}]}
    ] * 2  # fmt: skip
    assert lines(run, 1, "Ana", "provenance.jsonl")[1] == {
        "moment": 2, "day": 1, "night": 1, "choice": "resident", "examples": "generalised",
        "why": "Ben was there.",
    }  # fmt: skip
    assert lines(run, 1, "Ben", "dataset.jsonl") == []
    assert len(lines(run, 1, "Ana", "generalise.jsonl")) == 2  # every request with its reply
    assert not (run.night_dir(1) / "Ben" / "generalise.jsonl").exists()
    (asked,) = record()
    adapter = run.adapter_dir("Ana", 1)
    assert asked["cuda"] == "5" and asked["spec"]["base"] == "/models/base"
    assert asked["spec"]["jobs"] == [
        {
            "name": "town-Ana-night-01",
            "dataset": str((run.night_dir(1) / "Ana" / "dataset.jsonl").resolve()),
            "out": str(adapter.resolve()),
        }
    ]
    assert set(asked["spec"]["lora"]) == {
        "rank", "alpha", "dropout", "target_modules", "learning_rate", "epochs", "max_length",
        "batch_size", "seed",
    }  # fmt: skip
    ana_1 = served(run, "Ana", 1)
    assert re.fullmatch(r"town-Ana-night-01-[0-9a-f]{8}", ana_1)
    assert server.loaded == {ana_1: str(adapter.resolve())}
    assert switched == [{"Ana": ana_1, "Ben": None}]
    done = json.loads((run.night_dir(1) / "done.json").read_text())
    trained = json.loads((adapter / "training.json").read_text())
    assert done["residents"]["Ana"] | {"replies": 0} == {
        "ended": "done", "replies": 0, "marked": 2, "kept": 2, "examples": 2, "new": 2,
        "dropped": {}, "cut": 0, "dataset": 2, "fitted": True,
        "fit_seconds": trained["wall_seconds"],
        "adapter": ana_1,
    }  # fmt: skip
    ben = done["residents"]["Ben"]
    assert (ben["fitted"], ben["fit_seconds"], ben["adapter"], ben["marked"]) == (
        False, None, None, 0
    )  # fmt: skip
    (start,) = done["fits"]
    assert start["jobs"] == {"5": ["town-Ana-night-01"]} and start["free_gib"] == {"5": 45.0}
    assert [r.model for r in model.choices("Ana")] == [None, None]  # the base, the first night
    assert "Monday 2 March: 2\n\nThe days" in model.choices("Ana")[0].messages[1].content
    assert adapter_for(run.root, "Ana", 1) == adapter.resolve()
    assert adapter_for(run.root, "Ana", 0) is None and adapter_for(run.root, "Ben", 1) is None

    await live_day(run, 2)
    model.plans = {"Ana": keeps(1, 5), "Ben": keeps(4)}
    await night.live(2, lambda: {"Ana": 3, "Ben": 1}, switched.append)

    assert {r.model for r in model.choices("Ana")[2:]} == {ana_1}
    assert "Monday 2 March: 2\nTuesday 3 March: 3\n" in model.choices("Ana")[2].messages[1].content
    assert [k["moment"] for k in read(run, 2, "Ana", "kept.json")["kept"]] == [5]  # 1 carried
    assert [p["moment"] for p in lines(run, 2, "Ana", "provenance.jsonl")] == [2, 5]  # newest 2
    assert [p["night"] for p in lines(run, 2, "Ana", "provenance.jsonl")] == [1, 2]
    assert [[j["name"] for j in r["spec"]["jobs"]] for r in record()] == [
        ["town-Ana-night-01"],
        ["town-Ana-night-02", "town-Ben-night-02"],
    ]
    second = {"Ana": served(run, "Ana", 2), "Ben": served(run, "Ben", 2)}
    assert set(server.loaded) == set(second.values())  # night 1's let go
    assert switched[-1] == second
    assert adapter_for(run.root, "Ana", 1) == adapter.resolve()
    assert adapter_for(run.root, "Ana", 2) == run.adapter_dir("Ana", 2).resolve()


async def test_the_raw_arm_learns_moments_as_they_happened_the_random_arm_as_many_drawn(
    tmp_path, server, record
):
    run, model = await town(tmp_path, "raw"), Model(server)
    model.plans = {"Ana": keeps(2), "Ben": keeps()}
    await nights(run, server, tmp_path, model, examples="raw").live(
        1, lambda: {"Ana": 1, "Ben": 1}, dict
    )
    lived = life(run.agent_dir("Ana"), 1)
    (example,) = lines(run, 1, "Ana", "dataset.jsonl")
    assert example == {"messages": list(as_it_happened(lived.get(2), _kept(2)).messages)}
    assert [m["role"] for m in example["messages"]] == ["user", "assistant", "tool", "assistant"]
    assert model.generalising() == []
    assert lines(run, 1, "Ana", "provenance.jsonl")[0]["examples"] == "raw"

    run, model = await town(tmp_path, "random"), Model(server)
    model.plans = {"Ana": keeps(2), "Ben": keeps()}
    await nights(run, server, tmp_path, model, choice="random").live(
        1, lambda: {"Ana": 1, "Ben": 1}, dict
    )
    ana = read(run, 1, "Ana", "kept.json")
    assert [k["moment"] for k in ana["marked"]] == [2] and ana["drawn"] == "7-Ana-1"
    drawn = draw(life(run.agent_dir("Ana"), 1), 1, set(), "7-Ana-1")
    assert ana["kept"] == [k.model_dump() for k in drawn]
    assert [p["choice"] for p in lines(run, 1, "Ana", "provenance.jsonl")] == ["random"]
    assert read(run, 1, "Ben", "kept.json")["kept"] == []  # none marked, none drawn


async def test_a_night_broken_off_between_its_steps_is_completed_doing_only_what_is_missing(
    tmp_path, server, record, monkeypatch
):
    run, model = await town(tmp_path), Model(server)
    night = nights(run, server, tmp_path, model)
    with pytest.raises(ValueError, match="the world gave None as how many like Ben"):
        await night.live(1, lambda: {"Ana": 1}, dict)
    assert model.requests == []

    switched: list[dict] = []
    model.plans = {"Ana": keeps(1), "Ben": [LLMCallError("down")]}
    with pytest.raises(LLMCallError, match="down"):  # Ben's choice could not be made
        await night.live(1, lambda: {"Ana": 1, "Ben": 1}, switched.append)
    assert (run.night_dir(1) / "Ana" / "examples.json").is_file()
    assert not (run.night_dir(1) / "Ben" / "kept.json").exists() and record() == []
    asked = len(model.requests)

    model.plans = {"Ben": keeps(2)}
    monkeypatch.setenv("FAKE_TRAINER_FAIL", "town-Ben-night-01")
    with pytest.raises(
        TrainerError, match="on GPU 5 exited with 3"
    ):  # it fitted Ana's, then failed
        await night.live(1, lambda: {"Ana": 5, "Ben": 5}, switched.append)
    assert [_resident(r) for r in model.requests[asked:] if r.tools] == ["Ben", "Ben"]
    assert len(model.generalising()) == 2  # Ana's moment once, Ben's once
    assert [[j["name"] for j in r["spec"]["jobs"]] for r in record()] == [
        ["town-Ana-night-01", "town-Ben-night-01"]
    ]
    assert (run.adapter_dir("Ana", 1) / "training.json").is_file()
    assert not run.adapter_dir("Ben", 1).exists() and not (run.night_dir(1) / "done.json").exists()
    assert switched == [] and server.loaded == {}
    assert adapter_for(run.root, "Ana", 1) is None  # nobody wakes on a night not complete
    assert "out of memory" in (run.night_dir(1) / "trainer-5.log").read_text()

    monkeypatch.delenv("FAKE_TRAINER_FAIL")
    asked = len(model.requests)
    await night.live(1, lambda: {"Ana": 9, "Ben": 9}, switched.append)
    assert len(model.requests) == asked  # nothing asked again
    assert [[j["name"] for j in r["spec"]["jobs"]] for r in record()][1:] == [["town-Ben-night-01"]]
    names = {"Ana": served(run, "Ana", 1), "Ben": served(run, "Ben", 1)}
    assert switched == [names] and set(server.loaded) == set(names.values())
    assert json.loads((run.night_dir(1) / "liked_by.json").read_text()) == {"Ana": 1, "Ben": 1}

    # A complete night is never done again: it only puts everyone back on its adapters, as a run
    # resumed after it needs, loading what the server has lost.
    server.loaded.clear()
    await night.live(1, lambda: pytest.fail("the numbers asked again"), switched.append)
    assert len(model.requests) == asked and len(record()) == 2
    assert switched[-1] == names and set(server.loaded) == set(names.values())


async def test_a_later_night_resumed_on_a_restarted_server_loads_the_night_befores_adapters_first(
    tmp_path, record, monkeypatch
):
    run = await town(tmp_path)
    with FakeServer() as first:
        monkeypatch.setenv(KEY, first.key)
        model = Model(first)
        model.plans = {"Ana": keeps(1), "Ben": keeps(1)}
        await nights(run, first, tmp_path, model).live(1, lambda: {"Ana": 1, "Ben": 1}, dict)
    yesterday = {"Ana": served(run, "Ana", 1), "Ben": served(run, "Ben", 1)}
    await live_day(run, 2)

    with FakeServer() as restarted:  # it has lost every adapter loaded before
        model.server = restarted
        model.plans = {"Ana": keeps(4), "Ben": keeps()}
        switched: list[dict] = []
        await nights(run, restarted, tmp_path, model).live(
            2, lambda: {"Ana": 2, "Ben": 2}, switched.append
        )
    assert {r.model for r in model.choices("Ana")[2:]} == {yesterday["Ana"]}
    assert {r.model for r in model.choices("Ben")[2:]} == {yesterday["Ben"]}
    tonight = {"Ana": served(run, "Ana", 2), "Ben": yesterday["Ben"]}  # Ben kept nothing new
    assert switched == [tonight] and set(restarted.loaded) == set(tonight.values())


async def test_a_run_made_again_under_its_name_is_served_its_own_adapters_not_the_old(
    tmp_path, server, record
):
    run, model = await town(tmp_path), Model(server)
    model.plans = {"Ana": keeps(1), "Ben": keeps()}
    await nights(run, server, tmp_path, model).live(1, lambda: {"Ana": 1, "Ben": 1}, dict)
    old = fitted(run.root, "Ana", 1)

    shutil.rmtree(run.root)  # made again in its place, while the server keeps what it loaded
    run = await town(tmp_path)
    model.plans = {"Ana": keeps(1, 2), "Ben": keeps()}
    switched: list[dict] = []
    await nights(run, server, tmp_path, model).live(
        1, lambda: {"Ana": 1, "Ben": 1}, switched.append
    )
    new = fitted(run.root, "Ana", 1)
    assert new.path == old.path and new.name != old.name
    assert server.loaded == {old.name: str(old.path), new.name: str(new.path)}
    assert switched == [{"Ana": new.name, "Ben": None}]


async def test_an_example_the_trainer_might_find_too_long_is_dropped_and_counted(
    tmp_path, server, record, caplog
):
    run, model = await town(tmp_path, "raw"), Model(server)
    lived = life(run.agent_dir("Ana"), 1)
    sizes = {n: _estimate(as_it_happened(lived.get(n), _kept(n))) for n in (1, 2)}
    short, long = sorted(sizes, key=sizes.get)
    model.plans = {"Ana": keeps(1, 2), "Ben": keeps()}
    # The longer one's estimate is within the limit, but without the room it needs.
    most = max(sizes[long], math.ceil(sizes[short] * LENGTH_MARGIN))
    assert sizes[short] * LENGTH_MARGIN <= most < sizes[long] * LENGTH_MARGIN
    lora = LoraConfig(max_length=most)
    with caplog.at_level(logging.INFO, logger="learning"):
        await nights(run, server, tmp_path, model, examples="raw", lora=lora).live(
            1, lambda: {"Ana": 1, "Ben": 1}, dict
        )
    made = read(run, 1, "Ana", "examples.json")
    assert [e["moment"] for e in made["examples"]] == [short]
    assert [(d["moment"], d["reason"]) for d in made["dropped"]] == [(long, "too long")]
    done = json.loads((run.night_dir(1) / "done.json").read_text())["residents"]
    assert (done["Ana"]["dropped"], done["Ana"]["examples"]) == ({"too long": 1}, 1)
    assert "night 1, Ana: marked 2 of at most 2" in caplog.text and "too long 1" in caplog.text


async def test_the_jobs_are_divided_among_the_first_two_listed_gpus_with_room_fitted_at_once(
    tmp_path, server, record, gpus, monkeypatch, caplog
):
    run, model = await town(tmp_path), Model(server)
    model.plans = {"Ana": keeps(1), "Ben": keeps(2)}
    gpus.looks = [{"3": 41.9, "5": 10.0}]  # other jobs hold 3 GiB of GPU 3 and more of 5
    meeting = tmp_path / "meeting"
    meeting.mkdir()
    monkeypatch.setenv("FAKE_TRAINER_TOGETHER", f"2:{meeting}")  # one alone would fail
    with caplog.at_level(logging.INFO, logger="learning"):
        await nights(run, server, tmp_path, model, gpus=[3, 4, 5, 7, 1, 2]).live(
            1, lambda: {"Ana": 1, "Ben": 1}, dict
        )
    # Of the four with room, the first two; Ana's and Ben's are alike in work, and go, by name,
    # to the first GPU with the least.
    jobs = {"4": ["town-Ana-night-01"], "7": ["town-Ben-night-01"]}
    assert {r["cuda"]: [j["name"] for j in r["spec"]["jobs"]] for r in record()} == jobs
    assert {path.name for path in run.night_dir(1).glob("*-[0-9]*.*")} == {
        "jobs-4.json", "jobs-7.json", "trainer-4.log", "trainer-7.log"
    }  # fmt: skip
    done = json.loads((run.night_dir(1) / "done.json").read_text())
    (start,) = done["fits"]
    assert start["jobs"] == jobs
    assert start["free_gib"] == {"3": 41.9, "4": 45.0, "5": 10.0, "7": 45.0, "1": 45.0, "2": 45.0}
    assert start["passed_over"] == {
        "3": "no room", "5": "no room", "1": "not needed", "2": "not needed"
    }  # fmt: skip
    assert 0 <= start["waited_seconds"] < 60 and gpus.looked == 1
    for name in ("Ana", "Ben"):
        trained = json.loads((run.adapter_dir(name, 1) / "training.json").read_text())
        assert done["residents"][name]["fit_seconds"] == trained["wall_seconds"]
    assert (
        "fitting on GPU 4 town-Ana-night-01; on GPU 7 town-Ben-night-01; "
        "GPU 3 passed over, no room, 41.9 GiB free; GPU 5 passed over, no room, 10.0 GiB free; "
        "GPU 1 passed over, not needed, 45.0 GiB free"
    ) in caplog.text


async def test_a_night_waits_for_a_gpu_with_room_and_fails_resumably_when_it_has_waited_too_long(
    tmp_path, server, record, gpus, caplog
):
    run, model = await town(tmp_path), Model(server)
    model.plans = {"Ana": keeps(1), "Ben": keeps(2)}
    listed = [3, 4, 5, 7, 1, 2]
    night = nights(run, server, tmp_path, model, gpus=listed, patience_minutes=2)
    taken = {str(gpu): 3.5 for gpu in listed}
    gpus.looks = [taken]
    with pytest.raises(
        TrainerError, match=r"no GPU of 3, 4, 5, 7, 1, 2 had the 42.0 GiB .* in 2 m"
    ):
        await night.live(1, lambda: {"Ana": 1, "Ben": 1}, dict)
    assert gpus.looked == 3 and record() == []  # now, and after one minute and two
    assert not (run.night_dir(1) / "done.json").exists()

    # Resumed, it waits again, and fits on GPU 1 when its job has left it.
    gpus.looks, gpus.looked = [taken, taken, taken | {"1": 45.0}], 0
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="learning"):
        await night.live(1, lambda: pytest.fail("the numbers asked again"), dict)
    assert [(r["cuda"], [j["name"] for j in r["spec"]["jobs"]]) for r in record()] == [
        ("1", ["town-Ana-night-01", "town-Ben-night-01"])
    ]
    assert caplog.text.count("no GPU of 3, 4, 5, 7, 1, 2 has the 42.0 GiB a fit needs free") == 1
    assert "GPU 1 has room for a fit after 2 minutes" in caplog.text
    (start,) = json.loads((run.night_dir(1) / "done.json").read_text())["fits"]
    assert start["passed_over"] == {str(gpu): "no room" for gpu in listed if gpu != 1}
    assert start["free_gib"]["1"] == 45.0 and start["waited_seconds"] >= 0


async def test_a_trainer_that_fails_stops_the_others_and_the_resumed_night_fits_only_the_rest(
    tmp_path, server, record, monkeypatch
):
    run, model = await town(tmp_path), Model(server)
    model.plans = {"Ana": keeps(1), "Ben": keeps(2)}
    night = nights(run, server, tmp_path, model, gpus=[5, 6])
    meeting = tmp_path / "meeting"
    meeting.mkdir()
    monkeypatch.setenv("FAKE_TRAINER_TOGETHER", f"2:{meeting}")
    monkeypatch.setenv("FAKE_TRAINER_FAIL", "town-Ben-night-01")  # once Ana's is done
    monkeypatch.setenv("FAKE_TRAINER_HANG", "1")  # Ana's trainer, its job done, would go on
    with pytest.raises(TrainerError, match="the trainer on GPU 6 exited with 3"):
        await asyncio.wait_for(night.live(1, lambda: {"Ana": 1, "Ben": 1}, dict), 60)
    ana = next(r for r in record() if r["cuda"] == "5")
    with pytest.raises(ProcessLookupError):  # stopped
        os.kill(ana["pid"], 0)
    assert (run.adapter_dir("Ana", 1) / "training.json").is_file()
    assert not run.adapter_dir("Ben", 1).exists() and not (run.night_dir(1) / "done.json").exists()
    assert "out of memory" in (run.night_dir(1) / "trainer-6.log").read_text()

    for variable in ("FAKE_TRAINER_TOGETHER", "FAKE_TRAINER_FAIL", "FAKE_TRAINER_HANG"):
        monkeypatch.delenv(variable)
    await night.live(1, lambda: {"Ana": 1, "Ben": 1}, dict)
    assert [(r["cuda"], [j["name"] for j in r["spec"]["jobs"]]) for r in record()][2:] == [
        ("5", ["town-Ben-night-01"])
    ]
    done = json.loads((run.night_dir(1) / "done.json").read_text())
    assert [start["jobs"] for start in done["fits"]] == [
        {"5": ["town-Ana-night-01"], "6": ["town-Ben-night-01"]},
        {"5": ["town-Ben-night-01"]},
    ]
    assert {name: s["fitted"] for name, s in done["residents"].items()} == {
        "Ana": True,
        "Ben": True,
    }


def test_the_division_balances_the_work_by_tokens_and_steps_and_is_deterministic(tmp_path):
    def job(name: str, lines: int, length: int) -> Job:
        dataset = tmp_path / f"{name}.jsonl"
        dataset.write_text("".join("x" * length + "\n" for _ in range(lines)))
        return Job(name, dataset, tmp_path / name)

    # Work: a 10 long steps, b 5 long, c 15 short (as much as b), d 1 short.
    a, b, c, d = job("a", 10, 2999), job("b", 5, 2999), job("c", 15, 299), job("d", 1, 299)
    assert (1000 + STEP_COST) * 5 == (100 + STEP_COST) * 15
    assert divide([a, b, c, d], ["5", "6"]) == {"5": [a, d], "6": [b, c]}
    assert divide([d, c, b, a], ["5", "6"]) == {"5": [d, a], "6": [c, b]}  # the same, in order
    assert divide([a, b, c, d], ["6", "5"]) == {"6": [a, d], "5": [b, c]}
    assert divide([d], ["5", "6", "7"]) == {"5": [d]}


def test_the_gpus_are_listed_once_each_and_a_run_frozen_with_them_as_a_string_reads():
    def trainer(gpus) -> TrainerConfig:
        return TrainerConfig(python="/opt/python", base="/models/base", gpus=gpus)

    assert trainer([3, 4, 5]).gpus == trainer("3,4,5").gpus == (3, 4, 5)
    assert trainer([3]).gpus_at_once == 2
    with pytest.raises(ValidationError, match="names a GPU more than once"):
        trainer([3, 4, 3])


async def test_an_account_cut_to_be_generalised_is_counted(
    tmp_path, server, record, caplog, monkeypatch
):
    monkeypatch.setattr(generalise_module, "ACCOUNT_CHARS", 100)  # every moment is longer
    run, model = await town(tmp_path), Model(server)
    model.plans = {"Ana": keeps(1, 2), "Ben": keeps()}
    with caplog.at_level(logging.INFO, logger="learning"):
        await nights(run, server, tmp_path, model).live(1, lambda: {"Ana": 1, "Ben": 1}, dict)
    made = read(run, 1, "Ana", "examples.json")
    assert all(example["cut"] > 0 for example in made["examples"]) and len(made["examples"]) == 2
    done = json.loads((run.night_dir(1) / "done.json").read_text())["residents"]
    assert (done["Ana"]["cut"], done["Ben"]["cut"]) == (2, 0)
    assert "2 cut to be generalised" in caplog.text


def _estimate(example) -> int:
    return sum(len(json.dumps(m, ensure_ascii=False)) // 3 + 1 for m in example.messages)


def _kept(moment: int):
    from learning.choice import Kept

    return Kept(moment=moment, day=1)


def _resident(request: LLMRequest) -> str:
    return re.search(r"\bI am (\w+)", request.messages[0].content)[1]
