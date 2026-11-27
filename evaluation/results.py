"""Where the evaluations write, and how a result is begun, resumed and finished.

    results/<run>/day-NN/<benchmark>/<resident>.json    a resident's adapter at day NN
    results/models/<benchmark>/<model>.json              a bare served model: the base, which
                                                         stands for every resident on day 0, and
                                                         the reference

`<benchmark>` is `safety` or `mask`, or, for the safety instruments scored only in part,
`safety-<instrument>-...`, which lies apart from the full results (`evaluation.safety`). Beside
each result, `.jsonl` holds one record per item
(safety) or per scenario (MASK), appended as each is finished. The result is written when the
evaluation begins, with `status: running`, the header (the subject and everything that decides
its answers and their verdicts, the judge's reading rules by the digest of their files among it)
and the provenance (the code revision and the run whose settings were taken, which decide
nothing and are not compared), and written again when it ends, with `status: finished` and the
metrics. An evaluation run again refuses a finished result and resumes a running one, asking only
what its records lack; a header other than the one recorded is an error, since the records would
then mix two evaluations. A final record cut short by a killed process is dropped and asked again.
One process at a time holds a result, by a lock on `.lock` beside it, so that two arms' queues
that both come for the shared base model cannot write it together.
"""

import fcntl
import hashlib
import json
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Any

from infrastructure.storage import append_jsonl, day_tag, read_jsonl, write_json

MODELS = "models"
"""The directory of the bare models' results, beside the runs'."""
ROOT = Path(__file__).resolve().parents[1]


def digest(*paths: Path) -> str:
    """The hash of the files `paths`, each named by its path in the project, in order."""
    hashed = hashlib.sha256()
    for path in paths:
        hashed.update(f"{path.resolve().relative_to(ROOT)}\n".encode())
        hashed.update(path.read_bytes())
    return hashed.hexdigest()


def revision() -> str | None:
    """The project's checked-out commit, None where git cannot tell it."""
    found = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return found.stdout.strip() or None


class Status(StrEnum):
    RUNNING = "running"
    FINISHED = "finished"


def resident_result(results: Path, run: str, day: int, benchmark: str, resident: str) -> Path:
    """The result of `resident`'s adapter at `day` of `run` on `benchmark`."""
    return results / run / day_tag(day) / benchmark / f"{resident}.json"


def model_result(results: Path, benchmark: str, model: str) -> Path:
    """The result of the bare served model `model` on `benchmark`."""
    return results / MODELS / benchmark / f"{model}.json"


def read_result(path: Path) -> dict[str, Any]:
    """The finished result at `path` with its records; ValueError when it has not finished."""
    result = json.loads(path.read_text(encoding="utf-8"))
    if result["status"] != Status.FINISHED:
        raise ValueError(f"{path}: the evaluation has not finished")
    return result | {"records": list(read_jsonl(path.with_suffix(".jsonl")))}


class Store:
    """The result at `path` and its records."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.records = path.with_suffix(".jsonl")

    @property
    def finished(self) -> bool:
        return self.path.exists() and self._read()["status"] == Status.FINISHED

    @contextmanager
    def held(self) -> Iterator[None]:
        """The result held by this process alone for as long as the context lasts, by a lock on
        `<stem>.lock` beside it; RuntimeError when another process holds it."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError(f"{self.path} is being evaluated by another process") from None
            yield

    def begin(
        self, header: dict[str, Any], provenance: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """The records of the evaluation `header` describes kept so far, none for a new one,
        whose `provenance` is then recorded. FileExistsError for a finished result; ValueError for
        one of another header, or records without a result."""
        header = json.loads(json.dumps(header))
        if self.path.exists():
            found = self._read()
            if found["status"] == Status.FINISHED:
                raise FileExistsError(f"{self.path} is finished; it is never overwritten")
            if found["header"] != header:
                differ = sorted(
                    key
                    for key in found["header"].keys() | header.keys()
                    if found["header"].get(key) != header.get(key)
                )
                raise ValueError(
                    f"{self.path} was begun with another {', '.join(differ)}: resuming would mix "
                    "two evaluations"
                )
            return self._kept()
        if self.records.exists():
            raise ValueError(f"{self.records} has no result beside it")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        document = {"status": Status.RUNNING, "header": header, "provenance": provenance or {}}
        write_json(self.path, document)
        return []

    def add(self, record: dict[str, Any]) -> None:
        append_jsonl(self.records, record)

    def finish(self, header: dict[str, Any], metrics: dict[str, Any]) -> None:
        provenance = self._read().get("provenance", {})
        write_json(
            self.path,
            {
                "status": Status.FINISHED,
                "header": header,
                "provenance": provenance,
                "metrics": metrics,
            },
        )

    def _kept(self) -> list[dict[str, Any]]:
        """The records kept; a final one cut short, as a process killed while writing it leaves
        it, is dropped, so that its item is asked again."""
        if not self.records.exists():
            return []
        written = self.records.read_bytes()
        if written and not written.endswith(b"\n"):
            whole = written[: written.rfind(b"\n") + 1]
            self.records.write_bytes(whole)
            print(f"{self.records}: a final record cut short is dropped and asked again")
        return list(read_jsonl(self.records))

    def _read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))
