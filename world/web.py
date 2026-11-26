"""The web at the Office: whoever is there can search it (`search_web`) and read a public page
(`read_page`), a configured number of times a day each, and nowhere else.

It is reading only, done by the host on the resident's behalf, and nothing can be sent anywhere.
A search goes to the Tavily search service with the key of the environment variable
`SEARCH_KEY`, which no result, log entry or trace ever holds. Reading a page is one GET of an
http or https address on its usual port, with an ordinary browser's agent and no cookies, other
headers or body: the name is resolved and refused unless every address it has is on the public
internet (not loopback, private, link-local, multicast, reserved or unspecified), the connection
goes to the address that was checked, and each redirect is checked the same way, a few at most.
What comes back is read up to a size, within a time, reduced from HTML to its text and clipped to
what a result may hold.

Each search and page is logged for the one who made it alone (`web_search`, `web_page`), with
the query or the address and the size of what came back, never its text. The counts start again
at every checkpoint (`Web.new_day`), so a checkpoint holds none. The tests give `Web` a fake
transport and a fake resolver, and nothing of theirs touches the network.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any
from urllib.parse import SplitResult, urljoin, urlsplit

import httpx2

from agent.port import ToolResult
from world.config import SEARCH_KEY, WebSettings
from world.telling import cap, counted, you

if TYPE_CHECKING:
    from world.world import Resident, World

SEARCH_URL = "https://api.tavily.com/search"
RESULTS = 5
"""The results a search returns."""
AGENT = b"Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
"""The browser a page is read as."""
PORTS = {"http": 80, "https": 443}
"""The schemes a page is read by, each on its usual port, the only one allowed."""
REDIRECTS = 5
"""The redirects followed at most."""
REDIRECTED = (301, 302, 303, 307, 308)
TIMEOUT = httpx2.Timeout(15).as_dict()
"""Each step of a request, in seconds of real time."""
MAX_BYTES = 2_000_000
"""What is read of a page at most; the rest is not fetched."""
PAGE_CHARS = 12_000
"""The text of a page a result holds at most, below what the runtime passes on of any result
(`agent.runtime.RuntimeConfig.tool_result_chars`, 16,000)."""
SNIPPET_CHARS = 400
"""What a search result tells of its page at most."""
BLOCKS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}
HIDDEN = {"script", "style", "noscript", "template", "svg", "head"}

Resolve = Callable[[str, int], Awaitable[list[str]]]
"""The addresses a host name has, as text, for a port."""


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def public(address: str) -> bool:
    """Whether `address` is on the public internet: global, and neither multicast, reserved nor
    unspecified; an IPv4 address mapped into IPv6 is judged as itself."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_unspecified)


