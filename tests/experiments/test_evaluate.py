import json

import pytest
import yaml

import experiments.evaluate as cli
from evaluation import DEFAULT_CONFIG, FAMILIES, AgentResult, EvaluationConfig
from experiments.run import main as run_experiment
from infrastructure.config import load_config
from infrastructure.llm import ScriptedClient
from infrastructure.storage import RunDirectory, read_jsonl
from tests.evaluation.conftest import SMOKE, build_banks, write_work

CITY = SMOKE.with_name("city.yaml")


def _outside_evaluation(run: RunDirectory) -> dict[str, bytes]:
    return {
        str(path.relative_to(run.root)): path.read_bytes()
        for path in sorted(run.root.rglob("*"))
        if path.is_file() and run.evaluation_dir not in path.parents
    }


def test_evaluating_a_dry_run_prints_its_cost_and_scores_and_changes_nothing_else(
    tmp_path, monkeypatch, capsys
):
    run_experiment([str(SMOKE), "--seeds", "1", "--runs-root", str(tmp_path), "--dry-run"])
    run = RunDirectory.open(tmp_path / "smoke-dry-run" / "seed-0001")
    agents = sorted(path.name for path in run.agents_dir.iterdir())
    default = load_config(DEFAULT_CONFIG, EvaluationConfig).model_dump(mode="json")
    config = tmp_path / "evaluation.yaml"
    judge = {**default["judge"], "backend": "scripted"}
    bank = build_banks(tmp_path / "banks")
    work = write_work(tmp_path / "work.yaml")
    changes = {"judge": judge, "bank": str(bank), "work": str(work)}
    config.write_text(yaml.safe_dump({**default, **changes}), encoding="utf-8")

    # The CLI builds only the judge itself, and no code supplies a scripted judge's responder.
    judge_reply = {"evidence": [], "answer": False}
    monkeypatch.setattr(cli, "create_client", lambda llm: ScriptedClient(lambda r: judge_reply))
    before = _outside_evaluation(run)
    command = [str(run.root), "--days", "0", "3", "--config", str(config), "--levels", "2"]
    command += ["--repetitions", "1"]
    command += ["--traits", "cooperation", "honesty"]
    capsys.readouterr()

    cli.main(command)
    cost, header, *rows = capsys.readouterr().out.splitlines()
    chosen = [
        name for name, family in FAMILIES.items() if family.trait in ("cooperation", "honesty")
    ]
    scenes = len(agents) * 2 * len(chosen)
    assert cost.startswith(f"{scenes} scenes: between ")
    assert header.split() == [
        "agent",
        "day",
        "variant",
        "trait",
        "family",
        "score",
        "curve",
        "switch",
    ]
    assert len(rows) == scenes
    assert {row.split()[4] for row in rows} == set(chosen)
    results = [run.evaluation_path(f"day-{day:04d}", agent) for day in (0, 3) for agent in agents]
    assert all(path.exists() for path in results)
    purposes = {record["metadata"]["purpose"] for record in read_jsonl(run.evaluation_calls_path)}
    assert "act" in purposes and purposes <= {"act", "judge"}
    assert _outside_evaluation(run) == before

    written = [path.read_bytes() for path in results]
    with pytest.raises(FileExistsError):
        cli.main(command)
    assert [path.read_bytes() for path in results] == written
    cli.main([*command, "--overwrite"])
    assert _outside_evaluation(run) == before


def test_a_city_whose_residents_bear_strangers_names_is_evaluated_with_other_strangers(
    tmp_path, monkeypatch, capsys
):
    """The city's residents include Ines and Lena, names the probes give strangers; its dry run
    is evaluated, and a payer who would be Lena is someone else."""
    days = ["--dry-run", "--until-day", "1"]
    run_experiment([str(CITY), "--seeds", "1", "--runs-root", str(tmp_path), *days])
    run = RunDirectory.open(tmp_path / "city-dry-run" / "seed-0001")
    agents = sorted(path.name for path in run.agents_dir.iterdir())
    assert {"Ines", "Lena"} <= set(agents)
    for family in FAMILIES.values():
        for surface in range(family.surfaces):
            assert not set(family.cast(surface, agents)) & set(agents)
    default = load_config(DEFAULT_CONFIG, EvaluationConfig).model_dump(mode="json")
    config = tmp_path / "evaluation.yaml"
    judge = {**default["judge"], "backend": "scripted"}
    work = write_work(tmp_path / "work.yaml")
    changes = {"judge": judge, "bank": str(build_banks(tmp_path / "banks")), "work": str(work)}
    config.write_text(yaml.safe_dump({**default, **changes}), encoding="utf-8")
    judge_reply = {"evidence": [], "answer": False}
    monkeypatch.setattr(cli, "create_client", lambda llm: ScriptedClient(lambda r: judge_reply))

    command = [str(run.root), "--days", "0", "--config", str(config), "--levels", "1"]
    cli.main([*command, "--families", "misdirected_payment"])
    payer, other = FAMILIES["misdirected_payment"].cast(2, agents)
    assert other == "Kim" and payer not in ("Lena", *agents)
    for agent in agents:
        result = AgentResult.model_validate_json(
            run.evaluation_path("day-0000", agent).read_text(encoding="utf-8")
        )
        [lena] = [o for o in result.probes["misdirected_payment"].repetitions if o.surface == 2]
        told = json.dumps(lena.transcript)
        assert f"I'm {payer}." in told and "I'm Lena" not in told
