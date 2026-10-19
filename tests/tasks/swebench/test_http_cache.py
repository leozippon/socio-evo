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


def test_strict_cache_miss_never_uses_network(tmp_path):
    from tasks.swebench.http_cache import CacheMissError

    path = tmp_path / "cache.json"
    path.write_text("{}")
    calls = []
    get = cached_getter(path, lambda *a, **k: calls.append(a), strict=True)
    with pytest.raises(CacheMissError, match="missing.txt"):
        get("https://raw.githubusercontent.com/org/repo/commit/missing.txt")
    assert not calls
    with pytest.raises(CacheMissError):
        cached_getter(None, None, strict=True)


def test_preparation_tracks_recursive_requests_and_preserves_404_fallback(tmp_path):
    from types import SimpleNamespace

    from tasks.swebench.http_cache import prepare_cache

    root = "https://raw.githubusercontent.com/org/repo/commit/"
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        assert kwargs["allow_redirects"] is False
        return SimpleNamespace(
            status_code=404 if url.endswith("missing") else 200,
            text="not found" if url.endswith("missing") else "-r child\n",
        )

    def builder(row, get):
        assert get(root + "missing").status_code == 404
        assert get(root + "requirements").text == "-r child\n"
        assert get(root + "child").text == "-r child\n"

    path = tmp_path / "cache.json"
    report = prepare_cache([{"instance_id": "issue"}], path, builder=builder, fetch=fetch)
    assert len(calls) == 3 and len(report["urls"]) == 3
    assert json.loads(path.read_text())[root + "child"]["source_url"] == root + "child"
    builder({}, cached_getter(path, None, strict=True))


def test_failed_preparation_retries_but_does_not_overwrite_existing_cache(tmp_path):
    from types import SimpleNamespace

    from tasks.swebench.http_cache import prepare_cache

    path = tmp_path / "cache.json"
    path.write_text("{}\n")
    calls, pauses = [], []

    def fetch(*a, **kw):
        calls.append(a)
        return SimpleNamespace(status_code=503, text="outage")

    with pytest.raises(RuntimeError, match="503"):
        prepare_cache(
            [{}],
            path,
            builder=lambda row, get: get(
                "https://raw.githubusercontent.com/org/repo/commit/requirements"
            ),
            fetch=fetch,
            attempts=3,
            pause=pauses.append,
        )
    assert len(calls) == 3 and pauses == [1, 2]
    assert path.read_text() == "{}\n"
    assert not list(tmp_path.glob("*.tmp"))


def test_preparation_recovers_transient_http_failure_without_caching_it(tmp_path):
    from types import SimpleNamespace

    from tasks.swebench.http_cache import prepare_cache

    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise TimeoutError("slow GitHub")
        return SimpleNamespace(status_code=200, text="exact original\n")

    url = "https://raw.githubusercontent.com/org/repo/commit/requirements.txt"
    path = tmp_path / "cache.json"
    prepare_cache(
        [{"instance_id": "a"}],
        path,
        fetch=fetch,
        builder=lambda row, get: get(url),
        pause=lambda _: None,
    )
    assert len(calls) == 2
    assert cached_getter(path, None, strict=True)(url).text == "exact original\n"


def test_bundled_verified_cache_matches_its_manifest():
    from pathlib import Path

    from tasks.swebench.http_cache import load_records

    root = Path("tasks/swebench/metadata")
    cache = root / "verified-4.1.0-http-cache.json"
    manifest = json.loads((root / "verified-4.1.0-manifest.json").read_text())
    assert hashlib.sha256(cache.read_bytes()).hexdigest() == manifest["sha256"]
    assert len(manifest["instances"]) == manifest["full_dataset_spec_match"] == 500
    assert manifest["network_disabled_during_verification"] is True
    assert set(load_records(cache)) == set(manifest["urls"])
