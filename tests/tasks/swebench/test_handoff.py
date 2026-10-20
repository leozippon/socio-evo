"""Real Git merge behavior behind a local adapter; no Docker daemon is required."""

import io
import json
import subprocess
import tarfile
from types import SimpleNamespace

import pytest

import tasks.swebench.provider as provider_module
from tasks.swebench.provider import SWEbenchTaskProvider


@pytest.fixture
def repository(tmp_path, monkeypatch):
    bank = tmp_path / "bank.json"
    bank.write_text(
        json.dumps(
            [{"instance_id": "org__repo-1", "repo": "org/repo", "problem_statement": "Fix it"}]
        )
    )
    provider = SWEbenchTaskProvider(
        bank, (), tmp_path / "state", community=True, independent_workspaces=True
    )
    repo = tmp_path / "checkout"
    repo.mkdir()

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args])

    git("init", "-q")
    git("config", "user.email", "tests@example.invalid")
    git("config", "user.name", "Test")
    (repo / "a.py").write_text("first = 1\n")
    (repo / "b.py").write_text("second = 1\n")
    git("add", ".")
    git("commit", "-qm", "baseline")
    baseline = git("rev-parse", "HEAD").decode().strip()
    part = provider.part("org__repo-1")
    folder = provider.root / "workspaces" / provider._key(part, "Tomas", "task-1")
    folder.mkdir(parents=True)
    (folder / "workspace.json").write_text(json.dumps({"baseline": baseline}))
    removed = []
    uploaded = tmp_path / "incoming.patch"

    def put_archive(path, data):
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            uploaded.write_bytes(archive.extractfile("resident-handoff.patch").read())

    container = SimpleNamespace(
        put_archive=put_archive, remove=lambda **kwargs: removed.append(kwargs)
    )
    monkeypatch.setattr(provider, "_workspace", lambda *args: (container, folder))

    def execute(container, args):
        args = [
            str(repo)
            if a == "/testbed"
            else str(uploaded)
            if a == "/tmp/resident-handoff.patch"
            else a
            for a in args
        ]
        result = subprocess.run(args, capture_output=True)
        return SimpleNamespace(exit_code=result.returncode, output=result.stdout + result.stderr)

    monkeypatch.setattr("tasks.swebench.provider.captured_exec", execute)
    return provider, part, repo, folder, git, removed


@pytest.mark.parametrize("conflict", [False, True])
async def test_private_handoff_merges_or_keeps_previous_snapshot(repository, conflict):
    provider, part, repo, folder, git, removed = repository
    (repo / "a.py").write_text("first = 2\n")
    incoming = git("diff", "--binary", "HEAD").decode()
    git("reset", "--hard", "-q", "HEAD")
    (repo / ("a.py" if conflict else "b.py")).write_text("local = 3\n")
    previous = git("diff", "--binary", "HEAD").decode()
    (folder / "working.patch").write_text(previous)
    result = await provider.apply_handoff(part, "Tomas", "task-1", incoming)
    saved = (folder / "working.patch").read_text()
    assert removed == [{"force": True}]
    if conflict:
        assert result["exit_code"] != 0
        assert saved == previous
    else:
        assert result["exit_code"] == 0
        assert "first = 2" in saved and "local = 3" in saved


def test_private_workspace_keys_and_checkpoint(repository):
    provider, part, repo, folder, git, removed = repository
    assert provider._key(part, "Mei", "task-1") != provider._key(part, "Tomas", "task-1")
    (folder / "working.patch").write_text("saved private progress")
    provider.checkpoint(1)
    (folder / "working.patch").write_text("partial next day")
    provider.restore_checkpoint(1)
    assert (folder / "working.patch").read_text() == "saved private progress"


@pytest.mark.parametrize("stage", ["add", "diff"])
async def test_snapshot_failure_records_action_before_cleanup(repository, monkeypatch, stage):
    provider, part, repo, folder, git, removed = repository
    (folder / "working.patch").write_text("previous saved edits")
    capture = provider_module.captured_exec
    stages = []

    def fail_snapshot(container, args):
        stages.append(args[3])
        if args[3] == stage:
            return SimpleNamespace(exit_code=128, output=b"fatal: snapshot failed\xff\n")
        return capture(container, args)

    def execute(*args):
        (repo / "a.py").write_text("unsaved action edits\n")
        return {"exit_code": 0, "output": "terminal finished"}

    def remove(**kwargs):
        # This evidence must survive even though the failed checkout is destroyed.
        records = (folder / "snapshot_errors.jsonl").read_text().splitlines()
        record = json.loads(records[0])
        assert record["worker"] == "Tomas"
        assert record["command"] == "perform edit"
        assert record["result"] == {"exit_code": 0, "output": "terminal finished"}
        assert f"git {stage} exited with code 128" in record["error"]
        assert "fatal: snapshot failed" in record["error"]
        assert (folder / "working.patch").read_text() == "previous saved edits"
        removed.append(kwargs)

    monkeypatch.setattr("tasks.swebench.provider.captured_exec", fail_snapshot)
    monkeypatch.setattr("tasks.swebench.provider.execute", execute)
    container, _ = provider._workspace(part, "Tomas", "task-1")
    container.name = "fake"
    container.remove = remove
    with pytest.raises(RuntimeError, match=f"git {stage} exited with code 128"):
        await provider.run_command(part, "Tomas", "task-1", "perform edit")
    assert stages == (["add"] if stage == "add" else ["add", "diff"])
    assert removed == [{"force": True}]
    assert not (folder / "working.patch.tmp").exists()


async def test_diagnostic_write_failure_preserves_snapshot_error(repository, monkeypatch):
    provider, part, repo, folder, git, removed = repository
    (folder / "working.patch").write_text("previous saved edits")
    (folder / "snapshot_errors.jsonl").mkdir()
    original = RuntimeError("git add exited with code 128: original Git error")

    def snapshot(*args):
        raise original

    monkeypatch.setattr(provider, "_snapshot", snapshot)
    monkeypatch.setattr(
        "tasks.swebench.provider.execute",
        lambda *args: {"exit_code": 0, "output": "terminal finished"},
    )
    container, _ = provider._workspace(part, "Tomas", "task-1")
    container.name = "fake"
    with pytest.raises(RuntimeError) as caught:
        await provider.run_command(part, "Tomas", "task-1", "perform edit")
    assert caught.value is original
    assert "Could not persist snapshot diagnostics" in original.__notes__[0]
    assert (folder / "working.patch").read_text() == "previous saved edits"
    assert removed == [{"force": True}]
