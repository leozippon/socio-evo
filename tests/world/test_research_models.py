"""Pinned Hub snapshots, actual streamed bytes, and checkpoint admission boundaries."""

import hashlib
import io
import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from urllib.parse import unquote, urlsplit

import pytest

from world import research_models as models

SHA = "1" * 40
FUTURE = "2" * 40
CUTOFF = datetime(2025, 6, 1, tzinfo=UTC)


def sibling(name, data):
    digest = hashlib.sha256(data).hexdigest()
    return NS(
        rfilename=name,
        size=len(data),
        blob_id=hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest(),
        lfs=NS(size=len(data), sha256=digest) if name.endswith((".safetensors", ".bin")) else None,
    )


@pytest.fixture
def hub(tmp_path, monkeypatch):
    files = {
        "config.json": json.dumps(
            {"model_type": "fixture", "auto_map": {"AutoModel": "unused.Custom"}}
        ).encode(),
        "tokenizer.json": b'{"model":{"type":"BPE"}}',
        "tokenizer_config.json": b'{"tokenizer_class":"FixtureTokenizer"}',
        "model.safetensors.index.json": json.dumps(
            {
                "weight_map": {
                    "first": "model-00001-of-00002.safetensors",
                    "second": "model-00002-of-00002.safetensors",
                }
            }
        ).encode(),
        "model-00001-of-00002.safetensors": b"actual first weight bytes",
        "model-00002-of-00002.safetensors": b"actual second weight bytes",
        "pytorch_model.bin": b"duplicate PyTorch weights",
        "tf_model.h5": b"duplicate TensorFlow weights",
        "flax_model.msgpack": b"duplicate Flax weights",
        "component/pytorch_model.bin": b"separate unconverted component",
        "unused.py": b"raise RuntimeError('Remote code must never execute')\n",
    }
    calls, requests = [], []

    class API:
        private = False
        gated = False
        commits = [
            NS(commit_id=SHA, created_at=datetime(2024, 9, 1, tzinfo=UTC)),
            NS(commit_id=FUTURE, created_at=datetime(2025, 7, 1, tzinfo=UTC)),
            NS(commit_id="0" * 40, created_at=datetime(2023, 9, 1, tzinfo=UTC)),
        ]

        def model_info(self, repo_id, **kwargs):
            calls.append(("info", repo_id, kwargs))
            assert kwargs["token"] is False
            revision = kwargs.get("revision")
            return NS(
                private=self.private,
                gated=self.gated,
                created_at=datetime(2023, 1, 1, tzinfo=UTC),
                sha=revision or FUTURE,
                description="FUTURE DESCRIPTION",
                downloads=999999,
                siblings=[sibling(name, data) for name, data in files.items()],
            )

        def list_repo_commits(self, repo_id, **kwargs):
            calls.append(("commits", repo_id, kwargs))
            assert kwargs["token"] is False
            return self.commits

        def list_models(self, **kwargs):
            assert kwargs["token"] is False and kwargs["gated"] is False
            return [NS(id="example/model", description="FUTURE DESCRIPTION", likes=999999)]

    class Response(io.BytesIO):
        status = 200

    class Opener:
        transform = staticmethod(lambda name, data: data)

        def open(self, request, timeout):
            requests.append(request)
            assert request.get_header("Authorization") is None
            filename = unquote(urlsplit(request.full_url).path.split(f"/resolve/{SHA}/", 1)[1])
            return Response(self.transform(filename, files[filename]))

    api, opener = API(), Opener()
    monkeypatch.setattr(models, "_client", lambda endpoint: api)
    monkeypatch.setattr(models, "build_opener", lambda *args: opener)
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    return NS(
        gateway=models.ModelGateway(tmp_path / "cache"),
        api=api,
        opener=opener,
        files=files,
        calls=calls,
        requests=requests,
        tmp=tmp_path,
    )


def test_info_uses_commit_time_not_repository_creation_and_keeps_required_components(hub):
    result = hub.gateway.info("example/model", CUTOFF)
    assert result["revision"] == SHA and result["commit_time"] == "2024-09-01T00:00:00Z"
    names = {file["path"] for file in result["files"]}
    assert {
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "model.safetensors.index.json",
        "component/pytorch_model.bin",
    } <= names
    assert not {"pytorch_model.bin", "tf_model.h5", "flax_model.msgpack"} & names
    assert result["total_bytes"] == sum(len(hub.files[name]) for name in names)
    assert result["provenance"]["availability_verified"] is False
    assert "FUTURE DESCRIPTION" not in json.dumps(result) and "999999" not in json.dumps(result)
    assert hub.calls[-1][2]["revision"] == SHA


def test_download_streams_real_weights_and_publishes_only_complete_verified_snapshot(hub):
    receipt = hub.gateway.download("example/model", CUTOFF)
    root = hub.gateway.resolve(receipt)
    assert str(root) == receipt["local_path"]
    assert receipt["artifact_id"].startswith("hf-")
    assert receipt["remote_code_declared"] and receipt["inference_validated"] is False
    for file in receipt["files"]:
        data = (root / file["path"]).read_bytes()
        assert data == hub.files[file["path"]]
        assert file["sha256"] == hashlib.sha256(data).hexdigest()
    assert not (root / "pytorch_model.bin").exists()
    assert not list(hub.gateway.cache_dir.glob(".download-*"))
    previous = len(hub.requests)
    again = hub.gateway.download("example/model", CUTOFF, revision=SHA)
    assert len(hub.requests) == previous and again["manifest_sha256"] == receipt["manifest_sha256"]


