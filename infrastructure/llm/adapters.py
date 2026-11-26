"""LoRA adapters on the model server: loaded and unloaded while it serves.

vLLM started with `--enable-lora` and `VLLM_ALLOW_RUNTIME_LORA_UPDATING=True` loads an adapter
from a directory it can read (`POST /v1/load_lora_adapter`), lists it among its models with that
directory as its `root` (`GET /v1/models`), serves a request that names it as its model, and lets
it go again (`POST /v1/unload_lora_adapter`). An adapter's name is its identity: the server's
prefix cache is keyed by it, so a new version of an adapter takes a new name and directory.

`load_adapter` is idempotent for the same name and directory and refuses a name already loaded
from another; it then asks every replica (`LLMConfig.replicas`, by vLLM's `X-data-parallel-rank`
header) for one token from the adapter, so that an adapter one of them cannot serve fails here,
loudly, and not in a resident's request. `unload_adapter` of an adapter not loaded does nothing.
Every other answer of the server raises `LLMCallError` with what it said. The directory is sent as
an absolute path, which the server must see as this process does.
"""

import os
from pathlib import Path
from typing import Any

import httpx2

from infrastructure.llm.base import LLMCallError, LLMConfigError
from infrastructure.llm.config import LLMConfig

TIMEOUT = 300.0
"""Seconds an answer may take: loading reads the adapter's weights from disk."""


async def load_adapter(config: LLMConfig, name: str, path: Path) -> None:
    """Load the adapter in the directory `path` as `name` on the server of `config`, on every
    replica."""
    root = str(path.resolve())
    async with _server(config) as server:
        loaded = await _loaded(server)
        if name not in loaded:
            await _post(server, "/load_lora_adapter", {"lora_name": name, "lora_path": root})
        elif loaded[name] != root:
            raise LLMCallError(f"the adapter {name} is loaded from {loaded[name]}, not {root}")
        for replica in range(config.replicas):
            headers = {"X-data-parallel-rank": str(replica)} if config.replicas > 1 else {}
            probe = {"model": name, "messages": [{"role": "user", "content": "Yes?"}]}
            await _call(
                server, "POST", "/chat/completions", json=probe | {"max_tokens": 1}, headers=headers
            )


async def unload_adapter(config: LLMConfig, name: str) -> None:
    """Let the adapter `name` go from the server of `config`, if it is loaded."""
    async with _server(config) as server:
        if name in await _loaded(server):
            await _post(server, "/unload_lora_adapter", {"lora_name": name})


def _server(config: LLMConfig) -> httpx2.AsyncClient:
    """A client of the server's API, `base_url` expanded as `create_client` expands it."""
    key = os.environ.get(config.api_key_env)
    if not key:
        raise LLMConfigError(f"API key variable {config.api_key_env} is not set")
    base_url = os.path.expandvars(config.base_url)
    if "$" in base_url:
        raise LLMConfigError(f"base_url {config.base_url} names an unset environment variable")
    return httpx2.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {key}"},
        timeout=TIMEOUT,
    )


async def _loaded(server: httpx2.AsyncClient) -> dict[str, str]:
    """The adapters the server has loaded: each name with the directory it was loaded from."""
    response = await _call(server, "GET", "/models")
    return {
        model["id"]: model["root"]
        for model in response.json()["data"]
        if model.get("parent") is not None
    }


async def _post(server: httpx2.AsyncClient, path: str, body: dict[str, Any]) -> None:
    await _call(server, "POST", path, json=body)


async def _call(
    server: httpx2.AsyncClient, method: str, path: str, **kwargs: Any
) -> httpx2.Response:
    try:
        response = await server.request(method, path, **kwargs)
    except httpx2.HTTPError as error:
        raise LLMCallError(f"{method} {path}: {type(error).__name__}: {error}") from error
    if response.status_code != 200:
        raise LLMCallError(f"{method} {path}: {response.status_code} {response.text.strip()}")
    return response
