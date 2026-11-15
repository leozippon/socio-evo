"""Historical content selection and real bytes, rather than date-filtered live snippets."""

import gzip
import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from world import research_browser as browser

OLD = "1" * 40
NEW = "2" * 40
CUTOFF = datetime(2025, 6, 1, tzinfo=UTC)
HISTORY = """<div class="submission-history"><h2>Submission history</h2>
<strong><a>[v1]</a></strong> Wed, 1 Jan 2025 10:00:00 UTC<br/>
<strong>[v2]</strong> Tue, 1 Jul 2025 10:00:00 UTC</div>"""


def paper_html(identifier="2501.00001", version=1):
    title = "Historical result" if version == 1 else "FUTURE TITLE"
    abstract = "Evidence available in v1." if version == 1 else "FUTURE ABSTRACT"
    return f"""<html><head>
      <meta name="citation_pdf_url" content="https://arxiv.org/pdf/{identifier}">
      </head><body><strong>arXiv:{identifier}v{version}</strong>
      <h1 class="title mathjax"><span>Title:</span>{title}</h1>
      <div class="authors">Authors:<a href="/search/?searchtype=author">A Researcher</a></div>
      <blockquote class="abstract mathjax"><span>Abstract:</span>{abstract}</blockquote>
      <a class="abs-button download-pdf" href="/pdf/{identifier}v{version}">PDF</a>
      {HISTORY}</body></html>"""


def commit(sha=OLD):
    return {
        "sha": sha,
        "commit": {
            "committer": {"date": "2025-01-01T10:00:00Z" if sha == OLD else "2025-07-01T10:00:00Z"}
        },
    }


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    calls = []
    pdf = b"%PDF-1.4\n" + b"x" * (9 * 1024 * 1024)
    archive = gzip.compress(b"fixed repository source")

    def receive(url, destination, maximum):
        calls.append(url)
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        mime = "application/json"
        if parsed.hostname == "arxiv.org" and parsed.path.startswith("/abs/"):
            identifier = parsed.path.removeprefix("/abs/")
            body = (
                paper_html(*[identifier.rsplit("v", 1)[0], int(identifier.rsplit("v", 1)[1])])
                if "v" in identifier
                else HISTORY
            )
            mime = "text/html"
        elif parsed.hostname == "arxiv.org" and parsed.path == "/search/advanced":
            assert "advanced=" in url and query["size"] == ["50"]
            start = int(query["start"][0])
            body = f"<h1>Showing {start + 1}–{min(start + 50, 55)} of 55 results</h1><ol>"
            body += "".join(
                f'<li class="arxiv-result"><p class="list-title">'
                f'<a href="https://arxiv.org/abs/2501.{n:05d}">arXiv:{n}</a></p>'
                "<p>FUTURE TITLE AND ABSTRACT</p></li>"
                for n in range(start + 1, min(start + 51, 56))
            )
            body += "</ol>"
            mime = "text/html"
        elif parsed.hostname == "arxiv.org" and parsed.path.startswith("/pdf/"):
            body, mime = pdf, "application/pdf"
        elif parsed.path == "/search/repositories":
            body = {
                "total_count": 7,
                "incomplete_results": False,
                "items": [
                    {
                        "full_name": "example/project",
                        "created_at": "2024-01-01T00:00:00Z",
                        "private": False,
                        "description": "FUTURE DESCRIPTION",
                        "stargazers_count": 999999,
                    }
                ],
            }
        elif parsed.path == "/repos/example/project":
            body = {"private": False, "created_at": "2024-01-01T00:00:00Z"}
        elif parsed.path.endswith("/commits"):
            assert query["until"] == ["2025-06-01T00:00:00Z"]
            body = [commit()]
        elif "/commits/" in parsed.path:
            body = commit(parsed.path.rsplit("/", 1)[1])
        elif parsed.path.endswith("/readme"):
            assert query["ref"] in ([OLD], [NEW])
            body = {"path": "README.md"}
        elif "/contents/" in parsed.path:
            assert query["ref"] == [OLD]
            body = [
                {"type": "file", "name": "README.md", "path": "README.md"},
                {"type": "file", "name": "train.py", "path": "train.py"},
                {"type": "dir", "name": "src", "path": "src"},
            ]
        elif parsed.hostname == "raw.githubusercontent.com":
            assert f"/{OLD}/" in parsed.path
            body = (
                "# Historical README\n" + "\n".join(f"line {n}" for n in range(300))
                if parsed.path.endswith("README.md")
                else "print('historical code')\n"
            )
            mime = "text/plain"
        elif "/tarball/" in parsed.path or "/zipball/" in parsed.path:
            assert parsed.path.endswith(OLD)
            body, mime = archive, "application/gzip"
        else:
            raise AssertionError("Unexpected source " + url)
        if isinstance(body, dict) or isinstance(body, list):
            body = json.dumps(body)
        if isinstance(body, str):
            body = body.encode()
        if len(body) > maximum:
            raise ValueError("Fixture exceeds requested limit")
        destination.write_bytes(body)
        return url, mime

    monkeypatch.setattr(browser, "_receive", receive)
    return browser.BrowserGateway(tmp_path / "host-only-cache"), calls, pdf, archive


