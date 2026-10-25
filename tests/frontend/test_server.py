"""The viewer's server: the list of runs, a run's timeline, the progress of every run, a missing
run, the page, and no caching anywhere."""

from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from urllib.request import urlopen

from frontend.progress import progress
from frontend.server import Server
from frontend.timeline import timeline
from tests.frontend.conftest import live_a_day, new_town


def get(url: str) -> tuple[int, str, str, bytes]:
    try:
        with urlopen(url) as response:
            return (
                response.status,
                response.headers["Cache-Control"],
                response.headers["Content-Type"],
                response.read(),
            )
    except HTTPError as error:
        return (
            error.code,
            error.headers["Cache-Control"],
            error.headers["Content-Type"],
            (error.read()),
        )


async def test_the_endpoints_serve_runs_and_timelines_and_a_missing_run_is_404(tmp_path):
    run, town = new_town(tmp_path)
    await live_a_day(town)
    await town.close()
    run.checkpoint_path(1).write_text(json.dumps(town.checkpoints[0][1]))
    (tmp_path / "not-a-run").mkdir()
    server = Server(("127.0.0.1", 0), tmp_path)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, cache, kind, body = get(f"{base}/api/runs")
        assert (status, cache, kind) == (200, "no-store", "application/json; charset=utf-8")
        assert json.loads(body) == [{"name": "town", "status": "running", "days": 1}]

        status, cache, _, body = get(f"{base}/api/timeline?run=town")
        assert (status, cache) == (200, "no-store")
        assert json.loads(body) == json.loads(json.dumps(timeline(run.root)))

        status, cache, _, body = get(f"{base}/api/progress")
        assert (status, cache) == (200, "no-store")
        expected = {"name": "town", "status": "running", "days": 1} | progress(timeline(run.root))
        assert json.loads(body) == [json.loads(json.dumps(expected))]

        for missing in ("nope", "not-a-run", "town/..", ""):
            status, cache, _, body = get(f"{base}/api/timeline?run={missing}")
            assert (status, cache) == (404, "no-store") and "error" in json.loads(body)
        assert get(f"{base}/api/elsewhere")[0] == 404

        status, cache, kind, body = get(f"{base}/")
        assert (status, cache, kind) == (200, "no-store", "text/html")
        assert b"<title>Run timeline</title>" in body
        assert get(f"{base}/app.js")[:2] == (200, "no-store")
        assert get(f"{base}/missing.js")[0] == 404
    finally:
        server.shutdown()
        server.server_close()
