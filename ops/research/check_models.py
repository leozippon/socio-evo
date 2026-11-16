"""Verify the real dated-model tool, Docker and GPU 1 worker in a separate Zenith directory.

Run only after the operator has stopped other research work on GPU 1. This probe does not
start resident LLMs, call the judge, modify a formal run, or stop unrelated GPU processes.
"""

from __future__ import annotations

import argparse
import asyncio
import errno
import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from agent.directory import AgentDirectory
from experiments.config import PROJECT_ROOT, load_experiment
from ops.research.run_pair import remote_root
from world.clock import DAY, ManualClock
from world.config import ResearchSettings
from world.events import Idle
from world.living import put_to_sleep
from world.research import TRANSFORMERS_EXAMPLE, NoTasks
from world.research_models import ModelGateway
from world.world import World

PROMPTS = [
    "用一句话说明什么是信息检索。",
    "用一句话说明稠密检索与关键词检索的一个区别。",
]
GPU_CHECK = """python - <<'PY'
import json
from pathlib import Path
import torch
models = json.load(open('/records/models.json'))['models']
mounts = [line.split() for line in Path('/proc/self/mountinfo').read_text().splitlines()]
assert all(any(m[4] == '/models/' + key and 'ro' in m[5].split(',') for m in mounts)
           for key in models), 'A model mount is not read-only'
assert torch.cuda.device_count() == 1
device = torch.cuda.get_device_properties(0)
print('MODEL_PROBE_GPU_JSON=' + json.dumps({'uuid': str(device.uuid), 'name': device.name,
      'models': list(models), 'readonly': True}))
PY"""


def _link_or_copy(source, destination):
    try:
        return os.link(source, destination)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        return shutil.copy2(source, destination)


def _reuse_cache(source: Path, destination: Path, info: dict) -> bool:
    """Reuse a previously verified immutable snapshot without exposing the whole cache."""
    artifact = "hf-" + hashlib.sha256(
        (info["repo_id"] + "\n" + info["revision"]).encode()
    ).hexdigest()[:32]
    origin = source / artifact
    if not origin.exists():
        return False
    raw = (origin / "manifest.json").read_bytes()
    manifest = json.loads(raw)
    receipt = {
        "artifact_id": artifact, "repo_id": info["repo_id"], "revision": info["revision"],
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
    }
    ModelGateway(source).resolve(receipt)
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(origin, destination / artifact, copy_function=_link_or_copy)
    ModelGateway(destination).resolve(receipt)
    assert manifest["revision"] == info["revision"]
    return True


