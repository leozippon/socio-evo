"""The resident model tool admits dated snapshots before compute can see them."""

import asyncio
import json
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.directory import AgentDirectory
from experiments.config import load_experiment
from world import research_workspace
from world.clock import DAY, ManualClock
from world.config import ResearchSettings
from world.events import Idle
from world.research import NoTasks, Research, model_help
from world.world import World

MODEL_ID = "hf-" + "a" * 32


@pytest.fixture
def lab(tmp_path, monkeypatch):
    config = load_experiment(Path("experiments/configs/ir-lab.yaml")).town
    data = config.research.model_dump()
    data.update(models_enabled=True, inference_python="/serving/venv/bin/python")
    config = config.model_copy(update={"research": ResearchSettings.model_validate(data)})
    for resident in config.residents:
        AgentDirectory.create(tmp_path / "agents" / resident.name, background="An IR researcher.")
    world = World(config, tmp_path, NoTasks(), clock=ManualClock())
    world.research.initialize(world)

    class Gateway:
        def __init__(self):
            self.cache_dir = tmp_path / "model_cache"
            self.calls = []

        def search(self, query, as_of, limit):
            self.calls.append(("search", as_of))
            return {"results": [{"repo_id": "test/model"}]}

        def info(self, repo_id, as_of, revision=None):
            self.calls.append(("info", as_of))
            return {"repo_id": repo_id, "revision": revision or "b" * 40}

        def download(self, repo_id, as_of, revision=None, *, cancel):
            self.calls.append(("download", as_of))
            path = self.cache_dir / MODEL_ID / "snapshot"
            path.mkdir(parents=True, exist_ok=True)
            (path / "model.safetensors").write_bytes(b"test-weights")
            return {
                "provider": "huggingface",
                "repo_id": repo_id,
                "revision": revision or "b" * 40,
                "artifact_id": MODEL_ID,
                "local_path": str(path),
                "manifest_sha256": "c" * 64,
                "commit_time": "2025-01-01T00:00:00Z",
                "total_bytes": 12,
                "provenance": {"as_of": as_of.isoformat(), "availability_verified": False},
            }

        def resolve(self, receipt):
            assert receipt["artifact_id"] == MODEL_ID
            path = self.cache_dir / MODEL_ID / "snapshot"
            assert path.is_dir()
            return path

    gateway = Gateway()
    monkeypatch.setattr(Research, "_model_gateway", lambda self: gateway)
    return world, gateway


def activate(world):
    world.clock.set(7 * DAY + 7 * 3600)
    world.research.announce(world)
    for resident in world.residents.values():
        resident.base, resident.place = Idle(), "office"
        resident.reckoned = world.clock.now()
        resident.living.energy = 100
    return world.residents["Mei"]


async def model(world, **args):
    answer = await world.call(world.residents["Mei"], "model", args)
    if answer.text.startswith("Revision:"):
        return json.loads(answer.text.split("\n", 2)[2])
    return {"refusal": answer.text}


def test_model_configuration_is_opt_in_and_requires_host_managed_compute():
    assert not ResearchSettings().models_enabled
    with pytest.raises(ValueError, match="inference_python"):
        ResearchSettings(models_enabled=True, gpus="device=1")
    with pytest.raises(ValueError, match="GPU 1"):
        ResearchSettings(models_enabled=True, inference_python="/python", gpus="device=0")


async def test_capability_is_hidden_until_release_and_announced_once_to_all(lab):
    world, gateway = lab
    world.research.schedule(world, 1)
    assert "model" not in {s.name for s in world.tool_specs}
    assert not (world.research.records / "models-capability.json").exists()
    assert "unavailable" in (await model(world, action="list"))["refusal"]
    resident = activate(world)
    assert "model" in {s.name for s in world.usable(resident)}
    checkpoint = world.research.snapshot()
    world.research.schedule(world, 8)
    world.research.restore(checkpoint)
    world.research.schedule(world, 8)
    events = [e for e in world.log.entries() if e.get("payload", {}).get("capability") == "models"]
    assert len(events) == 1
    assert events[0]["payload"]["allowance"] == 0
    assert all(
        any("dated Hugging Face" in p.text for p in r.port.held) for r in world.residents.values()
    )
    resident.place = resident.home
    assert "Office" in (await model(world, action="list"))["refusal"]
    assert gateway.calls == []
    help_text = model_help(world.research.settings)
    assert "local_files_only=True" in help_text and "chat=False" in help_text
    assert "3600-second" in help_text


