"""Read-only public literature access; no credentials, private addresses or browser state."""

from __future__ import annotations

import http.client
import io
import ipaddress
import json
import socket
import ssl
from html.parser import HTMLParser
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


def fetch(url: str) -> tuple[str, str, bytes]:
    """Pin the validated public address for each connection, including redirects."""
    for _ in range(6):
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
        conn = http.client.HTTPConnection(parsed.hostname, port, timeout=20)
        sock = socket.create_connection((addresses[0][4][0], port), timeout=20)
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


def search(query: str) -> dict:
    url = "https://api.crossref.org/works?" + urlencode({"query.bibliographic": query, "rows": 8})
    final, _, data = fetch(url)
    items = json.loads(data)["message"]["items"]
    return {
        "source": final,
        "note": "Bibliographic matches, not verified findings or full texts.",
        "results": [
            {k: item.get(k) for k in ("title", "author", "DOI", "URL", "published")}
            for item in items
        ],
    }


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
