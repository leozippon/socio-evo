"""Serve the published site locally, publishing it again as the runs change.

    python -m frontend.server --runs-root runs [--host 127.0.0.1] [--port 8765]
                              [--site DIR] [--interval SECONDS]

The server publishes the runs with `frontend.publish`, exactly as for a deployment, and
serves the site directory as static files, so a browser gets the published documents at the
same relative URLs. The site lives in a temporary directory unless `--site` names one to keep.
Every `--interval` seconds (5 by default) the runs are published again; a failure is printed
and the last complete site stays served.
"""

import argparse
import sys
import tempfile
import threading
import traceback
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from frontend.publish import Publisher


class _Handler(SimpleHTTPRequestHandler):
    """Static files of the site with the caching of the deployment: a URL with `?v=` names
    content that never changes; anything else is fetched afresh. No directory listings."""

    def list_directory(self, path: str) -> None:
        self.send_error(HTTPStatus.NOT_FOUND)

    def end_headers(self) -> None:
        settled = "v" in parse_qs(urlsplit(self.path).query)
        self.send_header(
            "Cache-Control", "public, max-age=31536000, immutable" if settled else "no-store"
        )
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} {format % args}", file=sys.stderr)


class DevServer(ThreadingHTTPServer):
    """Serves the site `publisher` writes, publishing it again every `interval` seconds while
    it serves."""

    def __init__(self, address: tuple[str, int], publisher: Publisher, interval: float) -> None:
        publisher.publish()
        super().__init__(address, partial(_Handler, directory=str(publisher.out)))
        self.publisher = publisher
        self.interval = interval
        self._stop = threading.Event()

    def serve_forever(self, poll_interval: float = 0.5) -> None:
        threading.Thread(target=self._refresh, daemon=True).start()
        super().serve_forever(poll_interval)

    def shutdown(self) -> None:
        self._stop.set()
        super().shutdown()

    def _refresh(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.publisher.publish()
            except Exception:
                traceback.print_exc()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m frontend.server", description="Serve the published runs locally."
    )
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--site", type=Path, help="keep the published site in this directory")
    parser.add_argument("--interval", type=float, default=5.0, metavar="SECONDS")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="socio-evo-site-") as scratch:
        publisher = Publisher(args.runs_root, args.site or Path(scratch))
        server = DevServer((args.host, args.port), publisher, args.interval)
        print(f"Serving {args.runs_root} at http://{args.host}:{server.server_address[1]}/")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
