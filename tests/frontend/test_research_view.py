import json
import threading
from datetime import UTC, datetime
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

import pytest

from experiments.config import load_experiment
from frontend.publish import Publisher
from frontend.research_server import Handler, ResearchData
from infrastructure.storage import RunDirectory
from simulation.run import _create
from world.clock import DAY
from world.events import Idle
from world.research import NoTasks


@pytest.fixture
def prepared(tmp_path):
    config = load_experiment(
        Path(__file__).resolve().parents[2] / "experiments/configs/research-zenith.yaml"
    )
    runs = tmp_path / "runs"
    directory = RunDirectory.create(runs, config.name, config=config, code_revision="test")
    world = _create(
        directory,
        config,
        NoTasks(),
        {r.name: r.background_path.read_text() for r in config.residents},
    )
    return ResearchData(runs), world, config.name


def test_initial_research_snapshot_includes_real_allowance_and_eight_residents(prepared):
    store, world, name = prepared
    value = store.snapshot(name)
    assert value["run"] == name
    assert len(value["people"]) == 8
    assert next(p for p in value["people"] if p["name"] == "Aisha")["money"] == 620
    assert value["counts"] == {}
    assert not any(f["path"] == "files/paper.md" for f in value["files"])
    assert value["activity"][0]["kind"] == "research_brief"
    assert "Choose the question" in value["activity"][0]["text"]


@pytest.mark.asyncio
async def test_dashboard_links_to_exact_committed_paper_and_evidence(prepared):
    store, world, name = prepared
    r = world.residents["Aisha"]
    r.base, r.place = Idle(), "office"
    await world.call(
        r,
        "write_repo_file",
        {"path": "paper.md", "content": "# Test question\n", "revision": world.research.snapshot()},
    )
    value = store.snapshot(name)
    assert value["counts"]["write_repo_file"] == 1
    assert value["records"][0]["actor"] == "Aisha"
    evidence = store.file(name, value["records"][0]["path"], value["revision"])
    assert json.loads(evidence["text"])["arguments"]["content"] == "# Test question\n"
    (world.research.files / "paper.md").write_text("uncommitted half-write")
    assert store.file(name, "files/paper.md", value["revision"])["text"] == "# Test question\n"


def test_dashboard_does_not_expose_private_files_or_outside_runs(prepared):
    store, world, name = prepared
    for path in ("../model-api-key", "agents/Aisha/background.md", "../.git/config"):
        with pytest.raises(FileNotFoundError):
            store.file(name, path)
    with pytest.raises(ValueError):
        store.snapshot("../other")
    with pytest.raises(ValueError):
        store.file(name, "files/README.md", "--help")


def test_viewer_waits_cleanly_before_first_run(tmp_path):
    assert ResearchData(tmp_path).snapshot() == {"runs": [], "waiting": True}


@pytest.fixture
def pdf_artifacts(prepared):
    store, world, name = prepared
    research = world.research
    content = b"%PDF-1.7\n%\xff\xfe\xfd\xfc\n" + b"\x80" * 350000 + b"\n%%EOF\n"
    (research.files / "Paper draft.pdf").write_bytes(content)
    (research.files / "invalid.pdf").write_text("Not a PDF")
    (research.files / "wrong.txt").write_bytes(content)
    (research.files / "large.pdf").write_bytes(b"%PDF-" + b"0" * (8 * 1024 * 1024))
    (research.root / "private.pdf").write_bytes(content)
    (research.files / "link.pdf").symlink_to("../private.pdf")
    revision = research.repo.commit("Save PDF fixtures", date=datetime.now(UTC))
    (store.root / "linked-run").symlink_to(store.run(name), target_is_directory=True)
    # Preview the committed blob even while an agent is replacing the working copy.
    (research.files / "Paper draft.pdf").write_bytes(b"incomplete working copy")
    return store, name, revision, content


def test_pdf_preview_preserves_complete_committed_bytes_and_links_json(pdf_artifacts):
    store, name, revision, content = pdf_artifacts
    assert store.pdf(name, "files/Paper draft.pdf", revision) == content
    value = store.file(name, "files/Paper draft.pdf", revision)
    assert "text" not in value and "image" not in value
    assert value["mime"] == "application/pdf"
    url = urlsplit(value["pdf_url"])
    assert url.path == "/api/research/pdf"
    assert parse_qs(url.query) == {
        "run": [name], "path": ["files/Paper draft.pdf"], "revision": [revision],
    }
    run = store.run(name)
    revised = b"%PDF-1.7\nNew manuscript\n%%EOF\n"
    (run / "research/files/Paper draft.pdf").write_bytes(revised)
    store.git(run, "add", "files/Paper draft.pdf")
    store.git(run, "commit", "-m", "Revise manuscript")
    assert store.pdf(name, "files/Paper draft.pdf") == revised
    assert store.pdf(name, "files/Paper draft.pdf", revision) == content


def test_pdf_preview_rejects_symlinked_research_repository(pdf_artifacts, tmp_path):
    store, name, revision, _ = pdf_artifacts
    research = store.run(name) / "research"
    outside = tmp_path / "outside-research"
    research.rename(outside)
    research.symlink_to(outside, target_is_directory=True)
    with pytest.raises(FileNotFoundError):
        store.pdf(name, "files/Paper draft.pdf", revision)


