"""Local experiment display names and recoverable deletion; run identities stay stable."""

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path


class ManagementError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def display_name(experiment: Path) -> str | None:
    path = experiment / ".display.json"
    if not path.is_file():
        return None
    value = json.loads(path.read_text()).get("display_name")
    return value if isinstance(value, str) and value.strip() else None


def manage(runs_root: Path, request: dict) -> dict:
    """Called under the server's publication lock. No experiment paths come from labels."""
    name = request.get("experiment")
    if not isinstance(name, str) or not re.fullmatch(r"[\w.-]+", name) or name.startswith("."):
        raise ManagementError("Invalid experiment identifier.")
    root = runs_root.resolve()
    experiment = root / name
    if experiment.is_symlink() or experiment.resolve().parent != root:
        raise ManagementError("Invalid experiment path.")
    manifests = sorted(experiment.glob("seed-*/manifest.json"))
    if not experiment.is_dir() or not manifests:
        raise ManagementError("Experiment not found.", 404)
    if request.get("action") == "rename":
        label = request.get("display_name")
        if (
            not isinstance(label, str)
            or not 1 <= len(label.strip()) <= 120
            or any(ord(c) < 32 or ord(c) == 127 for c in label)
        ):
            raise ManagementError("Enter a name of 1–120 characters without control characters.")
        label = label.strip()
        temp = experiment / f".display-{uuid.uuid4().hex}.tmp"
        try:
            temp.write_text(json.dumps({"display_name": label}, ensure_ascii=False) + "\n")
            temp.replace(experiment / ".display.json")
        finally:
            temp.unlink(missing_ok=True)
        return {"experiment": name, "display_name": label}
    if request.get("action") == "delete":
        if request.get("confirm") != name:
            raise ManagementError("Confirm the exact experiment identifier before deleting.")
        # Fail closed on unknown states: only settled or explicitly interrupted runs move.
        if any(
            json.loads(p.read_text()).get("status") not in ("completed", "interrupted", "failed")
            for p in manifests
        ):
            raise ManagementError("Stop all running seeds before deleting this experiment.", 409)
        trash = root / ".trash"
        if trash.is_symlink():
            raise ManagementError("Invalid recovery directory.")
        trash.mkdir(exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = trash / f"{name}-{stamp}-{uuid.uuid4().hex[:8]}"
        experiment.rename(target)
        return {"experiment": name, "deleted": True, "recovery_path": str(target)}
    raise ManagementError("Unknown experiment operation.")
