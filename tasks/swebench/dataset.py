"""SWE-bench Verified as tasks, and the fixed train and eval splits drawn from it.

    python -m tasks.swebench.dataset    rewrites splits.json (checks every image on ghcr.io)

The 500 instances are read from the Hugging Face dataset `DATASET` at the pinned `REVISION`,
downloaded once into `CACHE` (set HF_ENDPOINT to use a mirror). A `Task` holds an instance
whole, hidden tests and gold patch included; what a worker may be told is its `brief`, the
problem statement alone unless the hints are asked for.

The splits are disjoint and drawn by `select`: the instance ids, sorted and shuffled with
`SEED`, are taken in that order, skipping the excluded ones; eval is the `EVAL_SIZE` instances
after the first `EVAL_START`, and train is every other one. Train was once those first 56 alone;
eval keeps its place after them so that it stays as first drawn, and excluding an instance that
comes after it changes nothing but train. An instance is excluded when Epoch AI publishes no
image for it, when its repository's images cannot be used on this machine (`EXCLUDED_REPOS`),
or when its gold patch fails in its image (`UNRESOLVABLE`, found by `python -m
tasks.swebench.pull`, which accepts every task's gold patch); splits.json, tracked in the
repository, records the exclusions with their reasons beside the two splits.
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

DATASET = "princeton-nlp/SWE-bench_Verified"
REVISION = "c104f840cc67f8b6eec6f759ebc8b2693d585d4a"
DATA_FILE = "data/test-00000-of-00001.parquet"
CACHE = Path.home() / ".cache" / "socio-evo" / "swebench"
SPLITS = Path(__file__).with_name("splits.json")
SEED = 20261024
EVAL_START, EVAL_SIZE = 56, 100
NO_IMAGE = "no image published on ghcr.io/epoch-research"
EXCLUDED_REPOS = {
    "matplotlib/matplotlib": "its images do not unpack under this machine's rootless Docker: "
    "they hold files owned by UID 197609 (the bundled qhull build), beyond the user's 65,536 "
    "subordinate IDs (8 of 8 tried failed)",
}
_OFFLINE = "the gold patch fails without network: hidden tests reach httpbin.org or time a connect"


def _passing(fail_to_pass: str, pass_to_pass: str) -> str:
    return (
        f"the gold patch fails in its image without network: {fail_to_pass} FAIL_TO_PASS and "
        f"{pass_to_pass} PASS_TO_PASS tests pass (python -m tasks.swebench.pull, 2026-10-25)"
    )


UNRESOLVABLE = {
    "astropy__astropy-7606": _passing("1/1", "240/241"),
    "astropy__astropy-8707": "the gold patch fails in its image: its pytest 7.4 turns the "
    "deprecation of nose-style setup into errors in 148 tests",
    "astropy__astropy-8872": _passing("0/1", "0/80"),
    "django__django-10097": _passing("431/438", "1427/1432"),
    "psf__requests-1724": _passing("0/6", "44/79"),
    "psf__requests-1766": _passing("0/6", "45/79"),
    "psf__requests-1921": _passing("1/6", "69/107"),
    "psf__requests-2317": _OFFLINE,
    "psf__requests-2931": _OFFLINE,
    "psf__requests-5414": _passing("1/1", "126/130"),
    "pylint-dev__pylint-4661": _passing("0/1", "0/0"),
    "scikit-learn__scikit-learn-14710": "the hidden tests of the gold patch run past 1800 s, "
    "the town's acceptance timeout (python -m tasks.swebench.pull, 2026-10-25)",
    "sphinx-doc__sphinx-10435": _passing("1/1", "73/74"),
    "sphinx-doc__sphinx-7985": _passing("0/2", "2/3"),
    "sphinx-doc__sphinx-8269": _passing("1/1", "2/5"),
    "sphinx-doc__sphinx-8475": _passing("1/1", "14/17"),
}

Split = Literal["train", "eval"]


class Task(StrictModel):
    """One SWE-bench Verified instance, with the fields of the dataset."""

    instance_id: str
    repo: str
    base_commit: str
    version: str
    environment_setup_commit: str
    created_at: str
    difficulty: str
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
def load_tasks() -> Mapping[str, Task]:
    """Every instance of the pinned dataset by instance id, downloaded on first use."""
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(
        DATASET, DATA_FILE, repo_type="dataset", revision=REVISION, cache_dir=CACHE / "hf"
    )
    rows = pq.read_table(path).to_pylist()
    return {row["instance_id"]: Task.model_validate(row) for row in rows}


def select(instance_ids: Iterable[str], excluded: Collection[str]) -> dict[str, list[str]]:
    """The splits drawn from `instance_ids` without `excluded`, each sorted."""
    order = sorted(instance_ids)
    random.Random(SEED).shuffle(order)
    eligible = [instance for instance in order if instance not in excluded]
    end = EVAL_START + EVAL_SIZE
    if len(eligible) < end:
        raise ValueError(
            f"{len(eligible)} eligible instances cannot place {EVAL_SIZE} eval "
            f"instances after the first {EVAL_START}"
        )
    return {
        "train": sorted(eligible[:EVAL_START] + eligible[end:]),
        "eval": sorted(eligible[EVAL_START:end]),
    }


def load_split(name: Split) -> list[Task]:
    """The tasks of a split, in the order splits.json lists them."""
    splits = json.loads(SPLITS.read_text())
    if (splits["dataset"], splits["revision"]) != (DATASET, REVISION):
        raise ValueError(f"{SPLITS} was drawn from another dataset or revision")
    tasks = load_tasks()
    return [tasks[instance] for instance in splits[name]]


def main() -> None:
    tasks = load_tasks()
    with ThreadPoolExecutor(32) as pool:
        found = pool.map(published, (task.image for task in tasks.values()))
        excluded = {instance: NO_IMAGE for instance, ok in zip(tasks, found, strict=True) if not ok}
    excluded |= {i: EXCLUDED_REPOS[t.repo] for i, t in tasks.items() if t.repo in EXCLUDED_REPOS}
    excluded = dict(sorted((excluded | UNRESOLVABLE).items()))
    splits = {
        "dataset": DATASET,
        "revision": REVISION,
        "seed": SEED,
        "excluded": excluded,
        **select(tasks, excluded),
    }
    SPLITS.write_text(json.dumps(splits, indent=2) + "\n")
    print(f"{len(excluded)} of {len(tasks)} instances excluded; wrote {SPLITS}")


if __name__ == "__main__":
    main()
