"""Official acceptance of a patch for a task, by the SWE-bench harness, in a fresh container.

    python -m tasks.swebench.accept <instance_id> <patch_file>

`accept` starts a new container of the task image without network, so nothing a worker did in
its workspace carries over, and goes through the steps of SWE-bench's `run_instance`: it applies
the patch with the harness's commands (`git apply`, then `git apply --reject`, then `patch
--fuzz=5`), runs the task's official eval script, which resets the test files the hidden test
patch touches, applies that patch and runs the tests, and grades the output with the harness's
log parser and resolution rule: resolved when every FAIL_TO_PASS and PASS_TO_PASS test passes.
An empty patch is not applied; the tests then run on the unchanged repository.

The verdict is `patch_apply_failed` when no command applies the patch, `timeout` when the eval
script runs past its time, `error` when the run cannot be graded on its merits (a process in
the container was killed for lack of memory, or the output lacks the harness's markers, as when
the container fails), and otherwise `resolved` or `failed_tests`. Only a graded run counts
tests; the others report none passed. The log tail shows the hidden tests' output, so it is not
for a worker's eyes. A task whose image is not pulled raises `MissingImage`; Docker failing to
start a container or to answer raises as well.

The eval script is the one `swebench.harness.test_spec.make_test_spec` builds, made here by the
same function, `make_eval_script_list`, without the environment-setup script `make_test_spec`
also builds, which fetches requirement files from GitHub and which the prebuilt images need not.
"""

import tempfile
from pathlib import Path
from typing import Literal

from pydantic import computed_field
from swebench.harness.constants import (
    DOCKER_PATCH,
    FAIL_TO_PASS,
    KEY_INSTANCE_ID,
    KEY_MODEL,
    KEY_PREDICTION,
    LATEST,
    MAP_REPO_TO_EXT,
    MAP_REPO_VERSION_TO_SPECS,
    PASS_TO_PASS,
)
from swebench.harness.grading import get_eval_report
from swebench.harness.run_evaluation import GIT_APPLY_CMDS
from swebench.harness.test_spec.create_scripts import make_eval_script_list
from swebench.harness.test_spec.test_spec import TestSpec

from infrastructure.config import StrictModel
from tasks.swebench.dataset import Task
from tasks.swebench.workspace import WORKDIR, Container

Status = Literal["resolved", "failed_tests", "patch_apply_failed", "error", "timeout"]
LOG_TAIL = 8_000
_EVAL_SCRIPT = "/eval.sh"


class Verdict(StrictModel):
    """The outcome of an acceptance, with the hidden tests passed of those run."""

    status: Status
    fail_to_pass: tuple[int, int]  # passed, total
    pass_to_pass: tuple[int, int]
    log_tail: str

    @computed_field
    @property
    def resolved(self) -> bool:
        return self.status == "resolved"


def harness_spec(task: Task) -> TestSpec:
    """The harness's test spec of `task`, without its environment-setup script."""
    specs = MAP_REPO_VERSION_TO_SPECS[task.repo][task.version]
    return TestSpec(
        instance_id=task.instance_id,
        repo=task.repo,
        version=task.version,
        repo_script_list=[],
        eval_script_list=make_eval_script_list(
            task.model_dump(), specs, "testbed", WORKDIR, task.base_commit, task.test_patch
        ),
        env_script_list=[],
        arch="x86_64",
        FAIL_TO_PASS=list(task.FAIL_TO_PASS),
        PASS_TO_PASS=list(task.PASS_TO_PASS),
        language=MAP_REPO_TO_EXT[task.repo],
        docker_specs=specs.get("docker_specs", {}),
        namespace=None,
        base_image_tag=LATEST,
        env_image_tag=LATEST,
        instance_image_tag=LATEST,
    )


async def accept(
    task: Task, patch: str, timeout_s: int = 1800, *, cpus: float = 4, memory: str = "16g"
) -> Verdict:
    """The official verdict on `patch` for `task`; the eval script may run `timeout_s`."""
    spec = harness_spec(task)
    container = await Container.start(
        task.image, f"accept-{task.instance_id}", cpus=cpus, memory=memory
    )
    try:
        return await _run(container, spec, patch, timeout_s)
    finally:
        await container.remove()


async def _run(container: Container, spec: TestSpec, patch: str, timeout_s: int) -> Verdict:
    if patch.strip():
        await container.write(DOCKER_PATCH, patch)
        for command in GIT_APPLY_CMDS:
            applied = await container.exec(["bash", "-c", f"{command} {DOCKER_PATCH}"], 600)
            if applied.exit_code == 0:
                break
        else:
            return _ungraded(spec, "patch_apply_failed", applied.stdout + applied.stderr)
    await container.write(_EVAL_SCRIPT, spec.eval_script)
    run = await container.exec(["bash", "-c", f"/bin/bash {_EVAL_SCRIPT} 2>&1"], timeout_s)
    log = run.stdout + run.stderr
    if run.timed_out:
        return _ungraded(spec, "timeout", f"{log}\n[eval script ran past {timeout_s} s]")
    events = await container.exec(["cat", "/sys/fs/cgroup/memory.events"], 60)
    counts = dict(line.split() for line in events.stdout.splitlines())
    if events.exit_code != 0 or "oom_kill" not in counts:
        return _ungraded(spec, "error", f"{log}\n[cannot read the container's memory events]")
    if int(counts["oom_kill"]):
        killed = f"[{counts['oom_kill']} processes killed for lack of memory]"
        return _ungraded(spec, "error", f"{log}\n{killed}")
    return grade(spec, patch, log)


def grade(spec: TestSpec, patch: str, log: str) -> Verdict:
    """The verdict on the output `log` of the eval script of `spec` run on `patch`."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory, "test_output.txt")
        path.write_text(log)
        prediction = {KEY_INSTANCE_ID: spec.instance_id, KEY_MODEL: "", KEY_PREDICTION: patch}
        report = get_eval_report(spec, prediction, str(path), include_tests_status=True)
    result = report[spec.instance_id]
    if not result["patch_successfully_applied"]:
        return _ungraded(spec, "error", f"{log}\n[the output lacks the harness's test markers]")
    tests = result["tests_status"]
    return Verdict(
        status="resolved" if result["resolved"] else "failed_tests",
        fail_to_pass=_count(tests[FAIL_TO_PASS]),
        pass_to_pass=_count(tests[PASS_TO_PASS]),
        log_tail=log[-LOG_TAIL:],
    )


def _ungraded(spec: TestSpec, status: Status, log: str) -> Verdict:
    return Verdict(
        status=status,
        fail_to_pass=(0, len(spec.FAIL_TO_PASS)),
        pass_to_pass=(0, len(spec.PASS_TO_PASS)),
        log_tail=log[-LOG_TAIL:],
    )


def _count(tests: dict[str, list[str]]) -> tuple[int, int]:
    return len(tests["success"]), len(tests["success"]) + len(tests["failure"])
