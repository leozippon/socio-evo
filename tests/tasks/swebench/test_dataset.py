import json

import pytest
from huggingface_hub import try_to_load_from_cache

from tasks.swebench.dataset import (
    CACHE,
    DATA_FILE,
    DATASET,
    EXCLUDED_REPOS,
    REVISION,
    SEED,
    SIZES,
    SPLITS,
    load_tasks,
    select,
)
from tests.tasks.swebench.conftest import make_task

IDS = [f"owner__repo-{number}" for number in range(500)]


def test_splits_are_deterministic_disjoint_and_sized():
    splits = select(IDS, excluded=())
    assert splits == select(reversed(IDS), excluded=())
    assert {name: len(ids) for name, ids in splits.items()} == SIZES
    assert not set(splits["train"]) & set(splits["eval"])


def test_excluding_an_instance_brings_in_exactly_one_other():
    before = select(IDS, excluded=())
    dropped = before["train"][0]
    after = select(IDS, excluded={dropped})
    chosen_before = set(before["train"] + before["eval"])
    chosen_after = set(after["train"] + after["eval"])
    assert dropped not in chosen_after
    assert len(chosen_after - chosen_before) == 1
    assert chosen_before - chosen_after == {dropped}


def test_too_few_eligible_instances_raise():
    with pytest.raises(ValueError, match="cannot fill"):
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
    left_out = {instance for instance, task in tasks.items() if task.repo in EXCLUDED_REPOS}
    assert left_out and left_out <= set(splits["excluded"])


def test_the_brief_is_the_problem_statement_without_hints_by_default():
    task = make_task()
    assert task.brief() == "Units misbehave."
    assert "Look at core.py." in task.brief(hints=True)
    assert make_task(hints_text="").brief(hints=True) == "Units misbehave."
    assert task.FAIL_TO_PASS == ("astropy/units/tests/test_units.py::test_new",)
