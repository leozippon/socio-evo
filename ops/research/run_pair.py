"""Preflight and run the town/academy pair on Zenith project storage.

This foreground controller starts two independent processes, retains their exit codes,
and forwards termination. It never restarts a failed experiment automatically.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml

from experiments.config import PROJECT_ROOT, load_experiment
from infrastructure.config import StrictModel
from infrastructure.llm import LLMRequest, Message, Sampling, complete_structured, create_client
from infrastructure.storage.run_directory import RunDirectory, RunStatus
from simulation.config import ExperimentConfig
from simulation.run import run
from world import research_sources, research_workspace

PROJECT_STORAGE = Path("/project_c20250210/260903018")
ARMS = ("town", "academy")


class Ready(StrictModel):
    ok: Literal[True]


def remote_root(value: Path) -> Path:
    root = value.resolve()
    if not value.is_absolute() or not root.is_relative_to(PROJECT_STORAGE):
        raise ValueError(f"--runs-root must be an absolute path under {PROJECT_STORAGE}")
    if not PROJECT_STORAGE.is_dir():
        raise ValueError("Zenith project storage is not mounted; no experiment was started")
    return root


def configuration(path: Path, seed: int, gpu: str | None) -> ExperimentConfig:
    config = load_experiment(path)
    data = config.model_dump(mode="json")
    data["name"] = f"{config.name}-seed-{seed}"
    data["town"]["seed"] = seed
    if gpu is not None:
        data["town"]["research"]["gpus"] = gpu
    return ExperimentConfig.model_validate(data)


def require_credentials(configs: dict[str, ExperimentConfig]) -> None:
    required = {"TAVILY_API_KEY"}
    for config in configs.values():
        research = config.town.research
        if research is None or research.judge is None or not research.milestones:
            raise ValueError("Both arms require research milestones and an external judge")
        for profile in (config.llm, research.judge):
            if profile.backend != "openai_compatible":
                raise ValueError(
                    "Research requires real OpenAI-compatible actor and judge services"
                )
            if not os.path.expandvars(profile.base_url).startswith(("https://", "http://")):
                raise ValueError("A model endpoint is missing or unresolved")
            required.add(profile.api_key_env)
        if config.llm.model == research.judge.model:
            raise ValueError("The external judge must differ from the actor model")
    missing = sorted(name for name in required if not os.environ.get(name, "").strip())
    if missing:
        raise ValueError("Missing credential environment variables: " + ", ".join(missing))


def _write(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


async def preflight(configs: dict[str, ExperimentConfig], control: Path) -> dict:
    """Use the exact profiles and real network/container operations, before either arm starts."""
    require_credentials(configs)
    report: dict = {"started_at": datetime.now(UTC).isoformat(), "checks": {}}
    stage = "actor"
    try:
        # Shared profiles need only one probe; distinct supplied profiles are checked separately.
        seen = set()
        for arm, config in configs.items():
            fingerprint = config.llm.model_dump_json()
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            stage = f"actor:{arm}"
            client = create_client(config.llm)
            request = LLMRequest(
                messages=(Message(role="user", content="Call echo with text hello."),),
                tools=(
                    {
                        "type": "function",
                        "function": {
                            "name": "echo",
                            "description": "Return text.",
                            "parameters": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"],
                                "additionalProperties": False,
                            },
                        },
                    },
                ),
                tool_choice="required",
                sampling=Sampling(max_tokens=4096),
                reasoning_effort=config.runtime.reasoning_effort,
            )
            answer = await client.stream(request)
            if (
                answer.truncated
                or not answer.tool_calls
                or any(
                    c.name != "echo" or c.arguments != {"text": "hello"} or c.unreadable
                    for c in answer.tool_calls
                )
            ):
                raise ValueError("Actor tool-call probe failed")
            continuation = await client.stream(
                LLMRequest(
                    messages=(
                        *request.messages,
                        Message(
                            role="assistant",
                            content=answer.text,
                            tool_calls=answer.tool_calls,
                            reasoning_content=answer.reasoning,
                        ),
                        *(
                            Message(role="tool", content="hello", tool_call_id=c.id)
                            for c in answer.tool_calls
                        ),
                        Message(role="user", content="Repeat the returned word, then stop."),
                    ),
                    sampling=Sampling(max_tokens=4096),
                    reasoning_effort=config.runtime.reasoning_effort,
                )
            )
            if continuation.truncated or "hello" not in continuation.text.lower():
                raise ValueError("Actor tool feedback probe failed")
            report["checks"][stage] = {"model": config.llm.model, "ok": True}
        seen.clear()
        for arm, config in configs.items():
            judge = config.town.research.judge
            fingerprint = judge.model_dump_json()
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            stage = f"judge:{arm}"
            await complete_structured(
                create_client(judge),
                LLMRequest(
                    messages=(Message(role="user", content='Reply with JSON {"ok": true}.'),),
                    sampling=Sampling(max_tokens=2048),
                ),
                Ready,
                attempts=1,
            )
            report["checks"][stage] = {"model": judge.model, "ok": True}
        for stage, call, argument in (
            ("tavily", research_sources.search_web, "reproducible research"),
            ("semantic_scholar", research_sources.search, "reproducible research"),
            ("curl", research_sources.curl_source, "https://example.org"),
        ):
            if stage == "semantic_scholar" and not any(
                config.town.research.semantic_scholar for config in configs.values()
            ):
                report["checks"][stage] = {"enabled": False, "status": "disabled"}
                continue
            result = await asyncio.to_thread(call, argument)
            report["checks"][stage] = {
                "ok": True,
                "source": result.get("source", result.get("url")),
            }
        seen.clear()
        for arm, config in configs.items():
            settings = config.town.research
            fingerprint = (
                settings.image,
                settings.network,
                settings.gpus,
                settings.cpus,
                settings.memory,
                settings.persistent_runtime,
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            stage = f"docker:{arm}"
            await asyncio.to_thread(research_workspace.require_image, settings.image)
            with tempfile.TemporaryDirectory(prefix="preflight-", dir=control) as temporary:
                files, records = Path(temporary) / "files", Path(temporary) / "records"
                files.mkdir()
                records.mkdir()
                probe = (
                    "import numpy, scipy, pandas, sklearn, sympy, networkx; "
                    'from pathlib import Path; Path("probe.txt").write_text("ok")'
                )
                if settings.persistent_runtime:
                    if not settings.gpus or not settings.gpus.startswith("device="):
                        raise ValueError("AI research requires an explicit GPU device selection")
                    probe += (
                        "; import torch; assert torch.cuda.is_available(); torch.manual_seed(7); "
                        "model=torch.nn.Linear(4,1).cuda(); before=model.weight.detach().clone(); "
                        "opt=torch.optim.Adam(model.parameters(),lr=0.01); "
                        "loss=model(torch.randn(8,4,device='cuda')).square().mean(); "
                        "loss.backward(); opt.step(); assert not torch.equal(before,model.weight); "
                        "torch.save(model.state_dict(),'probe.pt')"
                    )
                command = "python -c " + shlex.quote(probe)
                if settings.network:
                    command += (
                        " && curl --fail --silent --max-time 30 https://example.org >/dev/null"
                    )
                if settings.gpus:
                    command += (
                        " && nvidia-smi --query-gpu=uuid --format=csv,noheader > gpu-uuids.txt"
                    )
                runtime_dir = Path(temporary) / "runtime" if settings.persistent_runtime else None
                result = await research_workspace.execute(
                    settings.image,
                    files,
                    records,
                    command,
                    90,
                    network=settings.network,
                    gpus=settings.gpus,
                    cpus=settings.cpus,
                    memory=settings.memory,
                    runtime_dir=runtime_dir,
                )
                if result["exit_code"] != 0 or result["timed_out"]:
                    raise ValueError("Research container preflight failed")
                if (files / "probe.txt").read_text() != "ok":
                    raise ValueError("Research container output did not persist")
                report["checks"][stage] = {"ok": True, "gpus": settings.gpus}
                if settings.persistent_runtime:
                    expected = subprocess.check_output(
                        [
                            "nvidia-smi",
                            "--id",
                            settings.gpus.removeprefix("device="),
                            "--query-gpu=uuid",
                            "--format=csv,noheader",
                        ],
                        text=True,
                    ).splitlines()
                    observed = (files / "gpu-uuids.txt").read_text().splitlines()
                    if sorted(observed) != sorted(expected):
                        raise ValueError("Research container exposed the wrong physical GPU")
                    reload = await research_workspace.execute(
                        settings.image,
                        files,
                        records,
                        "python -c "
                        + shlex.quote(
                            "import torch; state=torch.load('probe.pt',map_location='cuda',"
                            "weights_only=True); assert all(torch.isfinite(v).all() "
                            "and v.is_cuda for v in state.values())"
                        ),
                        90,
                        network=False,
                        gpus=settings.gpus,
                        cpus=settings.cpus,
                        memory=settings.memory,
                        runtime_dir=runtime_dir,
                    )
                    if reload["exit_code"] != 0 or reload["timed_out"]:
                        raise ValueError("Research CUDA checkpoint reload failed")
                    report["checks"][stage].update(
                        cuda_training=True, checkpoint_reload=True, gpu_uuids=observed
                    )
        report["ok"] = True
        return report
    except Exception as error:
        report.update(ok=False, failed_check=stage, error_type=type(error).__name__)
        raise RuntimeError(f"Preflight failed at {stage}: {type(error).__name__}") from None
    finally:
        report["ended_at"] = datetime.now(UTC).isoformat()
        _write(control / "preflight.json", report)


def pending(configs, root: Path, *, resume: bool, until_day: int | None) -> dict:
    active = {}
    for arm, config in configs.items():
        until = until_day or config.days
        if not 1 <= until <= config.days:
            raise ValueError(f"--until-day must be between 1 and {config.days}")
        destination = root / config.name
        if not resume:
            if destination.exists():
                raise FileExistsError(f"Run exists: {destination}; use --resume explicitly")
        else:
            directory = RunDirectory.open(destination)
            if load_experiment(directory.config_path) != config:
                raise ValueError(f"Configuration differs from frozen run: {destination}")
            manifest = directory.read_manifest()
            if manifest.pid:
                try:
                    os.kill(manifest.pid, 0)
                except ProcessLookupError:
                    pass
                else:
                    raise ValueError(f"Run still has a live process: {destination}")
            saved = directory.latest_checkpoint()
            if saved is None:
                raise ValueError(f"No checkpoint to resume: {destination}")
            if saved >= until:
                continue
        active[arm] = config
    return active


async def launch(configs, root: Path, control: Path, *, resume: bool, until_day: int | None):
    # Validate every frozen profile before starting either process.
    for arm, config in configs.items():
        path = control / f"{arm}.yaml"
        serialized = yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False)
        if path.exists() and path.read_text() != serialized:
            raise ValueError(f"Frozen launch configuration differs: {path}")
        path.write_text(serialized)
    processes = []
    records = {arm: {"status": "starting"} for arm in configs}
    loop = asyncio.get_running_loop()

    def stop():
        for process in processes:
            if process.returncode is None:
                process.terminate()

    for sign in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sign, stop)

    async def worker(arm, config):
        path = control / f"{arm}.yaml"
        command = [
            sys.executable,
            "-m",
            "ops.research.run_pair",
            "--arm",
            arm,
            "--frozen-config",
            str(path),
            "--runs-root",
            str(root),
        ]
        if resume:
            command.append("--resume")
        if until_day is not None:
            command.extend(["--until-day", str(until_day)])
        with (control / f"{arm}.log").open("a") as log:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=PROJECT_ROOT,
                stdout=log,
                stderr=asyncio.subprocess.STDOUT,
            )
            processes.append(process)
            records[arm] = {"status": "running", "pid": process.pid, "run": config.name}
            _write(control / "status.json", records)
            code = await process.wait()
            manifest_path = root / config.name / "manifest.json"
            status = (
                json.loads(manifest_path.read_text())["status"]
                if manifest_path.exists()
                else "failed"
            )
            records[arm].update(status=status, pid=None, exit_code=code)
            _write(control / "status.json", records)
            return code

    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(worker(arm, config)) for arm, config in configs.items()]
        results = [task.result() for task in tasks]
        return 0 if all(code == 0 for code in results) else 1
    finally:
        stop()
        await asyncio.gather(*(process.wait() for process in processes))
        for sign in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sign)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260302)
    parser.add_argument("--until-day", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    for arm in ARMS:
        parser.add_argument(
            f"--{arm}-config",
            type=Path,
            default=PROJECT_ROOT / f"experiments/configs/autoresearch-{arm}.yaml",
        )
        parser.add_argument(f"--{arm}-gpu", help='Docker GPU selection, e.g. "device=0"')
    parser.add_argument("--arm", choices=ARMS, help=argparse.SUPPRESS)
    parser.add_argument("--frozen-config", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root = remote_root(args.runs_root)
    if args.arm:
        config = load_experiment(args.frozen_config)
        _, status = asyncio.run(run(config, root, resume=args.resume, until_day=args.until_day))
        return 1 if status == RunStatus.FAILED else 0
    configs = {
        arm: configuration(getattr(args, f"{arm}_config"), args.seed, getattr(args, f"{arm}_gpu"))
        for arm in ARMS
    }
    require_credentials(configs)
    control = root / f"pair-seed-{args.seed}"
    control.mkdir(parents=True, exist_ok=True)
    with (control / "controller.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        active = pending(configs, root, resume=args.resume, until_day=args.until_day)
        asyncio.run(preflight(configs, control))
        if args.preflight_only:
            print(f"Preflight passed: {control / 'preflight.json'}")
            return 0
        return asyncio.run(
            launch(active, root, control, resume=args.resume, until_day=args.until_day)
        )


if __name__ == "__main__":
    raise SystemExit(main())