async def test_download_admission_readonly_shell_and_vllm_share_exact_identity(lab, monkeypatch):
    world, gateway = lab
    activate(world)
    for action, args in (("search", {"query": "model"}), ("info", {"repo_id": "test/model"})):
        await model(world, action=action, **args)
    downloaded = await model(world, action="download", repo_id="test/model")
    as_of = datetime(2026, 3, 7, 23, tzinfo=UTC)
    assert all(when == as_of for _, when in gateway.calls)
    assert downloaded["model_id"] == MODEL_ID
    assert downloaded["mount_path"] == "/models/" + MODEL_ID
    assert "local_path" not in downloaded
    admission = json.loads((world.research.records / "models.json").read_text())
    assert admission["models"][MODEL_ID]["revision"] == "b" * 40
    assert str(gateway.cache_dir) not in json.dumps(admission)
    assert not list(world.research.root.rglob("*.safetensors"))

    commands = []

    class Process:
        returncode = 0

        async def communicate(self):
            return b"model loaded offline", b""

        async def wait(self):
            return 0

    async def spawn(*args, **kwargs):
        commands.append(args)
        return Process()

    monkeypatch.setattr(research_workspace.asyncio, "create_subprocess_exec", spawn)
    shell = await world.call(
        world.residents["Mei"],
        "shell",
        {
            "command": "python study.py",
            "revision": world.research.snapshot(),
        },
    )
    assert "model loaded offline" in shell.text
    mounts = [commands[0][i + 1] for i, word in enumerate(commands[0]) if word == "--mount"]
    path = gateway.resolve(admission["models"][MODEL_ID])
    assert f"type=bind,src={path},dst=/models/{MODEL_ID},readonly" in mounts
    assert not any(f"src={gateway.cache_dir}," in value for value in mounts)
    assert "HF_HUB_OFFLINE=1" in commands[0]

    seen = []

    async def generate(path, prompts, **params):
        seen.append((path, prompts, params))
        return {"outputs": [{"text": "检索用于查找相关资料。"}], "prompt_format": "chat_template"}

    monkeypatch.setitem(
        sys.modules, "ops.research.model_inference", SimpleNamespace(generate=generate)
    )
    result = await model(world, action="generate", model_id=MODEL_ID, prompt="什么是检索？")
    assert result["model"]["revision"] == "b" * 40
    assert result["outputs"][0]["text"].startswith("检索")
    assert seen[0][0] == path
    assert seen[0][2]["gpus"] == "device=1" and seen[0][2]["chat"] is True
    assert seen[0][2]["python"] == "/serving/venv/bin/python"
    assert seen[0][2]["log_dir"] == world.research.root.parent / "model_inference_logs"
    await model(world, action="generate", model_id=MODEL_ID, prompts=["a", "b"], chat=False)
    assert seen[1][1] == ["a", "b"] and seen[1][2]["chat"] is False

    async def failed(*args, **kwargs):
        raise RuntimeError("Model does not fit available memory")

    monkeypatch.setitem(
        sys.modules, "ops.research.model_inference", SimpleNamespace(generate=failed)
    )
    failure = await model(world, action="generate", model_id=MODEL_ID, prompt="hello")
    assert failure["ok"] is False and "memory" in failure["error"]
    assert failure["model"]["revision"] == "b" * 40


