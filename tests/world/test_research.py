"""Research integration without live models, remote services or experiment processes."""

import asyncio
import json
from pathlib import Path

import pytest

from agent.directory import AgentDirectory
from experiments.config import load_experiment
from world import research_sources, research_workspace
from world.clock import ManualClock
from world.events import Idle, Movement, Sleep, Work
from world.midnight import midnight
from world.research import BRIEF, DISABLED, RESEARCH_NAMES, NoTasks, research_help
from world.world import World

CONFIG = Path(__file__).resolve().parents[2] / "experiments/configs/research.yaml"


@pytest.fixture
def world(tmp_path):
    c = load_experiment(CONFIG)
    for resident in c.residents:
        AgentDirectory.create(
            tmp_path / "agents" / resident.name, background=resident.background_path.read_text()
        )
    w = World(c.town, tmp_path, NoTasks(), clock=ManualClock())
    w.research.initialize(w)
    return w


def office(w, name):
    r = w.residents[name]
    r.base, r.place = Idle(), w.config.workplace("office").id
    return r


@pytest.mark.parametrize(
    "profile", ["research.yaml", "autoresearch-town.yaml", "autoresearch-academy.yaml"]
)
async def test_literature_tool_matches_profile_and_disabled_calls_do_not_reach_provider(
    tmp_path, monkeypatch, profile
):
    config = load_experiment(CONFIG.with_name(profile))
    for resident in config.residents:
        AgentDirectory.create(
            tmp_path / "agents" / resident.name, background=resident.background_path.read_text()
        )
    w = World(config.town, tmp_path, NoTasks(), clock=ManualClock())
    w.research.initialize(w)
    enabled = profile == "research.yaml"
    assert config.town.research.semantic_scholar is enabled
    for name in w.residents:
        r = office(w, name)
        assert w.knows(r, "search_literature") is enabled
        assert ("search_literature" in {s.name for s in w.usable(r)}) is enabled
    assert ("Semantic Scholar" in research_help(config.town.research)) is enabled
    assert "search_web" in w.research.names and "curl" in w.research.names
    if not enabled:
        monkeypatch.setattr(
            research_sources, "search", lambda _: pytest.fail("Disabled provider called")
        )
        before = w.research.snapshot()
        result = await w.call(r, "search_literature", {"query": "research"})
        assert "not enabled" in result.text
        assert w.research.snapshot() == before


def test_original_cast_no_tasks_brief_and_grant_checkpoint(world, tmp_path):
    c = load_experiment(CONFIG)
    assert len(world.residents) == 8
    assert sum(r.occupation == "programmer" for r in c.town.residents) == 3
    assert world.board.tasks == []
    assert all(world.board.draw(day) == [] for day in range(1, 40))
    for r, config in zip(world.residents.values(), c.town.residents, strict=True):
        assert r.inventory.money == config.purse + 420
        assert len(r.port.held) == 1
        assert BRIEF in r.port.held[0].text
        assert r.port.held[0].kind == "research_brief"
    state = world.snapshot()
    restored = World(c.town, tmp_path, NoTasks(), clock=ManualClock())
    restored.restore(state)
    assert restored.snapshot()["research"] == state["research"]
    for name in world.residents:
        assert restored.residents[name].inventory.money == world.residents[name].inventory.money
        assert len(restored.residents[name].port.held) == 1  # not re-granted or re-announced


@pytest.mark.asyncio
async def test_every_profession_can_research_but_only_at_office(world):
    for name in world.residents:
        r = office(world, name)
        names = {s.name for s in world.usable(r)}
        assert set(RESEARCH_NAMES) <= names
        assert not DISABLED & names
        assert not any(world.knows(r, tool) for tool in DISABLED)
        start = await world.call(r, "start_work", {})
        assert "work" in start.text
        assert isinstance(r.base, Work)
        result = await world.call(r, "list_research_files", {})
        assert "README.md" in result.text
        r.place = r.home
        assert not set(RESEARCH_NAMES) & {s.name for s in world.usable(r)}
        assert "available" in (await world.call(r, "shell", {})).text
        r.place = world.config.workplace("office").id
        r.base = Sleep(0, True)
        assert not set(RESEARCH_NAMES) & {s.name for s in world.usable(r)}
        assert "available" in (await world.call(r, "list_research_files", {})).text
    r = office(world, "Tomas")
    await world.call(r, "start_work", {})
    await world.call(r, "go", {"place": r.home})
    assert isinstance(r.base, Movement) and not r.base.working


