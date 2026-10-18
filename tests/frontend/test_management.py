"""Management preserves experiment identities, protects live runs, and serializes publishing."""

import http.client
import json
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from frontend.management import ManagementError, display_name, manage
from frontend.server import DevServer


def make_run(root, name="example", status="completed", seed="seed-0000"):
    run = root / name / seed
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({"status": status}))
    (run / "events.jsonl").write_text("original evidence\n")
    return run


def test_rename_preserves_ids_events_and_all_seeds(tmp_path):
    first = make_run(tmp_path)
    second = make_run(tmp_path, seed="seed-0001")
    before = {p: p.read_bytes() for r in (first, second) for p in r.iterdir()}
    result = manage(
        tmp_path, {"action": "rename", "experiment": "example", "display_name": "  New study  "}
    )
    assert result["display_name"] == display_name(first.parent) == "New study"
    assert all(p.read_bytes() == data for p, data in before.items())
    assert (tmp_path / "example").is_dir()


@pytest.mark.parametrize("label", ["", "  ", "a" * 121, "bad\nname", 42])
def test_invalid_display_names(tmp_path, label):
    make_run(tmp_path)
    with pytest.raises(ManagementError):
        manage(tmp_path, {"action": "rename", "experiment": "example", "display_name": label})


@pytest.mark.parametrize("name", ["../outside", ".trash", "..", "/tmp", "a/b", "a%2fb", None])
def test_invalid_paths_rejected(tmp_path, name):
    with pytest.raises(ManagementError):
        manage(tmp_path, {"action": "delete", "experiment": name, "confirm": name})


def test_symlink_experiment_rejected(tmp_path):
    make_run(tmp_path, "real")
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(ManagementError):
        manage(tmp_path, {"action": "rename", "experiment": "link", "display_name": "No"})


def test_delete_moves_all_seeds_to_recovery_and_requires_confirmation(tmp_path):
    make_run(tmp_path)
    make_run(tmp_path, seed="seed-0001", status="failed")
    with pytest.raises(ManagementError):
        manage(tmp_path, {"action": "delete", "experiment": "example"})
    result = manage(tmp_path, {"action": "delete", "experiment": "example", "confirm": "example"})
    assert not (tmp_path / "example").exists()
    recovery = Path(result["recovery_path"])
    assert recovery.parent == tmp_path / ".trash"
    assert len(list(recovery.glob("seed-*/manifest.json"))) == 2
    assert (recovery / "seed-0000/events.jsonl").read_text() == "original evidence\n"


def test_any_running_seed_blocks_delete(tmp_path):
    make_run(tmp_path)
    make_run(tmp_path, seed="seed-0001", status="running")
    with pytest.raises(ManagementError) as error:
        manage(tmp_path, {"action": "delete", "experiment": "example", "confirm": "example"})
    assert error.value.status == 409
    assert (tmp_path / "example/seed-0000").is_dir()


@contextmanager
def viewer(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    out = tmp_path / "site"
    out.mkdir()
    publishes = []
    publisher = SimpleNamespace(runs_root=runs, out=out, publish=lambda: publishes.append(1))
    server = DevServer(("127.0.0.1", 0), publisher, interval=3600)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, runs, publishes
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def request(server, body, **overrides):
    host = f"127.0.0.1:{server.server_port}"
    headers = {
        "Origin": f"http://{host}",
        "Content-Type": "application/json",
        "X-Socio-Management": "1",
    }
    headers.update(overrides)
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
    connection.request("POST", "/api/experiments", json.dumps(body), headers)
    response = connection.getresponse()
    status, result = response.status, json.loads(response.read())
    connection.close()
    return status, result


def test_real_http_api_rename_delete_and_publish(tmp_path):
    with viewer(tmp_path) as (server, runs, publishes):
        make_run(runs)
        status, result = request(
            server, {"action": "rename", "experiment": "example", "display_name": "New"}
        )
        assert status == 200 and result["display_name"] == "New"
        assert len(publishes) == 2
        status, _ = request(
            server, {"action": "delete", "experiment": "example", "confirm": "example"}
        )
        assert status == 200 and len(publishes) == 3
        assert not (runs / "example").exists()


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "http://evil.example"},
        {"X-Socio-Management": "0"},
        {"Content-Type": "text/plain"},
        {"Host": "evil.example", "Origin": "http://evil.example"},
    ],
)
def test_http_rejects_cross_origin_and_untrusted_hosts(tmp_path, headers):
    with viewer(tmp_path) as (server, runs, _):
        make_run(runs)
        status, _ = request(
            server, {"action": "delete", "experiment": "example", "confirm": "example"}, **headers
        )
        assert status == 403
        assert (runs / "example").is_dir()


def test_publish_refreshes_display_name_and_prunes_deleted_pages(tmp_path):
    from core.agent.evolution import Evolver
    from core.environment import Trade
    from experiments.config import ExperimentConfig
    from frontend.publish import Publisher
    from infrastructure.config import load_config
    from infrastructure.llm import ScriptedClient
    from infrastructure.storage import RunDirectory
    from runtime.simulation import Setup, Simulation
    from tests.core.environment.test_technical_community import RepositoryProvider

    config = load_config(Path("experiments/configs/community/lite.yaml"), ExperimentConfig)
    runs = tmp_path / "runs"
    directory = RunDirectory.create(runs, "example", 0, config=config, code_revision="test")
    setup = Setup(
        simulation=config.simulation,
        environment=config.environment,
        agents=config.agents,
        cognition=config.cognition,
        evolver=Evolver(config.evolution),
        providers={Trade.PROGRAMMING: RepositoryProvider()},
        client=ScriptedClient(lambda r: "unused"),
    )
    Simulation.create(directory, setup)
    manifest = json.loads(directory.manifest_path.read_text())
    manifest["status"] = "interrupted"
    directory.manifest_path.write_text(json.dumps(manifest))
    publisher = Publisher(runs, tmp_path / "site")
    publisher.publish()
    index = tmp_path / "site/data/index.json"
    before = json.loads(index.read_text())["runs"][0]
    assert before["display_name"] is None
    manage(runs, {"action": "rename", "experiment": "example", "display_name": "Readable name"})
    publisher.publish()
    after = json.loads(index.read_text())["runs"][0]
    assert after["display_name"] == "Readable name" and after["experiment"] == "example"
    manage(runs, {"action": "delete", "experiment": "example", "confirm": "example"})
    publisher.publish()
    assert json.loads(index.read_text())["runs"] == []
    assert not (tmp_path / "site/data/runs/example/seed-0000/run.json").exists()