@pytest.mark.parametrize("field,value", [("private", True), ("gated", "auto"), ("gated", "manual")])
def test_private_or_gated_models_are_not_authorized_by_environment_tokens(
    hub, monkeypatch, field, value
):
    monkeypatch.setenv("HF_TOKEN", "credential-that-must-not-be-used")
    setattr(hub.api, field, value)
    with pytest.raises(ValueError, match="public, non-gated"):
        hub.gateway.download("example/model", CUTOFF)
    assert not hub.requests and list(hub.gateway.cache_dir.iterdir()) == []


def test_cached_snapshot_does_not_bypass_current_public_check(hub):
    receipt = hub.gateway.download("example/model", CUTOFF)
    hub.api.private = True
    with pytest.raises(ValueError, match="public, non-gated"):
        hub.gateway.download("example/model", CUTOFF)
    # A previously checkpoint-admitted receipt remains a reproducible local artifact.
    assert hub.gateway.resolve(receipt).is_dir()


def test_future_missing_and_naive_dates_fail_without_downloading(hub):
    with pytest.raises(ValueError, match="cutoff"):
        hub.gateway.download("example/model", CUTOFF, revision=FUTURE)
    with pytest.raises(ValueError, match="full 40-character"):
        hub.gateway.info("example/model", CUTOFF, revision="main")
    with pytest.raises(ValueError, match="timezone-aware"):
        hub.gateway.info("example/model", datetime(2025, 6, 1))
    with pytest.raises(ValueError, match="real-world future"):
        hub.gateway.info("example/model", datetime.now(UTC) + timedelta(days=1))
    hub.api.commits = [NS(commit_id=SHA, created_at=None)]
    with pytest.raises(ValueError, match="dated"):
        hub.gateway.download("example/model", CUTOFF)
    assert not hub.requests


def test_stream_checksum_failure_or_lfs_pointer_never_becomes_a_snapshot(hub):
    original = hub.files["model-00001-of-00002.safetensors"]
    hub.opener.transform = (
        lambda name, data: b"x" * len(original)
        if name.endswith("00001-of-00002.safetensors")
        else data
    )
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        hub.gateway.download("example/model", CUTOFF)
    assert list(hub.gateway.cache_dir.iterdir()) == []
    hub.opener.transform = (
        lambda name, data: b"version https://git-lfs.github.com/spec/v1"
        if name.endswith(".safetensors")
        else data
    )
    with pytest.raises(ValueError, match="size"):
        hub.gateway.download("example/model", CUTOFF)
    assert list(hub.gateway.cache_dir.iterdir()) == []


def test_cancel_during_stream_keeps_admitted_namespace_unchanged(hub):
    cancelled = threading.Event()

    def response(name, data):
        cancelled.set()
        return data

    hub.opener.transform = response
    with pytest.raises(InterruptedError, match="cancelled"):
        hub.gateway.download("example/model", CUTOFF, cancel=cancelled)
    assert list(hub.gateway.cache_dir.iterdir()) == []


def test_capacity_depends_on_real_free_space_not_an_arbitrary_download_limit(hub, monkeypatch):
    monkeypatch.setattr(models.shutil, "disk_usage", lambda _: NS(free=0))
    with pytest.raises(ValueError, match="Insufficient model-cache disk space"):
        hub.gateway.download("example/model", CUTOFF)
    assert not hub.requests
    big = sibling("model.safetensors", b"x")
    big.size = big.lfs.size = 12 * 1024**3
    selected, excluded = models._files([big])
    assert selected[0]["bytes"] == 12 * 1024**3 and not excluded


def test_missing_index_shard_is_not_published(hub):
    hub.files["model.safetensors.index.json"] = b'{"weight_map":{"weight":"absent.safetensors"}}'
    with pytest.raises(ValueError, match="missing shard"):
        hub.gateway.download("example/model", CUTOFF)
    assert list(hub.gateway.cache_dir.iterdir()) == []


def test_resolve_checks_admitted_manifest_and_rejects_symlink_escape(hub):
    receipt = hub.gateway.download("example/model", CUTOFF)
    with pytest.raises(ValueError, match="checksum"):
        hub.gateway.resolve(receipt | {"manifest_sha256": "0" * 64})
    with pytest.raises(ValueError, match="identifier"):
        hub.gateway.resolve(receipt | {"artifact_id": "../another-cache"})
    snapshot = Path(receipt["local_path"])
    file = snapshot / "tokenizer.json"
    original = file.read_bytes()
    file.unlink()
    outside = hub.tmp / "outside"
    outside.write_bytes(original)
    file.symlink_to(outside)
    with pytest.raises(ValueError, match="missing or modified"):
        hub.gateway.resolve(receipt)


def test_explicit_host_endpoint_is_used_consistently_and_recorded(hub, monkeypatch):
    monkeypatch.setenv("HF_ENDPOINT", "https://operator-selected.example")
    gate = models.ModelGateway(hub.tmp / "mirror-cache")
    receipt = gate.download("example/model", CUTOFF)
    assert receipt["provenance"]["endpoint"] == "https://operator-selected.example"
    assert all(
        request.full_url.startswith("https://operator-selected.example/")
        for request in hub.requests
    )
    monkeypatch.setenv("HF_ENDPOINT", "http://insecure.example")
    with pytest.raises(ValueError, match="HTTPS"):
        models.ModelGateway(hub.tmp / "invalid")


def test_search_exposes_historical_receipts_not_current_model_descriptions(hub):
    result = hub.gateway.search("model", CUTOFF)
    assert result["results"][0]["revision"] == SHA
    assert "FUTURE DESCRIPTION" not in json.dumps(result) and "999999" not in json.dumps(result)
