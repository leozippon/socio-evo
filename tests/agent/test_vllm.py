"""One real session against the local vLLM server, as the environment names it
(VLLM_BASE_URL, VLLM_API_KEY); skipped when the server cannot be reached."""

import asyncio
import os

import httpx2
import pytest

from agent.directory import AgentDirectory
from agent.runtime import Runtime, RuntimeConfig
from agent.testing import FakePort, running
from infrastructure.llm import LLMConfig, OpenAICompatibleClient
from infrastructure.storage import read_jsonl


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
    directory = AgentDirectory.create(
        tmp_path / "ana",
        background="# Ana Reyes\n\nYou are Ana Reyes, a programmer who lives in a small town.",
        town="The workshop opens at 09:00 and closes at 18:00.",
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
    assert len(replies) >= 2 and replies[1]["usage"]["cached_prompt_tokens"] > 0
