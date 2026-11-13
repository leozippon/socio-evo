"""Read-only research dashboard plus the original town viewer, on an independent port."""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import threading
import time
from collections import Counter
from functools import partial
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from frontend.publish import Publisher
from frontend.server import DevServer, _Handler
from frontend.timeline import timeline
from infrastructure.config import load_config
from simulation.config import ExperimentConfig
from world.log import Days


class ResearchData:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.lock = threading.Lock()
        self.logs = {}
        self.cache = {}
        self.records = {}

    def run(self, name: str) -> Path:
        if not re.fullmatch(r"[\w.-]+", name) or name.startswith("."):
            raise ValueError("Invalid run name")
        run = self.root / name
        if run.is_symlink() or not run.is_dir():
            raise FileNotFoundError(name)
        return run

    @staticmethod
    def git(run: Path, *args: str) -> bytes:
        return subprocess.check_output(
            ["git", "-C", str(run / "research"), *args], stderr=subprocess.PIPE, timeout=20
        )

    def entries(self, run: Path) -> list[dict]:
        path = run / "world.jsonl"
        offset, days = self.logs.get(run, (0, Days()))
        if not path.exists():
            return []
        if path.stat().st_size < offset:
            offset, days = 0, Days()
        with path.open("rb") as log:
            log.seek(offset)
            data = log.read()
        data = data[: data.rfind(b"\n") + 1]
        for line in data.splitlines():
            days.add(json.loads(line))
        self.logs[run] = (offset + len(data), days)
        return [e for day in days.lived() for e in day.entries]

    def snapshot(self, requested: str = "") -> dict:
        with self.lock:
            runs = sorted((p.parent.name for p in self.root.glob("*/manifest.json")), reverse=True)
            if not runs:
                return {"runs": [], "waiting": True}
            name = requested or runs[0]
            run = self.run(name)
            cached = self.cache.get(name)
            if cached and time.monotonic() - cached[0] < 3:
                return cached[1]
            config = load_config(run / "config.yaml", ExperimentConfig)
            if not config.town.research:
                raise ValueError("This is not a research experiment")
            manifest = json.loads((run / "manifest.json").read_text())
            entries = self.entries(run)
            data = timeline(run)
            now = data["now"]
            people = []
            for lane in data["residents"]:
                rc = next(r for r in config.town.residents if r.name == lane["name"])
                segment = lane["segments"][-1] if lane["segments"] else {}
                people.append(
                    {
                        "name": lane["name"],
                        "occupation": rc.occupation,
                        "state": segment.get("kind", "sleep"),
                        "place": data["places"].get(segment.get("place"), "On the way"),
                        "money": lane["purse"][-1][1],
                    }
                )
            revision = self.git(run, "rev-parse", "HEAD").decode().strip()
            files = self.file_index(run, revision)
            actions = [e for e in entries if e["kind"] == "research"]
            records = []
            for e in reversed(actions[-100:]):
                record = e["payload"]["record"]
                key = (run, record)
                if key not in self.records:
                    try:
                        raw = self.git(run, "show", f"{revision}:{record}")
                        item = json.loads(raw)
                    except subprocess.CalledProcessError:
                        continue
                    result = item.get("result", {})
                    self.records[key] = {
                        "path": record,
                        "actor": e["actor"],
                        "t": e["sim_time"],
                        "seq": e["seq"],
                        "tool": item["tool"],
                        "summary": str(
                            item["arguments"].get("command")
                            or item["arguments"].get("query")
                            or item["arguments"].get("url")
                            or item["arguments"].get("path", "")
                        )[:300],
                        "failed": bool(
                            result.get("error")
                            or result.get("cancelled")
                            or result.get("timed_out")
                            or result.get("exit_code")
                        ),
                    }
                records.append(self.records[key])
            counts = Counter(e["payload"]["action"] for e in actions)
            activity = [
                e
                for e in entries
                if e["kind"]
                in {
                    "research_brief",
                    "research_milestone",
                    "research",
                    "speech",
                    "message",
                    "announcement",
                    "start_work",
                    "leave_work",
                    "arrive",
                    "sleep",
                    "wake",
                    "cook",
                    "examination",
                    "treatment",
                }
            ]
            value = {
                "runs": runs,
                "run": name,
                "manifest": manifest,
                "days": config.days,
                "now": now,
                "people": people,
                "environment": "academy" if config.town.external_services else "town",
                "actor_model": config.llm.model,
                "currency": config.town.currency,
                "milestones": [
                    e["payload"] | {"record": f"records/milestone-{e['payload']['stage']}.json"}
                    for e in entries
                    if e["kind"] == "research_milestone"
                ],
                "scheduled_milestones": [
                    m.model_dump(mode="json") for m in config.town.research.milestones
                ],
                "comparison": self.comparison(runs),
                "revision": revision,
                "files": files,
                "records": records,
                "counts": dict(counts),
                "activity": [
                    {k: e[k] for k in ("seq", "kind", "sim_time", "actor", "text")}
                    for e in reversed(activity[-500:])
                ],
                "updated_at": time.time(),
            }
            self.cache[name] = (time.monotonic(), value)
            return value

    def comparison(self, runs: list[str]) -> list[dict]:
        rows = []
        for name in runs:
            run = self.run(name)
            config = load_config(run / "config.yaml", ExperimentConfig)
            if not config.town.research:
                continue
            manifest = json.loads((run / "manifest.json").read_text())
            milestones = [
                e["payload"] for e in self.entries(run) if e["kind"] == "research_milestone"
            ]
            rows.append(
                {
                    "run": name,
                    "environment": "academy" if config.town.external_services else "town",
                    "status": manifest["status"],
                    "people": len(config.town.residents),
                    "scores": {m["stage"]: m["score"] for m in milestones},
                    "reward_total": sum(m["reward_total"] for m in milestones),
                    "currency": config.town.currency,
                }
            )
        return rows

    def file_index(self, run: Path, revision: str) -> list[dict]:
        rows = self.git(run, "ls-tree", "-r", "-l", "-z", revision, "--", "files", "records")
        out = []
        for row in rows.split(b"\0"):
            if not row:
                continue
            meta, name = row.decode().split("\t", 1)
            mode, kind, oid, size = meta.split()
            if mode != "100644" and mode != "100755":
                continue
            out.append({"path": name, "bytes": int(size), "oid": oid})
        return out

    def file(self, name: str, path: str, revision: str = "") -> dict:
        run = self.run(name)
        revision = revision or self.git(run, "rev-parse", "HEAD").decode().strip()
        if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
            raise ValueError("Invalid revision")
        info = next((f for f in self.file_index(run, revision) if f["path"] == path), None)
        if info is None:
            raise FileNotFoundError("File is not a shared research artifact")
        if info["bytes"] > 8 * 1024 * 1024:
            return {**info, "text": "File exceeds the 8 MiB preview limit.", "revision": revision}
        content = self.git(run, "show", f"{revision}:{path}")
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(
            Path(path).suffix.lower()
        )
        value = {**info, "revision": revision}
        if mime:
            value["image"] = f"data:{mime};base64," + base64.b64encode(content).decode()
        else:
            value["text"] = content[:300000].decode("utf-8", errors="replace")
            value["truncated"] = len(content) > 300000
        return value


class Handler(_Handler):
    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/research.html")
            self.end_headers()
            return
        if url.path.startswith("/api/"):
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if url.path == "/api/research":
                    result = self.server.research.snapshot(q.get("run", ""))
                elif url.path == "/api/research/file":
                    result = self.server.research.file(
                        q.get("run", ""), q.get("path", ""), q.get("revision", "")
                    )
                else:
                    raise FileNotFoundError("Unknown endpoint")
                status = HTTPStatus.OK
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                result, status = {"error": str(error)}, HTTPStatus.BAD_REQUEST
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8918)
    args = parser.parse_args()
    publisher = Publisher(args.runs_root, args.site)
    server = DevServer(("127.0.0.1", args.port), publisher, 10)
    server.research = ResearchData(args.runs_root)
    server.RequestHandlerClass = partial(Handler, directory=str(publisher.out))
    print(f"Research viewer ready on http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
