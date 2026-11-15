"""Version-pinned arXiv/GitHub browsing, with explicit historical-availability limits.

The host owns this cache; it must never be mounted in a resident's container. A cached
object is not permission to serve it: every public operation resolves the cutoff again.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit

PAGE_SIZE = 5
READ_LIMIT = 8 * 1024 * 1024
DOWNLOAD_LIMIT = 256 * 1024 * 1024
_HOSTS = {
    "arxiv.org",
    "export.arxiv.org",
    "github.com",
    "api.github.com",
    "raw.githubusercontent.com",
    "codeload.github.com",
}
_ARXIV_ID = re.compile(r"^(\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})(?:v([1-9]\d*))?$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_ARXIV_LOCK = threading.Lock()
_ARXIV_LAST = 0.0
_DISCOVERY_NOTE = (
    "Candidates come from the provider's current search index, not a historical index. "
    "Displayed content is resolved to an eligible version; historical recall and ranking "
    "are not guaranteed. Submission/commit times do not prove public availability."
)


def _cutoff(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("The browser cutoff must be a timezone-aware datetime.")
    return value.astimezone(UTC)


def _date(value: str) -> datetime:
    return _cutoff(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _as_of(value: datetime) -> datetime:
    value = _cutoff(value)
    if value > datetime.now(UTC):
        raise ValueError(
            "The simulation cutoff is in the real-world future; no future corpus exists."
        )
    return value


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _arxiv_wait() -> None:
    global _ARXIV_LAST
    with _ARXIV_LOCK:
        delay = 3.0 - (time.monotonic() - _ARXIV_LAST)
        if delay > 0:
            time.sleep(delay)
        _ARXIV_LAST = time.monotonic()


def _receive(url: str, destination: Path, max_bytes: int) -> tuple[str, str]:
    """Fixed-provider HTTPS only; retry transient errors without exposing response bodies."""
    for _ in range(6):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in _HOSTS
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
        ):
            raise ValueError("Browser request left the supported arXiv/GitHub HTTPS hosts.")
        if parsed.hostname.endswith("arxiv.org"):
            _arxiv_wait()
        headers = {"User-Agent": "socio-evo-pit-browser/1.0", "Accept-Encoding": "identity"}
        if parsed.hostname == "api.github.com":
            headers.update(
                {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
            )
            token = os.environ.get("GITHUB_TOKEN", "").strip()
            if token:
                headers["Authorization"] = "Bearer " + token
        redirected = False
        for attempt in range(3):
            if attempt and parsed.hostname.endswith("arxiv.org"):
                _arxiv_wait()
            connection = http.client.HTTPSConnection(parsed.hostname, timeout=60)
            try:
                target = parsed.path or "/"
                if parsed.query:
                    target += "?" + parsed.query
                connection.request("GET", target, headers=headers)
                response = connection.getresponse()
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.getheader("Location")
                    if not location:
                        raise ValueError("Browser redirect has no destination.")
                    url = urljoin(url, location)
                    redirected = True
                    break
                transient = response.status == 429 or response.status in {500, 502, 503, 504}
                if transient and attempt < 2:
                    retry = response.getheader("Retry-After", "")
                    time.sleep(
                        min(10, max(2 ** (attempt + 1), int(retry) if retry.isdigit() else 0))
                    )
                    continue
                if response.status != 200:
                    raise SourceError(response.status, parsed.hostname)
                count = 0
                with destination.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        count += len(chunk)
                        if count > max_bytes:
                            raise ValueError(
                                f"Source exceeds the {max_bytes // 1024 // 1024} MiB limit."
                            )
                        output.write(chunk)
                return url, response.getheader("Content-Type", "application/octet-stream")
            except (OSError, http.client.HTTPException) as error:
                if attempt == 2:
                    raise ValueError(
                        f"{parsed.hostname} connection failed; no content was served."
                    ) from error
                time.sleep(2 ** (attempt + 1))
            finally:
                connection.close()
        if not redirected:
            break
    raise ValueError("Too many browser redirects.")


class SourceError(ValueError):
    def __init__(self, status: int, host: str):
        self.status = status
        super().__init__(f"{host} returned HTTP {status}; no content was served.")


@dataclass(frozen=True)
class _Resource:
    path: Path
    url: str
    content_type: str
    sha256: str
    retrieved_at: str
    size: int

    def text(self) -> str:
        return self.path.read_text(encoding="utf-8", errors="replace")

    def json(self):
        return json.loads(self.text())


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)


class _ArxivHTML(_HTMLText):
    """Read the visible selected version, and only identifiers from search results."""

    def __init__(self):
        super().__init__()
        self.stack = []
        self.title: list[str] = []
        self.abstract: list[str] = []
        self.authors: list[list[str]] = []
        self.links: list[str] = []
        self.identifiers: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        capture = None
        if tag == "h1" and "title" in classes:
            capture = self.title
        elif tag == "blockquote" and "abstract" in classes:
            capture = self.abstract
        elif tag == "a" and any("authors" in item[1] for item in self.stack):
            capture = []
            self.authors.append(capture)
        if tag == "a" and attrs.get("href"):
            href = attrs["href"]
            self.links.append(href)
            if any("arxiv-result" in item[1] for item in self.stack):
                parsed = urlsplit(urljoin("https://arxiv.org", href))
                if parsed.hostname == "arxiv.org" and parsed.path.startswith("/abs/"):
                    identifier = parsed.path.removeprefix("/abs/")
                    if identifier not in self.identifiers:
                        self.identifiers.append(identifier)
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append((tag, classes, capture))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        super().handle_data(data)
        for _, _, capture in self.stack:
            if capture is not None:
                capture.append(data)


def _arxiv_query(query: str) -> tuple[str, str]:
    """Translate a single API field, without pretending to translate its Boolean grammar."""
    message = "Use plain keywords or one ti:/au:/abs: field; complex API queries are unsupported."
    match = re.fullmatch(r'(all|ti|au|abs):\s*("[^"]+"|[^():]+)', query.strip())
    if match:
        field, term = match.groups()
        if not term.startswith('"') and re.search(r"\b(?:AND|OR|ANDNOT)\b", term):
            raise ValueError(message)
        return {"all": "all", "ti": "title", "au": "author", "abs": "abstract"}[field], term
    if re.search(r"\b(?:all|ti|au|abs|cat|id|submittedDate|lastUpdatedDate):", query):
        raise ValueError(message)
    return "all", query.strip()


class _NotAtCutoff(ValueError):
    pass


class BrowserGateway:
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _fetch(
        self,
        url: str,
        *,
        max_bytes: int = READ_LIMIT,
        observed_at_least: datetime | None = None,
        refresh: bool = False,
    ) -> _Resource:
        key = hashlib.sha256(url.encode()).hexdigest()
        metadata_path = self.cache_dir / (key + ".json")
        if metadata_path.exists() and not refresh:
            metadata = json.loads(metadata_path.read_text())
            if observed_at_least is None or observed_at_least <= _date(metadata["retrieved_at"]):
                body = self.cache_dir / metadata["sha256"]
                if body.stat().st_size > max_bytes:
                    raise ValueError(
                        "Cached source exceeds this operation's size limit; use download."
                    )
                return _Resource(path=body, **metadata)
        with tempfile.NamedTemporaryFile(dir=self.cache_dir, delete=False) as temp:
            temporary = Path(temp.name)
        try:
            final, mime = _receive(url, temporary, max_bytes)
            with temporary.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            body = self.cache_dir / digest
            temporary.replace(body)
            metadata = {
                "url": final,
                "content_type": mime,
                "sha256": digest,
                "retrieved_at": _iso(datetime.now(UTC)),
                "size": body.stat().st_size,
            }
            temporary.write_text(json.dumps(metadata))
            temporary.replace(metadata_path)
            return _Resource(path=body, **metadata)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _url(url: str):
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"https", "http"}
            or parsed.hostname not in {"arxiv.org", "github.com"}
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 80, 443}
            or parsed.query
        ):
            raise ValueError(
                "Open an arxiv.org paper or github.com repository URL without a query."
            )
        return parsed.hostname, unquote(parsed.path).strip("/")

    @staticmethod
    def _provenance(
        resource: _Resource, version: str, date: datetime, as_of: datetime, provider: str
    ) -> dict:
        return {
            "source_url": resource.url,
            "sha256": resource.sha256,
            "retrieved_at": resource.retrieved_at,
            "version": version,
            "version_time": _iso(date),
            "as_of": _iso(as_of),
            "time_basis": "submission_timestamp" if provider == "arxiv" else "committer_timestamp",
            "availability_verified": False,
            "limitation": (
                "arXiv announcement can follow submission; this timestamp does not prove "
                "public release."
                if provider == "arxiv"
                else "Git commit dates are author-controlled; historical public visibility, "
                "branch state, "
                "repository names and search ranking are not reconstructed."
            ),
        }

    def _arxiv(self, identifier: str, as_of: datetime) -> dict:
        match = _ARXIV_ID.fullmatch(identifier.removesuffix(".pdf"))
        if not match:
            raise ValueError("Use a valid arXiv identifier, optionally with vN.")
        base, requested = match.groups()
        # History is used internally only. Never send its future versions or the current abstract.
        history = self._fetch("https://arxiv.org/abs/" + base, observed_at_least=as_of)
        parser = _HTMLText()
        parser.feed(history.text())
        pattern = (
            r"\[v(\d+)\]\s*([A-Z][a-z]{2},?\s+\d{1,2}\s+[A-Z][a-z]{2}\s+"
            r"\d{4}\s+\d{2}:\d{2}:\d{2}\s+(?:UTC|GMT))"
        )
        versions = {
            int(v): parsedate_to_datetime(date.replace("UTC", "GMT"))
            for v, date in re.findall(pattern, " ".join(parser.parts))
        }
        if not versions:
            raise ValueError(
                "arXiv submission history could not be verified; no latest-version fallback."
            )
        eligible = [v for v, date in versions.items() if date <= as_of]
        selected = int(requested) if requested else max(eligible, default=0)
        if selected not in eligible:
            raise _NotAtCutoff("Requested arXiv version is unavailable at the simulation cutoff.")
        version = base + "v" + str(selected)
        resource = self._fetch("https://arxiv.org/abs/" + version)
        page = _ArxivHTML()
        page.feed(resource.text())
        # citation_pdf_url omits vN even on old pages. Check the visible version label
        # and actual versioned PDF anchor instead; never follow the unversioned meta URL.
        visible = " ".join(page.parts)
        exact_pdf = any(urlsplit(link).path == "/pdf/" + version for link in page.links)
        if (
            urlsplit(resource.url).path != "/abs/" + version
            or not exact_pdf
            or not re.search(r"arXiv:\s*" + re.escape(version) + r"(?!\d)", visible)
        ):
            raise ValueError("arXiv did not return the exact requested version page.")
        title = " ".join("".join(page.title).split()).removeprefix("Title:").strip()
        abstract = " ".join("".join(page.abstract).split()).removeprefix("Abstract:").strip()
        authors = [" ".join("".join(parts).split()) for parts in page.authors]
        if not title or not abstract:
            raise ValueError("The selected arXiv version page has no readable title/abstract.")
        return {
            "provider": "arxiv",
            "url": "https://arxiv.org/abs/" + version,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "version": version,
            "links": [
                {"label": label, "url": "https://arxiv.org/" + kind + "/" + version}
                for label, kind in (("Abstract", "abs"), ("PDF", "pdf"), ("Source", "src"))
            ],
            "provenance": self._provenance(resource, version, versions[selected], as_of, "arxiv"),
        }

    def _public_repository(self, repo: str, as_of: datetime) -> None:
        # A token can access private repositories. A historical cache is not authorization
        # to expose one after its current visibility changes; check the live provider each time.
        metadata = self._fetch("https://api.github.com/repos/" + repo, refresh=True).json()
        if metadata.get("private") is not False:
            raise ValueError("Only currently public GitHub repositories are available.")
        if _date(metadata["created_at"]) > as_of:
            raise _NotAtCutoff("The GitHub repository was created after the simulation cutoff.")

    def _github_commit(self, repo: str, ref: str, as_of: datetime) -> dict:
        base = "https://api.github.com/repos/" + repo
        if _SHA.fullmatch(ref):
            resource = self._fetch(base + "/commits/" + ref)
            commit = resource.json()
        else:
            args = {"until": _iso(as_of), "per_page": 1}
            if ref:
                args["sha"] = ref
            resource = self._fetch(base + "/commits?" + urlencode(args))
            commits = resource.json()
            if not isinstance(commits, list) or not commits:
                raise _NotAtCutoff("No repository commit was found at the simulation cutoff.")
            commit = commits[0]
        sha = commit.get("sha", "")
        if not _SHA.fullmatch(sha):
            raise ValueError("GitHub did not return a complete commit SHA.")
        date = _date(commit["commit"]["committer"]["date"])
        if date > as_of:
            raise _NotAtCutoff("Requested GitHub commit is after the simulation cutoff.")
        return {"sha": sha, "provenance": self._provenance(resource, sha, date, as_of, "github")}

    def _github(self, path: str, as_of: datetime) -> dict:
        parts = path.split("/")
        if len(parts) < 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", p) for p in parts[:2]):
            raise ValueError("Use a GitHub repository, tree, blob, or archive URL.")
        repo = "/".join(parts[:2]).removesuffix(".git")
        self._public_repository(repo, as_of)
        kind, ref, relative = "tree", "", ""
        if len(parts) > 2:
            kind = parts[2]
            if kind in {"tree", "blob"} and len(parts) >= 4:
                ref, relative = parts[3], "/".join(parts[4:])
            elif kind == "archive" and len(parts) >= 4:
                ref = "/".join(parts[3:]).removeprefix("refs/heads/").removeprefix("refs/tags/")
                ref = ref.removesuffix(".tar.gz").removesuffix(".zip")
            else:
                raise ValueError("Only repository trees, files and source archives are available.")
        if not ref and len(parts) > 2 or any(p in {".", ".."} for p in relative.split("/")):
            raise ValueError("Invalid repository ref or path.")
        commit = self._github_commit(repo, ref, as_of)
        sha = commit["sha"]
        url = (
            "https://github.com/" + repo + "/" + ("blob" if kind == "blob" else "tree") + "/" + sha
        )
        if relative:
            url += "/" + quote(relative, safe="/")
        return {
            "provider": "github",
            "repo": repo,
            "kind": kind,
            "relative": relative,
            "version": sha,
            "url": url,
            "title": repo,
            "archive_url": "https://github.com/" + repo + "/archive/" + sha + ".tar.gz",
            "provenance": commit["provenance"],
        }

    def _github_readme(self, document: dict) -> tuple[str, str]:
        url = (
            "https://api.github.com/repos/"
            + document["repo"]
            + "/readme?"
            + urlencode({"ref": document["version"]})
        )
        try:
            metadata = self._fetch(url).json()
        except SourceError as error:
            if error.status == 404:
                return "", ""
            raise
        path = metadata["path"]
        raw = (
            "https://raw.githubusercontent.com/"
            + document["repo"]
            + "/"
            + document["version"]
            + "/"
            + quote(path, safe="/")
        )
        return self._fetch(raw).text(), path

    def search(self, provider: str, query: str, as_of: datetime, page: int = 1) -> dict:
        as_of = _as_of(as_of)
        if not query.strip() or not 1 <= page <= 200:
            raise ValueError("Supply a search query and a page between 1 and 200.")
        results = []
        omitted = 0
        if provider == "arxiv":
            field, term = _arxiv_query(query)
            start = (page - 1) * PAGE_SIZE
            provider_start = start // 50 * 50
            # Official HTML is primary; the separate API need not be reachable.
            query_url = "https://arxiv.org/search/advanced?" + urlencode(
                {
                    "advanced": "",
                    "terms-0-operator": "AND",
                    "terms-0-term": term,
                    "terms-0-field": field,
                    "classification-include_cross_list": "include",
                    "date-filter_by": "date_range",
                    "date-from_date": "1991-01-01",
                    "date-to_date": f"{as_of:%Y-%m-%d}",
                    "date-date_type": "submitted_date",
                    "abstracts": "show",
                    "size": 50,
                    "order": "-announced_date_first",
                    "start": provider_start,
                }
            )
            resource = self._fetch(query_url, observed_at_least=as_of)
            listing = _ArxivHTML()
            listing.feed(resource.text())
            visible = " ".join(" ".join(listing.parts).split())
            count = re.search(r"\bof\s+([\d,]+)\s+results?\b", visible)
            if count and (listing.identifiers or int(count[1].replace(",", "")) == 0):
                total = int(count[1].replace(",", ""))
            elif "Sorry, your query" in visible and "produced no results" in visible:
                total = 0
            else:
                raise ValueError("arXiv search did not return a recognizable results page.")
            within = start - provider_start
            for identifier in listing.identifiers[within : within + PAGE_SIZE]:
                base = re.sub(r"v\d+$", "", identifier)
                try:
                    results.append(self._arxiv(base, as_of))
                except _NotAtCutoff:
                    omitted += 1
        elif provider == "github":
            query_url = "https://api.github.com/search/repositories?" + urlencode(
                {
                    "q": f"{query} is:public created:<={as_of:%Y-%m-%d}",
                    "per_page": PAGE_SIZE,
                    "page": page,
                }
            )
            resource = self._fetch(query_url, observed_at_least=as_of)
            data = resource.json()
            if data.get("incomplete_results"):
                raise ValueError(
                    "GitHub search timed out and returned incomplete results; try again."
                )
            total = min(data.get("total_count", 0), 1000)
            for item in data.get("items", []):
                if item.get("private") is not False:
                    continue
                if _date(item["created_at"]) > as_of:
                    omitted += 1
                    continue
                try:
                    document = self._github(item["full_name"], as_of)
                    readme, path = self._github_readme(document)
                    results.append(
                        {
                            k: document[k]
                            for k in ("provider", "url", "title", "version", "provenance")
                        }
                        | {
                            "readme": readme[:6000],
                            "readme_truncated": len(readme) > 6000,
                            "readme_path": path,
                            "download_url": document["archive_url"],
                        }
                    )
                except _NotAtCutoff:
                    omitted += 1
        else:
            raise ValueError("Browser search provider must be arxiv or github.")
        return {
            "provider": provider,
            "query": query,
            "as_of": _iso(as_of),
            "page": page,
            "has_more": page * PAGE_SIZE < total,
            "next_page": page + 1 if page * PAGE_SIZE < total else None,
            "results": results,
            "omitted_at_cutoff": omitted,
            "note": _DISCOVERY_NOTE,
            "search_provenance": {
                "source_url": resource.url,
                "sha256": resource.sha256,
                "retrieved_at": resource.retrieved_at,
            },
        }

    @staticmethod
    def _page(document: dict, text: str, links: list[dict], offset: int, limit: int) -> dict:
        if offset < 1 or not 1 <= limit <= 300:
            raise ValueError("Read offset starts at 1; limit must be between 1 and 300 lines.")
        # Wrap long PDF/README paragraphs so a single physical line cannot exhaust tool context.
        lines = [
            part
            for line in text.splitlines()
            for part in ([line[i : i + 240] for i in range(0, len(line), 240)] or [""])
        ]
        end = min(len(lines), offset - 1 + limit)
        return {k: document[k] for k in ("provider", "url", "title", "version", "provenance")} | {
            "text": "\n".join(
                f"{n + 1}: {line}" for n, line in enumerate(lines[offset - 1 : end], offset - 1)
            ),
            "offset": offset,
            "total_lines": len(lines),
            "next_offset": end + 1 if end < len(lines) else None,
            "links": links[offset - 1 : offset - 1 + limit],
            "total_links": len(links),
            "next_links_offset": offset + limit if offset - 1 + limit < len(links) else None,
        }

    def open(self, url: str, as_of: datetime, offset: int = 1, limit: int = 120) -> dict:
        as_of = _as_of(as_of)
        host, path = self._url(url)
        if host == "arxiv.org":
            kind, _, identifier = path.partition("/")
            if kind not in {"abs", "pdf", "src", "e-print"}:
                raise ValueError("Open an arXiv abs, pdf, or src URL.")
            document = self._arxiv(identifier, as_of)
            if kind == "pdf":
                resource = self._fetch(
                    "https://arxiv.org/pdf/" + document["version"], max_bytes=DOWNLOAD_LIMIT
                )
                with resource.path.open("rb") as stream:
                    if not stream.read(5).startswith(b"%PDF-"):
                        raise ValueError("arXiv did not return a PDF.")
                from pypdf import PdfReader

                with resource.path.open("rb") as stream:
                    text = "\n".join(page.extract_text() or "" for page in PdfReader(stream).pages)
                if not text.strip():
                    raise ValueError("No text could be extracted from this PDF; use download.")
                document["url"] = "https://arxiv.org/pdf/" + document["version"]
                document["provenance"] |= {
                    "content_sha256": resource.sha256,
                    "content_retrieved_at": resource.retrieved_at,
                }
            else:
                text = (
                    document["title"]
                    + "\n"
                    + ", ".join(document["authors"])
                    + "\n\n"
                    + document["abstract"]
                )
                if kind in {"src", "e-print"}:
                    text += "\n\nUse download for the source archive; it is not a text page."
            return self._page(document, text, document["links"], offset, limit)
        document = self._github(path, as_of)
        repo, sha, relative = document["repo"], document["version"], document["relative"]
        links = [{"label": "Download repository archive", "url": document["archive_url"]}]
        if document["kind"] == "blob":
            raw = (
                "https://raw.githubusercontent.com/"
                + repo
                + "/"
                + sha
                + "/"
                + quote(relative, safe="/")
            )
            resource = self._fetch(raw)
            if b"\x00" in resource.path.read_bytes()[:8192]:
                raise ValueError("This repository file is binary; use download.")
            text = resource.text()
            document["provenance"] |= {
                "content_sha256": resource.sha256,
                "content_retrieved_at": resource.retrieved_at,
            }
        else:
            entries = self._fetch(
                "https://api.github.com/repos/"
                + repo
                + "/contents/"
                + quote(relative, safe="/")
                + "?"
                + urlencode({"ref": sha})
            ).json()
            if not isinstance(entries, list):
                raise ValueError("This path is not a repository directory; use its blob URL.")
            text = repo + "\nCommit " + sha + "\n\n"
            for entry in entries:
                entry_kind = "tree" if entry["type"] == "dir" else "blob"
                target = (
                    "https://github.com/"
                    + repo
                    + "/"
                    + entry_kind
                    + "/"
                    + sha
                    + "/"
                    + quote(entry["path"], safe="/")
                )
                links.append({"label": entry["name"], "url": target})
                text += entry["type"] + " " + entry["name"] + "\n"
            if not relative:
                readme, readme_path = self._github_readme(document)
                text += "\n" + readme
                if readme_path:
                    links.append(
                        {
                            "label": "README",
                            "url": "https://github.com/"
                            + repo
                            + "/blob/"
                            + sha
                            + "/"
                            + quote(readme_path, safe="/"),
                        }
                    )
        return self._page(document, text, links, offset, limit)

    def download(self, url: str, as_of: datetime, destination: Path) -> dict:
        as_of = _as_of(as_of)
        host, path = self._url(url)
        if host == "arxiv.org":
            kind, _, identifier = path.partition("/")
            if kind not in {"abs", "pdf", "src", "e-print"}:
                raise ValueError("Download an arXiv PDF or source archive.")
            document = self._arxiv(identifier, as_of)
            kind = "src" if kind in {"src", "e-print"} else "pdf"
            target = "https://arxiv.org/" + kind + "/" + document["version"]
        else:
            document = self._github(path, as_of)
            if document["kind"] == "blob":
                target = (
                    "https://raw.githubusercontent.com/"
                    + document["repo"]
                    + "/"
                    + document["version"]
                    + "/"
                    + quote(document["relative"], safe="/")
                )
            else:
                target = (
                    "https://api.github.com/repos/"
                    + document["repo"]
                    + "/"
                    + ("zipball/" if path.endswith(".zip") else "tarball/")
                    + document["version"]
                )
        resource = self._fetch(target, max_bytes=DOWNLOAD_LIMIT)
        if host == "arxiv.org" and kind == "pdf":
            with resource.path.open("rb") as stream:
                if not stream.read(5).startswith(b"%PDF-"):
                    raise ValueError("arXiv did not return a PDF; no file was saved.")
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # The caller owns workspace path validation. Do not unpack untrusted archives.
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temp:
            temporary = Path(temp.name)
        try:
            shutil.copyfile(resource.path, temporary)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return {
            "provider": document["provider"],
            "url": target,
            "version": document["version"],
            "path": str(destination),
            "bytes": resource.size,
            "sha256": resource.sha256,
            "content_type": resource.content_type,
            "provenance": document["provenance"]
            | {"content_sha256": resource.sha256, "content_retrieved_at": resource.retrieved_at},
        }