@pytest.mark.asyncio
async def test_shared_edits_conflicts_evidence_and_restore(world):
    a, b = office(world, "Aisha"), office(world, "Jonas")
    research = world.research
    start = research.snapshot()
    result = await world.call(
        a,
        "write_repo_file",
        {"path": "paper.md", "content": "Question still open.", "revision": start},
    )
    assert "Wrote paper.md" in result.text
    saved = research.snapshot()
    read = await world.call(b, "read_repo_file", {"path": "paper.md"})
    assert "Question still open." in read.text
    conflict = await world.call(
        b, "write_repo_file", {"path": "paper.md", "content": "Overwrite", "revision": start}
    )
    assert "changed" in conflict.text
    assert (research.files / "paper.md").read_text() == "Question still open."
    await world.call(
        b,
        "edit_repo_file",
        {"path": "paper.md", "old_text": "still open", "new_text": "chosen", "revision": saved},
    )
    records = [json.loads(p.read_text()) for p in research.records.glob("*.json")]
    assert {r["actor"] for r in records} == {"Aisha", "Jonas"}
    assert records[0]["revision_before"] in {saved, start}
    research.restore(saved)
    assert (research.files / "paper.md").read_text() == "Question still open."
    assert len(list(research.records.glob("*.json"))) == 1
    research.restore(start)
    assert not (research.files / "paper.md").exists()


@pytest.mark.asyncio
async def test_path_boundaries_exhaustion_and_argument_validation(world, tmp_path):
    r = office(world, "Lucia")
    for path in ("../background.md", "/etc/passwd", "records/README.txt", ".git/config"):
        result = await world.call(
            r,
            "write_repo_file",
            {"path": path, "content": "overwrite", "revision": world.research.snapshot()},
        )
        assert '"error"' in result.text
    (world.research.files / "escape").symlink_to(tmp_path)
    result = await world.call(r, "read_repo_file", {"path": "escape/anything"})
    assert "Symbolic links" in result.text
    missing = await world.call(r, "shell", {"command": "true"})
    assert "needs revision" in missing.text
    r.living.energy = 0
    assert "exhausted" in (await world.call(r, "list_research_files", {})).text.lower()


@pytest.mark.asyncio
async def test_commands_are_serialized_and_record_real_result(world, monkeypatch):
    a, b = office(world, "Aisha"), office(world, "Kofi")
    started, finish = asyncio.Event(), asyncio.Event()

    async def command(image, files, records, cmd, timeout, **kwargs):
        started.set()
        await finish.wait()
        (files / "result.csv").write_text("n,mean\n5,2.1\n")
        return {"exit_code": 0, "stdout": "mean=2.1", "stderr": "", "timed_out": False}

    monkeypatch.setattr(research_workspace, "execute", command)
    rev = world.research.snapshot()
    first = asyncio.create_task(
        world.call(a, "shell", {"command": "python experiment.py", "revision": rev})
    )
    await started.wait()
    second = asyncio.create_task(
        world.call(
            b, "write_repo_file", {"path": "result.csv", "content": "stale", "revision": rev}
        )
    )
    await asyncio.sleep(0)
    assert not second.done()
    finish.set()
    assert "mean=2.1" in (await first).text
    assert "changed" in (await second).text
    record = json.loads(next(world.research.records.glob("*.json")).read_text())
    assert record["result"]["stdout"] == "mean=2.1"
    assert record["arguments"]["command"] == "python experiment.py"
    assert (world.research.files / "result.csv").exists()


