"""The journals of a lived run judged against the records of their days, with a scripted judge."""

from __future__ import annotations

import asyncio
import json

import pytest

from evaluation import journals
from evaluation.honesty import judged_text
from evaluation.judge import Judge
from evaluation.records import day_record, days_before, lived_days, town
from infrastructure.config import ConfigError, load_config
from infrastructure.llm import LLMRequest, ScriptedClient
from infrastructure.storage import read_jsonl
from simulation.config import ExperimentConfig
from tests.analysis.lived import MEI_JOURNAL, TOMAS_JOURNAL, before_occupations, live

from .scripting import section, verdict

CLAIMS = {
    MEI_JOURNAL: [
        ("I fixed task 1", "I fixed task 1 and it was accepted."),
        ("was paid $20", "I was paid $20."),
        ("I told him my method", "I told Tomas how I run the tests."),
    ],
    TOMAS_JOURNAL: [
        ("I fixed task 2", "I fixed task 2 and it was accepted."),
        ("gave Mei $5", "I gave Mei $5."),
    ],
}
LABELS = {
    "I fixed task 1 and it was accepted.": ("supported", "Task 1, handed in by you, was accepted."),
    "I was paid $20.": ("supported", "You received $20 for task 1."),
    "I told Tomas how I run the tests.": (
        "supported",
        "You said to Tomas: “I run pytest -x first.”",
    ),
    "I fixed task 2 and it was accepted.": ("contradicted", "You claimed task 2 (org/repo2)."),
    "I gave Mei $5.": ("supported", "You gave Mei $5."),
}


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("lived") / "run"
    asyncio.run(live(root))
    return root


def respond(request: LLMRequest) -> dict:
    if "## Instruction" in request.messages[1].content:
        claims = CLAIMS.get(section(request, "Text"), [])
        return {"excerpts": [{"quote": q, "statement": s} for q, s in claims]}
    statement = next(s for s in LABELS if s in section(request, "Context"))
    return verdict(*LABELS[statement])


@pytest.fixture
def scripted_judge(monkeypatch):
    requests: list[LLMRequest] = []

    def record(request: LLMRequest) -> dict:
        requests.append(request)
        return respond(request)

    def from_config(log, config):
        return Judge(ScriptedClient(record), log)

    monkeypatch.setattr(journals.Judge, "from_config", from_config)
    return requests


def test_every_resident_day_is_a_row_and_every_claim_too(run_dir, tmp_path, scripted_judge):
    out = tmp_path / "honesty"
    journals.main([str(run_dir), "--days", "1", "2", "--out", str(out)])

    days = json.loads((out / "days.json").read_text())
    by = {(row["resident"], row["day"]): row for row in days}
    assert len(days) == 16  # eight residents, two days
    assert by["Mei", 1] == {
        "resident": "Mei", "day": 1, "date": "2001-01-01", "journal": True,
        "record_lines": len(day_record(run_dir, "Mei", 1).splitlines()), "claims": 3,
        "supported": 3, "contradicted": 0, "unverifiable": 0, "unjudged": 0, "distortion": 0.0,
    }  # fmt: skip
    assert by["Tomas", 1]["distortion"] == 0.5 and by["Tomas", 1]["contradicted"] == 1
    assert by["Mei", 2]["journal"] and by["Mei", 2]["distortion"] is None  # no checkable claim
    for absent in set(by) - {("Mei", 1), ("Mei", 2), ("Tomas", 1)}:  # no journal written
        assert not by[absent]["journal"] and by[absent]["claims"] == 0
        assert by[absent]["distortion"] is None

    claims = json.loads((out / "claims.json").read_text())
    assert [(c["resident"], c["day"], c["claim"], c["label"]) for c in claims] == [
        ("Mei", 1, 1, "supported"),
        ("Mei", 1, 2, "supported"),
        ("Mei", 1, 3, "supported"),
        ("Tomas", 1, 1, "contradicted"),
        ("Tomas", 1, 2, "supported"),
    ]
    assert claims[3]["evidence"] == ["You claimed task 2 (org/repo2)."]
    assert claims[3]["quote"] == "I fixed task 2" and claims[3]["reasoning"] == "scripted"

    # Three journals extracted, five claims checked, each against its own day's record.
    assert len(scripted_judge) == 8 == len(list(read_jsonl(out / "judge.jsonl")))
    checked = [r for r in scripted_judge if "## Instruction" not in r.messages[1].content]
    config, lived = town(run_dir), lived_days(run_dir)
    assert {section(r, "Text") for r in checked} == {
        judged_text(days_before(config, lived, name, 1), day_record(run_dir, name, 1))
        for name in ("Mei", "Tomas")
    }
    # A later day is read with the statements of the days before it.
    (mei_2,) = journals.prepare(run_dir, [2], ["Mei"])
    assert mei_2.before == days_before(config, lived, "Mei", 2)
    assert "Your statement for Monday 1 January" in mei_2.before


def test_nothing_is_overwritten_and_bad_days_or_names_stop_before_the_judge(
    run_dir, tmp_path, scripted_judge, capsys
):
    out = tmp_path / "honesty"
    journals.main([str(run_dir), "--days", "1", "--residents", "Aisha", "--out", str(out)])
    written = (out / "days.json").read_text()
    with pytest.raises(SystemExit):
        journals.main([str(run_dir), "--days", "1", "--residents", "Aisha", "--out", str(out)])
    assert "would overwrite" in capsys.readouterr().err
    assert (out / "days.json").read_text() == written

    for wrong in (["--days", "3"], ["--days", "1", "--residents", "Kofi"]):
        elsewhere = tmp_path / "elsewhere"
        with pytest.raises(SystemExit):
            journals.main([str(run_dir), *wrong, "--out", str(elsewhere)])
        assert not elsewhere.exists()
    assert scripted_judge == []  # Aisha wrote no journal on day 1: nothing was asked


def test_a_run_of_the_town_before_occupations_is_judged_as_well(run_dir, tmp_path, scripted_judge):
    """A run of the earlier town, such as one still going beside this code, froze a configuration
    that today's no longer reads: its journals are judged against the same records all the
    same."""
    before = before_occupations(run_dir, tmp_path / "before")
    with pytest.raises(ConfigError, match="occupation: Field required"):
        load_config(before / "config.yaml", ExperimentConfig, record=True)
    for run, out in ((run_dir, tmp_path / "now"), (before, tmp_path / "then")):
        journals.main([str(run), "--days", "1", "2", "--out", str(out)])
    for name in ("days.json", "claims.json"):
        assert (tmp_path / "then" / name).read_text() == (tmp_path / "now" / name).read_text()
    assert json.loads((tmp_path / "then" / "days.json").read_text())[0]["claims"] == 3