async def check(
    config_path: Path, output: Path, inference_python: str,
    cache_source: Path | None = None, image: str | None = None,
) -> dict:
    output = remote_root(output)
    config = load_experiment(config_path).town
    if config.research is None:
        raise ValueError("The selected profile has no research workspace")
    settings = config.research.model_dump()
    settings.update(models_enabled=True, inference_python=inference_python, gpus="device=1")
    if image:
        settings["image"] = image
    config = config.model_copy(update={"research": ResearchSettings.model_validate(settings)})
    output.mkdir(parents=True, exist_ok=False)
    results = output / "tool-results"
    results.mkdir()
    stage = "initialize"

    def save(path, value):
        (output / path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    def awaken(current):
        resident = current.residents["Mei"]
        resident.base, resident.place = Idle(), "office"
        resident.reckoned = current.clock.now()
        resident.living.energy = 100
        return resident

    def snapshot(current):
        for resident in current.residents.values():
            resident.reckoned = current.clock.now()
            put_to_sleep(current, resident, current.clock.now() + 3600, suspended=True)
        return current.snapshot()

    calls = 0

    async def call(current, tool, args):
        nonlocal calls
        calls += 1
        answer = await current.call(awaken(current), tool, args)
        record = {"tool": tool, "arguments": args, "response": answer.text}
        if answer.text.startswith("Revision:"):
            _, record_line, content = answer.text.split("\n", 2)
            record["evidence"] = json.loads(
                (current.research.root / record_line.removeprefix("Record: ")).read_text()
            )
            result = json.loads(content)
        else:
            result = {"error": answer.text}
        save(f"tool-results/{calls:02d}-{tool}.json", record)
        return result

    try:
        expected_gpu = subprocess.check_output(
            ["nvidia-smi", "--id=1", "--query-gpu=uuid", "--format=csv,noheader"], text=True
        ).strip()
        assert expected_gpu.startswith("GPU-")
        for resident in config.residents:
            AgentDirectory.create(
                output / "agents" / resident.name,
                background="A synthetic infrastructure acceptance researcher.",
            )
        world = World(config, output, NoTasks(), clock=ManualClock())
        world.research.initialize(world)
        world.clock.set((config.research.start_day - 1) * DAY + world.forced_wake)
        world.research.announce(world)
        stage = "historical_model_info"
        info = await call(world, "model", {
            "action": "info", "repo_id": "Qwen/Qwen2.5-0.5B-Instruct",
        })
        assert "revision" in info, info
        cutoff = world.research.simulated_now(world)
        assert datetime.fromisoformat(info["commit_time"].replace("Z", "+00:00")) <= cutoff
        reused = cache_source is not None and _reuse_cache(
            cache_source, output / "model_cache", info
        )
        before = snapshot(world)
        save("checkpoint-before-admission.json", before)
        stage = "tool_download_admission"
        admission = await call(world, "model", {
            "action": "download", "repo_id": info["repo_id"], "revision": info["revision"],
        })
        assert admission.get("revision") == info["revision"] and "model_id" in admission
        assert "local_path" not in admission
        model_id = admission["model_id"]
        stage = "docker_transformers"
        shell = await call(world, "shell", {
            "command": TRANSFORMERS_EXAMPLE + "\n" + GPU_CHECK,
            "revision": world.research.snapshot(),
        })
        assert shell.get("exit_code") == 0 and not shell.get("timed_out"), shell
        gpu_line = next(
            line for line in shell["stdout"].splitlines()
            if line.startswith("MODEL_PROBE_GPU_JSON=")
        )
        docker_gpu = json.loads(gpu_line.split("=", 1)[1])
        assert docker_gpu["uuid"].removeprefix("GPU-") == expected_gpu.removeprefix("GPU-")
        assert shell["models"][0]["revision"] == admission["revision"]
        stage = "vllm_batch"
        generation = await call(world, "model", {
            "action": "generate", "model_id": model_id, "prompts": PROMPTS,
            "max_tokens": 96,
        })
        assert generation.get("ok") is True, generation
        assert generation["gpu_uuid"] == expected_gpu
        assert generation["model"]["revision"] == admission["revision"]
        assert len(generation["outputs"]) == 2
        assert all(item["text"].strip() for item in generation["outputs"])
        after = snapshot(world)
        save("checkpoint-after-inference.json", after)
        stage = "checkpoint_admission_isolation"
        restored = World(config, output, NoTasks(), clock=ManualClock())
        restored.restore(before)
        assert (output / "model_cache" / model_id).is_dir()
        assert (await call(restored, "model", {"action": "list"}))["models"] == []
        assert restored.research._model_mounts() == {}
        hidden = await call(restored, "model", {
            "action": "generate", "model_id": model_id, "prompt": PROMPTS[0],
        })
        assert "admitted model_id" in hidden.get("error", ""), hidden
        restored = World(config, output, NoTasks(), clock=ManualClock())
        restored.restore(after)
        listed = await call(restored, "model", {"action": "list"})
        assert [item["model_id"] for item in listed["models"]] == [model_id]
        assert list(restored.research._model_mounts()) == [model_id]
        save("checkpoint-final.json", snapshot(restored))
        receipt = {
            "ok": True, "finished_at": datetime.now(UTC).isoformat(),
            "simulated_as_of": cutoff.isoformat(), "repo_id": info["repo_id"],
            "revision": info["revision"], "model_id": model_id, "cache_reused": reused,
            "image": config.research.image, "gpu_uuid": expected_gpu,
            "docker": docker_gpu, "generation": generation,
            "restore_checks": 2, "unadmitted_cached_model_hidden": True,
            "tool_calls": calls, "formal_run": False, "judge_calls": 0,
            "limitations": info["provenance"]["limitation"],
        }
        save("receipt.json", receipt)
        return receipt
    except Exception as error:
        save("failure.json", {
            "ok": False, "stage": stage, "type": type(error).__name__, "message": str(error),
        })
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=PROJECT_ROOT / "experiments/configs/ir-lab.yaml"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inference-python", required=True)
    parser.add_argument("--cache-source", type=Path)
    parser.add_argument("--image")
    args = parser.parse_args(argv)
    try:
        receipt = asyncio.run(check(
            args.config, args.output, args.inference_python, args.cache_source, args.image,
        ))
    except Exception as error:
        print(json.dumps({"ok": False, "status": type(error).__name__, "message": str(error)}))
        return 1
    print(json.dumps({key: receipt[key] for key in (
        "ok", "revision", "gpu_uuid", "cache_reused", "restore_checks", "tool_calls",
    )}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
