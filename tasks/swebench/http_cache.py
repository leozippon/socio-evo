"""Original HTTP responses for official harness metadata, with fail-closed reads."""

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit


class CacheMissError(RuntimeError):
    """Prepare this exact official URL before starting an offline evaluation."""


def load_records(path: Path | None) -> dict:
    records = json.loads(path.read_text()) if path else {}
    for url, row in records.items():
        if row["status_code"] not in (200, 404):
            raise ValueError(f"Invalid cached HTTP status: {url}")
        if hashlib.sha256(row["text"].encode()).hexdigest() != row["sha256"]:
            raise ValueError(f"HTTP cache checksum mismatch: {url}")
    return records


def cached_getter(path: Path | None, fallback, *, strict=False, used=None):
    if strict and path is None:
        raise CacheMissError("Strict metadata cache requires a cache file")
    records = load_records(path)

    def get(url, **kwargs):
        if used is not None:
            used.add(url)
        if url in records:
            row = records[url]
            return SimpleNamespace(status_code=row["status_code"], text=row["text"])
        if strict:
            raise CacheMissError(f"Official metadata cache miss; prepare this URL: {url}")
        kwargs.setdefault("timeout", (10, 30))
        return fallback(url, **kwargs)

    return get


def prepare_cache(rows, path: Path, *, builder=None, fetch=None, attempts=3, pause=time.sleep):
    """Follow official metadata requests; commit only a completely validated cache."""
    if attempts < 1:
        raise ValueError("attempts must be positive")
    rows = list(rows)
    if builder is None:
        from tasks.swebench.environment_spec import build_spec

        builder = build_spec
    if fetch is None:
        import requests

        fetch = requests.get
    records = load_records(path) if path.exists() else {}
    used = set()

    def get(url, **kwargs):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "raw.githubusercontent.com":
            raise ValueError(f"Not an official raw GitHub metadata URL: {url}")
        used.add(url)
        if url not in records:
            for attempt in range(attempts):
                try:
                    result = fetch(
                        url,
                        timeout=(10, 30),
                        allow_redirects=False,
                        **{
                            k: v
                            for k, v in kwargs.items()
                            if k not in {"timeout", "allow_redirects"}
                        },
                    )
                    if result.status_code not in (200, 404):
                        raise RuntimeError(f"Metadata HTTP {result.status_code}: {url}")
                    records[url] = {
                        "status_code": result.status_code,
                        "text": result.text,
                        "sha256": hashlib.sha256(result.text.encode()).hexdigest(),
                        "fetched_at": datetime.now(UTC).isoformat(),
                        "source_url": url,
                    }
                    break
                except Exception:
                    if attempt + 1 == attempts:
                        raise
                    pause(min(2**attempt, 8))
        row = records[url]
        return SimpleNamespace(status_code=row["status_code"], text=row["text"])

    checked = []
    for row in rows:
        builder(row, get)
        checked.append(row["instance_id"])

    # Re-run fail-closed before publishing anything; no new HTTP can be needed.
    def offline(url, **kwargs):
        if url not in records:
            raise CacheMissError(url)
        row = records[url]
        return SimpleNamespace(status_code=row["status_code"], text=row["text"])

    for row in rows:
        builder(row, offline)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "instances": checked,
        "urls": sorted(used),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Prepare official environment metadata without running residents"
    )
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--instances", nargs="+", default=None)
    parser.add_argument("--attempts", type=int, default=3)
    args = parser.parse_args()
    rows = {row["instance_id"]: row for row in json.loads(args.dataset.read_text())}
    chosen = [rows[i] for i in (args.instances or sorted(rows))]
    print(json.dumps(prepare_cache(chosen, args.out, attempts=args.attempts), indent=2))


if __name__ == "__main__":
    main()
