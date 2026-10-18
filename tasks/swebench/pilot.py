"""Run bounded repository-repair agents in isolated SWE-bench instance containers.

This produces predictions for the official evaluator, not a town run or a benchmark score.
The model receives only the issue. Gold patches and evaluation tests stay outside containers.
"""

import argparse
import asyncio
import json
import re
import subprocess
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Literal

from pydantic import Field

from infrastructure.config import StrictModel, load_config
from infrastructure.llm import (
    LLMConfig,
    LLMRequest,
    Message,
    RecordingClient,
    complete_structured,
    create_client,
)
from tasks.swebench.docker_exec import captured_exec


class PilotConfig(StrictModel):
    llm: LLMConfig
    instances: tuple[str, ...] = Field(min_length=3, max_length=5)
    max_steps: int = Field(default=20, ge=1, le=100)
    command_seconds: int = Field(default=60, ge=1, le=300)


class Action(StrictModel):
    thought: str
    action: Literal["bash", "submit"]
    command: str


SYSTEM = """Repair the issue in the repository at /testbed. Inspect files, edit code, and run
targeted tests. Each bash action is a separate shell with the testbed Python environment
activated. Only changes to files persist. No network is available. Do not change tests to
hide failures, access external solutions, or rewrite git history. Use your own diagnosis.
Return JSON with thought, action ('bash' or 'submit'), and command (empty for submit).
Submit when your patch is ready; describe remaining uncertainty honestly in thought.
You have a limited number of actions. Use concise commands and targeted output.
"""


def public_issue(row: dict) -> str:
    """Explicit allowlist: never serialize a dataset row into a model prompt."""
    return f"Repository: {row['repo']}\nIssue:\n{row['problem_statement']}"


def image_for(instance_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+-\d+", instance_id):
        raise ValueError(f"invalid instance id: {instance_id}")
    name = instance_id.lower().replace("__", "_1776_")
    return f"docker.io/swebench/sweb.eval.x86_64.{name}:latest"


def container_args(name: str, image: str) -> list[str]:
    return [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "256",
        "--memory",
        "6g",
        "--cpus",
        "2",
        image,
        "sleep",
        "infinity",
    ]


def command(args: list[str], timeout: int = 120) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed ({result.returncode}): {result.stderr[-4000:]}")
    return result.stdout


def execute(name: str, script: str, seconds: int) -> dict:
    import docker

    # Both the shell and the timeout are INSIDE the task container, never on the host.
    prelude = "source /opt/miniconda3/bin/activate testbed && cd /testbed && "
    with closing(docker.from_env()) as client:
        result = captured_exec(
            client.containers.get(name), ["bash", "-lc", prelude + script], timeout=seconds
        )
    return {
        "exit_code": result.exit_code,
        "output": result.output.decode(errors="replace")[-16000:],
    }


async def solve(row: dict, config: PilotConfig, out: Path) -> dict:
    import docker

    instance = row["instance_id"]
    folder = out / instance
    folder.mkdir()
    name = "socio-swe-" + uuid.uuid4().hex[:12]
    status = "error"
    patch = ""
    steps = 0
    error = None
    started = time.time()
    created = False
    try:
        command(container_args(name, image_for(instance)), timeout=120)
        created = True
        with closing(docker.from_env()) as docker_client:
            container = docker_client.containers.get(name)
            (folder / "image.json").write_text(
                json.dumps(
                    {
                        "id": container.image.id,
                        "digests": container.image.attrs.get("RepoDigests", []),
                    },
                    indent=2,
                )
            )
            head = captured_exec(container, ["git", "-C", "/testbed", "rev-parse", "HEAD"])
            # Official images add a setup commit (permissions/dependency fixes).
            # Keep that environment intact and extract only the agent's changes.
            baseline = captured_exec(
                container,
                [
                    "git",
                    "-C",
                    "/testbed",
                    "merge-base",
                    "--is-ancestor",
                    row["base_commit"],
                    "HEAD",
                ],
            )
            if head.exit_code or baseline.exit_code:
                raise ValueError("instance image does not descend from dataset base_commit")
            image_head = head.output.decode().strip()
            (folder / "baseline.json").write_text(
                json.dumps(
                    {
                        "image_head": image_head,
                        "dataset_base_commit": row["base_commit"],
                        "base_is_ancestor": True,
                    },
                    indent=2,
                )
            )
        client = RecordingClient(create_client(config.llm), folder / "llm_calls.jsonl")
        messages = [
            Message(role="system", content=SYSTEM),
            Message(role="user", content=public_issue(row)),
        ]
        for steps in range(1, config.max_steps + 1):
            request = LLMRequest(
                messages=tuple(messages),
                metadata={"instance_id": instance, "step": steps},
            )
            action = await complete_structured(client, request, Action, attempts=2)
            messages.append(Message(role="assistant", content=action.model_dump_json()))
            if action.action == "submit":
                status = "submitted"
                break
            result = execute(name, action.command, config.command_seconds)
            with (folder / "commands.jsonl").open("a") as f:
                f.write(json.dumps({"step": steps, "command": action.command, **result}) + "\n")
            messages.append(Message(role="user", content=json.dumps(result)))
        else:
            status = "step_limit"
        with closing(docker.from_env()) as docker_client:
            container = docker_client.containers.get(name)
            added = captured_exec(container, ["git", "-C", "/testbed", "add", "-N", "."])
            diff = captured_exec(
                container, ["git", "-C", "/testbed", "diff", "--binary", image_head]
            )
            if added.exit_code or diff.exit_code:
                raise RuntimeError("could not extract repository patch")
            patch = diff.output.decode()
        (folder / "model.patch").write_text(patch)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if created:
            try:
                command(["docker", "rm", "-f", name])
            except Exception as exc:
                error = f"{error or ''}; cleanup failed for {name}: {exc}"
                status = "error"
    result = {
        "instance_id": instance,
        "status": status,
        "steps": steps,
        "elapsed_seconds": time.time() - started,
        "patch_bytes": len(patch.encode()),
        "error": error,
    }
    (folder / "result.json").write_text(json.dumps(result, indent=2))
    with (out / "predictions.jsonl").open("a") as f:
        f.write(
            json.dumps(
                {
                    "instance_id": instance,
                    "model_name_or_path": config.llm.model,
                    "model_patch": patch,
                }
            )
            + "\n"
        )
    return result


async def run(config: PilotConfig, dataset: Path, out: Path) -> None:
    rows = {row["instance_id"]: row for row in json.loads(dataset.read_text())}
    if len(set(config.instances)) != len(config.instances):
        raise ValueError("duplicate instance ids")
    if any(i not in rows for i in config.instances):
        raise ValueError("configured instance missing from Verified dataset")
    out.mkdir(parents=True, exist_ok=False)
    (out / "config.json").write_text(config.model_dump_json(indent=2))
    manifest = {"status": "running", "results": [], "kind": "swebench-repair-pilot"}
    path = out / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2))
    for instance in config.instances:
        print(f"Starting {instance}", flush=True)
        result = await solve(rows[instance], config, out)
        manifest["results"].append(result)
        path.write_text(json.dumps(manifest, indent=2))
        print(json.dumps(result), flush=True)
    manifest["status"] = "generation_finished"
    path.write_text(json.dumps(manifest, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(load_config(args.config, PilotConfig), args.dataset, args.out))


if __name__ == "__main__":
    main()
