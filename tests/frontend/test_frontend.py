import json
import shutil
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from experiments.run import main
from frontend.server import make_server

CONFIGS = Path(__file__).parents[2] / "experiments" / "configs"
RUN = "smoke-dry-run/seed-0003"


@pytest.fixture(scope="module")
def runs_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("runs")
    main([str(CONFIGS / "smoke.yaml"), "--seeds", "3", "--runs-root", str(root), "--dry-run"])
    return root


@pytest.fixture(scope="module")
def base(runs_root) -> Iterator[str]:
    server = make_server(runs_root, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def get(base: str, path: str):
    with urlopen(f"{base}{path}") as response:
        return json.load(response)


def status_of(base: str, path: str) -> int:
    try:
        urlopen(f"{base}{path}").close()
    except HTTPError as error:
        return error.code
    return 200


def snapshot(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def test_the_api_describes_a_run_and_follows_its_events(base, runs_root):
    [run] = get(base, "/api/runs")
    assert (run["experiment"], run["directory"], run["seed"], run["status"]) == (
        "smoke-dry-run",
        "seed-0003",
        3,
        "completed",
    )
    assert run["days_done"] == run["days"] == 3

    world = get(base, f"/api/runs/{RUN}/world")
    assert {place["kind"] for place in world["places"]} == {"home", "work", "social"}
    assert [agent["name"] for agent in world["agents"]] == ["Mei", "Tomas", "Aisha"]

    everything = get(base, f"/api/runs/{RUN}/events")
    events = everything["events"]
    assert events and everything["last"] == events[-1]["seq"]
    middle = events[len(events) // 2]["seq"]
    later = get(base, f"/api/runs/{RUN}/events?after={middle}")["events"]
    assert later == [event for event in events if event["seq"] > middle]
    assert get(base, f"/api/runs/{RUN}/events?after={everything['last']}")["events"] == []
    assert get(base, f"/api/runs/{RUN}/evaluation") == []


def test_agent_history_diff_and_files_come_from_git(base):
    history = get(base, f"/api/runs/{RUN}/agents/Mei/history")
    assert [version["time"] for version in history] == sorted(
        version["time"] for version in history
    )
    assert {version["level"] for version in history} >= {None, "L0"}
    commit = history[-1]["commit"]

    files = get(base, f"/api/runs/{RUN}/agents/Mei/commits/{commit[:8]}/files")
    assert files["commit"] == commit
    assert set(files) == {"commit", "policy", "skills", "insights", "diary"}
    assert files["diary"]["name"].startswith("day-")

    diff = get(base, f"/api/runs/{RUN}/agents/Mei/commits/{commit}/diff")["diff"]
    assert diff.startswith("diff --git")
    root_diff = get(base, f"/api/runs/{RUN}/agents/Mei/commits/{history[0]['commit']}/diff")
    assert root_diff["diff"].startswith("diff --git")


@pytest.mark.parametrize(
    "path",
    [
        "/api/runs/nope/seed-0001/world",
        f"/api/runs/{RUN}/agents/Zed/history",
        f"/api/runs/{RUN}/agents/Mei/commits/deadbeef/diff",
        f"/api/runs/{RUN}/events?after=soon",
        "/api/runs/..%2f/seed-0003/world",
        f"/api/runs/{RUN}/agents/..%2f..%2fMei/history",
        f"/api/runs/{RUN}/agents/Mei/commits/..%2fHEAD/files",
        "/%2e%2e/%2e%2e/etc/passwd",
        "/api/unknown",
    ],
)
def test_unknown_and_traversing_requests_are_404(base, path):
    assert status_of(base, path) == 404


def test_serving_never_modifies_the_run(base, runs_root):
    root = runs_root / RUN
    mei = root / "agents" / "Mei"

    def status() -> str:
        return subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=mei,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    before_status = status()  # refreshes the index, so take it before the snapshot
    before = snapshot(root)
    history = get(base, f"/api/runs/{RUN}/agents/Mei/history")
    for version in history:
        commit = version["commit"]
        get(base, f"/api/runs/{RUN}/agents/Mei/commits/{commit}/diff")
        get(base, f"/api/runs/{RUN}/agents/Mei/commits/{commit}/files")
    for path in ("/api/runs", f"/api/runs/{RUN}/world", f"/api/runs/{RUN}/events"):
        get(base, path)
    assert snapshot(root) == before
    assert status() == before_status == ""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_viewers_replay_reaches_the_state_the_environment_checkpointed(base, runs_root):
    root = runs_root / RUN
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("replay_final.mjs")), base, RUN],
        capture_output=True,
        text=True,
        check=True,
    )
    replayed = json.loads(result.stdout)
    final = max((root / "checkpoints").glob("day-*.json"))
    environment = json.loads(final.read_text(encoding="utf-8"))["environment"]
    assert replayed["balances"] == environment["balances"]
    assert replayed["locations"] == environment["locations"]
    assert replayed["stable"]
