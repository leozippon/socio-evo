"""What the world's tests share about the web at the Office: a fake of the network that answers
from a table of pages, and a fake resolver of host names, so that no test reaches the network.
`FakeWeb.sent` keeps every request the world made, to see what went out."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field

import httpx2

from world.web import SEARCH_URL
from world.world import World

HOSTS = {"example.org": ["93.184.215.14"], "news.example": ["2606:2800:21f:cb07::1"]}
"""Host names and their public addresses."""


@dataclass
class FakeWeb:
    """`pages` by the host name and path a request is made for (the address it connects to must
    be one the host has), each `(status, headers, body)`; `results` what a search finds, the
    service failing when there are none."""

    pages: dict[tuple[str, str], tuple[int, dict[str, str], bytes]] = field(default_factory=dict)
    hosts: dict[str, list[str]] = field(default_factory=lambda: dict(HOSTS))
    results: list[dict[str, str]] = field(default_factory=list)
    sent: list[httpx2.Request] = field(default_factory=list)

    async def resolve(self, host: str, port: int) -> list[str]:
        """The host's addresses, as the system's resolver gives them: an address for itself."""
        try:
            return [str(ipaddress.ip_address(host))]
        except ValueError:
            pass
        if host not in self.hosts:
            raise OSError(f"no address for {host}")
        return self.hosts[host]

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.sent.append(request)
        if str(request.url) == SEARCH_URL:
            if not self.results:
                return httpx2.Response(500)
            return httpx2.Response(200, json={"results": self.results})
        host = request.headers["host"]
        assert request.url.host in self.hosts[host]  # the address checked, connected to
        path = request.url.raw_path.decode()
        status, headers, body = self.pages.get((host, path), (404, {}, b""))
        return httpx2.Response(status, headers=headers, content=body)


def install(world: World, fake: FakeWeb) -> FakeWeb:
    """Give `world`'s web the fake network and resolver of `fake`."""
    world.web.transport = httpx2.MockTransport(fake.handler)
    world.web.resolve = fake.resolve
    return fake
