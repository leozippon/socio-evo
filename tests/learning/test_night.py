"""The night end to end on residents' real traces, with the scripted model, a fake trainer that
honours the jobs contract and a fake model server: each resident from its choice to its own
adapter, the three arms, and a night broken off between its steps completed doing only what is
missing."""

from __future__ import annotations

import json
import re
from datetime import date

import pytest

from agent.directory import AgentDirectory
from agent.runtime import RuntimeConfig
from infrastructure.llm import LLMCallError, LLMConfig, LLMRequest, ScriptedClient
from infrastructure.llm.scripted import reply, tool_call
from infrastructure.storage import RunDirectory, read_jsonl
from learning.adapters import adapter_for
from learning.choice import draw
from learning.config import LearningConfig, TrainerConfig
from learning.fit import TrainerError
from learning.generalise import Vocabulary, as_it_happened
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
    alike."""

    def __init__(self) -> None:
        self.plans: dict[str, list] = {}
        self.requests: list[LLMRequest] = []
        self.client = ScriptedClient(self._answer)

    def choices(self, name: str) -> list[LLMRequest]:
        return [r for r in self.requests if r.tools and _resident(r) == name]

    def generalising(self) -> list[LLMRequest]:
        return [r for r in self.requests if r.json_schema]

    def _answer(self, request: LLMRequest):
        self.requests.append(request)
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


async def town(tmp_path, name: str = "town") -> RunDirectory:
    run = RunDirectory.create(tmp_path / "runs", name, config=LearningConfig(), code_revision="t")
    for resident_name in ("Ana", "Ben"):
        resident(run.agent_dir(resident_name), background=f"I am {resident_name}, the baker.")
    await live_day(run, 1)
    return run


async def live_day(run: RunDirectory, day: int) -> None:
    await a_day(AgentDirectory(run.agent_dir("Ana")), day, friend="Ben")
    await a_day(AgentDirectory(run.agent_dir("Ben")), day, friend="Ana")


def nights(run, server, tmp_path, model, **settings) -> Nights:
    trainer = TrainerConfig(python=fake_trainer(tmp_path), base="/models/base", gpus="5")
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
        vocabulary=Vocabulary.of_town(
            residents=["Ana", "Ben"], places=[], things=["bread"], ids=[], currency="$"
        ),
    )


def keeps(*moments: int, why: str | None = None):
    calls = [tool_call("keep", moment=m, **({"why": why} if why else {})) for m in moments]
    return [reply("", *calls), reply("That is all.")] if moments else [reply("Not tonight.")]


def read(run, night, name, file):
    return json.loads((run.night_dir(night) / name / file).read_text())


def lines(run, night, name, file):
    return list(read_jsonl(run.night_dir(night) / name / file))


async def test_each_resident_goes_from_its_choice_to_its_own_adapter_night_after_night(
    tmp_path, server, record
):
    run, model = await town(tmp_path), Model()
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
    assert server.loaded == {"town-Ana-night-01": str(adapter.resolve())}
    assert switched == [{"Ana": "town-Ana-night-01", "Ben": None}]
    done = json.loads((run.night_dir(1) / "done.json").read_text())["residents"]
    assert done["Ana"] | {"replies": 0} == {
        "ended": "done", "replies": 0, "marked": 2, "kept": 2, "examples": 2, "new": 2,
        "dropped": {}, "dataset": 2, "fitted": True, "adapter": "town-Ana-night-01",
    }  # fmt: skip
    assert (done["Ben"]["fitted"], done["Ben"]["adapter"], done["Ben"]["marked"]) == (
        False, None, 0
    )  # fmt: skip
    assert [r.model for r in model.choices("Ana")] == [None, None]  # the base, the first night
    assert "Monday 2 March: 2\n\nThe days" in model.choices("Ana")[0].messages[1].content
    assert adapter_for(run.root, "Ana", 1) == adapter.resolve()
    assert adapter_for(run.root, "Ana", 0) is None and adapter_for(run.root, "Ben", 1) is None

    await live_day(run, 2)
    model.plans = {"Ana": keeps(1, 5), "Ben": keeps(4)}
    await night.live(2, lambda: {"Ana": 3, "Ben": 1}, switched.append)

    assert {r.model for r in model.choices("Ana")[2:]} == {"town-Ana-night-01"}
    assert "Monday 2 March: 2\nTuesday 3 March: 3\n" in model.choices("Ana")[2].messages[1].content
    assert [k["moment"] for k in read(run, 2, "Ana", "kept.json")["kept"]] == [5]  # 1 carried
    assert [p["moment"] for p in lines(run, 2, "Ana", "provenance.jsonl")] == [2, 5]  # newest 2
    assert [p["night"] for p in lines(run, 2, "Ana", "provenance.jsonl")] == [1, 2]
    assert [[j["name"] for j in r["spec"]["jobs"]] for r in record()] == [
        ["town-Ana-night-01"],
        ["town-Ana-night-02", "town-Ben-night-02"],
    ]
    assert set(server.loaded) == {"town-Ana-night-02", "town-Ben-night-02"}  # night 1's let go
    assert switched[-1] == {"Ana": "town-Ana-night-02", "Ben": "town-Ben-night-02"}
    assert adapter_for(run.root, "Ana", 1) == adapter.resolve()
    assert adapter_for(run.root, "Ana", 2) == run.adapter_dir("Ana", 2).resolve()


async def test_the_raw_arm_learns_moments_as_they_happened_the_random_arm_as_many_drawn(
    tmp_path, server, record
):
    run, model = await town(tmp_path, "raw"), Model()
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

    run, model = await town(tmp_path, "random"), Model()
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
    run, model = await town(tmp_path), Model()
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
    monkeypatch.setenv("FAKE_TRAINER_FAIL", "1")
    with pytest.raises(TrainerError, match="exited with 3"):  # it fitted Ana's, then failed
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
    assert "out of memory" in (run.night_dir(1) / "trainer.log").read_text()

    monkeypatch.delenv("FAKE_TRAINER_FAIL")
    asked = len(model.requests)
    await night.live(1, lambda: {"Ana": 9, "Ben": 9}, switched.append)
    assert len(model.requests) == asked  # nothing asked again
    assert [[j["name"] for j in r["spec"]["jobs"]] for r in record()][1:] == [["town-Ben-night-01"]]
    names = {"Ana": "town-Ana-night-01", "Ben": "town-Ben-night-01"}
    assert switched == [names] and set(server.loaded) == set(names.values())
    assert json.loads((run.night_dir(1) / "liked_by.json").read_text()) == {"Ana": 1, "Ben": 1}

    # A complete night is never done again: it only puts everyone back on its adapters, as a run
    # resumed after it needs, loading what the server has lost.
    server.loaded.clear()
    await night.live(1, lambda: pytest.fail("the numbers asked again"), switched.append)
    assert len(model.requests) == asked and len(record()) == 2
    assert switched[-1] == names and set(server.loaded) == set(names.values())


def _kept(moment: int):
    from learning.choice import Kept

    return Kept(moment=moment, day=1)


def _resident(request: LLMRequest) -> str:
    return re.search(r"\bI am (\w+)", request.messages[0].content)[1]
