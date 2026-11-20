"""Real Git artifacts, synthetic withheld labels and rollback-resistant score disclosure."""

import copy
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from infrastructure.git import Repository
from world.research_evaluation import EvaluationDesk


@pytest.fixture
def desk(tmp_path):
    root = tmp_path / "research"
    (root / "files").mkdir(parents=True)
    (root / "records").mkdir()
    repo = Repository.init(root, user_name="Test", user_email="test@invalid")
    (root / "files/strategy.py").write_text("raise RuntimeError('MUST NEVER EXECUTE')\n")
    (root / "records/README.txt").write_text("Recorded evidence.\n")
    repo.commit("Initial strategy", date=datetime.now(UTC))
    research = SimpleNamespace(root=root, records=root / "records", repo=repo)
    return EvaluationDesk(research)


def definition():
    return {
        "id": "toy", "title": "Synthetic retrieval acceptance", "split": "new-private-test",
        "metric": "hit_at_k", "top_k": 2, "max_calls": 3,
        "variants": ["baseline", "candidate"], "labels_unseen": True,
        "label_provenance": "Synthetic test only; these are not a real benchmark.",
        "queries": [
            {"id": "q1", "input": {"query": "first synthetic query"},
             "relevant_ids": ["secret-a", "secret-b"]},
            {"id": "q2", "relevant_ids": ["secret-c"]},
        ],
    }


def provision(desk, data=None):
    desk.source.mkdir(exist_ok=True)
    (desk.source / "toy.json").write_text(json.dumps(data or definition()))


def batch():
    return {"benchmark_id": "toy", "variants": [
        {"id": "baseline", "predictions": [
            {"query_id": "q1", "retrieved_ids": ["secret-a", "miss"], "calls": 3},
            {"query_id": "q2", "retrieved_ids": ["miss", "also-miss"], "calls": 3},
        ]},
        {"id": "candidate", "predictions": [
            {"query_id": "q1", "retrieved_ids": ["secret-b", "miss"], "calls": 2},
            {"query_id": "q2", "retrieved_ids": ["secret-c", "miss"], "calls": 3},
        ]},
    ]}


def commit_batch(desk, data=None):
    (desk.research.root / "files/predictions.json").write_text(json.dumps(data or batch()))
    revision = desk.research.repo.commit("Frozen predictions", date=datetime.now(UTC))
    return {"action": "submit", "benchmark_id": "toy", "revision": revision,
            "path": "predictions.json"}


def test_no_benchmark_and_public_metadata_never_reveal_labels(desk):
    assert desk.call({"action": "list"}) == {"benchmarks": [], "available": False}
    with pytest.raises(ValueError, match="No operator-provisioned"):
        desk.call({"action": "open", "benchmark_id": "toy"})
    provision(desk)
    summary = desk.call({"action": "list"})["benchmarks"][0]
    assert summary["query_count"] == 2 and "queries" not in summary
    opened = desk.call({"action": "open", "benchmark_id": "toy"})
    assert opened["queries"] == [{"id": "q1", "input": {"query": "first synthetic query"}},
                                 {"id": "q2"}]
    assert not opened["independence_verified"] and not opened["actual_compute_verified"]
    assert "secret-" not in json.dumps(opened)
    assert "label_provenance" not in opened


@pytest.mark.parametrize("metric,expected", [
    ("hit_at_k", [0.5, 1.0]), ("recall_at_k", [0.25, 0.75]),
])
def test_scores_frozen_git_batch_not_worktree_and_never_execute_strategy(desk, metric, expected):
    data = definition()
    data["metric"] = metric
    provision(desk, data)
    args = commit_batch(desk)
    (desk.research.root / "files/predictions.json").write_text("invalid live worktree JSON")
    # Unrelated commits do not invalidate the explicitly pinned strategy/predictions snapshot.
    desk.research.repo.commit("Concurrent unrelated work", date=datetime.now(UTC))
    result = desk.call(args)
    assert [v["score"] for v in result["scores"]] == expected
    assert result["submission"]["revision"] == args["revision"]
    assert not result["previously_disclosed"] and result["evaluation_count"] == 1
    assert result["actual_compute_verified"] is False
    assert "secret-" not in json.dumps(result) and "queries" not in result
    assert (desk.research.records / "evaluation-toy.json").exists()
    assert (desk.state / "toy/final.json").stat().st_mode & 0o777 == 0o600


