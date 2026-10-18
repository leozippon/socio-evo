"""Prepare a versioned Lite/Verified bank for repository work, outside agent storage.

python -m tasks.swebench.fetch --variant verified --out /path/to/swebench-verified
"""

import argparse
import hashlib
import json
from pathlib import Path

DATASETS = {
    "lite": "princeton-nlp/SWE-bench_Lite",
    "verified": "princeton-nlp/SWE-bench_Verified",
}


def save_bank(rows: list[dict], out: Path, *, variant: str, revision: str) -> Path:
    if not rows or len({r["instance_id"] for r in rows}) != len(rows):
        raise ValueError("dataset must contain distinct instances")
    for row in rows:
        if not all(
            row.get(key) for key in ("instance_id", "repo", "base_commit", "problem_statement")
        ):
            raise ValueError("incomplete repository issue")
    data = json.dumps(sorted(rows, key=lambda r: r["instance_id"]), ensure_ascii=False).encode()
    # Never replace an experiment's source dataset in place.
    out.mkdir(parents=True, exist_ok=False)
    target = out / "test.json"
    target.write_bytes(data)
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "dataset": DATASETS[variant],
                "variant": variant,
                "split": "test",
                "revision": revision,
                "sha256": hashlib.sha256(data).hexdigest(),
                "instances": [
                    r["instance_id"] for r in sorted(rows, key=lambda r: r["instance_id"])
                ],
            },
            indent=2,
        )
        + "\n"
    )
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=DATASETS, required=True)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    from datasets import load_dataset
    from huggingface_hub import HfApi

    repo = DATASETS[args.variant]
    revision = HfApi().dataset_info(repo, revision=args.revision).sha
    rows = load_dataset(repo, split="test", revision=revision).to_list()
    print(save_bank(rows, args.out, variant=args.variant, revision=revision))


if __name__ == "__main__":
    main()
