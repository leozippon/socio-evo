"""Adapters loaded and unloaded on a model server that speaks vLLM's runtime LoRA API, on
localhost: idempotent for the same adapter, loud for anything else, probed on every replica."""

from __future__ import annotations

import pytest

from infrastructure.llm import LLMCallError, LLMConfig, LLMConfigError
from infrastructure.llm.adapters import load_adapter, unload_adapter
from tests.support.server import KEY, FakeServer


@pytest.fixture
def server(monkeypatch):
    with FakeServer() as running:
        monkeypatch.setenv(KEY, running.key)
        yield running


def adapter(folder):
    folder.mkdir(parents=True)
    (folder / "adapter_config.json").write_text("{}")
    return folder


def config(server, **changes) -> LLMConfig:
    settings = {"base_url": server.url, "api_key_env": KEY, "model": "served", "replicas": 2}
    return LLMConfig(**(settings | changes))


async def test_an_adapter_is_loaded_once_on_every_replica_and_unloaded_once(server, tmp_path):
    path = adapter(tmp_path / "a" / "night-01")
    await load_adapter(config(server), "town-Ana-night-01", path)
    await load_adapter(config(server), "town-Ana-night-01", path)  # idempotent
    assert server.loaded == {"town-Ana-night-01": str(path.resolve())}
    loads = [body for method, url, body, _ in server.calls if url.endswith("/load_lora_adapter")]
    assert loads == [{"lora_name": "town-Ana-night-01", "lora_path": str(path.resolve())}]
    probes = [
        (body["model"], body["max_tokens"], rank)
        for _, url, body, rank in server.calls
        if url.endswith("/chat/completions")
    ]
    assert probes == [("town-Ana-night-01", 1, "0"), ("town-Ana-night-01", 1, "1")] * 2

    await unload_adapter(config(server), "town-Ana-night-01")
    await unload_adapter(config(server), "town-Ana-night-01")  # nothing left to unload
    assert server.loaded == {}
    unloads = [url for _, url, _, _ in server.calls if url.endswith("/unload_lora_adapter")]
    assert unloads == ["/v1/unload_lora_adapter"]
    one = config(server, replicas=1)
    await load_adapter(one, "town-Ana-night-01", path)
    assert server.calls[-1][1:] == (
        "/v1/chat/completions",
        {
            "model": "town-Ana-night-01",
            "messages": [{"role": "user", "content": "Yes?"}],
            "max_tokens": 1,
        },
        None,
    )


async def test_a_name_taken_a_refusal_or_a_missing_key_fails_loudly(server, tmp_path, monkeypatch):
    first, second = adapter(tmp_path / "one"), adapter(tmp_path / "two")
    await load_adapter(config(server), "town-Ana-night-01", first)
    with pytest.raises(LLMCallError, match="is loaded from .*one, not .*two"):
        await load_adapter(config(server), "town-Ana-night-01", second)
    with pytest.raises(LLMCallError, match="load_lora_adapter: 404 No adapter found"):
        await load_adapter(config(server), "town-Ana-night-02", tmp_path / "nowhere")
    server.refuse = True
    with pytest.raises(LLMCallError, match="404"):
        await load_adapter(config(server), "town-Ana-night-03", second)
    assert set(server.loaded) == {"town-Ana-night-01"}
    monkeypatch.setenv("SOCIO_EVO_OTHER_KEY", "wrong")
    with pytest.raises(LLMCallError, match="GET /models: 401"):
        await load_adapter(config(server, api_key_env="SOCIO_EVO_OTHER_KEY"), "x", first)
    monkeypatch.delenv(KEY)
    with pytest.raises(LLMConfigError, match=f"{KEY} is not set"):
        await unload_adapter(config(server), "town-Ana-night-01")
    stopped = config(server, base_url="http://127.0.0.1:9/v1")
    monkeypatch.setenv(KEY, server.key)
    with pytest.raises(LLMCallError, match="GET /models: ConnectError"):
        await load_adapter(stopped, "town-Ana-night-01", first)
