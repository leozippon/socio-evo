"""SWE-bench as tasks, and the fixed train and eval splits drawn from it.

    python -m tasks.swebench.dataset    rewrites splits.json (checks every image on ghcr.io)

The tasks are the instances of two Hugging Face datasets, each read at its pinned revision in
`REVISIONS` and downloaded once into `CACHE` (set HF_ENDPOINT to use a mirror): the 500 of
SWE-bench Verified (`VERIFIED`), and the 1,794 further instances of SWE-bench's full test split
(`FULL`), of which Verified is the human-validated subset; an instance of both is read from
Verified. A `Task` holds an instance whole, hidden tests and gold patch included; what a worker
may be told is its `brief`, the problem statement alone unless the hints are asked for.

The splits are disjoint and drawn by `select`. Eval is drawn from Verified alone: its instance
ids, sorted and shuffled with `SEED`, are taken in that order, skipping the excluded ones, and
eval is the `EVAL_SIZE` instances after the first `EVAL_START`. Train is every other eligible
Verified instance, sorted, followed by every eligible further instance, sorted, so that adding
the further ones left the Verified part as it was. Train was once those first 56 alone; eval
keeps its place after them so that it stays as first drawn, and excluding an instance that comes
after it changes nothing but train.

An instance is excluded when Epoch AI publishes no image for it, when its repository's images
cannot be used on this machine (`EXCLUDED_REPOS`), when the record of gold checks (gold.json,
written by `python -m tasks.swebench.pull`) says its image could not be pulled or its gold patch
was not resolved in it, or, for a further instance, when it is a sibling of an eval task: of the
same repository, with the same base commit or the same issue (`held_out_siblings`). splits.json,
tracked in the repository, records the exclusions with their reasons beside the two splits.
"""

import json
import random
from collections.abc import Collection, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator

from infrastructure.config import StrictModel
from tasks.swebench.images import image_name, published

VERIFIED = "princeton-nlp/SWE-bench_Verified"
FULL = "princeton-nlp/SWE-bench"
REVISIONS = {
    VERIFIED: "c104f840cc67f8b6eec6f759ebc8b2693d585d4a",
    FULL: "e48e2bd1e9fecd5bbd641e9414ac59da9f2e69f6",
}
DATA_FILE = "data/test-00000-of-00001.parquet"
CACHE = Path.home() / ".cache" / "socio-evo" / "swebench"
SPLITS = Path(__file__).with_name("splits.json")
GOLD = Path(__file__).with_name("gold.json")
RESOLVED = "resolved"
SEED = 20261024
EVAL_START, EVAL_SIZE = 56, 100
NO_IMAGE = "no image published on ghcr.io/epoch-research"
EXCLUDED_REPOS = {
    "matplotlib/matplotlib": "its images do not unpack under this machine's rootless Docker: "
    "they hold files owned by UID 197609 (the bundled qhull build), beyond the user's 65,536 "
    "subordinate IDs (8 of 8 tried failed)",
}

Split = Literal["train", "eval"]


class Task(StrictModel):
    """One SWE-bench instance, with the fields of the dataset; only Verified rates a difficulty."""

    instance_id: str
    repo: str
    base_commit: str
    version: str
    environment_setup_commit: str
    created_at: str
    difficulty: str | None = None
    problem_statement: str
    hints_text: str
    FAIL_TO_PASS: tuple[str, ...]
    PASS_TO_PASS: tuple[str, ...]
    test_patch: str
    patch: str

    @field_validator("FAIL_TO_PASS", "PASS_TO_PASS", mode="before")
    @classmethod
    def _decode(cls, value: object) -> object:
        return json.loads(value) if isinstance(value, str) else value

    @property
    def image(self) -> str:
        return image_name(self.instance_id)

    def brief(self, hints: bool = False) -> str:
        """What a worker is told: the problem statement, with the issue's discussion before
        the fix (`hints_text`) only when `hints` is asked for and there is any."""
        if hints and self.hints_text.strip():
            return f"{self.problem_statement}\n\nHints:\n{self.hints_text}"
        return self.problem_statement


