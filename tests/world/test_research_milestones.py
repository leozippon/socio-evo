"""Collective reviews, real checkpoint restoration and failure-before-payment behavior."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent.directory import AgentDirectory
from experiments.config import load_experiment
from infrastructure.llm import ScriptedClient, StructuredOutputError
from simulation.run import run
from world import research_milestones
from world.clock import ManualClock
from world.config import ResearchSettings
from world.research import NoTasks, milestone_terms
from world.world import World

CONFIG = Path(__file__).resolve().parents[2] / "experiments/configs/research.yaml"
PROPOSAL = "A falsifiable question with a controlled comparison."


def review_reply(scores=(4, 3, 2, 1)):
    return {
        **{
            name: {
                "score": score,
                "rationale": "Supported at this stage, with stated gaps.",
                "citations": [{"path": "files/proposal.md", "quote": "A falsifiable question"}],
            }
            for name, score in zip(research_milestones.DIMENSIONS, scores, strict=True)
        },
        "summary": "A feasible proposal, with remaining literature and procedure gaps.",
    }


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    config = load_experiment(CONFIG)
    settings = ResearchSettings(
        judge={
            "base_url": "https://judge.invalid/v1",
            "api_key_env": "JUDGE_KEY",
            "model": "judge",
        },
        milestones=[
            {"id": "proposal", "day": 7, "artifact": "proposal.md", "max_reward_per_resident": 100}
        ],
    )
    config = config.model_copy(
        update={"town": config.town.model_copy(update={"research": settings})}
    )
    for resident in config.residents:
        AgentDirectory.create(
            tmp_path / "agents" / resident.name, background=resident.background_path.read_text()
        )
    world = World(config.town, tmp_path, NoTasks(), clock=ManualClock())
    world.research.initialize(world)
    (world.research.files / "proposal.md").write_text(PROPOSAL)
    world.research.repo.commit("Save proposal", date=datetime.now(UTC))
    calls = []
    client = ScriptedClient(lambda request: calls.append(request) or review_reply())
    monkeypatch.setattr(research_milestones, "create_client", lambda _: client)
    return config, world, calls


async def test_collective_score_grant_checkpoint_resume_and_review_cache(prepared):
    config, world, calls = prepared
    before = world.snapshot()
    starting = {name: r.inventory.money for name, r in world.residents.items()}
    await world.research.review(world, 6)
    assert calls == []
    await world.research.review(world, 7)
    paid = world.snapshot()
    for name, resident in world.residents.items():
        assert resident.inventory.money == starting[name] + 62
    record = json.loads((world.research.records / "milestone-proposal.json").read_text())
    assert record["score"] == 62.5
    assert record["reward_total"] == 62 * 8
    assert record["judge_model"] == "judge"
    assert len(calls) == 1
    for state in (paid, before):
        restored = World(config.town, world.research.root.parent, NoTasks(), clock=ManualClock())
        restored.restore(state)
        await restored.research.review(restored, 7)
        for name, resident in restored.snapshot()["residents"].items():
            assert resident["inventory"] == paid["residents"][name]["inventory"]
            assert sum(p["kind"] == "research_milestone" for p in resident["held"]) == 1
    assert len(calls) == 1  # Replaying before payment reuses the exact successful review.
    audit = world.research.root.parent / record["audit"]
    assert (
        json.loads((audit / "input.json").read_text())["packet"]["documents"]["files/proposal.md"]
        == PROPOSAL
    )
    attempt = json.loads((audit / "attempts.jsonl").read_text())
    assert attempt["response"]["text"]
    assert "replica" not in attempt["request"] or attempt["request"]["replica"] is None


async def test_missing_deliverable_is_zero_without_calling_judge(prepared):
    _, world, calls = prepared
    (world.research.files / "proposal.md").unlink()
    world.research.repo.commit("No proposal submitted", date=datetime.now(UTC))
    before = {name: r.inventory.money for name, r in world.residents.items()}
    await world.research.review(world, 7)
    assert calls == []
    assert {name: r.inventory.money for name, r in world.residents.items()} == before
    record = json.loads((world.research.records / "milestone-proposal.json").read_text())
    assert record["status"] == "missing_deliverable" and record["reward_total"] == 0


async def test_checkpoint_holds_clock_and_saves_grant_before_handover(prepared, monkeypatch):
    _, world, _ = prepared
    saved = []

    def respond(request):
        assert world.clock.held
        assert world._all_resting()
        return review_reply()

    async def checkpoint(day, state):
        assert world.clock.held
        saved.append(state)

    monkeypatch.setattr(research_milestones, "create_client", lambda _: ScriptedClient(respond))
    world._on_checkpoint, world._until = checkpoint, 7
    waiters = [asyncio.create_task(r.port.wait()) for r in world.residents.values()]
    try:
        await asyncio.sleep(0)
        await world._checkpoint(7)
        assert saved[0]["research"] == world.research.repo.head()
        for resident in saved[0]["residents"].values():
            assert ["received", 62, "research grant proposal"] in resident["inventory"]["moves"]
    finally:
        for task in waiters:
            task.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)


@pytest.mark.parametrize("fault", ["malformed", "ungrounded", "transport"])
async def test_failed_judge_keeps_purses_unchanged_and_retains_audit(prepared, monkeypatch, fault):
    _, world, _ = prepared
    before = world.snapshot()

    def respond(request):
        if fault == "transport":
            raise RuntimeError("judge service failed")
        if fault == "malformed":
            return "not JSON"
        result = review_reply()
        result["evidence"]["citations"][0]["quote"] = "invented evidence"
        return result

    monkeypatch.setattr(research_milestones, "create_client", lambda _: ScriptedClient(respond))
    with pytest.raises((StructuredOutputError, ValueError, RuntimeError)):
        await world.research.review(world, 7)
    assert world.snapshot() == before
    assert not (world.research.records / "milestone-proposal.json").exists()
    assert list((world.research.root.parent / "research_reviews").rglob("failure.json"))
    assert list((world.research.root.parent / "research_reviews").rglob("attempts.jsonl"))


def test_dossier_redacts_authors_and_declares_omissions(prepared):
    _, world, _ = prepared
    research = world.research
    (research.files / "notes.md").write_text("Mei and Aisha examined a negative result.")
    (research.files / "large.txt").write_text("x" * research_milestones.INPUT_CHARACTERS)
    (research.records / "operation.json").write_text(
        json.dumps(
            {
                "actor": "Mei",
                "sim_time": 500,
                "real_time": "today",
                "tool": "shell",
                "arguments": {"command": "python study.py"},
                "result": {"returncode": 0},
            }
        )
    )
    packet = research_milestones.dossier(
        research, research.settings.milestones[0], list(world.residents)
    )
    assert (
        packet["documents"]["files/notes.md"] == "[author] and [author] examined a negative result."
    )
    evidence = json.loads(packet["documents"]["records/operation.json"])
    assert set(evidence) == {"tool", "arguments", "result"}
    assert next(row for row in packet["manifest"] if row["path"] == "files/large.txt")["omitted"]
    assert "28" not in milestone_terms(research.settings)


def test_dossier_preserves_recent_execution_and_code_before_large_support(prepared, monkeypatch):
    _, world, _ = prepared
    research = world.research
    monkeypatch.setattr(research_milestones, "INPUT_CHARACTERS", 6_000)
    (research.files / "a-library.txt").write_text("x" * 5_900)
    (research.files / "train.py").write_text("print('validation accuracy:', 0.75)")
    for filename, time in (("a-old.json", 1), ("z-new.json", 2)):
        (research.records / filename).write_text(
            json.dumps(
                {
                    "tool": "shell",
                    "sim_time": time,
                    "arguments": {"command": "python train.py"},
                    "result": {"returncode": 0, "stdout": str(time) + "x" * 2_500},
                }
            )
        )
    packet = research_milestones.dossier(research, research.settings.milestones[0], [])
    assert "records/z-new.json" in packet["documents"]
    assert "records/a-old.json" not in packet["documents"]
    assert "files/train.py" in packet["documents"]
    assert "files/a-library.txt" not in packet["documents"]
    assert len(json.dumps(packet, ensure_ascii=False)) <= 6_000


def test_dossier_bounds_manifest_and_reports_unlisted_omissions(prepared, monkeypatch):
    _, world, _ = prepared
    research = world.research
    monkeypatch.setattr(research_milestones, "INPUT_CHARACTERS", 2_000)
    for index in range(80):
        (research.files / f"checkpoint-{index:03}.bin").write_bytes(b"\xff\x00")
    packet = research_milestones.dossier(research, research.settings.milestones[0], [])
    assert len(json.dumps(packet, ensure_ascii=False)) <= 2_000
    coverage = packet["coverage"]
    assert coverage["total_files"] == coverage["supplied_files"] + coverage["omitted_files"]
    assert coverage["unlisted_omitted_files"] > 0
    assert len(packet["manifest"]) + coverage["unlisted_omitted_files"] == coverage["total_files"]
    assert packet["documents"]["files/proposal.md"] == PROPOSAL


def test_dossier_counts_json_escaping_and_never_truncates_primary(prepared, monkeypatch):
    _, world, _ = prepared
    monkeypatch.setattr(research_milestones, "INPUT_CHARACTERS", 1_000)
    (world.research.files / "proposal.md").write_text('"' * 800)
    with pytest.raises(ValueError, match="complete milestone artifact exceeds"):
        research_milestones.dossier(world.research, world.research.settings.milestones[0], [])


async def test_same_model_judge_and_missing_credentials_fail_before_run_creation(
    prepared, tmp_path
):
    config, _, _ = prepared
    settings = config.town.research
    same = settings.model_copy(
        update={"judge": settings.judge.model_copy(update={"model": config.llm.model})}
    )
    with pytest.raises(ValueError, match="must differ"):
        await run(
            config.model_copy(update={"town": config.town.model_copy(update={"research": same})}),
            tmp_path,
        )
    with pytest.raises(ValueError, match="JUDGE_KEY"):
        await run(config, tmp_path)
    assert not (tmp_path / config.name).exists()


PAPER = r"""\documentclass{article}
\begin{document}
A controlled study of model generalisation.
\input{results}
\end{document}
"""


def conference_reply(overall=7):
    citation = {"path": "files/results.tex", "quote": "A negative result under fixed controls."}
    return {
        **{
            name: {
                "score": 3,
                "rationale": "A useful controlled study, with bounded claims.",
                "citations": [citation.copy()],
            }
            for name in research_milestones.CONFERENCE_DIMENSIONS
        },
        "summary": "A controlled empirical study reports a negative result.",
        "strengths": [
            {"text": "The reported comparison has fixed controls.", "citations": [citation.copy()]}
        ],
        "weaknesses": [{"text": "No environment specification was supplied.", "citations": []}],
        "questions": [
            {"text": "Which dependency versions generated these results?", "citations": []}
        ],
        "required_revisions": [
            {
                "text": "Save dependency versions and a command to regenerate the comparison.",
                "citations": [],
            }
        ],
        "overall": overall,
        "confidence": 3,
    }


@pytest.fixture
def conference(prepared, monkeypatch):
    _, world, _ = prepared
    stage = world.research.settings.milestones[0].model_copy(
        update={"id": "paper", "day": 21, "artifact": "paper.tex"}
    )
    world.research.settings = world.research.settings.model_copy(
        update={
            "review_style": "conference",
            "domain": "artificial intelligence",
            "milestones": (stage,),
        }
    )
    (world.research.files / "paper.tex").write_text(PAPER)
    (world.research.files / "results.tex").write_text("A negative result under fixed controls.")
    world.research.repo.commit("Save LaTeX manuscript", date=datetime.now(UTC))
    calls = []
    monkeypatch.setattr(
        research_milestones,
        "create_client",
        lambda _: ScriptedClient(lambda request: calls.append(request) or conference_reply()),
    )
    return world, stage, calls


async def test_conference_review_archives_tex_feedback_and_reuses_exact_review(conference):
    world, stage, calls = conference
    research = world.research
    result = await research_milestones.evaluate(research, stage, list(world.residents))
    assert await research_milestones.evaluate(research, stage, list(world.residents)) == result
    assert len(calls) == 1
    assert result["score"] == pytest.approx(200 / 3)
    assert result["review"] == {**conference_reply(), "recommendation": "accept"}
    audit = research.root.parent / result["audit"]
    archived = json.loads((audit / "input.json").read_text())
    assert archived["packet"]["documents"]["files/paper.tex"] == PAPER
    assert "compiled LaTeX" in archived["rubric"]
    assert "research in artificial intelligence" in archived["rubric"]
    assert "technical quality" in archived["rubric"]
    assert archived["rubric"] == calls[0].messages[0].content
    assert json.loads((audit / "attempts.jsonl").read_text())["response"]["text"]
    before = {name: r.inventory.money for name, r in world.residents.items()}
    await research.review(world, 21)
    assert len(calls) == 1
    record = json.loads((research.records / "milestone-paper.json").read_text())
    assert record["review"]["required_revisions"] == conference_reply()["required_revisions"]
    assert record["review"]["overall"] == 7 and record["review"]["confidence"] == 3
    assert {name: r.inventory.money for name, r in world.residents.items()} == {
        name: amount + 66 for name, amount in before.items()
    }


async def test_review_style_changes_cache_even_for_identical_tex(conference, monkeypatch):
    world, stage, calls = conference
    research = world.research
    initial = await research_milestones.evaluate(research, stage, [])
    research.settings = research.settings.model_copy(update={"review_style": "standard"})
    legacy = review_reply()
    for key in research_milestones.DIMENSIONS:
        legacy[key]["citations"] = [{"path": "files/paper.tex", "quote": "A controlled study"}]
    monkeypatch.setattr(
        research_milestones,
        "create_client",
        lambda _: ScriptedClient(lambda request: calls.append(request) or legacy),
    )
    standard = await research_milestones.evaluate(research, stage, [])
    assert initial["revision"] == standard["revision"]
    assert initial["audit"] != standard["audit"] and len(calls) == 2
    assert standard["review"] == legacy and standard["score"] == 62.5


@pytest.mark.parametrize(
    "fault", ["rating", "confidence", "dimension", "strength", "revision", "overall"]
)
async def test_conference_invalid_judgment_fails_without_payment(conference, monkeypatch, fault):
    world, stage, _ = conference
    before = world.snapshot()
    reply = conference_reply()
    if fault == "rating":
        reply["overall"] = 11
    elif fault == "confidence":
        reply["confidence"] = True
    elif fault == "dimension":
        reply["novelty"]["citations"] = []
    elif fault == "strength":
        reply["strengths"][0]["citations"] = []
    elif fault == "overall":
        for name in research_milestones.CONFERENCE_DIMENSIONS:
            reply[name].update(score=0, citations=[])
        reply["strengths"] = []
    else:
        reply["required_revisions"][0]["citations"] = [
            {"path": "files/paper.tex", "quote": "Invented"}
        ]
    monkeypatch.setattr(
        research_milestones, "create_client", lambda _: ScriptedClient(lambda _: reply)
    )
    with pytest.raises((StructuredOutputError, ValueError)):
        await world.research.review(world, stage.day)
    assert world.snapshot() == before
    assert not (world.research.records / "milestone-paper.json").exists()
    assert list((world.research.root.parent / "research_reviews").rglob("failure.json"))


@pytest.mark.parametrize("field", ["strengths", "weaknesses", "questions", "required_revisions"])
def test_all_conference_feedback_citations_are_checked(field):
    reply = conference_reply()
    reply[field][0]["citations"] = [{"path": "files/missing.tex", "quote": "Unsupported"}]
    review = research_milestones.ConferenceReview.model_validate(reply)
    with pytest.raises(ValueError, match="citation is not an exact supplied quotation"):
        review.grounded_in({"files/results.tex": "A negative result under fixed controls."})


@pytest.mark.parametrize(
    "text, status",
    [
        ("  \n", "missing_deliverable"),
        ("% comments only", "invalid_deliverable"),
        (r"\documentclass{article}", "invalid_deliverable"),
        (r"\begin{document}Unfinished manuscript", "invalid_deliverable"),
        ("\\begin{document}\n% No scientific content\n\\end{document}", "invalid_deliverable"),
    ],
)
async def test_empty_or_invalid_tex_gives_explicit_zero_without_judge(conference, text, status):
    world, stage, calls = conference
    (world.research.files / "paper.tex").write_text(text)
    world.research.repo.commit("Save empty manuscript", date=datetime.now(UTC))
    before = {name: r.inventory.money for name, r in world.residents.items()}
    await world.research.review(world, stage.day)
    record = json.loads((world.research.records / "milestone-paper.json").read_text())
    assert record["status"] == status and record["score"] == 0
    assert record["summary"] and record["review"] is None
    assert calls == []
    assert {name: r.inventory.money for name, r in world.residents.items()} == before


def test_conference_rating_scale_and_acceptance_boundary():
    for rating, score, recommendation in (
        (1, 0, "reject"),
        (5, 400 / 9, "reject"),
        (6, 500 / 9, "accept"),
        (10, 100, "accept"),
    ):
        review = research_milestones.ConferenceReview.model_validate(conference_reply(rating))
        assert review.score == pytest.approx(score)
        assert review.recommendation == recommendation