def test_arxiv_search_reconstructs_old_abstract_and_versioned_links(gateway):
    gate, calls, *_ = gateway
    result = gate.search("arxiv", "research", CUTOFF)
    paper = result["results"][0]
    assert paper["title"] == "Historical result"
    assert paper["abstract"] == "Evidence available in v1."
    assert all(link["url"].endswith("v1") for link in paper["links"])
    assert result["has_more"] and result["next_page"] == 2
    assert "FUTURE" not in json.dumps(result) and "v2" not in json.dumps(result)
    assert paper["provenance"]["availability_verified"] is False
    assert "current search index" in result["note"]
    assert not any("export.arxiv.org" in url for url in calls)
    second = gate.search("arxiv", "research", CUTOFF, page=2)
    assert second["results"][0]["version"] == "2501.00006v1"
    tenth = gate.search("arxiv", "research", CUTOFF, page=10)
    last = gate.search("arxiv", "research", CUTOFF, page=11)
    assert tenth["results"][0]["version"] == "2501.00046v1"
    assert last["results"][0]["version"] == "2501.00051v1" and not last["has_more"]
    searches = [url for url in calls if "/search/advanced" in url]
    assert len(searches) == 2 and "start=50" in searches[-1]


def test_future_versions_remain_blocked_after_a_later_view_is_cached(gateway, tmp_path):
    gate, calls, *_ = gateway
    later = gate.open("https://arxiv.org/abs/2501.00001", datetime(2025, 8, 1, tzinfo=UTC))
    assert later["version"].endswith("v2")
    earlier = gate.open("https://arxiv.org/abs/2501.00001", CUTOFF)
    assert earlier["version"].endswith("v1") and "FUTURE" not in earlier["text"]
    for method in (
        lambda: gate.open("https://arxiv.org/abs/2501.00001v2", CUTOFF),
        lambda: gate.download(
            "https://arxiv.org/pdf/2501.00001v2", CUTOFF, tmp_path / "future.pdf"
        ),
    ):
        with pytest.raises(ValueError, match="cutoff"):
            method()
    assert not (tmp_path / "future.pdf").exists()
    assert not any("/pdf/2501.00001v2" in url for url in calls)


def test_cutoff_is_an_exact_instant_not_a_calendar_day(gateway):
    gate, *_ = gateway
    before = datetime.fromisoformat("2025-01-01T17:59:59+08:00")
    with pytest.raises(ValueError, match="cutoff"):
        gate.open("https://arxiv.org/abs/2501.00001v1", before)
    result = gate.open("https://arxiv.org/abs/2501.00001v1", before + timedelta(seconds=1))
    assert result["provenance"]["as_of"] == "2025-01-01T10:00:00Z"


