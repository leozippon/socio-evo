"""Public Hugging Face model snapshots, pinned to the laboratory's historical cutoff.

Only the caller can admit a completed receipt into a checkpoint. This module writes to a
host-only cache, never the research Git tree, and never imports or executes model code.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ENDPOINT = "https://huggingface.co"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_ARTIFACT = re.compile(r"^hf-[0-9a-f]{32}$")
_LIMITATION = (
    "Hub commit dates do not prove historical public availability. Visibility and gating are "
    "checked now; historical branch state, search ranking and coverage are not reconstructed."
)


class _Unavailable(ValueError):
    pass


def _instant(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("A dated, timezone-aware model commit and simulation cutoff are required.")
    return value.astimezone(UTC)


def _cutoff(value: datetime) -> datetime:
    value = _instant(value)
    if value > datetime.now(UTC):
        raise ValueError("The model cutoff is in the real-world future.")
    return value


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _get(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _relative(value: str) -> PurePosixPath:
    if not isinstance(value, str):
        raise ValueError("The model repository contains an unsafe file path.")
    path = PurePosixPath(value)
    if (
        not value
        or not path.parts
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or str(path) != value
        or path.parts[0] in {".git", ".cache"}
    ):
        raise ValueError("The model repository contains an unsafe file path.")
    return path


def _cancelled(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Model download cancelled; no snapshot was admitted.")


def _client(endpoint: str):
    from huggingface_hub import HfApi

    return HfApi(endpoint=endpoint, token=False, library_name="socio-evo-model-gateway")


def _call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except Exception as error:
        status = getattr(getattr(error, "response", None), "status_code", None)
        detail = f"HTTP {status}" if status else type(error).__name__
        # Do not copy upstream error bodies or signed download URLs into resident records.
        raise ValueError(f"Hugging Face metadata request failed ({detail}).") from error


class _HTTPSRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise ValueError("Hugging Face download redirected outside HTTPS.")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _stream_file(
    repo_id: str,
    revision: str,
    file: dict,
    destination: Path,
    cancel: threading.Event | None,
    *,
    endpoint: str = ENDPOINT,
) -> dict:
    from huggingface_hub import hf_hub_url
    from huggingface_hub.utils import build_hf_headers

    url = hf_hub_url(repo_id, file["path"], revision=revision, endpoint=endpoint) + "?download=true"
    opener = build_opener(_HTTPSRedirects())  # Retains standard HTTPS_PROXY support.
    destination.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        _cancelled(cancel)
        sha256 = hashlib.sha256()
        git_blob = hashlib.sha1(f"blob {file['bytes']}\0".encode())
        size = 0
        try:
            headers = build_hf_headers(token=False, library_name="socio-evo-model-gateway")
            headers["Accept-Encoding"] = "identity"
            request = Request(url, headers=headers)
            with opener.open(request, timeout=60) as response, destination.open("wb") as output:
                if response.status != 200:
                    raise ValueError("Hugging Face did not return a complete model file.")
                while chunk := response.read(1024 * 1024):
                    _cancelled(cancel)
                    size += len(chunk)
                    if size > file["bytes"]:
                        raise ValueError("Downloaded model file exceeds its pinned metadata size.")
                    sha256.update(chunk)
                    git_blob.update(chunk)
                    output.write(chunk)
            _cancelled(cancel)
            if size != file["bytes"]:
                raise ValueError("Model file size does not match its pinned metadata.")
            if file.get("sha256") and sha256.hexdigest() != file["sha256"]:
                raise ValueError("Model LFS SHA-256 mismatch; the snapshot is incomplete.")
            if not file.get("sha256") and git_blob.hexdigest() != file["git_blob_sha1"]:
                raise ValueError("Model Git blob checksum mismatch; the snapshot is incomplete.")
            return file | {"sha256": sha256.hexdigest()}
        except HTTPError as error:
            if (error.code == 429 or 500 <= error.code < 600) and attempt < 2:
                retry = error.headers.get("Retry-After", "")
                wait = min(30, max(2 ** (attempt + 1), int(retry) if retry.isdigit() else 0))
                if cancel is not None:
                    cancel.wait(wait)
                else:
                    time.sleep(wait)
                continue
            raise ValueError(f"Hugging Face model download failed (HTTP {error.code}).") from error
        except URLError as error:
            raise ValueError("Hugging Face model download connection failed.") from error
    raise ValueError("Hugging Face model download retries exhausted.")


def _files(siblings) -> tuple[list[dict], list[str]]:
    files = []
    for sibling in siblings or []:
        path = str(_relative(_get(sibling, "rfilename", "")))
        size, blob, lfs = (_get(sibling, field) for field in ("size", "blob_id", "lfs"))
        if not isinstance(size, int) or size < 0:
            raise ValueError("Hugging Face did not provide every model file's size.")
        file = {"path": path, "bytes": size}
        if lfs is not None:
            digest = _get(lfs, "sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("Hugging Face did not provide a model LFS SHA-256.")
            if _get(lfs, "size") != size:
                raise ValueError("Hugging Face model LFS sizes disagree.")
            file["sha256"] = digest
        elif not isinstance(blob, str) or not _SHA.fullmatch(blob):
            raise ValueError("Hugging Face did not provide a model Git blob hash.")
        else:
            file["git_blob_sha1"] = blob
        files.append(file)
    if len({f["path"] for f in files}) != len(files):
        raise ValueError("The model repository contains duplicate file paths.")
    # Only remove alternate weights for components that actually have safetensors.
    # A separate component without a safetensors conversion must retain its PyTorch weights.
    safe_dirs = {
        str(PurePosixPath(f["path"]).parent) for f in files if f["path"].endswith(".safetensors")
    }
    excluded = []
    selected = []
    for file in files:
        path = PurePosixPath(file["path"])
        duplicate = str(path.parent) in safe_dirs and (
            re.fullmatch(r"pytorch_model(?:-\d+-of-\d+)?\.bin(?:\.index\.json)?", path.name)
            or path.name in {"tf_model.h5", "flax_model.msgpack", "tf_model.ckpt.index"}
            or path.name.startswith("tf_model.ckpt.data-")
        )
        (excluded if duplicate else selected).append(file["path"] if duplicate else file)
    return sorted(selected, key=lambda f: f["path"]), sorted(excluded)


class ModelGateway:
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.endpoint = os.environ.get("HF_ENDPOINT", ENDPOINT).rstrip("/")
        parsed = urlsplit(self.endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("HF_ENDPOINT must be HTTPS without credentials, query or fragment.")

    def info(self, repo_id: str, as_of: datetime, revision: str | None = None) -> dict:
        as_of = _cutoff(as_of)
        from huggingface_hub.utils import validate_repo_id

        validate_repo_id(repo_id)
        if revision is not None and not _SHA.fullmatch(revision):
            raise ValueError("Specify a full 40-character model commit SHA, or omit revision.")
        api = _client(self.endpoint)
        current = _call(api.model_info, repo_id, token=False, timeout=30)
        if _get(current, "private") is not False or _get(current, "gated") is not False:
            raise _Unavailable(
                "Only currently public, non-gated Hugging Face models are available."
            )
        created = _instant(_get(current, "created_at"))
        if created > as_of:
            raise _Unavailable("The model repository was created after the simulation cutoff.")
        commits = _call(
            api.list_repo_commits,
            repo_id,
            repo_type="model",
            revision=revision,
            token=False,
            formatted=False,
        )
        eligible = []
        for commit in commits:
            sha, date = _get(commit, "commit_id"), _instant(_get(commit, "created_at"))
            if not isinstance(sha, str) or not _SHA.fullmatch(sha):
                raise ValueError("Hugging Face returned an invalid model commit SHA.")
            if date <= as_of and (revision is None or sha == revision):
                eligible.append((date, sha))
        if not eligible:
            raise _Unavailable("No model commit is available at the simulation cutoff.")
        date, sha = max(eligible)
        pinned = _call(
            api.model_info, repo_id, revision=sha, files_metadata=True, token=False, timeout=30
        )
        if _get(pinned, "sha") != sha:
            raise ValueError("Hugging Face did not return the exact requested model commit.")
        files, excluded = _files(_get(pinned, "siblings"))
        if not files:
            raise ValueError("The selected model commit has no files.")
        return {
            "provider": "huggingface",
            "repo_id": repo_id,
            "revision": sha,
            "commit_time": _iso(date),
            "files": files,
            "total_bytes": sum(f["bytes"] for f in files),
            "excluded_files": excluded,
            "provenance": {
                "source_url": f"{self.endpoint}/{repo_id}/tree/{sha}",
                "endpoint": self.endpoint,
                "as_of": _iso(as_of),
                "retrieved_at": _iso(datetime.now(UTC)),
                "time_basis": "commit_created_at",
                "availability_verified": False,
                "limitation": _LIMITATION,
            },
        }

    def search(self, query: str, as_of: datetime, limit: int = 5) -> dict:
        as_of = _cutoff(as_of)
        if not query.strip() or not 1 <= limit <= 20:
            raise ValueError("Supply a model query and limit between 1 and 20.")
        api = _client(self.endpoint)
        # Only IDs are used from the current index: no present-day popularity/description.
        candidates = _call(
            lambda: list(api.list_models(search=query, gated=False, limit=limit * 3, token=False))
        )
        results = []
        for item in candidates:
            try:
                results.append(self.info(_get(item, "id"), as_of))
            except _Unavailable:
                continue
            if len(results) == limit:
                break
        return {
            "provider": "huggingface",
            "query": query,
            "as_of": _iso(as_of),
            "results": results,
            "note": "Discovery uses the current Hub index. " + _LIMITATION,
        }

    def download(
        self,
        repo_id: str,
        as_of: datetime,
        revision: str | None = None,
        *,
        cancel: threading.Event | None = None,
    ) -> dict:
        _cancelled(cancel)
        info = self.info(repo_id, as_of, revision)
        _cancelled(cancel)
        artifact_id = (
            "hf-" + hashlib.sha256((repo_id + "\n" + info["revision"]).encode()).hexdigest()[:32]
        )
        root = self.cache_dir / artifact_id
        if (root / "manifest.json").exists():
            return self._receipt(root, info)
        required, free = info["total_bytes"], shutil.disk_usage(self.cache_dir).free
        if required > free:
            raise ValueError(
                f"Insufficient model-cache disk space: need {required} bytes; {free} free."
            )
        try:
            with tempfile.TemporaryDirectory(prefix=".download-", dir=self.cache_dir) as temporary:
                staging = Path(temporary)
                snapshot = staging / "snapshot"
                snapshot.mkdir()
                downloaded = []
                for file in info["files"]:
                    _cancelled(cancel)
                    downloaded.append(
                        _stream_file(
                            repo_id,
                            info["revision"],
                            file,
                            snapshot / file["path"],
                            cancel,
                            endpoint=self.endpoint,
                        )
                    )
                names = {f["path"] for f in downloaded}
                if "config.json" not in names or not any(
                    name.endswith((".safetensors", ".bin")) for name in names
                ):
                    raise ValueError(
                        "This snapshot lacks a Transformers config or PyTorch weights."
                    )
                config = json.loads((snapshot / "config.json").read_text())
                for name in names:
                    if name.endswith((".safetensors.index.json", ".bin.index.json")):
                        index = json.loads((snapshot / name).read_text())
                        for shard in index.get("weight_map", {}).values():
                            path = str(PurePosixPath(name).parent / _relative(shard))
                            if path not in names:
                                raise ValueError("Model weight index references a missing shard.")
                manifest = {
                    "schema": 1,
                    "artifact_id": artifact_id,
                    "repo_id": repo_id,
                    "revision": info["revision"],
                    "commit_time": info["commit_time"],
                    "files": downloaded,
                    "downloaded_at": _iso(datetime.now(UTC)),
                    "remote_code_declared": bool(config.get("auto_map")),
                    "inference_validated": False,
                }
                (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
                _cancelled(cancel)
                try:
                    staging.rename(root)
                except FileExistsError:
                    # Another completed transfer may have won; validate its receipt below.
                    pass
            return self._receipt(root, info)
        except OSError as error:
            if error.errno == errno.ENOSPC:
                raise ValueError(
                    "Model-cache disk filled during download; no snapshot was admitted."
                ) from error
            raise

    def _receipt(self, root: Path, info: dict) -> dict:
        raw = (root / "manifest.json").read_bytes()
        manifest = json.loads(raw)
        receipt = info | {
            key: manifest[key]
            for key in (
                "artifact_id",
                "downloaded_at",
                "remote_code_declared",
                "inference_validated",
            )
        }
        receipt |= {"files": manifest["files"], "manifest_sha256": hashlib.sha256(raw).hexdigest()}
        receipt["local_path"] = str(self.resolve(receipt))
        return receipt

    def resolve(self, receipt: dict) -> Path:
        """Resolve a checkpoint-admitted receipt, never an arbitrary host directory."""
        artifact_id = receipt.get("artifact_id", "")
        if not isinstance(artifact_id, str) or not _ARTIFACT.fullmatch(artifact_id):
            raise ValueError("Invalid model artifact identifier.")
        root = self.cache_dir / artifact_id
        if root.is_symlink() or not root.is_dir():
            raise ValueError("The admitted model snapshot is unavailable.")
        manifest_path = root / "manifest.json"
        if manifest_path.is_symlink():
            raise ValueError("Model manifests cannot be symbolic links.")
        raw = manifest_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != receipt.get("manifest_sha256"):
            raise ValueError("Model manifest checksum does not match its admitted receipt.")
        manifest = json.loads(raw)
        if any(
            manifest.get(key) != receipt.get(key) for key in ("artifact_id", "repo_id", "revision")
        ):
            raise ValueError("Model manifest identity does not match its admitted receipt.")
        snapshot = root / "snapshot"
        if snapshot.is_symlink() or not snapshot.is_dir():
            raise ValueError("The model snapshot is unavailable.")
        for file in manifest["files"]:
            path = snapshot / _relative(file["path"])
            if (
                any(part.is_symlink() for part in (path, *path.parents) if part != self.cache_dir)
                or not path.is_file()
                or path.stat().st_size != file["bytes"]
            ):
                raise ValueError("The admitted model snapshot has a missing or modified file.")
        return snapshot
