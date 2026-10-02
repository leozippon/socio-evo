from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from infrastructure.config import StrictModel, load_config
from infrastructure.storage import RunDirectory, RunStatus, append_jsonl, read_jsonl


class Settings(StrictModel):
    agents: int
    note: str


def _create(tmp_path) -> RunDirectory:
    return RunDirectory.create(
        tmp_path / "runs",
        "baseline",
        7,
        config=Settings(agents=3, note="première"),
        code_revision="abc123",
    )


def test_create_lays_out_a_run(tmp_path):
    run = _create(tmp_path)
    root = tmp_path / "runs" / "baseline" / "seed-0007"
    assert run.root == root
    assert all(path.is_dir() for path in (run.checkpoints_dir, run.agents_dir, run.evaluation_dir))
    assert load_config(run.config_path, Settings) == Settings(agents=3, note="première")
    assert run.events_path == root / "events.jsonl"
    assert run.llm_calls_path == root / "llm_calls.jsonl"
    assert run.checkpoint_path(3) == root / "checkpoints" / "day-0003.json"
    assert run.agent_dir("ana") == root / "agents" / "ana"
    assert run.evaluation_path("day-30", "ana") == root / "evaluation" / "day-30" / "ana.json"

    manifest = run.read_manifest()
    assert (manifest.seed, manifest.status, manifest.code_revision) == (7, "running", "abc123")
    assert manifest.started_at.tzinfo is not None and manifest.ended_at is None


def test_runs_are_never_created_twice_and_opened_only_if_present(tmp_path):
    run = _create(tmp_path)
    with pytest.raises(FileExistsError):
        _create(tmp_path)
    assert RunDirectory.open(run.root).read_manifest() == run.read_manifest()
    with pytest.raises(FileNotFoundError):
        RunDirectory.open(tmp_path / "runs" / "baseline" / "seed-0008")


def test_manifest_updates_are_validated_and_persisted(tmp_path):
    run = _create(tmp_path)
    ended = datetime.now(UTC)
    run.update_manifest(status=RunStatus.COMPLETED, ended_at=ended)
    for bad in ({"status": "paused"}, {"colour": "red"}, {"ended_at": datetime(2030, 1, 1)}):
        with pytest.raises(ValidationError):
            run.update_manifest(**bad)
    manifest = RunDirectory.open(run.root).read_manifest()
    assert (manifest.status, manifest.ended_at) == (RunStatus.COMPLETED, ended)


def test_latest_checkpoint_is_the_highest_day(tmp_path):
    run = _create(tmp_path)
    assert run.latest_checkpoint() is None
    for day in (2, 10, 9):
        run.checkpoint_path(day).write_text("{}")
    assert run.latest_checkpoint() == run.checkpoint_path(10)


def test_jsonl_round_trip(tmp_path):
    path = tmp_path / "events.jsonl"
    records = [{"seq": 0, "text": "Ana dit bonjour."}, {"seq": 1, "payload": {"nested": [1, None]}}]
    for record in records:
        append_jsonl(path, record)
    assert list(read_jsonl(path)) == records
    assert path.read_text(encoding="utf-8").count("\n") == 2


def test_append_rejects_values_that_are_not_json(tmp_path):
    path = tmp_path / "events.jsonl"
    with pytest.raises(ValueError):
        append_jsonl(path, {"score": float("nan")})
    assert not path.exists()


@pytest.mark.parametrize(
    "second_line", ["not json\n", "[1, 2]\n", "\n", '{"seq": 1'], ids=str.strip
)
def test_read_jsonl_rejects_any_bad_line(tmp_path, second_line):
    path = tmp_path / "events.jsonl"
    path.write_text('{"seq": 0}\n' + second_line)
    with pytest.raises(ValueError, match=r"events\.jsonl:2:"):
        list(read_jsonl(path))
