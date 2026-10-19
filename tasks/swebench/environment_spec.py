"""Build official environment/image specs without gold tests or patch information."""

import hashlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace

from tasks.swebench.http_cache import cached_getter

_SPEC_LOCK = threading.RLock()
PUBLIC_METADATA = ("instance_id", "repo", "base_commit", "version", "environment_setup_commit")


def build_spec(row, get):
    from swebench.harness.test_spec import python as python_spec
    from swebench.harness.test_spec.test_spec import make_test_spec

    public = {key: row[key] for key in PUBLIC_METADATA if key in row}
    # These fields affect eval scripts only, not environment setup or image identity.
    public.update(test_patch="", PASS_TO_PASS=[], FAIL_TO_PASS=[], problem_statement="")
    with _SPEC_LOCK:
        previous = python_spec.requests
        try:
            python_spec.requests = SimpleNamespace(get=get)
            return make_test_spec(public, namespace="swebench", arch="x86_64")
        finally:
            python_spec.requests = previous


def inspect_spec(row, cache: Path):
    used = set()
    spec = build_spec(row, cached_getter(cache, None, strict=True, used=used))
    return {
        "instance": row["instance_id"],
        "image": spec.instance_image_key,
        "environment_image": spec.env_image_key,
        "metadata_urls": sorted(used),
        "cache_sha256": hashlib.sha256(cache.read_bytes()).hexdigest(),
        "status": "passed",
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("instance")
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    row = next(r for r in json.loads(args.dataset.read_text()) if r["instance_id"] == args.instance)
    print(json.dumps(inspect_spec(row, args.cache)))


if __name__ == "__main__":
    main()
