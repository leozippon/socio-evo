"""Selected Git snapshots isolate commands without exposing unrelated or live files."""

import asyncio
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from world import research_workspace as workspace


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def repository():
    with TemporaryDirectory(prefix="socio-workspace-test-") as temporary:
        root = Path(temporary) / "research"
        files, records = root / "files", root / "records"
        (files / "src").mkdir(parents=True)
        records.mkdir()
        git(root, "init", "-q")
        git(root, "config", "user.name", "Test")
        git(root, "config", "user.email", "test@example.invalid")
        (files / "src/read.py").write_text("print('original')\n")
        (files / "src/read.py").chmod(0o755)
        (files / "other.txt").write_text("unrelated shared work")
        (records / "evidence.json").write_text('{"value": 1}')
        (records / "other.json").write_text('{"value": 2}')
        (root / "private.txt").write_text("outside the admitted workspace")
        git(root, "add", ".")
        git(root, "commit", "-qm", "Original")
        old = git(root, "rev-parse", "HEAD")
        (files / "src/read.py").write_text("print('newer')\n")
        git(root, "commit", "-qam", "Newer shared work")
        (files / "src/untracked.txt").write_text("not committed")
        yield root, files, records, old


def test_snapshot_exports_only_selected_tracked_old_content_and_optional_outputs(repository):
    root, files, records, old = repository
    with workspace.snapshot(
        files, records, old, ["files/src", "records/evidence.json"],
        optional_paths=["files/other.txt", "files/results/new.json"],
    ) as (selected, evidence):
        staging = selected.parent
        assert staging.parent == root.parent
        assert (selected / "src/read.py").read_text() == "print('original')\n"
        assert (selected / "src/read.py").stat().st_mode & 0o111
        assert (evidence / "evidence.json").read_text() == '{"value": 1}'
        assert (selected / "other.txt").read_text() == "unrelated shared work"
        assert (selected / "results").is_dir()
        assert not (selected / "results/new.json").exists()
        assert {p.relative_to(staging).as_posix() for p in staging.rglob("*") if p.is_file()} == {
            "files/src/read.py", "files/other.txt", "records/evidence.json",
        }
        assert not (staging / ".git").exists()
        (selected / "other.txt").write_text("isolated output")
        assert (files / "other.txt").read_text() == "unrelated shared work"
    assert not staging.exists()
    assert (files / "src/read.py").read_text() == "print('newer')\n"


@pytest.mark.parametrize("paths,optional", [
    (["files/../private.txt"], []),
    (["private.txt"], []),
    (["files/.git/config"], []),
    (["files/missing.txt"], []),
    (["files/src/read.py"], ["files/src"]),
])
def test_snapshot_rejects_unscoped_missing_and_directory_output_paths(repository, paths, optional):
    root, files, records, old = repository
    with pytest.raises(ValueError), workspace.snapshot(
        files, records, old, paths, optional_paths=optional,
    ):
        pytest.fail("Invalid selection must not yield a snapshot")
    assert not list(root.parent.glob("research-snapshot-*"))


def test_snapshot_rejects_tracked_symlinks(repository):
    root, files, records, _ = repository
    (files / "link").symlink_to(root / "private.txt")
    git(root, "add", "files/link")
    git(root, "commit", "-qm", "Link")
    with pytest.raises(ValueError, match="regular tracked"), workspace.snapshot(
        files, records, git(root, "rev-parse", "HEAD"), ["files/link"],
    ):
        pytest.fail("A tracked symlink must not be exported")


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("readonly", [False, True])
async def test_scoped_command_mounts_pinned_paths_and_cleans_up(
    repository, monkeypatch, cancel, readonly,
):
    root, files, records, old = repository
    runtime = root.parent / "research_runtime"
    started, finished = asyncio.Event(), asyncio.Event()
    commands, snapshots = [], []

    class Process:
        def __init__(self, running=False):
            self.returncode = None if running else 0

        async def communicate(self):
            if cancel:
                await finished.wait()
            self.returncode = 0
            return b"original", b""

        async def wait(self):
            return self.returncode

        def kill(self):
            self.returncode = -9
            finished.set()

    async def spawn(*args, **kwargs):
        commands.append(args)
        if args[1] == "run":
            mounts = [args[i + 1] for i, arg in enumerate(args) if arg == "--mount"]
            research = next(m for m in mounts if ",dst=/research" in m)
            assert research.endswith(",readonly") is readonly
            assert all(mount.endswith(",readonly") for mount in mounts if mount != research)
            selected = Path(research.split("src=", 1)[1].split(",", 1)[0])
            assert (selected / "src/read.py").read_text() == "print('original')\n"
            assert not (selected / "other.txt").exists()
            assert "TMPDIR=/tmp" in args and "PYTHONDONTWRITEBYTECODE=1" in args
            assert args[args.index("--gpus") + 1] == "device=1"
            assert args[args.index("--network") + 1] == "none"
            snapshots.append(selected.parent)
            started.set()
            return Process(True)
        assert args[1:3] == ("rm", "-f")
        finished.set()
        return Process()

    monkeypatch.setattr(workspace.asyncio, "create_subprocess_exec", spawn)

    async def run():
        with workspace.snapshot(files, records, old, ["files/src/read.py"]) as (selected, evidence):
            return await workspace.execute(
                "test-image", selected, evidence, "cat src/read.py", 10,
                network=False, gpus="device=1", runtime_dir=runtime,
                readonly=readonly, runtime_readonly=not readonly,
            )

    task = asyncio.create_task(run())
    await started.wait()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        assert (await task)["stdout"] == "original"
    assert not snapshots[0].exists()
    assert commands[-1][1:3] == ("rm", "-f")
