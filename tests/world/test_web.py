"""The web at the Office: there and nowhere else; a search sent to the service with the key that
nothing else ever holds; a page read by one plain GET of a checked public address, redirects
checked again, what comes back capped and clipped; so many a day; logged for the reader alone.
No test reaches the network: the fake of `tests.world.fakeweb` answers."""

from __future__ import annotations

import json

import pytest

from tests.support.towns import awake_at, town_config
from tests.world.fakeweb import FakeWeb, install
from world.config import SEARCH_KEY, WebSettings
from world.web import AGENT, MAX_BYTES, PAGE_CHARS, SEARCH_URL

KEY = "the-secret-search-key"
HTML = (
    b"<html><head><title>T</title><style>p {}</style></head><body><h1>Hello</h1>"
    b"<script>track()</script><p>World &amp;  more</p><ul><li>one</li><li>two</li></ul></body>"
    b"</html>"
)


@pytest.fixture
def web_town(make_town, monkeypatch):
    """The small town whose workshop has the web, two searches and three pages a day; Mei and
    Tomas at work there."""
    monkeypatch.setenv(SEARCH_KEY, KEY)
    web = WebSettings(enabled=True, searches_a_day=2, pages_a_day=3)
    town = make_town(town_config().model_copy(update={"web": web}))
    fake = install(town.world, FakeWeb())

    async def ready():
        await awake_at(town)
        for name in ("Mei", "Tomas"):
            await town.call(name, "go", place="workshop")
        await town.until("07:10")
        return town, fake

    return ready


def names(town, who: str) -> set[str]:
    return {spec.name for spec in town.world.ports[who].tool_specs()}


def logged(town, kind: str) -> list[dict]:
    return [e for e in town.world.log.entries() if e["kind"] == kind]


async def test_the_web_is_at_the_office_alone_and_the_rules_say_so(web_town, make_town):
    town, _ = await web_town()
    assert {"search_web", "read_page"} <= names(town, "Mei")
    assert {"search_web", "read_page"}.isdisjoint(names(town, "Aisha"))  # at home
    refused = await town.call("Aisha", "search_web", query="news")
    assert refused.text == "The web is at the workshop, and you are not there."
    assert (
        "The workshop has the web: anyone there can search it with search_web and read a public "
        "page with read_page, 2 searches and 3 pages a day."
    ) in town.world.rules.sections("Aisha")["town"]
    without = make_town(town_config(), root=town.world.log.path.parent / "without")
    assert not without.world.knows("search_web") and not without.world.knows("read_page")
    assert "web" not in without.world.rules.text("Mei")


async def test_a_search_goes_to_the_service_with_the_key_and_is_logged_for_the_searcher(web_town):
    town, fake = await web_town()
    fake.results = [
        {"title": "A  fix", "url": "https://a.example/fix", "content": "The   fix is here."},
        {"title": "", "url": "https://b.example/", "content": "x" * 1000},
    ]
    found = await town.call("Mei", "search_web", query="parse dates")
    assert found.text.startswith(
        "What the web has for “parse dates”:\n1. A fix\n   https://a.example/fix\n   The fix is "
        "here.\n2. (no title)\n   https://b.example/\n   xxx"
    )
    [request] = fake.sent
    assert request.method == "POST" and str(request.url) == SEARCH_URL
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert json.loads(request.content) == {"query": "parse dates", "max_results": 5}
    [entry] = logged(town, "web_search")
    assert entry["actor"] == "Mei" and entry["audience"] == []
    assert entry["payload"] == {
        "query": "parse dates", "results": 2, "characters": len(found.text), "ok": True,
    }  # fmt: skip
    fake.results = []  # the service fails
    failed = await town.call("Mei", "search_web", query="again")
    assert failed.text == "The search could not be made just now."
    assert logged(town, "web_search")[-1]["payload"]["ok"] is False
    assert KEY not in town.world.log.path.read_text() and KEY not in found.text + failed.text


async def test_a_page_is_one_plain_get_of_the_checked_address_reduced_to_its_text(web_town):
    town, fake = await web_town()
    fake.pages[("example.org", "/a?b=1")] = (200, {"content-type": "text/html"}, HTML)
    read = await town.call("Mei", "read_page", address=" http://example.org/a?b=1#top ")
    assert read.text == "The page at http://example.org/a?b=1#top:\n\nHello\nWorld & more\none\ntwo"
    [request] = fake.sent
    assert request.method == "GET" and request.content == b""
    assert str(request.url) == "http://93.184.215.14/a?b=1"  # the address checked, port 80
    assert dict(request.headers) == {"host": "example.org", "user-agent": AGENT.decode()}
    assert "sni_hostname" not in request.extensions
    [entry] = logged(town, "web_page")
    assert entry["audience"] == [] and entry["payload"] == {
        "url": "http://example.org/a?b=1#top", "final": "http://example.org/a?b=1#top",
        "status": 200, "bytes": len(HTML), "characters": len("Hello\nWorld & more\none\ntwo"),
        "ok": True,
    }  # fmt: skip
    # Over https, to an IPv6 address, the name is still the one the certificate is checked for.
    fake.pages[("news.example", "/")] = (200, {"content-type": "text/plain"}, b"Plain news.")
    read = await town.call("Tomas", "read_page", address="https://news.example")
    assert read.text == "The page at https://news.example:\n\nPlain news."
    request = fake.sent[-1]
    assert str(request.url) == "https://[2606:2800:21f:cb07::1]/"
    assert request.extensions["sni_hostname"] == "news.example"


