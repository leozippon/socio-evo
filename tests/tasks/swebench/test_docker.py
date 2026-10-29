"""Workspaces and acceptance on real task images; skipped unless Docker runs and they are pulled."""

import asyncio
import subprocess

import pytest

from tasks.swebench.acceptance import accept
from tasks.swebench.workspace import Workspace
from tests.support.swebench import pulled

pytestmark = pytest.mark.docker

DJANGO = "django__django-11276"
ASTROPY = "astropy__astropy-14096"  # its image leaves an edited pyproject.toml uncommitted
UNREACHABLE = "python -c \"import socket; socket.create_connection(('1.1.1.1', 443), 5)\""


def containers(name: str) -> str:
    listed = ["docker", "ps", "--all", "--quiet", "--filter", f"name={name}"]
    return subprocess.run(listed, capture_output=True, text=True, check=True).stdout


async def test_a_workspace_runs_commands_offline_and_returns_its_changes():
    task = pulled(DJANGO)
    async with await Workspace.open(task, "tester") as workspace:
        python = await workspace.exec("which python", 60)
        assert python.stdout.strip() == "/opt/miniconda3/envs/testbed/bin/python"
        offline = await workspace.exec(UNREACHABLE, 60)
        assert offline.exit_code != 0 and "unreachable" in offline.stderr
        slow = await workspace.exec("sleep 60", 2)
        assert slow.timed_out
        await workspace.write_file("notes/new.txt", "hello\n")
        assert await workspace.read_file("notes/new.txt") == "hello\n"
        await workspace.exec("echo '# edited' >> django/__init__.py && git commit -qam wip", 60)
        patch = await workspace.diff()
        name = workspace.container.name
    assert "+++ b/notes/new.txt" in patch and "+# edited" in patch
    assert containers(name) == ""


async def test_a_workspace_holds_no_history_newer_than_the_base_commit():
    task = pulled(DJANGO)
    fixed = "django/utils/html.py"  # the file the gold patch changes
    async with await Workspace.open(task, "tester") as workspace:
        await workspace.write_file("/tmp/fix.diff", task.patch)
        blob = await workspace.exec(f"git apply /tmp/fix.diff && git hash-object {fixed}", 60)
        assert blob.exit_code == 0
        assert (await workspace.exec(f"git cat-file -e {blob.stdout.strip()}", 60)).exit_code != 0
        since = "$(( $(git show -s --format=%ct HEAD) + 1 ))"
        newer = await workspace.exec(f"git rev-list --all --since={since} | wc -l", 60)
        assert newer.stdout.strip() == "0"


async def test_acceptance_resolves_the_gold_patch_and_nothing_else():
    task = pulled(DJANGO)
    gold, empty, garbage = await asyncio.gather(
        accept(task, task.patch), accept(task, ""), accept(task, "not a patch\n")
    )
    assert (gold.status, gold.resolved, gold.fail_to_pass) == ("resolved", True, (26, 26))
    assert (empty.status, empty.resolved) == ("failed_tests", False)
    assert (garbage.status, garbage.resolved) == ("patch_apply_failed", False)


async def test_a_workspace_patch_applies_over_the_images_uncommitted_edits():
    task = pulled(ASTROPY)
    async with await Workspace.open(task, "tester") as workspace:
        assert (await workspace.exec("git status --porcelain", 60)).stdout.strip()
        await workspace.write_file("/tmp/fix.diff", task.patch)
        assert (await workspace.exec("git apply /tmp/fix.diff", 60)).exit_code == 0
        patch = await workspace.diff()
    assert "pyproject.toml" not in patch
    assert (await accept(task, patch)).status == "resolved"


async def test_running_out_of_memory_is_an_error_not_a_failure():
    task = pulled(DJANGO)
    async with await Workspace.open(task, "tester") as workspace:
        await workspace.exec("echo '_hog = b\"x\" * (6 << 30)' >> django/utils/html.py", 60)
        patch = await workspace.diff()
    verdict = await accept(task, patch, memory="1g")
    assert (verdict.status, verdict.resolved) == ("error", False)
    assert "lack of memory" in verdict.log_tail