@pytest.mark.parametrize(
    ("path", "error"),
    [
        ("../private.pdf", FileNotFoundError),
        ("private.pdf", FileNotFoundError),
        ("agents/Aisha/private.pdf", FileNotFoundError),
        ("files/link.pdf", FileNotFoundError),
        ("files/missing.pdf", FileNotFoundError),
        ("files/invalid.pdf", ValueError),
        ("files/wrong.txt", ValueError),
        ("files/large.pdf", ValueError),
    ],
)
def test_pdf_preview_rejects_unshared_or_invalid_artifacts(pdf_artifacts, path, error):
    store, name, revision, _ = pdf_artifacts
    with pytest.raises(error):
        store.pdf(name, path, revision)


def test_pdf_http_serves_inline_binary_and_rejects_invalid_requests(pdf_artifacts, tmp_path):
    store, name, revision, content = pdf_artifacts
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(Handler, directory=str(tmp_path / "site"))
    )
    server.research = store
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def url(path="files/Paper draft.pdf", run=name, rev=revision):
        return base + "/api/research/pdf?" + urlencode(
            {"run": run, "path": path, "revision": rev}
        )

    try:
        with urlopen(url(), timeout=5) as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "application/pdf"
            assert int(response.headers["Content-Length"]) == len(content)
            assert response.headers["Content-Disposition"] == (
                'inline; filename="Paper_draft.pdf"; filename*=UTF-8\'\'Paper%20draft.pdf'
            )
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.read() == content
        for request, status in [
            (url(path="../private.pdf"), 404),
            (url(path="files/link.pdf"), 404),
            (url(run="linked-run"), 404),
            (url(run="../other"), 400),
            (url(rev="--help"), 400),
            (url(path="files/invalid.pdf"), 400),
            (url(path="files/large.pdf"), 400),
        ]:
            with pytest.raises(HTTPError) as error:
                urlopen(request, timeout=5)
            assert error.value.code == status
            assert json.loads(error.value.read())["error"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


async def test_delayed_commission_replays_living_allowance_only_at_start(tmp_path):
    config = load_experiment(
        Path(__file__).resolve().parents[2] / "experiments/configs/ai-lab.yaml"
    )
    runs = tmp_path / "runs"
    directory = RunDirectory.create(runs, config.name, config=config, code_revision="test")
    world = _create(
        directory, config, NoTasks(),
        {r.name: r.background_path.read_text() for r in config.residents},
    )
    def balances():
        snapshot = ResearchData(runs).snapshot(config.name)
        actual = {r.name: r.inventory.money for r in world.residents.values()}
        assert {p["name"]: p["money"] for p in snapshot["people"]} == actual
        return actual

    assert set(balances().values()) == {200 + config.town.research.allowance}
    snapshot = ResearchData(runs).snapshot(config.name)
    assert snapshot["paper_artifact"] == "paper.tex"
    assert [s["day"] for s in snapshot["scheduled_milestones"]] == [28, 49, 70]
    resident = world.residents["Aisha"]
    resident.base, resident.place = Idle(), "store"
    await world.call(resident, "buy", {"item": "bread"})
    before = balances()
    world.clock.set(7 * DAY + 7 * 3600)
    world.research.announce(world)
    assert balances() == before


async def test_academy_dashboard_and_publisher_need_no_service_residents(tmp_path):
    config = load_experiment(
        Path(__file__).resolve().parents[2] / "experiments/configs/autoresearch-academy.yaml"
    )
    runs = tmp_path / "runs"
    directory = RunDirectory.create(runs, config.name, config=config, code_revision="test")
    world = _create(
        directory,
        config,
        NoTasks(),
        {r.name: r.background_path.read_text() for r in config.residents},
    )
    resident = world.residents["Aisha"]
    resident.base, resident.place = Idle(), "store"
    await world.call(resident, "buy", {"item": "bread"})
    resident.place = "hospital"
    await world.call(resident, "seek_care", {"service": "examination"})
    await world.call(resident, "seek_care", {"service": "treatment"})
    grant = {
        "stage": "proposal",
        "day": 7,
        "score": 50,
        "reward_per_resident": 315,
        "reward_total": 1260,
        "status": "reviewed",
        "summary": "Feasible question.",
        "review": {"evidence": ["files/proposal.md"]},
        "audit": "research_reviews/proposal",
    }
    for person in world.residents.values():
        person.inventory.receive(315, "received", "research grant proposal")
    world.record("research_milestone", lambda w: "Proposal reviewed.", payload=grant)
    snapshot = ResearchData(runs).snapshot(config.name)
    assert {p["name"] for p in snapshot["people"]} == {"Mei", "Aisha", "Ravi", "Kofi"}
    assert {p["occupation"] for p in snapshot["people"]} == {"teacher", "student"}
    assert {p["name"]: p["money"] for p in snapshot["people"]} == {
        p.name: p.inventory.money for p in world.residents.values()
    }
    assert snapshot["milestones"][0]["review"]["evidence"] == ["files/proposal.md"]
    assert snapshot["milestones"][0]["record"] == "records/milestone-proposal.json"
    assert snapshot["comparison"][0]["scores"] == {"proposal": 50}
    assert snapshot["comparison"][0]["reward_total"] == 1260
    site = tmp_path / "site"
    Publisher(runs, site).publish()
    bundle = json.loads((site / "data" / "runs" / config.name / "world.json").read_text())
    assert len(bundle["residents"]) == 4
    assert {r["occupation"] for r in bundle["residents"]} == {"teacher", "student"}
