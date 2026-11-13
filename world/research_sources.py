"""Office web tools; service credentials stay out of recorded arguments and results."""

from __future__ import annotations

import http.client
import io
import ipaddress
import json
import os
import socket
import ssl
import subprocess
import tempfile
from email.parser import Parser
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlencode, urljoin, urlsplit

MAX_BYTES = 8 * 1024 * 1024


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "div", "br", "h1", "h2", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _public_target(url: str):
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Use a public HTTP(S) URL without credentials.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in {80, 443}:
        raise ValueError("Only public web ports 80 and 443 are available.")
    addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Private and local network addresses are unavailable.")
    return parsed, port, addresses[0][4][0]


def fetch(url: str) -> tuple[str, str, bytes]:
    """Pin the validated public address for each connection, including redirects."""
    for _ in range(6):
        parsed, port, address = _public_target(url)
        conn = http.client.HTTPConnection(parsed.hostname, port, timeout=20)
        sock = socket.create_connection((address, port), timeout=20)
        try:
            if parsed.scheme == "https":
                sock = ssl.create_default_context().wrap_socket(
                    sock, server_hostname=parsed.hostname
                )
            conn.sock = sock
            path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
            if parsed.query:
                path += "?" + parsed.query
            conn.request(
                "GET",
                path,
                headers={"User-Agent": "socio-evo-research/0.1", "Accept-Encoding": "identity"},
            )
            response = conn.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                target = response.getheader("Location")
                if not target:
                    raise ValueError("Redirect has no destination.")
                url = urljoin(url, target)
                continue
            if response.status != 200:
                raise ValueError(f"Source returned HTTP {response.status}.")
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError("Source exceeds the 8 MiB reading limit.")
            return url, response.getheader("Content-Type", ""), data
        finally:
            conn.close()
            sock.close()
    raise ValueError("Too many redirects.")


def _api(host: str, path: str, *, headers=None, body=None) -> dict:
    """Call a fixed service endpoint without forwarding secrets through redirects."""
    conn = http.client.HTTPSConnection(host, timeout=30)
    try:
        conn.request(
            "POST" if body is not None else "GET",
            path,
            body=json.dumps(body) if body is not None else None,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError(f"{host} returned HTTP {response.status}; search did not succeed.")
        data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("Search response exceeds 8 MiB.")
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError("Search service returned an invalid response.")
        return result
    finally:
        conn.close()


def search(query: str) -> dict:
    path = "/graph/v1/paper/search?" + urlencode(
        {
            "query": query,
            "limit": 8,
            "fields": "title,authors,year,abstract,url,externalIds,openAccessPdf,citationCount",
        }
    )
    key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    data = _api("api.semanticscholar.org", path, headers={"x-api-key": key} if key else {})
    if not isinstance(data.get("data"), list):
        raise ValueError("Semantic Scholar returned no valid results list.")
    return {
        "source": "https://api.semanticscholar.org" + path,
        "provider": "Semantic Scholar",
        "note": "Bibliographic matches and abstracts, not verified findings or full texts.",
        "results": [
            {
                k: item.get(k)
                for k in (
                    "paperId",
                    "title",
                    "authors",
                    "year",
                    "abstract",
                    "url",
                    "externalIds",
                    "openAccessPdf",
                    "citationCount",
                )
            }
            for item in data["data"]
        ],
    }


def search_web(query: str) -> dict:
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not key:
        raise ValueError("TAVILY_API_KEY is not configured; web search is unavailable.")
    data = _api(
        "api.tavily.com",
        "/search",
        headers={"Authorization": "Bearer " + key},
        body={"query": query, "max_results": 8, "search_depth": "basic"},
    )
    if not isinstance(data.get("results"), list):
        raise ValueError("Tavily returned no valid results list.")
    return {
        "source": "https://api.tavily.com/search",
        "provider": "Tavily",
        "query": query,
        "note": "Search excerpts are leads; read the original source to verify claims.",
        "results": [
            {k: item.get(k) for k in ("title", "url", "content", "score")}
            for item in data["results"]
        ],
    }


def curl_source(url: str) -> dict:
    """Fetch a public body with actual curl; redirects are resolved and checked one by one."""
    requested = url
    with tempfile.TemporaryDirectory(prefix="research-curl-") as temp:
        body, header = Path(temp) / "body", Path(temp) / "headers"
        for _ in range(6):
            parsed, port, address = _public_target(url)
            if ":" in address:
                address = f"[{address}]"
            try:
                response = subprocess.run(
                    [
                        "curl",
                        "--disable",
                        "--silent",
                        "--show-error",
                        "--globoff",
                        "--noproxy",
                        "*",
                        "--proto",
                        "=http,https",
                        "--max-time",
                        "30",
                        "--max-filesize",
                        str(MAX_BYTES),
                        "--resolve",
                        f"{parsed.hostname}:{port}:{address}",
                        "--dump-header",
                        str(header),
                        "--output",
                        str(body),
                        "--write-out",
                        "%{http_code}",
                        "--url",
                        url,
                    ],
                    capture_output=True,
                    timeout=35,
                    # curl needs no resident or provider credentials.
                    env={"PATH": os.environ.get("PATH", os.defpath)},
                )
            except subprocess.TimeoutExpired as error:
                raise ValueError("curl timed out; source has not been read.") from error
            if response.returncode:
                raise ValueError(f"curl failed with exit code {response.returncode}.")
            status = int(response.stdout)
            # The final header block accounts for informational HTTP responses.
            block = header.read_text().strip().split("\n\n")[-1]
            headers = Parser().parsestr(block.partition("\n")[2])
            if status in {301, 302, 303, 307, 308}:
                location = headers.get("Location")
                if not location:
                    raise ValueError("Redirect has no destination.")
                url = urljoin(url, location)
                continue
            if status != 200:
                raise ValueError(f"Source returned HTTP {status}.")
            if body.stat().st_size > MAX_BYTES:
                raise ValueError("Source exceeds the 8 MiB reading limit.")
            return {
                "requested_url": requested,
                "url": url,
                "status": status,
                "content_type": headers.get("Content-Type", ""),
                "text": body.read_text(errors="replace"),
            }
    raise ValueError("Too many redirects.")


def read(url: str) -> dict:
    final, mime, data = fetch(url)
    if "application/pdf" in mime or data.startswith(b"%PDF"):
        from pypdf import PdfReader

        text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
    elif "html" in mime:
        parser = _Text()
        parser.feed(data.decode("utf-8", errors="replace"))
        text = "".join(parser.parts)
    elif mime.startswith("text/") or any(t in mime for t in ("json", "xml")):
        text = data.decode("utf-8", errors="replace")
    else:
        raise ValueError(f"Unsupported source type: {mime}; use text, HTML or PDF.")
    if not text.strip():
        raise ValueError("No readable text was extracted; this source has not been read.")
    return {"requested_url": url, "url": final, "content_type": mime, "text": text}
