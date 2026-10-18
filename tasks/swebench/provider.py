"""Town residents repair isolated repositories; official tests grade their submitted diffs."""

import asyncio
import hashlib
import io
import json
import os
import random
import subprocess
import sys
import tarfile
import uuid
from pathlib import Path

from core.environment import Assessment, Part
from tasks.swebench.docker_exec import captured_exec
from tasks.swebench.pilot import command, container_args, execute, image_for, public_issue


class SWEbenchTaskProvider:
    def __init__(
        self,
        dataset: Path,
        instances: tuple[str, ...],
        root: Path,
        *,
        command_seconds: int = 60,
        evaluation_seconds: int = 600,
    ):
        rows = {r["instance_id"]: r for r in json.loads(dataset.read_text())}
        self.rows = {i: rows[i] for i in instances}
        self.dataset, self.root = dataset.resolve(), root.resolve()
        self.command_seconds, self.evaluation_seconds = command_seconds, evaluation_seconds
        self.client = None
        self.containers = {}

    def part(self, instance: str) -> Part:
        row = self.rows[instance]
        return Part(
            title=f"Repair {row['repo']}: {row['problem_statement'].splitlines()[0][:100]}",
            specification=public_issue(row) + "\n\n"
            "Your desk has an isolated checkout at /testbed and its installed Python "
            "dependencies. Choose 'use the terminal' to inspect files, edit them, and run "
            "tests with a shell command. Each command starts in /testbed with the testbed "
            "Python environment; only files persist between commands. No network is "
            "available. Do not rewrite git history or weaken tests. To try your repair "
            "with the client or hand it in, put exactly WORKTREE in the code field: the "
            "clerk collects your current diff. You may instead supply a complete unified "
            "diff. The client checks the repair and regressions in a separate checkout. "
            "Passing local tests alone does not guarantee acceptance. Keep terminal "
            "output short. You can discuss your diagnosis with neighbours.",
            reward=60,
            deadline_days=2,
            reference=instance,
        )

    def sample(self, rng: random.Random, count: int) -> tuple[Part, ...]:
        return tuple(self.part(i) for i in rng.sample(list(self.rows), count))

    def sample_posting(self, rng: random.Random, count: int, index: int) -> tuple[Part, ...]:
        # Fixed distinct issues on the pilot's single posting, not repeat random draws.
        if count != 1 or index >= len(self.rows):
            raise ValueError("SWE-bench posting exceeds the fixed single-part task pool")
        return (self.part(list(self.rows)[index]),)

    def _workspace(self, part: Part, worker: str, task_id: str):
        import docker

        if self.client is None:
            self.client = docker.from_env()
        key = hashlib.sha256(f"{worker}:{task_id}:{part.reference}".encode()).hexdigest()[:20]
        folder = self.root / "workspaces" / key
        folder.mkdir(parents=True, exist_ok=True)
        if key in self.containers:
            return self.containers[key], folder
        name = "socio-town-" + uuid.uuid4().hex[:16]
        command(container_args(name, image_for(part.reference)))
        container = self.client.containers.get(name)
        self.containers[key] = container
        base = captured_exec(container, ["git", "-C", "/testbed", "rev-parse", "HEAD"])
        ancestor = captured_exec(
            container,
            [
                "git",
                "-C",
                "/testbed",
                "merge-base",
                "--is-ancestor",
                self.rows[part.reference]["base_commit"],
                "HEAD",
            ],
        )
        if base.exit_code or ancestor.exit_code:
            raise RuntimeError("official image does not contain the expected base commit")
        baseline = base.output.decode().strip()
        metadata = folder / "workspace.json"
        if metadata.exists() and json.loads(metadata.read_text())["baseline"] != baseline:
            raise RuntimeError("workspace image changed; refusing to restore onto another baseline")
        metadata.write_text(
            json.dumps(
                {
                    "worker": worker,
                    "task_id": task_id,
                    "instance_id": part.reference,
                    "container": name,
                    "baseline": baseline,
                    "image_id": container.image.id,
                },
                indent=2,
            )
        )
        snapshot = folder / "working.patch"
        if snapshot.exists() and snapshot.read_bytes():
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as archive:
                data = snapshot.read_bytes()
                entry = tarfile.TarInfo("town-restore.patch")
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
            container.put_archive("/tmp", buf.getvalue())
            result = captured_exec(
                container, ["git", "-C", "/testbed", "apply", "/tmp/town-restore.patch"]
            )
            if result.exit_code:
                raise RuntimeError("could not restore resident worktree snapshot")
        return container, folder

    def _snapshot(self, container, folder: Path) -> str:
        base = json.loads((folder / "workspace.json").read_text())["baseline"]
        added = captured_exec(container, ["git", "-C", "/testbed", "add", "-N", "."])
        diff = captured_exec(container, ["git", "-C", "/testbed", "diff", "--binary", base])
        if added.exit_code or diff.exit_code:
            raise RuntimeError("cannot save resident repository changes")
        patch = diff.output.decode()
        (folder / "working.patch").write_text(patch)
        return patch

    async def run_command(self, part: Part, worker: str, task_id: str, script: str) -> dict:
        return await asyncio.to_thread(self._command, part, worker, task_id, script)

    def _command(self, part, worker, task_id, script):
        container, folder = self._workspace(part, worker, task_id)
        result = execute(container.name, script, self.command_seconds)
        self._snapshot(container, folder)
        with (folder / "commands.jsonl").open("a") as f:
            f.write(json.dumps({"worker": worker, "command": script, **result}) + "\n")
        (folder / "last_command.json").write_text(json.dumps({"command": script, **result}))
        return result

    def desk_view(self, part: Part, worker: str, task_id: str) -> str:
        key = hashlib.sha256(f"{worker}:{task_id}:{part.reference}".encode()).hexdigest()[:20]
        path = self.root / "workspaces" / key / "last_command.json"
        if not path.exists():
            return ""
        latest = json.loads(path.read_text())
        return (
            f"Your terminal screen, from your most recent command:\n{latest['command']}\n"
            f"Exit code: {latest['exit_code']}\n{latest['output']}"
        )

    async def prepare_submission(self, part: Part, worker: str, task_id: str, solution: str):
        if solution.strip() != "WORKTREE":
            return solution

        def collect():
            container, folder = self._workspace(part, worker, task_id)
            return self._snapshot(container, folder)

        return await asyncio.to_thread(collect)

    async def assess(self, part: Part, solution: str) -> Assessment:
        return await asyncio.to_thread(self._assess, part, solution)

    def _assess(self, part: Part, solution: str) -> Assessment:
        if not solution.strip():
            return Assessment(
                passed=False, quality=0, feedback="No repository changes were submitted."
            )
        if not solution.lstrip().startswith("diff --git "):
            return Assessment(
                passed=False,
                quality=0,
                feedback="Submit a unified git diff, or WORKTREE to collect your edits.",
            )
        digest = hashlib.sha256((part.reference + "\n" + solution).encode()).hexdigest()[:24]
        folder = self.root / "evaluations" / digest
        folder.mkdir(parents=True, exist_ok=True)
        cached = folder / "assessment.json"
        if cached.exists():
            return Assessment.model_validate_json(cached.read_text())
        predictions = folder / "predictions.jsonl"
        predictions.write_text(
            json.dumps(
                {
                    "instance_id": part.reference,
                    "model_name_or_path": "town-resident",
                    "model_patch": solution,
                }
            )
            + "\n"
        )
        run_id = "town-" + digest
        args = [
            sys.executable,
            "-m",
            "tasks.swebench.evaluate",
            "--dataset_name",
            str(self.dataset),
            "--predictions_path",
            str(predictions),
            "--instance_ids",
            part.reference,
            "--max_workers",
            "1",
            "--timeout",
            str(self.evaluation_seconds),
            "--cache_level",
            "instance",
            "--run_id",
            run_id,
        ]
        env = dict(os.environ)
        http_cache = self.dataset.parent / "http-cache.json"
        if http_cache.exists():
            env["SWE_BENCH_HTTP_CACHE"] = str(http_cache)
            (folder / "http-cache.sha256").write_text(
                hashlib.sha256(http_cache.read_bytes()).hexdigest()
            )
        project = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = project + os.pathsep + env.get("PYTHONPATH", "")
        with (folder / "evaluator.log").open("w") as log:
            subprocess.run(
                args,
                cwd=folder,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=self.evaluation_seconds + 240,
                check=True,
            )
        report = (
            folder
            / "logs/run_evaluation"
            / run_id
            / "town-resident"
            / part.reference
            / "report.json"
        )
        if not report.exists():
            # Do not assign zero skill for an environment/harness failure.
            raise RuntimeError(f"Official grading did not produce a verdict; inspect {folder}")
        row = json.loads(report.read_text())[part.reference]
        resolved = row["resolved"]
        assessment = Assessment(
            passed=resolved,
            quality=float(resolved),
            feedback=(
                "The client accepted the repair; its defect and regression checks passed."
                if resolved
                else "The client rejected the repair: defect or regression checks still fail. "
                "Inspect the issue and use local tests to investigate."
            ),
        )
        cached.write_text(assessment.model_dump_json(indent=2))
        return assessment

    async def close(self):
        def cleanup():
            errors = []
            for container in self.containers.values():
                try:
                    container.remove(force=True)
                except Exception as exc:
                    errors.append(str(exc))
            if self.client is not None:
                self.client.close()
            self.containers.clear()
            if errors:
                raise RuntimeError("workspace cleanup failed: " + "; ".join(errors))

        await asyncio.to_thread(cleanup)