class _Text(HTMLParser):
    """The text of an HTML page: what it shows, a line to each block."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in HIDDEN:
            self._hidden += 1
        elif tag in BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in HIDDEN:
            self._hidden = max(0, self._hidden - 1)
        elif tag in BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)


def text_of(html: str) -> str:
    """The text an HTML page shows, its blank lines and runs of spaces closed up."""
    parser = _Text()
    parser.feed(html)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


class Web:
    """The web at the Office for one town (see the module docstring), through `transport`, a
    new one for each request if none is given, and `resolve`, the system's resolver if none is.
    `used` counts each resident's searches and pages since the last checkpoint."""

    def __init__(
        self,
        settings: WebSettings,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
        resolve: Resolve | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.resolve = resolve or _resolve
        self.used: dict[str, list[int]] = {}

    def new_day(self) -> None:
        """The checkpoint: the counts start again."""
        self.used = {}

    @asynccontextmanager
    async def _transport(self) -> AsyncIterator[httpx2.AsyncBaseTransport]:
        if self.transport is not None:
            yield self.transport
            return
        async with httpx2.AsyncHTTPTransport(retries=0) as transport:
            yield transport

    async def search(self, query: str) -> tuple[str, dict[str, Any]]:
        """What a search for `query` found, as the resident reads it, and the log's facts."""
        key = os.environ.get(SEARCH_KEY, "").strip()
        request = httpx2.Request(
            "POST",
            SEARCH_URL,
            json={"query": query, "max_results": RESULTS},
            headers={b"Authorization": b"Bearer " + key.encode()},
            extensions={"timeout": TIMEOUT},
        )
        try:
            async with self._transport() as transport:
                response = await transport.handle_async_request(request)
                try:
                    body = await _read(response)
                finally:
                    await response.aclose()
            found = json.loads(body) if response.status_code == 200 else None
        except (httpx2.HTTPError, ValueError):
            found = None
        results = found.get("results") if isinstance(found, dict) else None
        if not isinstance(results, list):
            told = "The search could not be made just now."
            return told, {"results": None, "characters": 0, "ok": False}
        lines = []
        for n, result in enumerate(r for r in results if isinstance(r, dict)):
            title = " ".join(str(result.get("title") or "").split()) or "(no title)"
            snippet = " ".join(str(result.get("content") or "").split())[:SNIPPET_CHARS]
            lines.append(f"{n + 1}. {title}\n   {result.get('url') or ''}\n   {snippet}")
        if lines:
            told = f"What the web has for “{query}”:\n" + "\n".join(lines)
        else:
            told = f"The search for “{query}” found nothing."
        return told, {"results": len(lines), "characters": len(told), "ok": True}

    async def read(self, address: str) -> tuple[str, dict[str, Any]]:
        """The page at `address`, as the resident reads it, and the log's facts: the address
        finally read, the last status, the bytes and the characters of text read, and whether
        the page was read."""
        url = address.strip()
        facts: dict[str, Any] = {"final": None, "status": None, "bytes": 0, "characters": 0}
        facts["ok"] = False
        try:
            async with self._transport() as transport:
                for _ in range(REDIRECTS + 1):
                    target = await self._target(url)
                    if isinstance(target, str):
                        return target, facts
                    response = await transport.handle_async_request(_request(*target))
                    try:
                        facts["status"] = response.status_code
                        location = response.headers.get("location")
                        if response.status_code in REDIRECTED and location:
                            url = urljoin(url, location)
                            continue
                        facts["final"] = url
                        if response.status_code != 200:
                            return f"The page at {url} answered {response.status_code}.", facts
                        body = await _read(response)
                        kind = response.headers.get("content-type", "")
                        charset = response.charset_encoding or "utf-8"
                    finally:
                        await response.aclose()
                    break
                else:
                    return "The page sent you on too many times.", facts
        except httpx2.TimeoutException:
            return f"The page at {url} did not answer in time.", facts
        except (httpx2.HTTPError, httpx2.InvalidURL, UnicodeError):
            return f"The page at {url} could not be reached.", facts
        facts["bytes"] = len(body)
        try:
            decoded = body.decode(charset, errors="replace")
        except LookupError:
            decoded = body.decode("utf-8", errors="replace")
        if "html" in kind or (not kind and decoded.lstrip()[:1] == "<"):
            text = text_of(decoded)
        elif kind.startswith("text/") or "xml" in kind:
            text = decoded.strip()
        else:
            told = f"The page at {url} is not text that can be read here ({kind.split(';')[0]})."
            return told, facts
        if not text:
            return f"The page at {url} shows no text.", facts
        told = f"The page at {url}:\n\n{text[:PAGE_CHARS]}"
        if len(text) > PAGE_CHARS or len(body) > MAX_BYTES:
            told += "\n\n[The page goes on; this is as much of it as can be read here.]"
        return told, facts | {"characters": len(text), "ok": True}

    async def _target(self, url: str) -> tuple[SplitResult, str, int] | str:
        """`url` and the address and port to connect to for it, or why it cannot be read: not
        http or https on its usual port, with a user name, or anything but public addresses."""
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            return f"{url} is not a web address."
        usual = PORTS.get(parts.scheme)
        if usual is None or not parts.hostname:
            return "Give an address that begins with http:// or https://."
        if parts.username is not None or parts.password is not None:
            return f"{url} is not a public address."
        if port not in (None, usual):
            return f"Pages are read on the usual port only, not {port}."
        try:
            addresses = await self.resolve(parts.hostname, usual)
        except (OSError, UnicodeError):
            return f"There is no such address as {parts.hostname} on the web."
        if not addresses or not all(public(address) for address in addresses):
            return f"{parts.hostname} is not on the public web."
        return parts, addresses[0], usual


def _request(parts: SplitResult, address: str, port: int) -> httpx2.Request:
    """The one GET of the page `parts` names, made to the `address` checked for its host, under
    the host's own name, as a browser makes it."""
    host = f"[{address}]" if ":" in address else address
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    extensions: dict[str, Any] = {"timeout": TIMEOUT}
    if parts.scheme == "https":
        extensions["sni_hostname"] = parts.hostname
    return httpx2.Request(
        "GET",
        f"{parts.scheme}://{host}:{port}{path}",
        headers={b"Host": parts.netloc.encode("idna"), b"User-Agent": AGENT},
        extensions=extensions,
    )


async def _read(response: httpx2.Response) -> bytes:
    """The body of `response`, read up to one byte beyond `MAX_BYTES`, so that a longer one is
    known to be longer."""
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body += chunk
        if len(body) > MAX_BYTES:
            break
    return bytes(body[: MAX_BYTES + 1])


def _away(world: World, r: Resident) -> ToolResult | None:
    """The refusal of the web away from the Office, where it is; None at the Office."""
    office = world.config.workplace("office")
    if r.place != office.id:
        return ToolResult(f"The web is at {office.name}, and you are not there.")
    return None


def _counted(world: World, r: Resident, which: int) -> ToolResult | None:
    """Count a search (`which` 0) or a page (1) for `r` today, or refuse one beyond the day's."""
    settings = world.web.settings
    allowed = (settings.searches_a_day, settings.pages_a_day)[which]
    used = world.web.used.setdefault(r.name, [0, 0])
    if used[which] >= allowed:
        done = (
            f"searched the web {counted(allowed, 'time')}"
            if which == 0
            else f"read {counted(allowed, 'page')} of the web"
        )
        return ToolResult(f"You have {done} today, as many as a day allows.")
    used[which] += 1
    return None


async def _search_web(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    query = args["query"].strip()
    if refused := _away(world, r):
        return refused
    if not query:
        return ToolResult("Say what to search the web for.")
    if refused := _counted(world, r, 0):
        return refused
    told, facts = await world.web.search(query)
    world.record(
        "web_search",
        lambda w: f"{cap(you(r.name, w))} searched the web for “{query}”.",
        actor=r,
        payload={"query": query} | facts,
    )
    return ToolResult(told)


async def _read_page(world: World, r: Resident, args: dict[str, Any]) -> ToolResult:
    address = args["address"].strip()
    if refused := _away(world, r):
        return refused
    if not address:
        return ToolResult("Give the address of the page.")
    if refused := _counted(world, r, 1):
        return refused
    told, facts = await world.web.read(address)
    world.record(
        "web_page",
        lambda w: f"{cap(you(r.name, w))} read the page at {address}.",
        actor=r,
        payload={"url": address} | facts,
    )
    return ToolResult(told)


HANDLERS = {"search_web": _search_web, "read_page": _read_page}
