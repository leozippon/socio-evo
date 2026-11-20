"""Submission versions, timed feedback and grants survive real checkpoint rollback."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pypdf import PdfWriter

from agent.directory import AgentDirectory
from experiments.config import load_experiment
from infrastructure.llm import ScriptedClient
from world import research_conferences as conferences
from world.clock import ManualClock
from world.config import ConferenceVenue, ResearchSettings
from world.research import NoTasks
from world.world import World

PAPER = r"\documentclass{article}\begin{document}Measured retrieval recall.\end{document}"


def write_pdf(world, title):
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": title})
    writer.write(world.research.files / "paper.pdf")


@pytest.fixture
def lab(tmp_path, monkeypatch):
    config = load_experiment(
        Path(__file__).resolve().parents[2] / "experiments/configs/autoresearch-academy.yaml"
    ).town
    venue = ConferenceVenue(
        id="test",
        title="Test IR Conference",
        scope="Information retrieval",
        abstract_at="2026-03-03T23:59:00-12:00",
        submission_at="2026-03-04T23:59:00-12:00",
        reviews_at="2026-03-06T00:00:00-12:00",
        rebuttal_at="2026-03-08T23:59:00-12:00",
        notification_at="2026-03-10T23:59:00-12:00",
        camera_ready_at="2026-03-12T23:59:00-12:00",
    )
    config = config.model_copy(
        update={
            "research": ResearchSettings(
                conferences=(venue,),
                judge={
                    "model": "external",
                    "base_url": "https://judge.invalid",
                    "api_key_env": "JUDGE_KEY",
                },
            )
        }
    )
    for resident in config.residents:
        AgentDirectory.create(tmp_path / "agents" / resident.name, background="A researcher.")
    world = World(config, tmp_path, NoTasks(), clock=ManualClock())
    world.research.initialize(world)
    (world.research.files / "paper.tex").write_text(PAPER)
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(world.research.files / "paper.pdf")
    world.research.repo.commit("Manuscript", date=datetime.now(UTC))
    calls = []

    def respond(request):
        calls.append(request)
        citation = {"path": "files/paper.tex", "quote": "Measured retrieval recall."}
        if request.metadata["phase"] == "decision":
            return {
                "decision": "accept",
                "overall": 7,
                "confidence": 3,
                "rationale": "Evidence supports a useful contribution.",
                "citations": [citation],
            }
        return {
            **{
                name: {
                    "score": 3,
                    "rationale": "Supported, with limitations.",
                    "citations": [citation],
                }
                for name in (
                    "technical_quality",
                    "novelty",
                    "significance",
                    "evidence",
                    "reproducibility",
                )
            },
            **{
                name: [{"text": "Clarify the comparison.", "citations": [citation]}]
                for name in ("strengths", "weaknesses", "questions", "required_revisions")
            },
            "overall": 6,
            "confidence": 3,
            "summary": "Useful study with a question.",
        }

    monkeypatch.setattr(conferences, "create_client", lambda _: ScriptedClient(respond))
    return world, venue, calls


def moment(world, target):
    world.clock.set(
        world.clock.now() + int((target - world.research.simulated_now(world)).total_seconds())
    )


async def action(world, name, **kwargs):
    return await conferences.ConferenceDesk(world.research).call(
        world, next(iter(world.residents.values())), {"action": name, "venue": "test", **kwargs}
    )


async def submitted(world):
    await action(world, "register", title="Retrieval study", abstract="Compare retrieval methods.")
    return await action(world, "submit")


async def test_frozen_submission_timed_reviews_latest_response_and_idempotent_grant(lab):
    world, venue, calls = lab
    entry = await submitted(world)
    frozen = json.loads(world.research._path(entry["manuscript_record"]).read_text())
    (world.research.files / "paper.tex").write_text(PAPER.replace("Measured", "Invented"))
    world.research.repo.commit("Working draft changed", date=datetime.now(UTC))
    moment(world, venue.reviews_at - timedelta(seconds=1))
    assert "reviews" not in (await action(world, "open"))["submissions"][0]
    assert calls == []
    moment(world, venue.reviews_at)
    opened = await action(world, "open")
    assert len(opened["submissions"][0]["reviews"]) == len(calls) == 3
    assert len({request.metadata["role"] for request in calls}) == 3
    assert all(
        json.loads(r.messages[1].content)["documents"]["files/paper.tex"] == PAPER for r in calls
    )
    money = next(iter(world.residents.values())).inventory.money
    for text in ("First answer", "Updated answer"):
        (world.research.files / "rebuttal.md").write_text(text)
        (world.research.files / "new-measurements.txt").write_text(
            "Additional measured recall: 0.7"
        )
        world.research.repo.commit("Response", date=datetime.now(UTC))
        await action(world, "rebuttal", evidence=["new-measurements.txt"])
    (world.research.files / "new-measurements.txt").write_text("Changed after response")
    before = world.snapshot()
    moment(world, venue.notification_at)
    await action(world, "open")
    assert len(calls) == 7
    final_request = json.loads(calls[-1].messages[1].content)
    assert final_request["documents"]["review/rebuttal.md"] == "Updated answer"
    assert (
        final_request["documents"]["response/new-measurements.txt"]
        == "Additional measured recall: 0.7"
    )
    assert "review/updated.json" in final_request["documents"]
    assert next(iter(world.residents.values())).inventory.money == money + 840
    paid = world.snapshot()
    for snapshot in (paid, before):
        restored = World(world.config, world.research.root.parent, NoTasks(), clock=ManualClock())
        restored.restore(snapshot)
        moment(restored, venue.notification_at)
        await action(restored, "open")
        assert next(iter(restored.residents.values())).inventory.money == money + 840
    assert len(calls) == 7
    assert json.loads(restored.research._path(entry["manuscript_record"]).read_text()) == frozen
    assert all(
        any(p.kind == "research_milestone" for p in r.port.held)
        for r in restored.residents.values()
    )
    await action(restored, "camera_ready")
    assert "active" not in (await action(restored, "list"))["state"]


async def test_deadlines_and_invalid_pdf(lab):
    world, venue, calls = lab
    moment(world, venue.abstract_at)
    await action(world, "register", title="A", abstract="B")
    (world.research.files / "paper.pdf").write_bytes(b"not a PDF")
    with pytest.raises(ValueError, match="PDF cannot"):
        await action(world, "submit")
    moment(world, venue.submission_at + timedelta(seconds=1))
    assert (await action(world, "open"))["submissions"][0]["status"] == "missed_submission"
    with pytest.raises(ValueError, match="deadline has passed"):
        await action(world, "register", title="A", abstract="B")
    assert calls == []


async def test_parallel_papers_resolve_by_id_and_keep_independent_lifecycles(lab):
    world, venue, calls = lab
    other = venue.model_copy(
        update={
            "id": "other",
            "title": "Other IR Conference",
            "submission_kind": "arr_commitment",
            "commitment_at": venue.rebuttal_at + timedelta(days=1),
        }
    )
    settings = world.research.settings.model_copy(update={"conferences": (venue, other)})
    world.research.settings = settings
    world.config = world.config.model_copy(update={"research": settings})
    first = await submitted(world)
    second = await action(world, "register", venue="other", title="Study B", abstract="B")
    (world.research.files / "paper.tex").write_text(PAPER.replace("recall.", "recall. Study B."))
    write_pdf(world, "Study B")
    await action(world, "submit", venue="other")  # Unique venue preserves old call syntax.
    third = await action(world, "register", title="Study C", abstract="C")
    with pytest.raises(ValueError, match="submission_id"):
        await action(world, "submit")
    with pytest.raises(ValueError, match="Unknown submission_id"):
        await action(world, "withdraw", submission_id="missing")
    with pytest.raises(ValueError, match="does not belong"):
        await action(world, "withdraw", submission_id=second["id"])
    write_pdf(world, "Study C")
    await action(world, "submit", submission_id=third["id"])
    assert len((await action(world, "open"))["submissions"]) == 2
    await action(world, "withdraw", submission_id=third["id"])
    assert (await action(world, "open", submission_id=third["id"]))["submissions"][0][
        "status"
    ] == "withdrawn"
    with pytest.raises(ValueError, match="is withdrawn"):
        await action(world, "submit", submission_id=third["id"])
    missing = await action(world, "register", title="Unfinished draft", abstract="D")
    moment(world, venue.reviews_at)
    opened = await action(world, "open", venue=None)
    states = {s["id"]: s for s in opened["submissions"]}
    assert states[first["id"]]["status"] == states[second["id"]]["status"] == "reviewed"
    assert states[missing["id"]]["status"] == "missed_submission"
    assert states[third["id"]]["status"] == "withdrawn"
    assert len(calls) == 6
    (world.research.files / "rebuttal.md").write_text("Response for study A only.")
    await action(world, "rebuttal", submission_id=first["id"])
    await action(world, "commit", venue=None, submission_id=second["id"])
    before = world.snapshot()
    money = next(iter(world.residents.values())).inventory.money
    moment(world, venue.notification_at)
    await action(world, "open", venue=None)
    assert len(calls) == 14
    assert next(iter(world.residents.values())).inventory.money == money + 2 * 840
    decisions = {
        r.metadata["submission"]: json.loads(r.messages[1].content)
        for r in calls
        if r.metadata["phase"] == "decision"
    }
    assert decisions[first["id"]]["documents"]["review/rebuttal.md"] == "Response for study A only."
    assert (
        decisions[second["id"]]["documents"]["review/rebuttal.md"]
        == "No author response was submitted."
    )
    assert "Study B" not in decisions[first["id"]]["documents"]["files/paper.tex"]
    assert "Study B" in decisions[second["id"]]["documents"]["files/paper.tex"]
    after = world.snapshot()
    for checkpoint in (after, before):
        restored = World(world.config, world.research.root.parent, NoTasks(), clock=ManualClock())
        restored.restore(checkpoint)
        moment(restored, venue.notification_at)
        await action(restored, "open", venue=None)
        assert len(calls) == 14
        assert next(iter(restored.residents.values())).inventory.money == money + 2 * 840
    await action(restored, "camera_ready", submission_id=first["id"])
    moment(restored, venue.camera_ready_at + timedelta(seconds=1))
    states = {s["id"]: s for s in (await action(restored, "open", venue=None))["submissions"]}
    assert states[first["id"]]["status"] == "camera_ready"
    assert states[second["id"]]["status"] == "missed_camera_ready"
    assert all(any(first["id"] in p.text for p in r.port.held) for r in restored.residents.values())


@pytest.mark.parametrize("different_venue", [False, True])
async def test_identical_pdf_requires_resolving_active_submission_even_if_renamed(
    lab, different_venue
):
    world, venue, _ = lab
    other = venue.model_copy(update={"id": "other", "title": "Other Conference"})
    world.research.settings = world.research.settings.model_copy(
        update={"conferences": (venue, other)}
    )
    first = await submitted(world)
    target = "other" if different_venue else "test"
    second = await action(world, "register", venue=target, title="Different title", abstract="B")
    (world.research.files / "renamed.pdf").write_bytes(
        (world.research.files / "paper.pdf").read_bytes()
    )
    # Comparison uses the frozen original, even after its working PDF is changed.
    write_pdf(world, "Unsubmitted working revision")
    with pytest.raises(ValueError, match=first["id"]) as error:
        await action(world, "submit", venue=target, submission_id=second["id"], pdf="renamed.pdf")
    assert "withdraw" in str(error.value) and "different paper" in str(error.value)
    record = conferences.ConferenceDesk(world.research)._load()["submissions"][1]
    assert record["status"] == "registered" and "manuscript_record" not in record
    await action(world, "withdraw", submission_id=first["id"])
    moved = await action(
        world, "submit", venue=target, submission_id=second["id"], pdf="renamed.pdf"
    )
    assert moved["status"] == "submitted"


async def test_legacy_duplicate_pdfs_remain_visible_and_independently_actionable(lab):
    world, venue, calls = lab
    first = await submitted(world)
    desk = conferences.ConferenceDesk(world.research)
    state = desk._load()
    duplicate = state["submissions"][0] | {"id": "test-old-copy", "title": "Legacy copy"}
    state["submissions"].append(duplicate)
    desk._save(state, "Historical duplicate submissions")
    checkpoint = world.snapshot()
    restored = World(world.config, world.research.root.parent, NoTasks(), clock=ManualClock())
    restored.restore(checkpoint)
    original = desk.path.read_text()
    listed = (await action(restored, "list"))["state"]["submissions"]
    assert listed[0]["duplicate_pdf_with"] == [duplicate["id"]]
    assert listed[1]["duplicate_pdf_with"] == [first["id"]]
    assert "Historical records remain actionable" in listed[1]["duplicate_pdf_notice"]
    assert desk.path.read_text() == original  # Derived warnings do not rewrite old records.
    assert restored.research.snapshot() == checkpoint["research"]
    moment(restored, venue.reviews_at)
    opened = await action(restored, "open", submission_id=duplicate["id"])
    assert opened["submissions"][0]["duplicate_pdf_with"] == [first["id"]]
    assert len(calls) == 6
    (restored.research.files / "rebuttal.md").write_text("Response for the legacy copy.")
    await action(restored, "rebuttal", submission_id=duplicate["id"])
    await action(restored, "withdraw", submission_id=first["id"])
    remaining = (await action(restored, "open", submission_id=duplicate["id"]))["submissions"][0]
    assert remaining["status"] == "reviewed"
    assert remaining["rebuttal"]["text"] == "Response for the legacy copy."
    assert remaining["duplicate_pdf_with"] == []


async def test_legacy_active_pointer_does_not_block_registration_or_restore_withdrawals(lab):
    world, _, _ = lab
    old = await submitted(world)
    desk = conferences.ConferenceDesk(world.research)
    state = desk._load()
    state["active"] = old["id"]
    state["submissions"].insert(
        0,
        {
            "id": "test-legacy",
            "venue": "test",
            "title": "Withdrawn history",
            "status": "withdrawn",
        },
    )
    desk._save(state, "Legacy checkpoint")
    snapshot = world.snapshot()
    restored = World(world.config, world.research.root.parent, NoTasks(), clock=ManualClock())
    restored.restore(snapshot)
    new = await action(restored, "register", title="Independent new paper", abstract="New")
    assert new["id"] != old["id"]
    state = (await action(restored, "list"))["state"]
    assert "active" not in state and len(state["submissions"]) == 3
    assert state["submissions"][0]["status"] == "withdrawn"
    assert state["submissions"][1]["status"] == "submitted"


def test_parallel_policy_notice_is_gated_once_and_preserves_legacy_guides(lab):
    world, _, _ = lab
    marker = world.research.records / "conference-policy-v2.json"
    assert marker.exists()  # New commissions already explain the current rule.
    world.research.schedule(world, 1)
    assert not any(
        e.get("payload", {}).get("policy") == "parallel_conference_submissions"
        for e in world.log.entries()
    )
    # Reconstruct a historical commission, then resume it using the current policy.
    marker.unlink()
    original = world.research.files / "conferences.md"
    original.write_text("Historical single-submission handbook.\n")
    commission = world.research.records / "commission.json"
    commission.write_text(json.dumps({"brief": "Historical single-submission commission."}))
    world.research.repo.commit("Historical commission", date=datetime.now(UTC))
    world.research.active = False
    world.research.schedule(world, 1)
    assert not marker.exists()
    world.research.active = True
    world.research.schedule(world, 8)
    before = world.snapshot()
    restored = World(world.config, world.research.root.parent, NoTasks(), clock=ManualClock())
    restored.restore(before)
    restored.research.schedule(restored, 8)
    assert original.read_text() == "Historical single-submission handbook.\n"
    assert json.loads(commission.read_text())["brief"] == "Historical single-submission commission."
    assert "Different papers" in (world.research.records / "conferences-v2.md").read_text()
    assert all(
        sum("Conference policy update" in p.text for p in r.port.held) == 1
        for r in restored.residents.values()
    )
    assert all(
        any("not automatically restored" in p.text for p in r.port.held)
        for r in restored.residents.values()
    )


async def test_arr_requires_explicit_commitment_and_never_pays_early(lab):
    world, venue, calls = lab
    venue = venue.model_copy(
        update={
            "submission_kind": "arr_commitment",
            "commitment_at": venue.rebuttal_at + timedelta(days=1),
        }
    )
    world.research.settings = world.research.settings.model_copy(update={"conferences": (venue,)})
    submission = await submitted(world)
    assert submission["next_steps"][0]["action"] == "await_reviews"
    with pytest.raises(ValueError, match="Only reviewed ARR"):
        await action(world, "commit")
    moment(world, venue.reviews_at)
    reviewed = (await action(world, "open"))["submissions"][0]
    assert [s["action"] for s in reviewed["next_steps"]] == ["commit", "rebuttal"]
    assert reviewed["next_steps"][0]["deadline"] == venue.commitment_at.isoformat()
    assert all(any(f"submission_id='{submission['id']}'" in p.text
                   and "a rebuttal does not count as commitment" in p.text
                   for p in r.port.held) for r in world.residents.values())
    before = world.snapshot()
    money = next(iter(world.residents.values())).inventory.money
    moment(world, venue.notification_at)
    missed = (await action(world, "open"))["submissions"][0]
    assert missed["status"] == "missed_commitment" and missed["next_steps"] == []
    assert len(calls) == 3 and next(iter(world.residents.values())).inventory.money == money
    restored = World(world.config, world.research.root.parent, NoTasks(), clock=ManualClock())
    restored.restore(before)
    restored.research.settings = world.research.settings
    moment(restored, venue.commitment_at)
    event_count = len(list(restored.log.entries()))
    resumed = (await action(restored, "open", submission_id=submission["id"]))["submissions"][0]
    assert [s["action"] for s in resumed["next_steps"]] == ["commit"]
    assert len(list(restored.log.entries())) == event_count
    committed = await action(restored, "commit", submission_id=submission["id"])
    assert [s["action"] for s in committed["next_steps"]] == ["await_decision"]
    moment(restored, venue.notification_at)
    assert (await action(restored, "open"))["submissions"][0]["status"] == "accepted"
    assert len(calls) == 7


async def test_review_schema_failure_stops_without_public_review_or_payment(lab, monkeypatch):
    world, venue, calls = lab
    await submitted(world)
    money = next(iter(world.residents.values())).inventory.money
    monkeypatch.setattr(
        conferences,
        "create_client",
        lambda _: ScriptedClient(lambda request: {"malformed": "response"}),
    )
    moment(world, venue.reviews_at)
    with pytest.raises(RuntimeError, match="StructuredOutputError"):
        await action(world, "open")
    state = json.loads((world.research.records / "conferences.json").read_text())
    assert "reviews" not in state["submissions"][0]
    assert next(iter(world.residents.values())).inventory.money == money
    assert list((world.research.root.parent / "conference_reviews").rglob("failure.json"))


async def test_invalid_citations_and_input_overflow_fail_before_publication(lab, monkeypatch):
    world, venue, calls = lab
    entry = await submitted(world)
    desk = conferences.ConferenceDesk(world.research)
    packet = json.loads(world.research._path(entry["manuscript_record"]).read_text())["packet"]
    # A schema-valid meta-review still cannot cite content outside the supplied evidence.
    monkeypatch.setattr(
        conferences,
        "create_client",
        lambda _: ScriptedClient(
            lambda request: {
                "decision": "accept",
                "overall": 7,
                "confidence": 3,
                "rationale": "Unsupported",
                "citations": [{"path": "files/paper.tex", "quote": "An invented quotation"}],
            }
        ),
    )
    with pytest.raises(RuntimeError, match="exact supplied quotation"):
        await desk._judge(entry, venue, "decision", "Meta-reviewer", packet, conferences.Decision)
    oversized = packet | {"documents": {"files/paper.tex": "x" * conferences.REVIEW_CHARACTERS}}
    with pytest.raises(ValueError, match="no evidence was truncated"):
        await desk._judge(
            entry, venue, "initial", conferences.ROLES[0], oversized, conferences.ConferenceReview
        )
    state = desk._load()
    assert state["submissions"][0]["status"] == "submitted"
    assert "decision" not in state["submissions"][0]


async def test_next_year_notification_remains_pending_at_year_end(lab):
    world, venue, calls = lab
    venue = venue.model_copy(
        update={
            "notification_at": datetime(2027, 1, 4, tzinfo=UTC),
            "camera_ready_at": datetime(2027, 1, 31, tzinfo=UTC),
        }
    )
    world.research.settings = world.research.settings.model_copy(update={"conferences": (venue,)})
    await submitted(world)
    money = next(iter(world.residents.values())).inventory.money
    moment(world, datetime(2026, 12, 31, 23, 59, tzinfo=UTC))
    assert (await action(world, "open"))["submissions"][0]["status"] == "reviewed"
    assert len(calls) == 3
    assert next(iter(world.residents.values())).inventory.money == money


async def test_venue_response_limits_and_explicit_revised_manuscript(lab):
    world, venue, calls = lab
    venue = venue.model_copy(update={"response_limit_chars": 500, "allow_response_evidence": False})
    world.research.settings = world.research.settings.model_copy(update={"conferences": (venue,)})
    await submitted(world)
    moment(world, venue.reviews_at)
    await action(world, "open")
    response = world.research.files / "rebuttal.md"
    response.write_text("x" * 501)
    with pytest.raises(ValueError, match="limit is 500"):
        await action(world, "rebuttal")
    response.write_text("A correction.")
    with pytest.raises(ValueError, match="does not allow response evidence"):
        await action(world, "rebuttal", evidence=["paper.tex"])
    with pytest.raises(ValueError, match="does not allow a revised"):
        await action(world, "rebuttal", paper="paper.tex", pdf="paper.pdf")
    await action(world, "rebuttal")
    venue = venue.model_copy(update={"allow_revised_manuscript": True})
    world.research.settings = world.research.settings.model_copy(update={"conferences": (venue,)})
    (world.research.files / "paper.tex").write_text(PAPER.replace("Measured", "Revised measured"))
    await action(world, "rebuttal", paper="paper.tex", pdf="paper.pdf")
    (world.research.files / "paper.tex").write_text(PAPER.replace("Measured", "Later draft"))
    moment(world, venue.notification_at)
    await action(world, "open")
    packet = json.loads(calls[-1].messages[1].content)
    assert packet["documents"]["files/paper.tex"] == PAPER
    assert packet["documents"]["revised/files/paper.tex"] == PAPER.replace(
        "Measured", "Revised measured"
    )
    assert packet["revised_manuscript"]["pdf_sha256"]


async def test_acceptance_probe_runs_seven_call_protocol_without_scientific_credit(
    tmp_path, monkeypatch
):
    from ops.research.check_conference import check

    def reply(request):
        if request.metadata["phase"] == "decision":
            return {
                "decision": "reject",
                "overall": 1,
                "confidence": 5,
                "rationale": "Synthetic infrastructure test only.",
                "citations": [],
            }
        return {
            **{
                name: {"score": 0, "rationale": "No scientific claim.", "citations": []}
                for name in (
                    "technical_quality",
                    "novelty",
                    "significance",
                    "evidence",
                    "reproducibility",
                )
            },
            **{name: [] for name in ("strengths", "weaknesses", "questions", "required_revisions")},
            "overall": 1,
            "confidence": 5,
            "summary": "Infrastructure test only.",
        }

    monkeypatch.setenv("LIGHTING_API_KEY", "test-value")
    monkeypatch.setattr(conferences, "create_client", lambda _: ScriptedClient(reply))
    profile = Path(__file__).resolve().parents[2] / "experiments/configs/ir-lab.yaml"
    receipt = await check(profile, tmp_path / "probe")
    assert receipt["judge_calls"] == 7
    assert receipt["restore_checks"] == 2
    assert receipt["reward_per_resident"] == receipt["duplicate_grants"] == 0
