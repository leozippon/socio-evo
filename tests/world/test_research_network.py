"""Provider request contracts, truthful failures, and curl's public-source boundary."""

import json
import socket
import subprocess
from pathlib import Path

import pytest

from world import research_sources as sources


def test_search_services_use_separate_credentials_and_record_no_keys(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "private-tavily-key")
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "private-scholar-key")
    calls = []

    def request(host, path, **kwargs):
        calls.append((host, path, kwargs))
        if "tavily" in host:
            return {
                "results": [
                    {
                        "title": "Study",
                        "url": "https://example.org",
                        "content": "Excerpt",
                        "api_key": "private-tavily-key",
                    }
                ]
            }
        return {
            "data": [
                {
                    "title": "Paper",
                    "abstract": "A result",
                    "year": 2026,
                    "url": "https://example.org/paper",
                    "key": "private-scholar-key",
                }
            ]
        }

    monkeypatch.setattr(sources, "_api", request)
    web, literature = sources.search_web("causal inference"), sources.search("causal inference")
    assert web["results"][0]["content"] == "Excerpt"
    assert literature["results"][0]["abstract"] == "A result"
    assert calls[0][2]["headers"] == {"Authorization": "Bearer private-tavily-key"}
    assert calls[1][2]["headers"] == {"x-api-key": "private-scholar-key"}
    assert "query=causal+inference" in calls[1][1]
    assert "private-" not in json.dumps([web, literature])


def test_scholar_key_is_optional_and_missing_tavily_key_fails(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    calls = []

    def request(host, path, **kwargs):
        calls.append(kwargs)
        return {"data": []}

    monkeypatch.setattr(sources, "_api", request)
    with pytest.raises(ValueError, match="TAVILY_API_KEY"):
        sources.search_web("research")
    assert not calls
    assert sources.search("research")["results"] == []
    assert calls == [{"headers": {}}]


def test_provider_error_does_not_expose_response_or_credentials(monkeypatch):
    class Connection:
        def __init__(self, *args, **kwargs):
            self.status = 429

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return self

        def read(self, size):
            pytest.fail("Error body may contain a credential; do not expose it.")

        def close(self):
            pass

    monkeypatch.setattr(sources.http.client, "HTTPSConnection", Connection)
    with pytest.raises(ValueError, match="HTTP 429") as error:
        sources._api("api.tavily.com", "/search", headers={"Authorization": "private-key"})
    assert "private-key" not in str(error.value)


@pytest.mark.parametrize("status", [200, 429, 302])
def test_curl_captures_body_and_rejects_http_failures_or_private_redirect(monkeypatch, status):
    calls = []

    def addresses(host, port, **kwargs):
        ip = "127.0.0.1" if host == "127.0.0.1" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    def command(args, **kwargs):
        calls.append((args, kwargs))
        assert "--location" not in args  # each redirect must pass address validation
        assert "example.org:443:93.184.216.34" in args
        header = Path(args[args.index("--dump-header") + 1])
        header.write_text(
            f"HTTP/1.1 {status} Response\r\nContent-Type: text/plain\r\n"
            "Location: http://127.0.0.1/private\r\n\r\n"
        )
        Path(args[args.index("--output") + 1]).write_text("observed result")
        return subprocess.CompletedProcess(args, 0, str(status).encode(), b"")

    monkeypatch.setattr(sources.socket, "getaddrinfo", addresses)
    monkeypatch.setattr(sources.subprocess, "run", command)
    if status == 200:
        result = sources.curl_source("https://example.org/paper")
        assert result["text"] == "observed result"
        assert result["content_type"] == "text/plain"
    else:
        with pytest.raises(ValueError, match="HTTP 429" if status == 429 else "Private"):
            sources.curl_source("https://example.org/paper")
    assert len(calls) == 1
    assert set(calls[0][1]["env"]) == {"PATH"}
    assert not Path(calls[0][0][calls[0][0].index("--output") + 1]).exists()