def test_later_real_time_resume_refreshes_mutable_arxiv_history(tmp_path, monkeypatch):
    now = [datetime(2025, 2, 1, tzinfo=UTC)]
    histories = []

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now[0]

    def receive(url, destination, maximum):
        if url.endswith("v1") or url.endswith("v2"):
            body = paper_html(version=2 if url.endswith("v2") else 1)
        else:
            histories.append(now[0])
            body = HISTORY if now[0].month >= 7 else HISTORY.partition("<strong>[v2]")[0]
        destination.write_text(body)
        return url, "text/html"

    monkeypatch.setattr(browser, "datetime", Clock)
    monkeypatch.setattr(browser, "_receive", receive)
    cache = tmp_path / "cache"
    first = browser.BrowserGateway(cache).open("https://arxiv.org/abs/2501.00001", now[0])
    assert first["version"].endswith("v1")
    now[0] = datetime(2025, 8, 1, tzinfo=UTC)
    # A new instance shares the cache, as it would after a later resume.
    second = browser.BrowserGateway(cache).open("https://arxiv.org/abs/2501.00001v2", now[0])
    assert second["version"].endswith("v2") and len(histories) == 2
    old_again = browser.BrowserGateway(cache).open("https://arxiv.org/abs/2501.00001", CUTOFF)
    assert old_again["version"].endswith("v1") and len(histories) == 2


def test_download_preserves_large_pdf_bytes_and_reuses_versioned_cache(gateway, tmp_path):
    gate, calls, pdf, _ = gateway
    first = gate.download("https://arxiv.org/pdf/2501.00001", CUTOFF, tmp_path / "paper.pdf")
    assert first["bytes"] > 8 * 1024 * 1024
    assert first["sha256"] == hashlib.sha256(pdf).hexdigest()
    assert (tmp_path / "paper.pdf").read_bytes() == pdf
    assert first["url"].endswith("v1")
    previous = len(calls)
    second = gate.download(first["url"], CUTOFF, tmp_path / "again.pdf")
    assert second["sha256"] == first["sha256"] and len(calls) == previous


def test_github_search_browse_click_read_and_archive_are_same_commit(gateway, tmp_path):
    gate, calls, _, archive = gateway
    results = gate.search("github", "research", CUTOFF)
    match = results["results"][0]
    assert match["version"] == OLD and "Historical README" in match["readme"]
    assert "FUTURE" not in json.dumps(results) and "999999" not in json.dumps(results)
    listing = gate.open(match["url"], CUTOFF)
    code_url = next(link["url"] for link in listing["links"] if link["label"] == "train.py")
    code = gate.open(code_url, CUTOFF)
    assert "historical code" in code["text"] and code["version"] == OLD
    readme_url = next(link["url"] for link in listing["links"] if link["label"] == "README")
    first = gate.open(readme_url, CUTOFF, limit=2)
    second = gate.open(readme_url, CUTOFF, offset=first["next_offset"], limit=2)
    assert first["next_offset"] == 3 and second["text"].startswith("3: line 1")
    download = gate.download(match["download_url"], CUTOFF, tmp_path / "source.tar.gz")
    assert (tmp_path / "source.tar.gz").read_bytes() == archive
    assert download["sha256"] == hashlib.sha256(archive).hexdigest()
    assert not any("/main/" in url for url in calls)
    assert not (tmp_path / "source").exists()  # archives are never unpacked


@pytest.mark.parametrize("kind", ["tree", "blob", "archive"])
def test_github_explicit_future_sha_is_rejected_for_every_route(gateway, tmp_path, kind):
    gate, *_ = gateway
    url = f"https://github.com/example/project/{kind}/{NEW}"
    if kind == "blob":
        url += "/train.py"
    elif kind == "archive":
        url += ".tar.gz"
    with pytest.raises(ValueError, match="after the simulation cutoff"):
        gate.open(url, CUTOFF)
    with pytest.raises(ValueError, match="after the simulation cutoff"):
        gate.download(url, CUTOFF, tmp_path / "future")


