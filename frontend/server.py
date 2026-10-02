"""Serve the town viewer and its read-only JSON API.

    python -m frontend.server --runs-root runs [--host 127.0.0.1] [--port 8765]

Routes, all GET (`<run>` is `<experiment>/<seed>`):

    /api/runs
    /api/runs/<run>/world
    /api/runs/<run>/events[?after=<seq>]
    /api/runs/<run>/evaluation
    /api/runs/<run>/agents/<agent>/history
    /api/runs/<run>/agents/<agent>/commits/<commit>/diff
    /api/runs/<run>/agents/<agent>/commits/<commit>/files

Everything else is a static file from `frontend/static`.
"""

import argparse
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from frontend.api import Api, NotFound

STATIC = Path(__file__).parent / "static"
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}


def route(api: Api, path: str, query: dict[str, list[str]]) -> Any:
    """The JSON answer for an API `path` (below `/api/`); raises NotFound for no such route."""
    parts = [unquote(part) for part in path.split("/")]
    match parts:
        case ["runs"]:
            return api.runs()
        case ["runs", experiment, seed, "world"]:
            return api.world(experiment, seed)
        case ["runs", experiment, seed, "events"]:
            try:
                after = int(query.get("after", ["-1"])[0])
            except ValueError:
                raise NotFound("`after` must be an integer") from None
            return api.events(experiment, seed, after)
        case ["runs", experiment, seed, "evaluation"]:
            return api.evaluation(experiment, seed)
        case ["runs", experiment, seed, "agents", agent, "history"]:
            return api.history(experiment, seed, agent)
        case ["runs", experiment, seed, "agents", agent, "commits", commit, "diff"]:
            return api.diff(experiment, seed, agent, commit)
        case ["runs", experiment, seed, "agents", agent, "commits", commit, "files"]:
            return api.files(experiment, seed, agent, commit)
    raise NotFound(f"no route /api/{path}")


def handler_for(api: Api) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            url = urlsplit(self.path)
            try:
                if url.path.startswith("/api/"):
                    body = json.dumps(
                        route(api, url.path.removeprefix("/api/"), parse_qs(url.query))
                    )
                    self._send(HTTPStatus.OK, "application/json", body.encode())
                else:
                    self._static(url.path)
            except NotFound as error:
                self._error(HTTPStatus.NOT_FOUND, str(error))
            except Exception as error:  # report, never crash the server thread silently
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(error).__name__}: {error}")

        def _static(self, path: str) -> None:
            name = "index.html" if path == "/" else path.lstrip("/")
            file = (STATIC / name).resolve()
            if not file.is_relative_to(STATIC.resolve()) or not file.is_file():
                raise NotFound(f"no file {path}")
            kind = TYPES.get(file.suffix, "application/octet-stream")
            self._send(HTTPStatus.OK, kind, file.read_bytes())

        def _error(self, status: HTTPStatus, message: str) -> None:
            self._send(status, "application/json", json.dumps({"error": message}).encode())

        def _send(self, status: HTTPStatus, kind: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            print(f"{self.address_string()} {format % args}", file=sys.stderr)

    return Handler


def make_server(runs_root: Path, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    """A server for `runs_root`; port 0 picks a free one."""
    if not runs_root.is_dir():
        raise FileNotFoundError(f"runs root {runs_root} is not a directory")
    return ThreadingHTTPServer((host, port), handler_for(Api(runs_root)))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Replay viewer for socio-evo runs.")
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    server = make_server(args.runs_root, args.host, args.port)
    print(f"Serving {args.runs_root} at http://{args.host}:{server.server_address[1]}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
