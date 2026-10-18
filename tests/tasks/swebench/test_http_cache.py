import hashlib
import json

import pytest

from tasks.swebench.http_cache import cached_getter


def test_cache_preserves_original_text_and_bounds_network_fallback(tmp_path):
    path = tmp_path / "cache.json"
    body = "pytest==7.3.0\n"
    record = {"status_code": 200, "text": body, "sha256": hashlib.sha256(body.encode()).hexdigest()}
    path.write_text(json.dumps({"https://example.test/requirements.txt": record}))
    calls = []
    get = cached_getter(path, lambda url, **kw: calls.append((url, kw)))
    assert get("https://example.test/requirements.txt").text == body
    assert not calls
    get("https://example.test/missing")
    assert calls[0][1]["timeout"] == (10, 30)
    record["text"] = "changed"
    path.write_text(json.dumps({"url": record}))
    with pytest.raises(ValueError, match="checksum"):
        cached_getter(path, None)