async def test_restore_hides_future_cached_models_and_rejects_unadmitted_generation(lab):
    world, gateway = lab
    activate(world)
    before = world.research.snapshot()
    await model(world, action="download", repo_id="test/model")
    admitted = world.research.snapshot()
    world.research.restore(before)
    assert gateway.cache_dir.exists()
    assert (await model(world, action="list"))["models"] == []
    assert world.research._model_mounts() == {}
    failure = await model(world, action="generate", model_id=MODEL_ID, prompt="hello")
    assert "admitted" in failure["error"]
    world.research.restore(admitted)
    assert list(world.research._model_mounts()) == [MODEL_ID]


def test_enabled_continuation_announces_at_startup_and_retains_marker_on_restore(lab, tmp_path):
    template, _ = lab
    target = template.config
    old = target.model_copy(
        update={"research": target.research.model_copy(update={"models_enabled": False})}
    )
    directory = tmp_path / "continuation"
    for resident in old.residents:
        AgentDirectory.create(directory / "agents" / resident.name, background="A researcher.")
    previous = World(old, directory, NoTasks(), clock=ManualClock())
    previous.research.initialize(previous)
    previous.clock.set(7 * DAY + 7 * 3600)
    previous.research.announce(previous)
    state = previous.snapshot()
    restored = World(target, directory, NoTasks(), clock=ManualClock())
    restored.restore(state)
    assert restored.research.active
    assert not (restored.research.records / "models-capability.json").exists()
    restored.research.schedule(restored, 8)
    state = restored.snapshot()
    again = World(target, directory, NoTasks(), clock=ManualClock())
    again.restore(state)
    again.research.schedule(again, 8)
    assert all(
        sum("dated Hugging Face" in p.text for p in r.port.held) == 1
        for r in again.residents.values()
    )


@pytest.mark.parametrize("outcome", ["cancel", "timeout"])
async def test_late_model_download_cannot_admit_after_cancel_or_restore(lab, monkeypatch, outcome):
    world, gateway = lab
    activate(world)
    started, finished = threading.Event(), threading.Event()
    stops = []
    original = gateway.download

    def delayed(*args, cancel, **kwargs):
        stops.append(cancel)
        started.set()
        finished.wait(5)
        # Even an uncooperative late network operation only populates the private cache.
        return original(*args, cancel=cancel, **kwargs)

    monkeypatch.setattr(gateway, "download", delayed)
    if outcome == "timeout":
        world.research.settings = world.research.settings.model_copy(
            update={"model_download_timeout_s": 0.02}
        )
    before = world.research.snapshot()
    task = asyncio.create_task(model(world, action="download", repo_id="test/model"))
    await asyncio.to_thread(started.wait, 2)
    try:
        if outcome == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert "timed out" in (await task)["error"]
        assert stops[0].is_set()
        world.research.restore(before)
    finally:
        finished.set()
    for _ in range(100):
        if (gateway.cache_dir / MODEL_ID / "snapshot/model.safetensors").exists():
            break
        await asyncio.sleep(0.01)
    assert not (world.research.records / "models.json").exists()
    assert world.research._model_mounts() == {}


async def test_model_generation_and_shell_training_use_one_lock(lab, monkeypatch):
    world, _ = lab
    activate(world)
    await model(world, action="download", repo_id="test/model")
    started, finish = asyncio.Event(), asyncio.Event()
    commands = []

    async def generate(*args, **kwargs):
        started.set()
        await finish.wait()
        return {"outputs": [{"text": "done"}]}

    async def execute(*args, **kwargs):
        commands.append(args)
        return {"exit_code": 0, "stdout": "trained", "stderr": "", "timed_out": False}

    monkeypatch.setitem(
        sys.modules, "ops.research.model_inference", SimpleNamespace(generate=generate)
    )
    monkeypatch.setattr(research_workspace, "execute", execute)
    first = asyncio.create_task(model(world, action="generate", model_id=MODEL_ID, prompt="hello"))
    await started.wait()
    second = asyncio.create_task(
        world.call(
            world.residents["Aisha"],
            "shell",
            {
                "command": "train.py",
                "revision": world.research.snapshot(),
            },
        )
    )
    await asyncio.sleep(0)
    assert commands == [] and not second.done()
    finish.set()
    await first
    assert "trained" in (await second).text
