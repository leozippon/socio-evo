import hashlib
import json

import pytest
from huggingface_hub import try_to_load_from_cache

from tasks.swebench.dataset import (
    CACHE,
    DATA_FILE,
    EVAL_SIZE,
    EVAL_START,
    EXCLUDED_REPOS,
    FULL,
    REVISIONS,
    SEED,
    SPLITS,
    VERIFIED,
    held_out_siblings,
    load_dataset,
    select,
)
from tests.tasks.swebench.conftest import make_task

IDS = [f"owner__repo-{number}" for number in range(500)]
FURTHER = [f"owner__repo-{number}" for number in range(500, 600)]
EVAL_SHA256 = "b616bc4c8f5e40e4988fc66d108d1730a03f59140b64b394f68d94d165758ae0"
"""Of the eval split drawn on 2026-10-24, its ids joined by newlines: it must never change."""


def test_the_eval_split_is_the_one_first_drawn():
    splits = json.loads(SPLITS.read_text())
    assert hashlib.sha256("\n".join(splits["eval"]).encode()).hexdigest() == EVAL_SHA256


def test_eval_is_drawn_from_verified_and_train_is_every_other_eligible_instance():
    excluded = set(IDS[::7]) | set(FURTHER[::7])
    splits = select(IDS, FURTHER, excluded)
    assert splits == select(reversed(IDS), reversed(FURTHER), excluded)
    assert len(splits["eval"]) == EVAL_SIZE and set(splits["eval"]) <= set(IDS) - excluded
    verified = sorted(set(IDS) - excluded - set(splits["eval"]))
    assert splits["train"] == verified + sorted(set(FURTHER) - excluded)


def test_excluding_a_training_instance_drawn_after_eval_changes_nothing_else():
    before = select(IDS, FURTHER, excluded=())
    late = [i for i in before["train"] if select(IDS, FURTHER, {i})["eval"] == before["eval"]]
    assert len(late) == len(IDS) + len(FURTHER) - EVAL_START - EVAL_SIZE
    after = select(IDS, FURTHER, excluded={late[0]})
    assert after == {"train": [i for i in before["train"] if i != late[0]], "eval": before["eval"]}


def test_too_few_eligible_instances_raise():
    with pytest.raises(ValueError, match="cannot place"):
        select(IDS[:200], FURTHER, excluded=IDS[:50])


def test_a_sibling_shares_a_held_out_tasks_repository_and_base_commit_or_issue():
    held_out = make_task(instance_id="astropy__astropy-1", base_commit="a" * 40)
    commit = make_task(instance_id="astropy__astropy-2", base_commit="a" * 40)
    issue = make_task(instance_id="astropy__astropy-3", base_commit="b" * 40)
    other = make_task(instance_id="astropy__astropy-4", problem_statement="Other.")
    elsewhere = make_task(instance_id="other__other-1", repo="other/other", base_commit="a" * 40)
    siblings = held_out_siblings([commit, issue, other, elsewhere], [held_out])
    assert siblings == {
        "astropy__astropy-2": "the same base commit as the held-out astropy__astropy-1",
        "astropy__astropy-3": "the same issue as the held-out astropy__astropy-1",
    }


downloaded = pytest.mark.skipif(
    not all(
        isinstance(
            try_to_load_from_cache(
                name, DATA_FILE, cache_dir=CACHE / "hf", revision=revision, repo_type="dataset"
            ),
            str,
        )
        for name, revision in REVISIONS.items()
    ),
    reason="the datasets are not downloaded",
)


@downloaded
def test_tracked_splits_are_drawn_from_the_pinned_datasets():
    splits = json.loads(SPLITS.read_text())
    verified, full = load_dataset(VERIFIED), load_dataset(FULL)
    assert (len(verified), len(full), len(verified.keys() - full.keys())) == (500, 2294, 0)
    assert (splits["datasets"], splits["seed"]) == (REVISIONS, SEED)
    tasks = full.keys()
    assert set(splits["excluded"]) <= tasks
    drawn = select(verified, tasks - verified.keys(), splits["excluded"])
    assert (splits["train"], splits["eval"]) == (drawn["train"], drawn["eval"])
    assert set(splits["train"]) | set(splits["eval"]) | set(splits["excluded"]) == tasks
    left_out = {instance for instance, task in full.items() if task.repo in EXCLUDED_REPOS}
    assert left_out and left_out <= set(splits["excluded"])


def test_the_brief_is_the_problem_statement_without_hints_by_default():
    task = make_task()
    assert task.brief() == "Units misbehave."
    assert "Look at core.py." in task.brief(hints=True)
    assert make_task(hints_text="").brief(hints=True) == "Units misbehave."
    assert task.FAIL_TO_PASS == ("astropy/units/tests/test_units.py::test_new",)
