import json
import random

import pytest

from core.environment.rejection import AssessmentUnavailable
from tasks.swebench.provider import SWEbenchTaskProvider


@pytest.fixture
def provider(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(
        json.dumps(
            [
                {
                    "instance_id": f"org__repo-{i}",
                    "repo": "org/repo",
                    "problem_statement": "Fix it",
                    "patch": "GOLD_SECRET",
                    "test_patch": "TEST_SECRET",
                }
                for i in range(1, 12)
            ]
        )
    )
    return SWEbenchTaskProvider(path, (), tmp_path / "repositories", community=True)


def test_joint_has_one_issue_unused_pool_and_exhaustion(provider):
    first = provider.sample_available(random.Random(1), 2, [])
    assert len(first) == 1 and "shared" in first[0].specification
    assert "SECRET" not in first[0].specification
    next_job = provider.sample_available(random.Random(1), 1, [first[0].reference])
    assert first[0].reference != next_job[0].reference
    assert provider.sample_available(random.Random(1), 1, list(provider.rows)) == ()


def test_shared_screen_and_checkpoint_roll_back_partial_day(provider):
    part = provider.part("org__repo-1")
    key = provider._key(part, "Mei", "task-1")
    assert key == provider._key(part, "Tomas", "task-1")
    assert key != provider._key(part, "Mei", "task-2")
    provider.checkpoint(0)
    folder = provider.root / "workspaces" / key
    folder.mkdir(parents=True)
    (folder / "working.patch").write_text("DAY1")
    (folder / "last_command.json").write_text(
        json.dumps(
            {
                "worker": "Mei",
                "command": "pytest",
                "exit_code": 1,
                "output": "test failed",
            }
        )
    )
    assert "command by Mei" in provider.desk_view(part, "Tomas", "task-1")
    provider.checkpoint(1)
    (folder / "working.patch").write_text("DAY2")
    provider.restore_checkpoint(1)
    assert (folder / "working.patch").read_text() == "DAY1"
    provider.restore_checkpoint(0)
    assert not folder.exists()


async def test_harness_failure_never_becomes_quality_zero(provider, monkeypatch):
    def broken(*args):
        raise RuntimeError("official harness produced no report")

    monkeypatch.setattr(provider, "_assess", broken)
    with pytest.raises(AssessmentUnavailable):
        await provider.assess(provider.part("org__repo-1"), "diff --git a/x b/x")
    assert (provider.root / "assessment_errors.jsonl").exists()
    assert not list(provider.root.rglob("assessment.json"))


def test_resume_rejects_changed_bank_before_touching_workspace(provider):
    provider.checkpoint(0)
    folder = provider.root / "workspaces"
    folder.mkdir()
    (folder / "keep").write_text("existing data")
    provider.bank_identity["sha256"] = "changed"
    with pytest.raises(ValueError, match="different dataset"):
        provider.restore_checkpoint(0)
    assert (folder / "keep").read_text() == "existing data"


async def test_both_workers_edit_and_submit_the_same_workspace(provider, monkeypatch):
    from types import SimpleNamespace

    part = provider.part("org__repo-1")
    files = []
    container = SimpleNamespace(name="fake-shared-container")

    def workspace(part, worker, task_id):
        folder = provider.root / "workspaces" / provider._key(part, worker, task_id)
        folder.mkdir(parents=True, exist_ok=True)
        return container, folder

    def execute(name, script, timeout):
        assert name == container.name
        files.append(script)
        return {"exit_code": 0, "output": "\n".join(files)}

    monkeypatch.setattr(provider, "_workspace", workspace)
    monkeypatch.setattr("tasks.swebench.provider.execute", execute)
    monkeypatch.setattr(provider, "_snapshot", lambda container, folder: "\n".join(files))
    await provider.run_command(part, "Mei", "task-1", "first edit")
    result = await provider.run_command(part, "Tomas", "task-1", "second edit")
    assert result["output"] == "first edit\nsecond edit"
    assert await provider.prepare_submission(part, "Mei", "task-1", "WORKTREE") == result["output"]
    _, folder = workspace(part, "Tomas", "task-1")
    commands = [json.loads(line) for line in (folder / "commands.jsonl").read_text().splitlines()]
    assert [entry["worker"] for entry in commands] == ["Mei", "Tomas"]
