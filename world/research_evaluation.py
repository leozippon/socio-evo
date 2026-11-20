"""Optional, one-batch held-out retrieval scoring; never execute resident code.

Operator workflow (all files stay on the experiment host):

1. Provision ``run_dir/research_evaluations/<id>.json`` outside the research Git tree
   and all container mounts. Use genuinely withheld labels, not previously inspected
   HotpotQA answers or another exposed test set. The operator declares ``labels_unseen``;
   this module cannot independently establish dataset independence or PIT eligibility.
2. The JSON object has ``id``, ``title``, ``split``, ``metric`` (``hit_at_k`` or
   ``recall_at_k``), positive integer ``top_k`` and ``max_calls``, preselected ``variants``
   (a list of IDs), ``labels_unseen: true``, ``label_provenance`` (private), and ``queries``.
   Each query has ``id``, private nonempty ``relevant_ids``, and optional public ``input``.
   First visibility freezes the entire definition privately. Do not change it thereafter.
3. Residents inspect ``evaluation list/open``, prepare all variants without score feedback,
   and commit one shared JSON file: ``{"benchmark_id": "...", "variants": [{"id": "...",
   "predictions": [{"query_id": "...", "retrieved_ids": ["doc1"], "calls": 1}]}]}``.
   Every declared variant must cover every query exactly once with exactly ``top_k``
   distinct document IDs. ``calls`` is a declaration bounded by ``max_calls``; actual
   retrieval calls, runtime and compute equality are NOT verified.
4. Submit ``benchmark_id``, a full committed ``revision``, and the JSON ``path`` under
   shared files. Only that Git blob is read; scripts in the snapshot are never executed.
   All variants receive aggregate scores in one final batch, rounded to three decimals.
   No labels, per-query scores, confidence feedback or partial variant scores are returned.

Private frozen definitions and final receipts live in ``research_evaluation_state``;
they must be preserved across restore, migration and forks of the same experiment.
The public receipt in research/records is checkpointed by Research.call. Its removal by
checkpoint rollback does not replenish the evaluation budget: an identical replay only
restores the original receipt, and different predictions cannot receive another score.
Reprovisioning the same exposed labels under another ID/run defeats this protocol and is
an operator error, not a fresh held-out evaluation. No benchmark is installed by default.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from infrastructure.git import GitError

MAX_BYTES = 8 * 1024 * 1024
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys are not accepted.")
        result[key] = value
    return result


def _json(raw: bytes) -> Any:
    if len(raw) > MAX_BYTES:
        raise ValueError("Evaluation JSON exceeds 8 MiB.")
    try:
        value = json.loads(raw, object_pairs_hook=_object_pairs)
        _canonical(value)  # Reject NaN/Infinity, including in optional public inputs.
        return value
    except (UnicodeError, ValueError, TypeError) as error:
        raise ValueError("Evaluation input must be valid JSON without duplicate keys.") from error


def _read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Evaluation file is missing, unsafe or exceeds 8 MiB.")
    return path.read_bytes()


def _write(path: Path, value: Any, *, private: bool = True) -> None:
    """Persist before disclosing; a crash cannot replenish the one-batch budget."""
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".evaluation-")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600 if private else 0o644)
            stream.write(_canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("Use a benchmark or variant ID containing letters, digits, _ or -.")
    return value


def _strings(value: Any) -> bool:
    return (isinstance(value, list) and bool(value)
            and all(isinstance(item, str) and bool(item) for item in value)
            and len(set(value)) == len(value))


def _definition(value: Any, identifier: str) -> dict:
    """Validation errors deliberately never interpolate private labels or inputs."""
    def require(condition):
        if not condition:
            raise ValueError("Invalid benchmark definition.")

    try:
        require(isinstance(value, dict) and value["id"] == identifier)
        require(all(isinstance(value[key], str) and value[key]
                    for key in ("title", "split", "label_provenance")))
        require(value["labels_unseen"] is True)
        require(value["metric"] in {"hit_at_k", "recall_at_k"})
        require(all(type(value[key]) is int and value[key] > 0
                    for key in ("top_k", "max_calls")))
        require(_strings(value["variants"]))
        for variant in value["variants"]:
            _identifier(variant)
        queries = value["queries"]
        require(isinstance(queries, list) and queries)
        require(_strings([query["id"] for query in queries]))
        require(all(_strings(query["relevant_ids"]) for query in queries))
        return value
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Operator benchmark definition is invalid; no evaluation is available.") \
            from error


def _public(definition: dict) -> dict:
    return {
        **{key: definition[key] for key in
           ("id", "title", "split", "metric", "top_k", "max_calls", "variants")},
        "queries": [{"id": query["id"], **({"input": query["input"]}
                                          if "input" in query else {})}
                    for query in definition["queries"]],
        "label_visibility": "operator_declared_unseen",
        "independence_verified": False,
        "actual_compute_verified": False,
        "strategy_execution_verified": False,
        "calls_policy": "self-declared per-query upper bound; not measured execution",
        "evaluation_policy": "one final batch containing every predeclared variant",
    }


class EvaluationDesk:
    """Called synchronously under the research lock; also serializes host-side writers."""

    def __init__(self, research):
        self.research = research
        self.source = research.root.parent / "research_evaluations"
        self.state = research.root.parent / "research_evaluation_state"

    def call(self, args: dict) -> dict:
        action = args.get("action")
        if action not in {"list", "open", "submit"}:
            raise ValueError("Evaluation action must be list, open or submit.")
        if self.source.is_symlink() or self.state.is_symlink():
            raise ValueError("Evaluation directories must not be symbolic links.")
        self.state.mkdir(mode=0o700, exist_ok=True)
        with (self.state / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if action == "list":
                items = []
                for path in sorted(self.source.glob("*.json")):
                    item = self._open(_identifier(path.stem))
                    item["query_count"] = len(item.pop("queries"))
                    items.append(item)
                return {"benchmarks": items, "available": bool(items)}
            identifier = _identifier(args.get("benchmark_id"))
            definition = self._freeze(identifier)
            if action == "open":
                return self._open(identifier, definition)
            return self._submit(identifier, definition, args)

    def _freeze(self, identifier: str) -> dict:
        path = self.state / identifier
        if path.is_symlink():
            raise ValueError("Unsafe evaluation state.")
        source = self.source / f"{identifier}.json"
        if not source.exists():
            raise ValueError("No operator-provisioned benchmark with that ID is available.")
        try:
            definition = _definition(_json(_read(source)), identifier)
        except ValueError as error:
            raise ValueError("Operator benchmark definition is invalid or unavailable.") from error
        path.mkdir(mode=0o700, exist_ok=True)
        frozen = path / "definition.json"
        if frozen.exists():
            if _canonical(_json(_read(frozen))) != _canonical(definition):
                raise ValueError("The benchmark definition changed after it was frozen; "
                                 "unavailable.")
        else:
            _write(frozen, definition)
        return definition

    def _open(self, identifier: str, definition: dict | None = None) -> dict:
        metadata = _public(definition or self._freeze(identifier))
        final = self.state / identifier / "final.json"
        metadata["already_evaluated"] = final.exists()
        if final.exists():
            receipt = _json(_read(final))
            self._publish(identifier, receipt)
            metadata["previous_receipt"] = receipt
        return metadata

    def _artifact(self, args: dict, *, require_ancestor: bool) -> tuple[str, str, bytes]:
        revision = args.get("revision")
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40,64}", revision):
            raise ValueError("Submit a full committed research revision.")
        raw_path = args.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            raise ValueError("Submit a prediction JSON path within shared files.")
        path = PurePosixPath(raw_path)
        if path.is_absolute() or any(part in {"..", ".git"} for part in path.parts):
            raise ValueError("Prediction path must remain within shared files.")
        if not path.parts or path.parts[0] == "records" or path.suffix != ".json":
            raise ValueError("Submit a prediction JSON path within shared files.")
        # Shared tool paths normally omit files/. Also accept the explicit repository path.
        relative = path if path.parts[0] == "files" else PurePosixPath("files") / path
        repo = self.research.repo
        try:
            if require_ancestor:
                repo._git("merge-base", "--is-ancestor", revision, repo.head())
            entry = repo._git("ls-tree", "-z", revision, "--", str(relative))
            info, found = entry.rstrip("\0").split("\t", 1)
            mode, kind, oid = info.split()
            if found != str(relative) or kind != "blob" or mode not in {"100644", "100755"}:
                raise ValueError("Not a regular prediction artifact.")
            if int(repo._git("cat-file", "-s", oid)) > MAX_BYTES:
                raise ValueError("Prediction artifact exceeds 8 MiB.")
            raw = repo.blobs([oid])[oid]
        except (GitError, ValueError) as error:
            raise ValueError("Prediction artifact must be a regular committed file in this "
                             "history.") from error
        return revision, str(relative), raw

    def _scores(self, definition: dict, batch: Any) -> list[dict]:
        if not isinstance(batch, dict) or batch.get("benchmark_id") != definition["id"]:
            raise ValueError("Prediction batch must name this benchmark_id.")
        variants = batch.get("variants")
        expected = definition["variants"]
        if (not isinstance(variants, list) or not all(isinstance(v, dict) for v in variants)
                or len(variants) != len(expected)
                or not _strings([v.get("id") for v in variants])
                or {v.get("id") for v in variants} != set(expected)):
            raise ValueError("Submit all predeclared variants exactly once in one final batch.")
        query_ids = {query["id"] for query in definition["queries"]}
        checked = {}
        # Validate the whole batch before looking at any label or computing any score.
        for variant in variants:
            predictions = variant.get("predictions")
            if (not isinstance(predictions, list)
                    or not all(isinstance(p, dict) for p in predictions)
                    or len(predictions) != len(query_ids)
                    or not _strings([p.get("query_id") for p in predictions])
                    or {p.get("query_id") for p in predictions} != query_ids):
                raise ValueError("Every variant must predict each public query exactly once.")
            for prediction in predictions:
                ids = prediction.get("retrieved_ids")
                calls = prediction.get("calls")
                if not _strings(ids) or len(ids) != definition["top_k"]:
                    raise ValueError("Each prediction needs exactly top_k distinct document IDs.")
                if type(calls) is not int or not 0 <= calls <= definition["max_calls"]:
                    raise ValueError("Each prediction needs declared calls within max_calls.")
            checked[variant["id"]] = {p["query_id"]: p for p in predictions}
        scores = []
        for variant in expected:
            values = []
            for query in definition["queries"]:
                predicted = set(checked[variant][query["id"]]["retrieved_ids"])
                relevant = set(query["relevant_ids"])
                hits = len(predicted & relevant)
                values.append(float(hits > 0) if definition["metric"] == "hit_at_k"
                              else hits / len(relevant))
            scores.append({"variant": variant, "score": round(sum(values) / len(values), 3)})
        return scores

    def _submit(self, identifier: str, definition: dict, args: dict) -> dict:
        final = self.state / identifier / "final.json"
        replay = final.exists()
        revision, path, raw = self._artifact(args, require_ancestor=not replay)
        fingerprint = {"revision": revision, "path": path, "predictions_sha256": _hash(raw)}
        if replay:
            receipt = _json(_read(final))
            if receipt["submission"] != fingerprint:
                raise ValueError("This benchmark was already disclosed; changed submissions "
                                 "cannot receive another score.")
        else:
            scores = self._scores(definition, _json(raw))
            receipt = {
                "benchmark_id": identifier,
                "public_contract_sha256": _hash(_canonical(_public(definition))),
                "submission": fingerprint,
                "metric": definition["metric"], "split": definition["split"],
                "query_count": len(definition["queries"]), "top_k": definition["top_k"],
                "max_calls": definition["max_calls"], "actual_compute_verified": False,
                "strategy_execution_verified": False,
                "calls_policy": "self-declared per-query upper bound; not measured execution",
                "label_visibility": "operator_declared_unseen", "independence_verified": False,
                "evaluation_count": 1, "scores": scores,
                "disclosed_at": datetime.now(UTC).isoformat(),
            }
            _write(final, receipt)
        public = self._publish(identifier, receipt)
        return {**receipt, "record": f"records/{public.name}", "previously_disclosed": replay}

    def _publish(self, identifier: str, receipt: dict) -> Path:
        # A rollback may remove the public record. The private final always remains authoritative.
        public = self.research.records / f"evaluation-{identifier}.json"
        if public.is_symlink():
            raise ValueError("Unsafe evaluation receipt path.")
        _write(public, receipt, private=False)
        return public
