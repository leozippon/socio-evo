"""Published GPU guidance reaches the same command path and retains explicit failures."""

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.directory import AgentDirectory
from experiments.config import load_experiment
from world import research_workspace
from world.clock import ManualClock
from world.config import ResearchSettings
from world.events import Idle
from world.research import NoTasks, research_help
from world.world import World


@pytest.fixture
def lab(tmp_path):
    config = load_experiment(
        Path(__file__).resolve().parents[2] / "experiments/configs/ai-lab.yaml"
    )
    for resident in config.town.residents:
        AgentDirectory.create(tmp_path / "agents" / resident.name, background="A researcher.")
    world = World(config.town, tmp_path, NoTasks(), clock=ManualClock())
    world.research.initialize(world)
    return world


def test_gpu_guidance_is_published_only_with_the_commission(lab):
    assert "cuda:0" not in (lab.research.files / "README.md").read_text()
    assert "research" not in lab.rules.topics()
    lab.research.announce(lab)
    help_text = lab.rules.help("research")
    readme = (lab.research.files / "README.md").read_text()
    assert help_text in readme
    for resident in lab.residents.values():
        brief = next(p.text for p in resident.port.held if p.kind == "research_brief")
        assert "device=1" in brief and "cuda:0" in brief
    assert "nvidia-smi" in help_text and "loss.backward()" in help_text
    assert "CPU remains appropriate" in help_text
    no_gpu = research_help(ResearchSettings())
    assert "No GPU is configured" in no_gpu and "loss.backward()" not in no_gpu


def test_published_example_fails_explicitly_without_cuda(lab, monkeypatch):
    lab.research.announce(lab)
    text = (lab.research.files / "README.md").read_text()
    command, = re.findall(r"```sh\n(.*?)\n```", text, re.DOTALL)
    python = command.split("<<'PY'\n", 1)[1].removesuffix("\nPY")
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: False)
    ))
    with pytest.raises(RuntimeError, match="CUDA is unavailable"):
        exec(compile(python, "published-gpu-example", "exec"), {})


@pytest.mark.parametrize("exit_code", [0, 1])
async def test_published_shell_example_uses_configured_gpu_and_records_outcome(
    lab, monkeypatch, exit_code
):
    lab.research.announce(lab)
    text = lab.rules.help("research")
    command, = re.findall(r"```sh\n(.*?)\n```", text, re.DOTALL)
    calls = []

    class Process:
        returncode = exit_code

        async def communicate(self):
            return (b"command output", b"CUDA is unavailable" if exit_code else b"")

        async def wait(self):
            return self.returncode

    async def spawn(*args, **kwargs):
        calls.append(args)
        return Process()

    monkeypatch.setattr(research_workspace.asyncio, "create_subprocess_exec", spawn)
    resident = lab.residents["Aisha"]
    resident.base, resident.place = Idle(), "office"
    result = await lab.call(resident, "shell", {
        "command": command, "revision": lab.research.snapshot(),
    })
    argv = calls[0]
    assert argv[argv.index("--gpus") + 1] == "device=1"
    assert argv[argv.index("--cpus") + 1] == "8.0"
    assert argv[-4:] == (lab.research.settings.image, "sh", "-c", command)
    records = [json.loads(p.read_text()) for p in lab.research.records.glob("*.json")]
    execution, = [r for r in records if r.get("tool") == "shell"]
    assert execution["arguments"]["command"] == command
    assert execution["result"]["exit_code"] == exit_code
    assert execution["result"]["stderr"] == ("CUDA is unavailable" if exit_code else "")
    assert f'"exit_code": {exit_code}' in result.text
    assert calls[-1][1:3] == ("rm", "-f")
