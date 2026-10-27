"""Exporting a run's residents as they stood at a day's checkpoint, with each resident's commit
and the run's model and runtime settings recorded beside them; an export of the run's present
tags kept, and one of other commits replaced."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent.runtime import RuntimeConfig
from evaluation.exports import MANIFEST, Export
from experiments.export import export_day, main
from infrastructure.config import StrictModel
from infrastructure.git import Repository
from infrastructure.llm import LLMConfig
from infrastructure.storage import RunDirectory, day_tag

LLM = LLMConfig(base_url="${VLLM_BASE_URL}", api_key_env="VLLM_API_KEY", model="qwen")
RUNTIME = RuntimeConfig(reasoning_effort="low")


class Frozen(StrictModel):
    """The sections of a run's configuration that an export records."""

    llm: LLMConfig
    runtime: RuntimeConfig


def make_run(runs: Path, start: str = "You are {name}") -> RunDirectory:
    """Run c of Mei and Tomas with the checkpoints of days 0 and 1, each resident's background
    `start`, then the day; and a day lost to an interruption after them."""
    run = RunDirectory.create(
        runs, "c", config=Frozen(llm=LLM, runtime=RUNTIME), code_revision="abc"
    )
    for name in ("Mei", "Tomas"):
        agent = run.agent_dir(name)
        repository = Repository.init(agent, user_name=name, user_email="x@town.invalid")
        for day in (0, 1):
            (agent / "background.md").write_text(f"{start.format(name=name)}, as of day {day}.\n")
            (agent / "memory").mkdir(exist_ok=True)
            (agent / "memory" / "work.md").write_text("Notes.\n")
            (agent / "skills").mkdir(exist_ok=True)
            (agent / "skills" / "bake.md").write_text("Bake bread.\n")
            (agent / "session.jsonl").write_text("{}\n")
            (agent / "trace.jsonl").write_text("{}\n")
            repository.commit(day_tag(day), date=datetime(2026, 3, 2 + day, tzinfo=UTC))
            repository.tag(day_tag(day))
            run.checkpoint_path(day).write_text("{}\n")
        (agent / "background.md").write_text("A day lost to an interruption.\n")
    return run


def tagged(run: RunDirectory, day: int) -> dict[str, str]:
    """Each resident's commit at the tag of `day`."""
    return {
        name: Repository(run.agent_dir(name)).log(day_tag(day))[0].id for name in ("Mei", "Tomas")
    }


def test_a_day_is_exported_for_every_resident_from_its_tag(tmp_path):
    run = make_run(tmp_path / "runs")
    exports = export_day(run.root, 0, tmp_path / "day-00")
    assert exports == {name: tmp_path / "day-00" / name for name in ("Mei", "Tomas")}
    assert (exports["Mei"] / "background.md").read_text() == "You are Mei, as of day 0.\n"
    assert not (exports["Mei"] / ".git").exists()
    for path in exports.values():
        assert not (path / "session.jsonl").exists() and not (path / "trace.jsonl").exists()
        assert (path / "memory" / "work.md").is_file() and (path / "skills" / "bake.md").is_file()
    export = Export.of(exports["Mei"])
    assert export == Export(
        run=str(run.root.resolve()), day=0, commits=tagged(run, 0), llm=LLM, runtime=RUNTIME
    )
    assert export.commit(exports["Tomas"]) == tagged(run, 0)["Tomas"] != tagged(run, 1)["Tomas"]
    with pytest.raises(ValueError, match="no checkpoint of day 2"):
        export_day(run.root, 2, tmp_path / "day-02")
    with pytest.raises(FileExistsError):
        export_day(run.root, 0, tmp_path / "day-00")
    shutil.copytree(exports["Mei"], tmp_path / "elsewhere" / "Mei")
    with pytest.raises(FileNotFoundError, match="is in no export"):
        Export.of(tmp_path / "elsewhere" / "Mei")
    shutil.copytree(exports["Mei"], tmp_path / "day-00" / "Kofi")
    with pytest.raises(ValueError, match="lists no resident Kofi"):
        Export.of(tmp_path / "day-00" / "Kofi")


def test_the_command_keeps_an_export_of_the_present_tags_and_replaces_another(tmp_path, capsys):
    run, out = make_run(tmp_path / "runs"), tmp_path / "exports" / "day-00"
    command = [str(run.root), "--day", "0", "--out", str(out)]
    main(command)
    first = (out / MANIFEST).read_text()
    (out / "Mei" / "note.md").write_text("kept\n")
    capsys.readouterr()
    main(command)
    assert capsys.readouterr().out == f"{out} holds this export already\n"
    assert (out / "Mei" / "note.md").is_file() and (out / MANIFEST).read_text() == first

    # The run created again under the same name: its tags are other commits.
    shutil.rmtree(run.root)
    run = make_run(tmp_path / "runs", start="You are {name} again")
    main(command)
    assert "held an export of other commits or settings" in capsys.readouterr().out
    assert Export.of(out / "Mei").commits == tagged(run, 0)
    assert (out / "Mei" / "background.md").read_text() == "You are Mei again, as of day 0.\n"
    assert not (out / "Mei" / "note.md").exists()

    (tmp_path / "plain" / "Mei").mkdir(parents=True)
    with pytest.raises(SystemExit):
        main([str(run.root), "--day", "0", "--out", str(tmp_path / "plain")])
    assert "holds no export.json: it is no export to replace" in capsys.readouterr().err
    assert (tmp_path / "plain" / "Mei").is_dir()