@cache
def load_dataset(name: str) -> Mapping[str, Task]:
    """Every instance of the dataset `name` at its pinned revision by instance id, downloaded on
    first use."""
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(
        name, DATA_FILE, repo_type="dataset", revision=REVISIONS[name], cache_dir=CACHE / "hf"
    )
    rows = pq.read_table(path).to_pylist()
    return {row["instance_id"]: Task.model_validate(row) for row in rows}


def load_tasks() -> Mapping[str, Task]:
    """Every task by instance id: Verified's instances as Verified has them, and the further
    instances of the full test split."""
    return {**load_dataset(FULL), **load_dataset(VERIFIED)}


def load_gold() -> dict[str, str]:
    """The record of gold checks: for each instance checked, `RESOLVED` or why it was not."""
    return json.loads(GOLD.read_text())


def held_out_siblings(candidates: Iterable[Task], held_out: Iterable[Task]) -> dict[str, str]:
    """Why each of `candidates` that is a sibling of a `held_out` task is one: it is of the
    held-out task's repository and has its base commit (a sibling pull request) or its issue."""
    commits, issues = {}, {}
    for task in held_out:
        commits[task.repo, task.base_commit] = task.instance_id
        issues[task.repo, task.problem_statement.strip()] = task.instance_id
    siblings = {}
    for task in candidates:
        if twin := commits.get((task.repo, task.base_commit)):
            siblings[task.instance_id] = f"the same base commit as the held-out {twin}"
        elif twin := issues.get((task.repo, task.problem_statement.strip())):
            siblings[task.instance_id] = f"the same issue as the held-out {twin}"
    return siblings


def select(
    verified: Iterable[str], further: Iterable[str], excluded: Collection[str]
) -> dict[str, list[str]]:
    """The splits drawn from the instance ids of Verified and the further ones without
    `excluded`: eval from Verified alone, and train every other eligible Verified instance,
    sorted, then every eligible further instance, sorted."""
    order = sorted(verified)
    random.Random(SEED).shuffle(order)
    eligible = [instance for instance in order if instance not in excluded]
    end = EVAL_START + EVAL_SIZE
    if len(eligible) < end:
        raise ValueError(
            f"{len(eligible)} eligible instances cannot place {EVAL_SIZE} eval "
            f"instances after the first {EVAL_START}"
        )
    return {
        "train": sorted(eligible[:EVAL_START] + eligible[end:])
        + sorted(instance for instance in further if instance not in excluded),
        "eval": sorted(eligible[EVAL_START:end]),
    }


def load_split(name: Split) -> list[Task]:
    """The tasks of a split, in the order splits.json lists them."""
    splits = json.loads(SPLITS.read_text())
    if splits["datasets"] != REVISIONS:
        raise ValueError(f"{SPLITS} was drawn from other datasets or revisions")
    tasks = load_tasks()
    return [tasks[instance] for instance in splits[name]]


def main() -> None:
    verified, full = load_dataset(VERIFIED), load_dataset(FULL)
    tasks = {**full, **verified}
    further = sorted(full.keys() - verified.keys())
    with ThreadPoolExecutor(32) as pool:
        found = pool.map(published, (task.image for task in tasks.values()))
        excluded = {instance: NO_IMAGE for instance, ok in zip(tasks, found, strict=True) if not ok}
    excluded |= {i: EXCLUDED_REPOS[t.repo] for i, t in tasks.items() if t.repo in EXCLUDED_REPOS}
    excluded |= {i: why for i, why in load_gold().items() if why != RESOLVED}
    held_out = select(verified, further, excluded)["eval"]
    excluded |= held_out_siblings(
        (tasks[i] for i in further if i not in excluded), (tasks[i] for i in held_out)
    )
    excluded = dict(sorted(excluded.items()))
    splits = {
        "datasets": REVISIONS,
        "seed": SEED,
        "excluded": excluded,
        **select(verified, further, excluded),
    }
    SPLITS.write_text(json.dumps(splits, indent=2) + "\n")
    print(f"{len(excluded)} of {len(tasks)} instances excluded; wrote {SPLITS}")


if __name__ == "__main__":
    main()
