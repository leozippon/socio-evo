"""One real session against the local vLLM server, as the environment names it
(VLLM_BASE_URL, VLLM_API_KEY); skipped when the server cannot be reached. The resident is Mei
with the real town's rules. The server counts cached prompt tokens in units of well over a
thousand tokens (a repeated 5,233-token prompt reports 4,704 cached, a 1,219-token one none), so
a session this short cannot show a cache hit; the test checks that the count is reported, and
the service's probe (`ops/vllm/verify.py`) checks hits on a long repeated prefix."""

import asyncio
import os
from pathlib import Path

import httpx2
import pytest

from agent.directory import AgentDirectory
from agent.runtime import Runtime, RuntimeConfig
from agent.testing import FakePort, running
from experiments.config import load_experiment
from infrastructure.llm import LLMConfig, OpenAICompatibleClient
from infrastructure.storage import read_jsonl
from world.rules import Rules

REPO = Path(__file__).resolve().parents[2]


def _served() -> LLMConfig:
    base_url, key = os.environ.get("VLLM_BASE_URL"), os.environ.get("VLLM_API_KEY")
    if not base_url or not key:
        pytest.skip("VLLM_BASE_URL and VLLM_API_KEY are not set")
    try:
        models = httpx2.get(
            f"{base_url}/models", headers={"Authorization": f"Bearer {key}"}, timeout=5
        )
        models.raise_for_status()
    except httpx2.HTTPError as error:
        pytest.skip(f"the vLLM server cannot be reached: {type(error).__name__}")
    model = models.json()["data"][0]["id"]
    return LLMConfig(base_url=base_url, api_key_env="VLLM_API_KEY", model=model, timeout=600)


async def test_a_real_session_writes_a_file_then_replies(tmp_path):
    config = _served()
    town = load_experiment(REPO / "experiments" / "configs" / "groups" / "a.yaml").town
    directory = AgentDirectory.create(
        tmp_path / "mei",
        background=(REPO / "experiments" / "residents" / "mei.md").read_text(encoding="utf-8"),
        town=Rules(town).text("Mei"),
    )
    port = FakePort(
        situation="It is 18:30 on Monday. You are at home. Only your files are at hand."
    )
    port.deliver(
        "You remember that today you fixed task 3, a crash when a settings file was empty. "
        "Add one line about it to memory/work.md, then stop for the evening."
    )
    runtime = Runtime(
        directory,
        port,
        OpenAICompatibleClient(config),
        RuntimeConfig(reasoning_effort="low", reply_max_tokens=4096),
    )
    async with running(runtime):
        await asyncio.wait_for(port.waiting.wait(), 600)

    records = list(read_jsonl(directory.trace_path))
    replies = [r for r in records if r["kind"] == "reply"]
    assert not [r for r in records if r["kind"] == "lapse"]
    writes = [
        r for r in records if r["kind"] == "tool_call" and r["name"] in ("write_file", "edit_file")
    ]
    assert writes and all(r["arguments"]["path"] == "memory/work.md" for r in writes)
    assert "3" in (directory.root / "memory" / "work.md").read_text()
    assert replies[-1]["tool_calls"] == [] and replies[-1]["finish_reason"] == "stop"
    assert len(replies) >= 2 and all(r["usage"]["cached_prompt_tokens"] is not None for r in replies)