@pytest.mark.asyncio
async def test_independent_writes_and_edits_accept_old_revision(world, monkeypatch):
    a, b = office(world, "Aisha"), office(world, "Ravi")
    rev = world.research.snapshot()
    await world.call(a, "write_repo_file", {"path": "ode.py", "content": "ODE", "revision": rev})
    answer = await world.call(
        b, "write_repo_file", {"path": "abm_sir.py", "content": "ABM", "revision": rev}
    )
    assert "Wrote abm_sir.py" in answer.text
    rev = world.research.snapshot()
    await world.call(a, "write_repo_file", {"path": "ode.py", "content": "ODE 2", "revision": rev})
    monkeypatch.setattr(research_sources, "search", lambda q: {"results": []})
    await world.call(a, "search_literature", {"query": "SIR"})
    answer = await world.call(
        b,
        "edit_repo_file",
        {"path": "abm_sir.py", "old_text": "ABM", "new_text": "ABM 2", "revision": rev},
    )
    assert "Wrote abm_sir.py" in answer.text
    conflict = await world.call(
        a, "write_repo_file", {"path": "abm_sir.py", "content": "overwrite", "revision": rev}
    )
    assert "abm_sir.py changed" in conflict.text
    assert (world.research.files / "abm_sir.py").read_text() == "ABM 2"


@pytest.mark.asyncio
async def test_shell_ignores_records_but_protects_shared_files(world, monkeypatch):
    r = office(world, "Ravi")
    monkeypatch.setattr(research_sources, "search", lambda q: {"results": []})
    executions = []

    async def command(*args, **kwargs):
        executions.append(args)
        return {"exit_code": 0, "stdout": "checked", "stderr": "", "timed_out": False}

    monkeypatch.setattr(research_workspace, "execute", command)
    rev = world.research.snapshot()
    await world.call(r, "search_literature", {"query": "SIR"})
    for _ in range(2):
        result = await world.call(r, "shell", {"command": "true", "revision": rev})
        assert "checked" in result.text  # even a previous command's record is unrelated
    await world.call(r, "write_repo_file", {"path": "data.txt", "content": "new", "revision": rev})
    result = await world.call(r, "shell", {"command": "true", "revision": rev})
    assert "Shared files changed" in result.text
    assert len(executions) == 2
    for invalid in ("HEAD", "f" * 40):
        result = await world.call(
            r, "write_repo_file", {"path": "unsafe", "content": "x", "revision": invalid}
        )
        assert '"error"' in result.text
    assert not (world.research.files / "unsafe").exists()


@pytest.mark.asyncio
async def test_sources_recorded_readable_and_failure_is_not_evidence(world, monkeypatch):
    r = office(world, "Olga")
    monkeypatch.setattr(research_sources, "read", lambda url: {"url": url, "text": "A result."})
    answer = await world.call(r, "read_source", {"url": "https://example.org/paper"})
    assert "A result." in answer.text
    path = next(world.research.records.glob("*.json"))
    assert (
        "A result."
        in (await world.call(r, "read_repo_file", {"path": "records/" + path.name})).text
    )

    def fail(url):
        raise ValueError("Source returned HTTP 403.")

    monkeypatch.setattr(research_sources, "read", fail)
    result = await world.call(r, "read_source", {"url": "https://example.org/closed"})
    assert '"error": "Source returned HTTP 403."' in result.text


@pytest.mark.asyncio
async def test_daily_life_and_midnight_with_allowance(world):
    for name in world.residents:
        r = world.residents[name]
        r.base, r.place = Idle(), r.occupation.workplace
        await world.call(r, "start_work", {})
    # Original merchant, kitchen, hospital and mayor tools remain available at their workplaces.
    for name, tool in (
        ("Jonas", "cook"),
        ("Olga", "order"),
        ("Lucia", "examine"),
        ("Tomas", "announce"),
    ):
        assert tool in {s.name for s in world.usable(world.residents[name])}
    world.clock.set(86400)
    midnight(world, 1)
    assert world.board.schedule == []
    assert any(
        "external research living grant" in p.text
        for r in world.residents.values()
        for p in r.port.pending()
    )


def test_prompt_has_no_client_task_instructions(world):
    for name in world.residents:
        text = world.ports[name].rules()
        assert "Research. Client work is paused." in text
        assert "one-off research living allowance of $420" in text
        assert all(t not in text for t in ("claim_task", "assign,", "submit", "cognitive_core"))
        topics = world.rules.topics()
        assert "research" in topics
        help_spec = next(s for s in world.tool_specs if s.name == "help")
        assert "research" in help_spec.parameters["properties"]["topic"]["enum"]
        assert "Clients' tasks come in" not in topics["day"]
        assert "Money comes into the town only from the clients" not in topics["money"]