@pytest.mark.parametrize(
    ("address", "refused"),
    [
        ("http://127.0.0.1/", "127.0.0.1 is not on the public web."),
        ("http://localhost:80/admin", "localhost is not on the public web."),
        ("http://10.1.2.3/", "10.1.2.3 is not on the public web."),
        ("http://172.16.5.4/", "172.16.5.4 is not on the public web."),
        ("http://192.168.0.1/", "192.168.0.1 is not on the public web."),
        ("http://169.254.169.254/latest/", "169.254.169.254 is not on the public web."),
        ("http://100.64.0.1/", "100.64.0.1 is not on the public web."),
        ("http://0.0.0.0/", "0.0.0.0 is not on the public web."),
        ("http://224.0.0.1/", "224.0.0.1 is not on the public web."),
        ("http://240.0.0.1/", "240.0.0.1 is not on the public web."),
        ("http://[::1]/", "::1 is not on the public web."),
        ("http://[fe80::1]/", "fe80::1 is not on the public web."),
        ("http://[fc00::1]/", "fc00::1 is not on the public web."),
        ("http://[::ffff:127.0.0.1]/", "::ffff:127.0.0.1 is not on the public web."),
        ("http://[ff02::1]/", "ff02::1 is not on the public web."),
        ("http://mixed.example/", "mixed.example is not on the public web."),
        ("http://nowhere.example/", "There is no such address as nowhere.example on the web."),
        ("ftp://example.org/", "Give an address that begins with http:// or https://."),
        ("file:///etc/passwd", "Give an address that begins with http:// or https://."),
        ("example.org", "Give an address that begins with http:// or https://."),
        ("http://user:pw@example.org/", "http://user:pw@example.org/ is not a public address."),
        ("http://example.org:8080/", "Pages are read on the usual port only, not 8080."),
        ("https://example.org:80/", "Pages are read on the usual port only, not 80."),
        ("http://example.org:99999/", "http://example.org:99999/ is not a web address."),
    ],
)
async def test_an_address_off_the_public_web_is_refused_and_nothing_is_sent(
    web_town, address, refused
):
    town, fake = await web_town()
    fake.hosts |= {"localhost": ["127.0.0.1"], "mixed.example": ["93.184.215.14", "10.0.0.1"]}
    read = await town.call("Mei", "read_page", address=address)
    assert read.text == refused and fake.sent == []
    assert logged(town, "web_page")[-1]["payload"]["ok"] is False


async def test_a_redirect_is_checked_again_and_followed_a_few_times_at_most(web_town):
    town, fake = await web_town()
    fake.pages |= {
        ("example.org", "/old"): (301, {"location": "/new"}, b""),
        ("example.org", "/new"): (200, {"content-type": "text/plain"}, b"Moved here."),
        ("example.org", "/out"): (302, {"location": "http://10.0.0.1/inside"}, b""),
        ("example.org", "/loop"): (302, {"location": "/loop"}, b""),
    }
    read = await town.call("Mei", "read_page", address="http://example.org/old")
    assert read.text == "The page at http://example.org/new:\n\nMoved here."
    assert logged(town, "web_page")[-1]["payload"]["final"] == "http://example.org/new"
    fake.sent.clear()
    read = await town.call("Mei", "read_page", address="http://example.org/out")
    assert read.text == "10.0.0.1 is not on the public web."
    assert [r.url.path for r in fake.sent] == ["/out"]  # the private address never reached
    fake.sent.clear()
    read = await town.call("Tomas", "read_page", address="http://example.org/loop")
    assert read.text == "The page sent you on too many times." and len(fake.sent) == 6


async def test_what_comes_back_is_read_up_to_a_size_and_clipped_and_other_kinds_refused(web_town):
    town, fake = await web_town()
    fake.pages |= {
        ("example.org", "/big"): (200, {"content-type": "text/plain"}, b"w " * MAX_BYTES),
        ("example.org", "/picture"): (200, {"content-type": "image/png"}, b"\x89PNG"),
        ("example.org", "/gone"): (404, {}, b""),
    }
    read = await town.call("Mei", "read_page", address="http://example.org/big")
    assert read.text.endswith("\n\n[The page goes on; this is as much of it as can be read here.]")
    assert len(read.text) < PAGE_CHARS + 200
    assert logged(town, "web_page")[-1]["payload"]["bytes"] == MAX_BYTES + 1
    read = await town.call("Mei", "read_page", address="http://example.org/picture")
    assert read.text == (
        "The page at http://example.org/picture is not text that can be read here (image/png)."
    )
    read = await town.call("Mei", "read_page", address="http://example.org/gone")
    assert read.text == "The page at http://example.org/gone answered 404."


async def test_each_resident_has_so_many_a_day_and_the_count_starts_again_at_the_checkpoint(
    web_town,
):
    town, fake = await web_town()
    fake.results = [{"title": "T", "url": "https://t.example/", "content": "c"}]
    for _ in range(2):
        assert (await town.call("Mei", "search_web", query="q")).text.startswith("What the web")
    refused = await town.call("Mei", "search_web", query="q")
    assert refused.text == "You have searched the web 2 times today, as many as a day allows."
    assert len(logged(town, "web_search")) == 2  # the refused one went nowhere
    assert (await town.call("Tomas", "search_web", query="q")).text.startswith("What the web")
    for _ in range(3):
        await town.call("Mei", "read_page", address="http://nowhere.example/")
    refused = await town.call("Mei", "read_page", address="http://nowhere.example/")
    assert refused.text == "You have read 3 pages of the web today, as many as a day allows."
    town.rest()
    await town.until("02:30", day=2)  # the checkpoint
    assert town.world.web.used == {} and town.checkpoints
    await town.until("07:00", day=2)
    await town.call("Mei", "go", place="workshop")
    await town.until("07:20", day=2)
    assert (await town.call("Mei", "search_web", query="q")).text.startswith("What the web")
