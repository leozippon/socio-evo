import hashlib
import json
import re
import shutil
import subprocess
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import urlopen

import pytest

from core.agent.evolution import History
from core.agent.prompts import REPLY
from core.interaction import EventKind
from frontend.publish import KINDS, Publisher
from frontend.publish import main as publish
from frontend.server import DevServer
from infrastructure.storage import RunDirectory
from tests.analysis.test_measures import truncate_mid_day
from tests.conftest import TOWN

PROJECT = Path(__file__).parents[2]
README = PROJECT / "frontend" / "README.md"
PUSH = PROJECT / "frontend" / "deploy" / "push.sh"
RUN = "data/runs/town/seed-0007"


def files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def stamps(root: Path) -> dict[str, tuple[int, int]]:
    return {
        path.relative_to(root).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.fixture(scope="module")
def site(town, tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("site")
    Publisher(town.parents[1], out).publish()
    return out


def in_progress(town: Path, runs: Path) -> Path:
    """A copy of the town under `runs`, stopped in the middle of day 2 while running."""
    root = runs / "town" / "seed-0007"
    shutil.copytree(town, root)
    truncate_mid_day(root, 2)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest.update(status="running", ended_at=None)
    (root / "manifest.json").write_text(json.dumps(manifest))
    return root


def complete(town: Path, root: Path) -> None:
    """Let the copy at `root` run to the end of the town."""
    for name in ("events.jsonl", "manifest.json"):
        shutil.copy(town / name, root / name)
    for checkpoint in (town / "checkpoints").iterdir():
        shutil.copy(checkpoint, root / "checkpoints")


def contract() -> dict[str, list[str]]:
    """The README's file kinds: each path pattern with the fields its table documents."""
    documented = {}
    for section in re.split(r"^### ", README.read_text(encoding="utf-8"), flags=re.M)[1:]:
        heading, _, body = section.partition("\n")
        table = re.search(r"^\| Field \|.*\n\|[- |]+\n((?:\|.*\n)+)", body, flags=re.M)
        documented[heading.strip().strip("`")] = re.findall(r"^\| `([^`]+)` \|", table[1], re.M)
    return documented


def values_at(document: Any, path: str) -> list[Any]:
    """The values at a documented path: `a.b` is field `b` of `a`, `a[]` each element of `a`."""
    values = [document]
    for part in filter(None, path.split(".")):
        values = [value[part.removesuffix("[]")] for value in values]
        if part.endswith("[]"):
            values = [item for value in values for item in value]
    return values


def test_every_file_has_exactly_the_documented_fields(site):
    documented = contract()
    assert set(documented) == set(KINDS.values())
    for pattern, fields in documented.items():
        paths = sorted((site / "data").glob(re.sub(r"\{\w+\}", "*", pattern)))
        assert paths, pattern
        children = defaultdict(set)
        for field in fields:
            parent, _, name = field.rpartition(".")
            children[parent].add(name)
        for path in paths:
            document = json.loads(path.read_bytes())
            for parent, names in children.items():
                for value in values_at(document, parent):
                    assert set(value) == names, (path, parent)

    kinds = dict(re.findall(r"^\| `(\w+)` \|[^|]*\|[^|]*\| (.*) \|$", README.read_text(), re.M))
    assert set(kinds) == {str(kind) for kind in EventKind}
    seen = set()
    for path in (site / RUN / "events").iterdir():
        for event in json.loads(path.read_bytes())["events"]:
            seen.add(event["kind"])
            assert set(event["payload"]) <= set(re.findall(r"`(\w+)`", kinds[event["kind"]]))
    assert len(seen) >= 20


def test_references_carry_the_hash_of_files_inside_the_site(site, town):
    for name, data in files(site).items():
        assert not (site / name).is_symlink()
        assert str(town.parents[1]) not in data.decode()
        if not name.endswith(".json"):
            continue
        document = data.decode()
        for reference in re.findall(r'"([^"?]+\?[vr]=[0-9a-f]{16})"', document):
            url = urljoin(f"http://site/{quote(name)}", reference)
            target = (site / urlsplit(url).path.lstrip("/")).resolve()
            assert target.is_relative_to(site.resolve())
            digest = hashlib.sha256(target.read_bytes()).hexdigest()[:16]
            assert reference.endswith(f"={digest}")


def test_the_bundle_holds_no_model_call(site, town):
    calls = [json.loads(line) for line in (town / "llm_calls.jsonl").read_text().splitlines()]
    prompts = [call["request"]["messages"][-1]["content"] for call in calls]
    assert all(prompt.endswith(REPLY) for prompt in prompts[:10])

    def keys(value: Any) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {key for item in value.values() for key in keys(item)}
        if isinstance(value, list):
            return {key for item in value for key in keys(item)}
        return set()

    for name, data in files(site).items():
        assert REPLY.encode() not in data
        if name.endswith(".json"):
            assert not keys(json.loads(data)) & {"messages", "request", "response", "reasoning"}


def test_an_agent_is_published_as_its_repository_holds_it(site, town):
    log = [json.loads(line) for line in (town / "events.jsonl").read_text().splitlines()]
    for agent in ("Ana", "Ben", "Cai"):
        directory, base = town / "agents" / agent, site / RUN / "agents" / agent
        history = json.loads((base / "versions.json").read_bytes())
        commits = subprocess.run(
            ["git", "rev-list", "--reverse", "HEAD"], cwd=directory, capture_output=True, text=True
        ).stdout.split()
        assert [version["commit"] for version in history["versions"]] == commits
        assert [
            (version["level"], version["trigger"], version["commit"])
            for version in history["versions"]
            if version["level"]
        ] == [
            (event["payload"]["level"], event["payload"]["trigger"], event["payload"]["commit"])
            for event in log
            if event["kind"] == "evolution" and event["actor"] == agent
        ]

        last = history["versions"][-1]
        day = json.loads((base / urlsplit(last["url"]).path).read_bytes())
        [state] = [
            version["state"] for version in day["versions"] if version["commit"] == last["commit"]
        ]
        memory = directory / "memory"
        assert state["policy"] == (directory / "parameters" / "policy.md").read_text()
        skills = {path.stem: path.read_text() for path in sorted(memory.glob("skills/*.md"))}
        assert skills and state["skills"] == skills
        insights = (memory / "insights.jsonl").read_text().splitlines()
        assert state["insights"] == [json.loads(line) for line in insights]
        diary = sorted(memory.glob("diary/day-*.md"))
        assert state["diary"] == [int(path.stem.removeprefix("day-")) for path in diary]
        for entry in history["diary"]:
            holder = json.loads((base / urlsplit(entry["url"]).path).read_bytes())
            [text] = [found["text"] for found in holder["diary"] if found["day"] == entry["day"]]
            assert text == (memory / "diary" / f"day-{entry['day']:04d}.md").read_text()


def test_a_run_in_progress_is_published_and_completed_by_a_later_publish(town, tmp_path):
    runs, out = tmp_path / "runs", tmp_path / "site"
    root = in_progress(town, runs)
    Publisher(runs, out).publish()
    run = json.loads((out / RUN / "run.json").read_bytes())
    assert (run["status"], run["settled_day"], run["last_day"]) == ("running", 1, 2)
    assert [(day["day"], day["settled"]) for day in run["event_days"]] == [(1, True), (2, False)]
    assert "?v=" in run["event_days"][0]["url"] and "?r=" in run["event_days"][1]["url"]
    before = stamps(out)

    complete(town, root)
    written = set(Publisher(runs, out).publish().written)
    settled = {
        f"{RUN}/events/day-0001.json",
        f"{RUN}/world.json",
        *(f"{RUN}/agents/{agent}/day-0001.json" for agent in ("Ana", "Ben", "Cai")),
    }
    assert not written & settled
    assert {f"{RUN}/events/day-0002.json", f"{RUN}/events/day-0003.json"} <= written
    assert all(stamps(out)[name] == before[name] for name in settled)

    fresh = tmp_path / "fresh"
    Publisher(town.parents[1], fresh).publish()
    assert files(out) == files(fresh)


def test_a_run_just_created_is_published_before_its_first_checkpoint(tmp_path):
    runs = tmp_path / "runs"
    run = RunDirectory.create(runs, TOWN.name, 7, config=TOWN, code_revision="test")
    History.init(run.agent_dir("Ana"), "Ana")  # its first commit is still to come
    Publisher(runs, tmp_path / "site").publish()
    document = json.loads((tmp_path / "site" / RUN / "run.json").read_bytes())
    assert (document["settled_day"], document["last_day"], document["events"]) == (0, 0, 0)
    assert document["event_days"] == []
    assert [agent["versions"] for agent in document["agents"]] == [0, 0, 0]


def test_republishing_an_unchanged_run_rewrites_nothing(town, tmp_path, capsys):
    out = tmp_path / "site"
    publish(["--runs-root", str(town.parents[1]), "--out", str(out)])
    before = stamps(out)
    publisher = Publisher(town.parents[1], out)
    assert publisher.publish().written == []
    assert publisher.publish().written == []
    publish(["--runs-root", str(town.parents[1]), "--out", str(out)])
    assert capsys.readouterr().out.splitlines()[-1].endswith(": 0 written, 0 removed")
    assert stamps(out) == before


def test_publishing_never_modifies_the_run(town, tmp_path):
    def status(agent: str) -> str:
        command = ["git", "status", "--porcelain", "--untracked-files=all"]
        return subprocess.run(
            command, cwd=town / "agents" / agent, capture_output=True, text=True, check=True
        ).stdout

    agents = ("Ana", "Ben", "Cai")
    statuses = [status(agent) for agent in agents]  # refreshes the index: before the snapshot
    before = stamps(town)
    Publisher(town.parents[1], tmp_path / "site").publish()
    assert stamps(town) == before
    assert [status(agent) for agent in agents] == statuses == ["", "", ""]


def test_publishing_refuses_unsafe_targets_and_malformed_runs(town, tmp_path):
    runs = tmp_path / "runs"
    root = runs / "town" / "seed-0007"
    shutil.copytree(town, root)
    with pytest.raises(ValueError, match="inside the runs root"):
        Publisher(runs, runs / "site")
    stranger = tmp_path / "stranger"
    stranger.mkdir()
    (stranger / "notes.txt").write_text("mine")
    with pytest.raises(FileExistsError):
        Publisher(runs, stranger).publish()
    assert files(stranger) == {"notes.txt": b"mine"}

    log = root / "events.jsonl"
    lines = log.read_bytes().split(b"\n")
    lines[3] = lines[3].replace(b'"seq": 3,', b'"seq": "three",')
    log.write_bytes(b"\n".join(lines))
    with pytest.raises(ValueError, match="events.jsonl:4") as error:
        Publisher(runs, tmp_path / "site").publish()
    assert any(str(root) in note for note in error.value.__notes__)


def test_the_dev_server_serves_exactly_the_published_site(town, site, tmp_path):
    server = DevServer(("127.0.0.1", 0), Publisher(town.parents[1], tmp_path / "served"), 0.1)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/"

    def get(path: str) -> tuple[int, bytes, str | None]:
        try:
            with urlopen(urljoin(base, path)) as response:
                return response.status, response.read(), response.headers["Cache-Control"]
        except HTTPError as error:
            return error.code, b"", None

    try:
        published = files(site)
        for name, data in published.items():
            assert get(quote(name))[:2] == (200, data)
        assert get("")[1] == published["index.html"]
        run = json.loads(published[f"{RUN}/run.json"])
        assert get(f"{RUN}/{run['world']}")[2] == "public, max-age=31536000, immutable"
        assert get("data/index.json")[2] == "no-store"
        for missing in ("data/", "data/runs/", "%2e%2e/%2e%2e/etc/passwd", "data/nothing.json"):
            assert get(missing)[0] == 404
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(shutil.which("sha256sum") is None, reason="GNU coreutils are missing")
def test_push_uploads_only_what_changed_and_switches_the_site_at_once(town, tmp_path):
    ssh = tmp_path / "ssh"
    ssh.write_text('#!/bin/sh\nshift\nexec sh -c "$1"\n')  # runs the command here instead
    ssh.chmod(0o755)
    runs, out, server = tmp_path / "runs", tmp_path / "site", tmp_path / "server"

    def push() -> str:
        command = [str(PUSH), "example.org", str(out), str(server)]
        environment = {"PATH": "/usr/bin:/bin", "PUSH_SSH": str(ssh)}
        result = subprocess.run(command, capture_output=True, text=True, env=environment)
        assert result.returncode == 0, result.stderr
        return result.stdout

    root = in_progress(town, runs)
    Publisher(runs, out).publish()
    first = files(out)
    assert push().startswith(f"{len(first)} files uploaded")
    assert files(server / "site") == first
    old = (server / "site").resolve()

    complete(town, root)
    Publisher(runs, out).publish()
    second = files(out)
    changed = {name for name, data in second.items() if first.get(name) != data}
    removed = set(first) - set(second)
    output = push()
    assert output.startswith(f"{len(changed)} files uploaded")
    assert f", {len(removed)} removed;" in output
    new = (server / "site").resolve()
    assert new != old and files(server / "site") == second
    assert files(old) == first  # the previous release is kept as it was
    unchanged = set(first) & set(second) - changed
    assert unchanged and all(
        (old / name).stat().st_ino == (new / name).stat().st_ino for name in unchanged
    )
    assert push().strip() == "the server already has this site"
    assert sorted(path.name for path in (server / "releases").iterdir()) == sorted(
        [old.name, new.name]
    )
