"""The development server: it serves exactly the published site, settled files as immutable
and everything else uncached, with no directory listings and nothing outside the site."""

from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from urllib.parse import quote, urljoin
from urllib.request import urlopen

from frontend.publish import Publisher
from frontend.server import DevServer
from tests.support.runs import RUN, files, make_run


async def test_the_dev_server_serves_exactly_the_published_site(tmp_path, capsys):
    runs = tmp_path / "runs"
    await make_run(runs)
    Publisher(runs, tmp_path / "site").publish()
    published = files(tmp_path / "site")
    server = DevServer(("127.0.0.1", 0), Publisher(runs, tmp_path / "served"), 0.1)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/"

    def get(path: str) -> tuple[int, bytes, str | None]:
        try:
            with urlopen(urljoin(base, path)) as response:
                return response.status, response.read(), response.headers["Cache-Control"]
        except HTTPError as error:
            return error.code, b"", None

    try:
        for name, data in published.items():
            assert get(quote(name))[:2] == (200, data)
        assert get("")[1] == published["index.html"]
        run = json.loads(published[f"{RUN}/run.json"])
        assert get(f"{RUN}/{run['world']}")[2] == "public, max-age=31536000, immutable"
        assert get(f"{RUN}/{run['timeline']}")[2] == "no-store"
        assert get("data/index.json")[2] == "no-store"
        for missing in ("data/", "data/runs/", "%2e%2e/%2e%2e/etc/passwd", "data/nothing.json"):
            assert get(missing)[0] == 404
    finally:
        server.shutdown()
        server.server_close()
    assert capsys.readouterr().out.startswith(f"{tmp_path / 'served'}: ")