def test_checkpoint_rollback_cannot_buy_another_score(desk):
    provision(desk)
    checkpoint = desk.research.repo.head()
    args = commit_batch(desk)
    original = desk.call(args)
    desk.research.repo.commit("Public evaluation receipt", date=datetime.now(UTC))
    desk.research.repo.reset_hard(checkpoint)
    assert not (desk.research.records / "evaluation-toy.json").exists()
    opened = desk.call({"action": "open", "benchmark_id": "toy"})
    assert opened["already_evaluated"]
    assert opened["previous_receipt"]["scores"] == original["scores"]
    # Exact original blob survives in Git even though it is no longer an ancestor of HEAD.
    replay = desk.call(args)
    assert replay["previously_disclosed"] and replay["scores"] == original["scores"]
    modified = batch()
    modified["variants"][0]["predictions"][1]["retrieved_ids"] = ["secret-c", "miss"]
    with pytest.raises(ValueError, match="already disclosed"):
        desk.call(commit_batch(desk, modified))
    assert json.loads((desk.state / "toy/final.json").read_text())["scores"] == original["scores"]


@pytest.mark.parametrize("change", [
    lambda x: x["variants"].pop(),
    lambda x: x["variants"][0]["predictions"].pop(),
    lambda x: x["variants"][0]["predictions"][0].update(retrieved_ids=["secret-a"]),
    lambda x: x["variants"][0]["predictions"][0].update(retrieved_ids=["same", "same"]),
    lambda x: x["variants"][0]["predictions"][0].update(calls=4),
    lambda x: x["variants"][0]["predictions"][0].update(calls=True),
    lambda x: x["variants"][0].update(id=[]),
    lambda x: x["variants"][0]["predictions"][0].update(query_id={}),
])
def test_invalid_partial_or_unequal_budget_batch_never_discloses_or_consumes_score(desk, change):
    provision(desk)
    invalid = copy.deepcopy(batch())
    change(invalid)
    with pytest.raises(ValueError) as error:
        desk.call(commit_batch(desk, invalid))
    assert "secret-" not in str(error.value)
    assert not (desk.state / "toy/final.json").exists()
    assert not (desk.research.records / "evaluation-toy.json").exists()
    assert desk.call(commit_batch(desk))["evaluation_count"] == 1


def test_definition_is_frozen_before_any_scores_and_exposed_labels_are_rejected(desk):
    data = definition()
    data["labels_unseen"] = False
    provision(desk, data)
    with pytest.raises(ValueError, match="Operator benchmark"):
        desk.call({"action": "list"})
    provision(desk)
    desk.call({"action": "open", "benchmark_id": "toy"})
    data = definition()
    data["queries"][0]["relevant_ids"] = ["new-secret"]
    provision(desk, data)
    with pytest.raises(ValueError, match="changed after it was frozen"):
        desk.call(commit_batch(desk))
    assert not (desk.state / "toy/final.json").exists()


@pytest.mark.parametrize("path", ["../private.json", "/tmp/private.json", "records/truth.json",
                                  "files/../../private.json", "files/.git/config.json"])
def test_prediction_path_is_confined_to_committed_shared_files(desk, path):
    provision(desk)
    args = commit_batch(desk)
    args["path"] = path
    with pytest.raises(ValueError, match="shared files"):
        desk.call(args)


def test_symlink_predictions_and_unknown_revisions_cannot_read_private_files(desk):
    provision(desk)
    (desk.research.root / "files/leak.json").symlink_to(desk.source / "toy.json")
    revision = desk.research.repo.commit("Malicious symlink", date=datetime.now(UTC))
    args = {"action": "submit", "benchmark_id": "toy", "revision": revision,
            "path": "leak.json"}
    with pytest.raises(ValueError, match="regular committed"):
        desk.call(args)
    args["revision"] = "f" * 40
    with pytest.raises(ValueError, match="regular committed"):
        desk.call(args)


def test_private_final_survives_public_receipt_write_failure(desk, monkeypatch):
    from world import research_evaluation

    provision(desk)
    args = commit_batch(desk)
    write = research_evaluation._write

    def fail_public(path, value, *, private=True):
        if not private:
            raise OSError("simulated crash after private finalization")
        return write(path, value, private=private)

    monkeypatch.setattr(research_evaluation, "_write", fail_public)
    with pytest.raises(OSError):
        desk.call(args)
    assert (desk.state / "toy/final.json").exists()
    monkeypatch.setattr(research_evaluation, "_write", write)
    assert desk.call(args)["previously_disclosed"] is True