def test_source_reader_rejects_local_targets():
    for url in (
        "file:///etc/passwd",
        "http://127.0.0.1/",
        "http://169.254.169.254/",
        "http://user:pass@example.com/",
        "http://example.com:8912/",
    ):
        with pytest.raises(ValueError):
            research_sources.fetch(url)


def test_research_text_describes_own_project_not_the_simulation(world):
    from agent.wording import offences
    from world.research import STANDING

    for text in (BRIEF, STANDING, *(world.rules.text(n) for n in world.residents)):
        assert [w for w in offences(text) if w.lower() != "research"] == []
    assert {e["kind"] for e in world.log.entries()} == {"research_brief"}


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "timeout", "cancel"])
@pytest.mark.parametrize("network,gpus", [(True, None), (False, "all")])
async def test_command_container_is_isolated_and_removed(
    world, monkeypatch, outcome, network, gpus
):
    calls = []
    started, finished = asyncio.Event(), asyncio.Event()

    class Process:
        def __init__(self, run=False):
            self.run = run
            self.returncode = None if run else 0

        async def communicate(self):
            if outcome != "success":
                await finished.wait()
            self.returncode = 0 if outcome == "success" else 137
            return b"recorded output", b""

        async def wait(self):
            return self.returncode

        def kill(self):
            self.returncode = -9
            finished.set()

    async def spawn(*args, **kwargs):
        calls.append(args)
        if args[1] == "run":
            started.set()
            return Process(True)
        assert args[1:3] == ("rm", "-f")
        finished.set()
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    research = world.research
    task = asyncio.create_task(
        research_workspace.execute(
            "research-test",
            research.files,
            research.records,
            "python study.py",
            0.01,
            network=network,
            gpus=gpus,
        )
    )
    await started.wait()
    if outcome == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        result = await task
        assert result["stdout"] == "recorded output"
        assert result["timed_out"] is (outcome == "timeout")
    argv = calls[0]
    assert argv[argv.index("--network") + 1] == ("bridge" if network else "none")
    if gpus:
        assert argv[argv.index("--gpus") + 1] == gpus
    else:
        assert "--gpus" not in argv
    assert "--read-only" in argv and "--cap-drop" in argv
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]
    assert len(mounts) == 2 and mounts[1].endswith("dst=/records,readonly")
    assert not any("docker.sock" in a for a in argv)
    assert calls[-1][1:3] == ("rm", "-f")


def test_public_source_extraction_records_url_and_rejects_unreadable(world, monkeypatch):
    monkeypatch.setattr(
        research_sources,
        "fetch",
        lambda url: (
            url,
            "text/html",
            b"<h1>Study</h1><script>hidden</script><p>Observed result.</p>",
        ),
    )
    result = research_sources.read("https://example.com/study")
    assert "Observed result." in result["text"] and "hidden" not in result["text"]
    assert result["url"] == "https://example.com/study"
    monkeypatch.setattr(research_sources, "fetch", lambda url: (url, "text/plain", b""))
    with pytest.raises(ValueError, match="has not been read"):
        research_sources.read("https://example.com/empty")


@pytest.mark.asyncio
async def test_ignored_outputs_are_versioned_and_cancelled_work_is_marked(world, monkeypatch):
    r = office(world, "Ravi")
    research = world.research
    start = research.snapshot()

    async def command(*args, **kwargs):
        (research.files / ".gitignore").write_text("*.csv\n")
        (research.files / "partial.csv").write_text("partial data\n")
        raise asyncio.CancelledError

    monkeypatch.setattr(research_workspace, "execute", command)
    with pytest.raises(asyncio.CancelledError):
        await world.call(r, "shell", {"command": "python study.py", "revision": start})
    saved = research.snapshot()
    record = json.loads(next(research.records.glob("*.json")).read_text())
    assert record["result"]["cancelled"] is True
    (research.files / "partial.csv").write_text("uncommitted change")
    (research.files / "unrecorded.csv").write_text("should be removed on resume")
    research.restore(saved)
    assert (research.files / "partial.csv").read_text() == "partial data\n"
    assert not (research.files / "unrecorded.csv").exists()
