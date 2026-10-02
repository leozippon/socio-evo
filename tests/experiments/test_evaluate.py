from pathlib import Path

import pytest
import yaml

import experiments.evaluate as cli
from evaluation import DEFAULT_CONFIG, PROBES, EvaluationConfig
from experiments.run import main as run_experiment
from infrastructure.config import load_config
from infrastructure.llm import ScriptedClient
from infrastructure.storage import RunDirectory, read_jsonl

SMOKE = Path(__file__).parents[2] / "experiments" / "configs" / "smoke.yaml"


def _outside_evaluation(run: RunDirectory) -> dict[str, bytes]:
    return {
        str(path.relative_to(run.root)): path.read_bytes()
        for path in sorted(run.root.rglob("*"))
        if path.is_file() and run.evaluation_dir not in path.parents
    }


def test_evaluating_a_dry_run_writes_and_prints_scores_and_changes_nothing_else(
    tmp_path, monkeypatch, capsys
):
    run_experiment([str(SMOKE), "--seeds", "1", "--runs-root", str(tmp_path), "--dry-run"])
    run = RunDirectory.open(tmp_path / "smoke-dry-run" / "seed-0001")
    agents = sorted(path.name for path in run.agents_dir.iterdir())
    default = load_config(DEFAULT_CONFIG, EvaluationConfig).model_dump(mode="json")
    config = tmp_path / "evaluation.yaml"
    judge = {**default["judge"], "backend": "scripted"}
    config.write_text(yaml.safe_dump({**default, "judge": judge, "repetitions": 1}))

    real_create_client = cli.create_client

    def create_client(llm, responder=None):
        """The real factory, except for the judge, which no code supplies a responder for."""
        if llm.backend == "scripted" and responder is None:
            return ScriptedClient(lambda request: {"evidence": [], "answer": False})
        return real_create_client(llm, responder)

    monkeypatch.setattr(cli, "create_client", create_client)
    before = _outside_evaluation(run)
    command = [str(run.root), "--days", "0", "3", "--config", str(config)]
    capsys.readouterr()

    cli.main(command)
    header, *rows = capsys.readouterr().out.splitlines()
    assert header.split() == ["agent", "day", "dimension", "probe", "score"]
    assert len(rows) == len(agents) * 2 * len(PROBES)
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
