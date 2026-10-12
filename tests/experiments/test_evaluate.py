import pytest
import yaml

import experiments.evaluate as cli
from evaluation import DEFAULT_CONFIG, FAMILIES, EvaluationConfig
from experiments.run import main as run_experiment
from infrastructure.config import load_config
from infrastructure.llm import ScriptedClient
from infrastructure.storage import RunDirectory, read_jsonl
from tests.evaluation.conftest import ANCHOR, SMOKE, build_banks, write_work


def _outside_evaluation(run: RunDirectory) -> dict[str, bytes]:
    return {
        str(path.relative_to(run.root)): path.read_bytes()
        for path in sorted(run.root.rglob("*"))
        if path.is_file() and run.evaluation_dir not in path.parents
    }


def test_evaluating_a_dry_run_prints_its_cost_and_scores_and_changes_nothing_else(
    tmp_path, monkeypatch, capsys
):
    town = yaml.safe_load(SMOKE.read_text(encoding="utf-8"))
    town["environment"]["places"].append(ANCHOR)
    experiment = tmp_path / "town.yaml"
    experiment.write_text(yaml.safe_dump(town), encoding="utf-8")
    run_experiment([str(experiment), "--seeds", "1", "--runs-root", str(tmp_path), "--dry-run"])
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
