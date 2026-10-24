"""Serve the timeline viewer of the runs under a directory.

    python -m frontend.server --runs-root runs [--host 127.0.0.1] [--port 8765]

    GET /                        the page and its static files
    GET /api/runs                [{"name": "smoke", "status": "running", "days": 2}, ...]
    GET /api/timeline?run=NAME   the timeline of that run (`frontend.timeline`)

A run is a directory directly under the root that holds a manifest; its status is the
manifest's and its days the last day checkpointed (0 before the first). An unknown run is a
404. Every response is sent with `Cache-Control: no-store`. The server only reads.
"""

from __future__ import annotations

import argparse
import json
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from frontend.timeline import timeline
from infrastructure.storage import RunDirectory

STATIC = Path(__file__).parent / "static"


def runs(root: Path) -> dict[str, RunDirectory]:
    """The runs under `root`, by name."""
    return {
        path.parent.name: RunDirectory(path.parent) for path in sorted(root.glob("*/manifest.json"))
    }


def summary(name: str, run: RunDirectory) -> dict[str, Any]:
    return {
        "name": name,
        "status": run.read_manifest().status.value,
        "days": run.latest_checkpoint() or 0,
    }


class Server(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], runs_root: Path) -> None:
        super().__init__(address, partial(Handler, directory=str(STATIC)))
        self.runs_root = runs_root


class Handler(SimpleHTTPRequestHandler):
    server: Server

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if not url.path.startswith("/api/"):
            super().do_GET()
            return
        found = runs(self.server.runs_root)
        try:
            if url.path == "/api/runs":
                self._json([summary(name, run) for name, run in found.items()])
                return
            if url.path == "/api/timeline":
                name = parse_qs(url.query).get("run", [""])[0]
                if name in found:
                    self._json(timeline(found[name].root))
                    return
                self._json({"error": f"no run named {name!r}"}, HTTPStatus.NOT_FOUND)
                return
        except (OSError, ValueError) as error:
            self._json(
                {"error": f"{type(error).__name__}: {error}"}, HTTPStatus.INTERNAL_SERVER_ERROR
            )
            return
        self._json({"error": f"no such endpoint {url.path}"}, HTTPStatus.NOT_FOUND)

    def list_directory(self, path: str | Path) -> None:
        self.send_error(HTTPStatus.NOT_FOUND)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m frontend.server", description="Serve the timeline viewer of the runs."
    )
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if not args.runs_root.is_dir():
        parser.error(f"{args.runs_root} is not a directory")
    server = Server((args.host, args.port), args.runs_root)
    print(f"Serving the runs under {args.runs_root} at http://{args.host}:{server.server_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
