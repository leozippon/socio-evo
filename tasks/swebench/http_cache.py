"""Verified original HTTP responses for the official harness's environment metadata."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace


def cached_getter(path: Path | None, fallback):
    records = json.loads(path.read_text()) if path else {}
    for url, row in records.items():
        if hashlib.sha256(row["text"].encode()).hexdigest() != row["sha256"]:
            raise ValueError(f"HTTP cache checksum mismatch: {url}")

    def get(url, **kwargs):
        if url in records:
            row = records[url]
            return SimpleNamespace(status_code=row["status_code"], text=row["text"])
        kwargs.setdefault("timeout", (10, 30))
        return fallback(url, **kwargs)

    return get
