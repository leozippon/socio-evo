"""Persistent dependencies remain separate from research evidence and survive commands."""


import pytest

from world import research_workspace


@pytest.mark.asyncio
async def test_runtime_mount_is_optional_persistent_and_separate(tmp_path, monkeypatch):
    files, records = tmp_path / "research/files", tmp_path / "research/records"
    files.mkdir(parents=True)
    records.mkdir()
    runtime = tmp_path / "research_runtime"
    commands = []

    class Process:
        returncode = 0

        async def communicate(self):
            return b"ok", b""

        async def wait(self):
            return 0

    async def spawn(*args, **kwargs):
        if args[1] == "run":
            commands.append(args)
        return Process()

    monkeypatch.setattr(research_workspace.asyncio, "create_subprocess_exec", spawn)
    await research_workspace.execute("image", files, records, "true", 10)
    assert not runtime.exists()
    await research_workspace.execute("image", files, records, "true", 10, runtime_dir=runtime)
    dependency = runtime / "python/installed.py"
    dependency.write_text("VALUE = 42")
    await research_workspace.execute("image", files, records, "true", 10, runtime_dir=runtime)
    assert dependency.read_text() == "VALUE = 42"
    assert not runtime.is_relative_to(files.parent)
    for command in commands:
        mounts = [command[i + 1] for i, arg in enumerate(command) if arg == "--mount"]
        assert any(m.endswith("dst=/records,readonly") for m in mounts)
        assert not any("docker.sock" in m for m in mounts)
    assert len([a for a in commands[0] if a == "--mount"]) == 2
    assert f"type=bind,src={runtime.resolve()},dst=/runtime" in commands[-1]
    assert all((runtime / p).is_dir() for p in ("tmp", "home", "huggingface", "torch", "python"))
