import hashlib
import json

import pytest
from huggingface_hub import try_to_load_from_cache

from tasks.swebench.dataset import (
    CACHE,
    DATA_FILE,
    DATASET,
    EVAL_SIZE,
    EVAL_START,
    EXCLUDED_REPOS,
    REVISION,
    SEED,
    SPLITS,
    load_tasks,
    select,
)
from tests.tasks.swebench.conftest import make_task

IDS = [f"owner__repo-{number}" for number in range(500)]
EVAL_SHA256 = "b616bc4c8f5e40e4988fc66d108d1730a03f59140b64b394f68d94d165758ae0"
"""Of the eval split drawn on 2026-10-24, its ids joined by newlines: it must never change."""


def test_the_eval_split_is_the_one_first_drawn():
    splits = json.loads(SPLITS.read_text())
    assert hashlib.sha256("\n".join(splits["eval"]).encode()).hexdigest() == EVAL_SHA256


def test_eval_is_drawn_by_seed_and_train_is_every_other_eligible_instance():
    excluded = set(IDS[::7])
    splits = select(IDS, excluded)
    assert splits == select(reversed(IDS), excluded)
    assert len(splits["eval"]) == EVAL_SIZE and not set(splits["train"]) & set(splits["eval"])
    assert set(splits["train"]) | set(splits["eval"]) == set(IDS) - excluded


def test_excluding_a_training_instance_drawn_after_eval_changes_nothing_else():
    before = select(IDS, excluded=())
    late = [i for i in before["train"] if select(IDS, {i})["eval"] == before["eval"]]
    assert len(late) == len(IDS) - EVAL_START - EVAL_SIZE
    after = select(IDS, excluded={late[0]})
    assert after == {"train": [i for i in before["train"] if i != late[0]], "eval": before["eval"]}


def test_too_few_eligible_instances_raise():
    with pytest.raises(ValueError, match="cannot place"):
        select(IDS[:200], excluded=IDS[:50])


@pytest.mark.skipif(
    not isinstance(
        try_to_load_from_cache(
            DATASET, DATA_FILE, cache_dir=CACHE / "hf", revision=REVISION, repo_type="dataset"
        ),
        str,
    ),
    reason="the dataset is not downloaded",
)
def test_tracked_splits_are_drawn_from_the_pinned_dataset():
    splits = json.loads(SPLITS.read_text())
    tasks = load_tasks()
    assert len(tasks) == 500
    assert (splits["dataset"], splits["revision"], splits["seed"]) == (DATASET, REVISION, SEED)
    assert set(splits["excluded"]) <= set(tasks)
    drawn = select(tasks, splits["excluded"])
    assert (splits["train"], splits["eval"]) == (drawn["train"], drawn["eval"])
    assert set(splits["train"]) | set(splits["eval"]) | set(splits["excluded"]) == set(tasks)
    left_out = {instance for instance, task in tasks.items() if task.repo in EXCLUDED_REPOS}
    assert left_out and left_out <= set(splits["excluded"])


def test_the_brief_is_the_problem_statement_without_hints_by_default():
    task = make_task()
    assert task.brief() == "Units misbehave."
    assert "Look at core.py." in task.brief(hints=True)
    assert make_task(hints_text="").brief(hints=True) == "Units misbehave."
    assert task.FAIL_TO_PASS == ("astropy/units/tests/test_units.py::test_new",)