def test_token_does_not_authorize_private_search_or_cached_repository_content(
    tmp_path, monkeypatch
):
    private = [False]
    calls = []

    def receive(url, destination, maximum):
        calls.append(url)
        path = urlsplit(url).path
        if path == "/search/repositories":
            assert "is:public" in parse_qs(urlsplit(url).query)["q"][0]
            body = {
                "total_count": 1,
                "items": [
                    {
                        "full_name": "example/secret",
                        "private": True,
                        "description": "PRIVATE MATERIAL",
                    }
                ],
            }
        elif path == "/repos/example/project":
            body = {"private": private[0], "created_at": "2024-01-01T00:00:00Z"}
        elif "/commits/" in path:
            body = commit()
        elif url.startswith("https://raw.githubusercontent.com/"):
            destination.write_text("once public source")
            return url, "text/plain"
        else:
            raise AssertionError("Private content must never be fetched")
        destination.write_text(json.dumps(body))
        return url, "application/json"

    monkeypatch.setenv("GITHUB_TOKEN", "token-with-private-repo-access")
    monkeypatch.setattr(browser, "_receive", receive)
    gate = browser.BrowserGateway(tmp_path / "host-cache")
    search = gate.search("github", "research", CUTOFF)
    assert search["results"] == [] and "PRIVATE MATERIAL" not in json.dumps(search)
    url = f"https://github.com/example/project/blob/{OLD}/train.py"
    assert "once public source" in gate.open(url, CUTOFF)["text"]
    private[0] = True
    previous = len(calls)
    with pytest.raises(ValueError, match="currently public"):
        gate.open(url, CUTOFF)
    with pytest.raises(ValueError, match="currently public"):
        gate.download(url, CUTOFF, tmp_path / "forbidden.py")
    assert calls[previous:] == ["https://api.github.com/repos/example/project"] * 2
    assert not (tmp_path / "forbidden.py").exists()


def test_repository_creation_after_cutoff_blocks_commit_and_archive_fetch(tmp_path, monkeypatch):
    calls = []

    def receive(url, destination, maximum):
        calls.append(url)
        assert url == "https://api.github.com/repos/example/project"
        destination.write_text(json.dumps({"private": False, "created_at": "2025-07-01T00:00:00Z"}))
        return url, "application/json"

    monkeypatch.setattr(browser, "_receive", receive)
    gate = browser.BrowserGateway(tmp_path / "cache")
    with pytest.raises(ValueError, match="created after"):
        gate.download(
            f"https://github.com/example/project/archive/{OLD}.tar.gz",
            CUTOFF,
            tmp_path / "future.tar.gz",
        )
    assert len(calls) == 1 and not (tmp_path / "future.tar.gz").exists()


def test_naive_and_real_future_cutoffs_and_unsupported_sites_fail_before_network(gateway):
    gate, calls, *_ = gateway
    for value, message in [
        (datetime(2025, 1, 1), "timezone-aware"),
        (datetime.now(UTC) + timedelta(days=1), "real-world future"),
    ]:
        with pytest.raises(ValueError, match=message):
            gate.search("arxiv", "query", value)
    with pytest.raises(ValueError, match="arxiv.org"):
        gate.open("https://example.org/current", CUTOFF)
    assert not calls


def test_unreadable_arxiv_history_does_not_silently_serve_latest(tmp_path, monkeypatch):
    def receive(url, destination, maximum):
        destination.write_text("<html>No submission history</html>")
        return url, "text/html"

    monkeypatch.setattr(browser, "_receive", receive)
    with pytest.raises(ValueError, match="no latest-version fallback"):
        browser.BrowserGateway(tmp_path).open("https://arxiv.org/abs/2501.00001", CUTOFF)


def test_arxiv_simple_field_query_maps_to_official_html_without_changing_semantics(gateway):
    gate, calls, *_ = gateway
    result = gate.search("arxiv", 'ti:"Search-R1"', CUTOFF)
    query = parse_qs(
        urlsplit(result["search_provenance"]["source_url"]).query, keep_blank_values=True
    )
    assert query["advanced"] == [""]
    assert query["terms-0-term"] == ['"Search-R1"'] and query["terms-0-field"] == ["title"]
    assert query["date-to_date"] == ["2025-06-01"]
    previous = len(calls)
    with pytest.raises(ValueError, match="complex API"):
        gate.search("arxiv", "ti:reasoning AND au:smith", CUTOFF)
    assert len(calls) == previous


