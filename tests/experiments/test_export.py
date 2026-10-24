"""Exporting a run's residents as they stood at a day's checkpoint."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from experiments.export import export_day
from infrastructure.config import StrictModel
from infrastructure.git import Repository
from infrastructure.storage import RunDirectory, day_tag


class Nothing(StrictModel):
    pass


def test_a_day_is_exported_for_every_resident_from_its_tag(tmp_path):
    run = RunDirectory.create(tmp_path / "runs", "c", config=Nothing(), code_revision="abc")
    for name in ("Mei", "Tomas"):
        agent = run.agent_dir(name)
        repository = Repository.init(agent, user_name=name, user_email="x@town.invalid")
        for day in (0, 1):
            (agent / "background.md").write_text(f"You are {name}, as of day {day}.\n")
            repository.commit(day_tag(day), date=datetime(2026, 3, 2 + day, tzinfo=UTC))
            repository.tag(day_tag(day))
            run.checkpoint_path(day).write_text("{}\n")
        (agent / "background.md").write_text("A day lost to an interruption.\n")

    exports = export_day(run.root, 0, tmp_path / "day-00")
    assert exports == {name: tmp_path / "day-00" / name for name in ("Mei", "Tomas")}
    assert (exports["Mei"] / "background.md").read_text() == "You are Mei, as of day 0.\n"
    assert not (exports["Mei"] / ".git").exists()
    with pytest.raises(ValueError, match="no checkpoint of day 2"):
        export_day(run.root, 2, tmp_path / "day-02")
    with pytest.raises(FileExistsError):
        export_day(run.root, 0, tmp_path / "day-00")
