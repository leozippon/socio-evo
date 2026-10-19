"""Town residents repair isolated repositories; official tests grade their submitted diffs."""

import asyncio
import hashlib
import io
import json
import os
import random
import shutil
import subprocess
import sys
import tarfile
import threading
import uuid
from pathlib import Path

from core.environment import Assessment, Part
from core.environment.rejection import AssessmentUnavailable
from tasks.swebench.docker_exec import captured_exec
from tasks.swebench.pilot import command, container_args, execute, image_for, public_issue


class WorkBudgetExceeded(RuntimeError):
    """Discard edits that exceed the per-action persistence budget."""


class SWEbenchTaskProvider:
    def __init__(
        self,
        dataset: Path,
        instances: tuple[str, ...],
        root: Path,
        *,
        command_seconds: int = 60,
        evaluation_seconds: int = 600,
        community: bool = False,
        repository_guidance: bool = False,
        independent_workspaces: bool = False,
        solo_deadline_days: int = 2,
        joint_deadline_days: int = 2,
    ):
        rows = {r["instance_id"]: r for r in json.loads(dataset.read_text())}
        self.rows = {i: rows[i] for i in (instances or tuple(sorted(rows)))}
        self.bank_identity = {
            "sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
            "instances": sorted(self.rows),
        }
        self.community = community
        self.independent_workspaces = independent_workspaces
        self.repository_guidance = repository_guidance
        self.preflights: dict[str, dict] = {}
        self.solo_deadline_days = solo_deadline_days
        self.joint_deadline_days = joint_deadline_days
        self._lock = threading.RLock()
        self.dataset, self.root = dataset.resolve(), root.resolve()
        self.command_seconds, self.evaluation_seconds = command_seconds, evaluation_seconds
        self.client = None
        self.containers = {}

    def part(self, instance: str) -> Part:
        row = self.rows[instance]
        notes = ""
        if self.repository_guidance:
            from tasks.swebench.preflight import operating_notes

            notes = operating_notes(self._preflight(instance), self.command_seconds, self.community)
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
            "output short. You can discuss your diagnosis with neighbours." + notes,
            reward=60,
            deadline_days=self.solo_deadline_days,
            reference=instance,
        )

    def work_guide(self, part: Part) -> str:
        """Public operating instructions only; never grading fields or reference patches."""
        from tasks.swebench.preflight import operating_notes, recipe

        row = self.rows[part.reference]
        report = (
            self._preflight(part.reference)
            if self.repository_guidance
            else {"guide": recipe(row["repo"])[1]}
        )
        return (
            "SWE-bench work guide for " + row["repo"] + ":\n"
            "1. Inspect the public issue and existing repository files before editing.\n"
            "2. Discover existing tests and select a focused test entry point; "
            "do not guess paths.\n"
            "3. Edit source, inspect your diff, and run relevant tests. A failed launcher or zero "
            "collected tests is not a passed test. Read failures before retrying.\n"
            "4. Partners keep private workspaces; exchange and apply explicit code handoffs.\n"
            "5. Submit WORKTREE from a work activity. In a conversation, first leave and "
            "resume work; saying 'submitted' does not execute a submission. Wait for the "
            "actual background assessment receipt/result.\n"
            + operating_notes(report, self.command_seconds, self.community)
        )

    def _preflight(self, instance: str) -> dict:
        from tasks.swebench.preflight import inspect_environment

        if instance not in self.preflights:
            row = self.rows[instance]
            self.preflights[instance] = inspect_environment(
                instance, row["repo"], row["base_commit"], self.root / "preflight"
            )
        return self.preflights[instance]

    def sample_available(self, rng, workers: int, issued: list[str]) -> tuple[Part, ...]:
        available = sorted(set(self.rows) - set(issued))
        if not available:
            return ()
        part = self.part(rng.choice(available))
        days = self.joint_deadline_days if workers == 2 else self.solo_deadline_days
        text = part.specification
        if workers == 2 and self.independent_workspaces:
            text += (
                "\nThis is one repair for two partners, each with a private checkout. "
                "Choose parallel subtasks or a serial relay. Export an immutable code handoff "
                "and explicitly apply a partner's version; resolve conflicts before submitting. "
                "Either partner may submit their integrated WORKTREE; unshared changes in "
                "another checkout are never automatically included."
            )
        elif workers == 2:
            text += (
                "\nThis is one shared repair for two partners. Both use the same checkout; "
                "changes made by either are visible to the other. Coordinate file edits, "
                "review diffs and run local tests. Terminal commands execute in order. "
                "Either partner may submit the final integrated WORKTREE and report."
            )
        return (part.model_copy(update={"deadline_days": days, "specification": text}),)

    def _key(self, part, worker: str, task_id: str) -> str:
        owner = "shared" if self.community and not self.independent_workspaces else worker
        return hashlib.sha256(f"{owner}:{task_id}:{part.reference}".encode()).hexdigest()[:20]

    def checkpoint(self, day: int) -> None:
        if not self.community:
            return
        destination = self.root / "checkpoints" / f"day-{day:04d}"
        temporary = destination.with_suffix(".tmp")
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir(parents=True)
        (temporary / "bank.json").write_text(json.dumps(self.bank_identity, sort_keys=True))
        workspaces = self.root / "workspaces"
        if workspaces.exists():
            shutil.copytree(workspaces, temporary / "workspaces")
        if destination.exists():
            shutil.rmtree(destination)
        temporary.rename(destination)

    def restore_checkpoint(self, day: int) -> None:
        if not self.community:
            return
        source = self.root / "checkpoints" / f"day-{day:04d}"
        if not source.is_dir():
            raise FileNotFoundError(f"Missing repository checkpoint: {source}")
        if json.loads((source / "bank.json").read_text()) != self.bank_identity:
            raise ValueError(
                "repository checkpoint belongs to a different dataset or instance pool"
            )
        if self.containers:
            raise RuntimeError("restore requires an unopened workspace provider")
        target = self.root / "workspaces"
        if target.exists():
            shutil.rmtree(target)
        if (source / "workspaces").exists():
            shutil.copytree(source / "workspaces", target)

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
        key = self._key(part, worker, task_id)
        folder = self.root / "workspaces" / key
        folder.mkdir(parents=True, exist_ok=True)
        if key in self.containers:
            return self.containers[key], folder
        checked = self._preflight(part.reference) if self.repository_guidance else None
        name = "socio-town-" + uuid.uuid4().hex[:16]
        command(container_args(name, image_for(part.reference)))
        container = self.client.containers.get(name)
        self.containers[key] = container
        if self.repository_guidance:
            from tasks.swebench.preflight import EnvironmentPreflightError

            if checked["image_id"] != container.image.id:
                container.remove(force=True)
                self.containers.pop(key, None)
                raise EnvironmentPreflightError("Workspace image differs from its preflight image")
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
        if self.community and len(diff.output) > 2_000_000:
            raise WorkBudgetExceeded("Edits exceed the 2 MB limit; this action was rolled back.")
        patch = diff.output.decode()
        (folder / "working.patch").write_text(patch)
        return patch

    async def run_command(self, part: Part, worker: str, task_id: str, script: str) -> dict:
        return await asyncio.to_thread(self._command, part, worker, task_id, script)

    def _command(self, part, worker, task_id, script):
        with self._lock:
            return self._locked_command(part, worker, task_id, script)

    def _locked_command(self, part, worker, task_id, script):
        container, folder = self._workspace(part, worker, task_id)
        try:
            result = execute(container.name, script, self.command_seconds)
            if self.community:
                result["output"] = result["output"][:16000]
            try:
                self._snapshot(container, folder)
            except WorkBudgetExceeded as exc:
                result = {"exit_code": 1, "output": str(exc)}
        finally:
            if self.community:
                # Persist only the worktree patch; kill all processes, including detached children.
                container.remove(force=True)
                self.containers.pop(self._key(part, worker, task_id), None)
        with (folder / "commands.jsonl").open("a") as f:
            f.write(json.dumps({"worker": worker, "command": script, **result}) + "\n")
        (folder / "last_command.json").write_text(
            json.dumps({"worker": worker, "command": script, **result})
        )
        return result

    async def export_handoff(self, part: Part, worker: str, task_id: str) -> str:
        if not self.independent_workspaces:
            raise ValueError("Code handoffs require independent workspaces")
        return await self.prepare_submission(part, worker, task_id, "WORKTREE")

    async def apply_handoff(self, part: Part, worker: str, task_id: str, patch: str) -> dict:
        """Three-way merge into a private disposable checkout; conflict keeps its old snapshot."""
        if not self.independent_workspaces:
            raise ValueError("Code handoffs require independent workspaces")
        return await asyncio.to_thread(self._apply_handoff, part, worker, task_id, patch)

    def _apply_handoff(self, part, worker, task_id, patch):
        with self._lock:
            container, folder = self._workspace(part, worker, task_id)
            try:
                if len(patch.encode()) > 2_000_000:
                    return {"exit_code": 1, "output": "Handoff exceeds the patch size limit."}
                if not patch.strip():
                    return {"exit_code": 0, "output": "No changes in this handoff."}
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w") as archive:
                    data = patch.encode()
                    item = tarfile.TarInfo("resident-handoff.patch")
                    item.size = len(data)
                    archive.addfile(item, io.BytesIO(data))
                container.put_archive("/tmp", buf.getvalue())
                staged = captured_exec(container, ["git", "-C", "/testbed", "add", "-A"])
                if staged.exit_code:
                    return {"exit_code": 1, "output": staged.output.decode()}
                result = captured_exec(
                    container,
                    ["git", "-C", "/testbed", "apply", "--3way", "/tmp/resident-handoff.patch"],
                )
                if result.exit_code:
                    return {"exit_code": result.exit_code, "output": result.output.decode()}
                try:
                    self._snapshot(container, folder)
                except WorkBudgetExceeded as exc:
                    return {"exit_code": 1, "output": str(exc)}
                return {"exit_code": 0, "output": result.output.decode() or "Code handoff applied."}
            finally:
                # A conflict never gets snapshotted, so all partially applied files disappear.
                container.remove(force=True)
                self.containers.pop(self._key(part, worker, task_id), None)

    def desk_view(self, part: Part, worker: str, task_id: str) -> str:
        key = self._key(part, worker, task_id)
        path = self.root / "workspaces" / key / "last_command.json"
        if not path.exists():
            return ""
        latest = json.loads(path.read_text())
        return (
            f"Terminal screen, command by {latest.get('worker', worker)}:\n{latest['command']}\n"
            f"Exit code: {latest['exit_code']}\n{latest['output']}"
        )

    async def prepare_submission(self, part: Part, worker: str, task_id: str, solution: str):
        if solution.strip() != "WORKTREE":
            return solution

        def collect():
            with self._lock:
                if self.community:
                    # Each work action already persisted its patch before killing the container.
                    patch = (
                        self.root
                        / "workspaces"
                        / self._key(part, worker, task_id)
                        / "working.patch"
                    )
                    return patch.read_text() if patch.exists() else ""
                container, folder = self._workspace(part, worker, task_id)
                return self._snapshot(container, folder)

        return await asyncio.to_thread(collect)

    async def assess(self, part: Part, solution: str) -> Assessment:
        try:
            return await asyncio.to_thread(self._assess, part, solution)
        except (subprocess.SubprocessError, OSError, RuntimeError, ValueError, KeyError) as exc:
            if not self.community:
                raise
            self.root.mkdir(parents=True, exist_ok=True)
            with (self.root / "assessment_errors.jsonl").open("a") as log:
                log.write(json.dumps({"instance_id": part.reference, "error": str(exc)}) + "\n")
            raise AssessmentUnavailable("Checking service unavailable") from exc

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
        if row.get("error") or "resolved" not in row:
            raise RuntimeError("Official grading returned no usable verdict")
        resolved = row["resolved"]
        if not isinstance(resolved, bool):
            raise RuntimeError("Official grading returned an invalid verdict")
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