@pytest.mark.parametrize(
    "html, empty",
    [
        ("<html><h1>Advanced Search</h1><form>Search form</form></html>", False),
        ("<html>Verify you are human</html>", False),
        ("<html>Sorry, your query: unknown produced no results.</html>", True),
    ],
)
def test_search_form_or_block_page_is_not_an_empty_success(tmp_path, monkeypatch, html, empty):
    def receive(url, destination, maximum):
        destination.write_text(html)
        return url, "text/html"

    monkeypatch.setattr(browser, "_receive", receive)
    gate = browser.BrowserGateway(tmp_path)
    if empty:
        assert gate.search("arxiv", "unknown", CUTOFF)["results"] == []
    else:
        with pytest.raises(ValueError, match="recognizable results"):
            gate.search("arxiv", "unknown", CUTOFF)


def test_versioned_url_does_not_make_an_unversioned_or_wrong_page_trustworthy(
    tmp_path, monkeypatch
):
    def receive(url, destination, maximum):
        body = paper_html(version=2) if url.endswith("v1") else HISTORY
        destination.write_text(body)
        return url, "text/html"

    monkeypatch.setattr(browser, "_receive", receive)
    with pytest.raises(ValueError, match="exact requested version"):
        browser.BrowserGateway(tmp_path).open("https://arxiv.org/abs/2501.00001v1", CUTOFF)


def test_http_retry_and_redirect_keep_token_on_api_host_only(tmp_path, monkeypatch):
    statuses = iter([429, 503, 302, 200])
    calls, sleeps = [], []

    class Connection:
        def __init__(self, host, **kwargs):
            self.host, self.status, self.consumed = host, next(statuses), False

        def request(self, method, target, headers):
            calls.append((self.host, headers.copy()))

        def getresponse(self):
            return self

        def getheader(self, key, default=None):
            return {
                "Location": "https://codeload.github.com/example/project/tar.gz/" + OLD,
                "Content-Type": "application/gzip",
            }.get(key, default)

        def read(self, size):
            assert self.status == 200  # never expose upstream error bodies
            if self.consumed:
                return b""
            self.consumed = True
            return b"archive bytes"

        def close(self):
            pass

    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    monkeypatch.setattr(browser.http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(browser.time, "sleep", sleeps.append)
    final, mime = browser._receive(
        "https://api.github.com/repos/example/project/tarball/" + OLD, tmp_path / "archive", 1024
    )
    assert final.startswith("https://codeload.github.com/") and mime == "application/gzip"
    assert sleeps == [2, 4]
    assert all(call[1]["Authorization"] == "Bearer secret-token" for call in calls[:3])
    assert "Authorization" not in calls[-1][1]


def test_arxiv_requests_are_spaced_three_seconds(monkeypatch):
    clock = [10.0]
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(browser, "_ARXIV_LAST", 0.0)
    monkeypatch.setattr(browser.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(browser.time, "sleep", sleep)
    browser._arxiv_wait()
    browser._arxiv_wait()
    browser._arxiv_wait()
    assert waits == [3.0, 3.0]


def test_forbidden_redirect_and_exhausted_retries_fail_explicitly(tmp_path, monkeypatch):
    attempts = []

    class Connection:
        status = 429

        def __init__(self, *args, **kwargs):
            attempts.append(1)

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return self

        def getheader(self, key, default=None):
            return "https://127.0.0.1/private" if key == "Location" else default

        def close(self):
            pass

    monkeypatch.setattr(browser.http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(browser.time, "sleep", lambda _: None)
    with pytest.raises(ValueError, match="HTTP 429"):
        browser._receive("https://api.github.com/search/repositories", tmp_path / "output", 1024)
    assert len(attempts) == 3
    Connection.status = 302
    with pytest.raises(ValueError, match="supported"):
        browser._receive("https://api.github.com/search/repositories", tmp_path / "output", 1024)
    assert not (tmp_path / "output").exists()
