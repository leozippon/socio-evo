"""Explicit direct execution preserves grading and does not change the default."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from core.environment import Trade
from experiments.config import PROJECT_ROOT, ExperimentConfig, TasksConfig
from experiments.run import setup
from infrastructure.config import load_config
from tasks.coding import BANK, CodingTaskProvider
from tasks.coding.sandbox import Isolation


def test_isolation_requires_an_explicit_valid_choice():
    assert TasksConfig().isolation is Isolation.BUBBLEWRAP
    assert CodingTaskProvider(BANK).isolation is Isolation.BUBBLEWRAP
    with pytest.raises(ValidationError):
        TasksConfig(isolation="invalid")


async def test_direct_profile_runs_real_checks_and_preserves_grading(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VLLM_API_KEY", "test-only")
    config = load_config(
        PROJECT_ROOT / "experiments/configs/zenith-direct-smoke.yaml", ExperimentConfig
    )
    assert config.tasks.isolation is Isolation.NONE
    # This grading test uses a tiny fixture bank, independently of downloaded deployment data.
    config = config.model_copy(
        update={"tasks": config.tasks.model_copy(update={"banks": {Trade.PROGRAMMING: str(BANK)}})}
    )
    parts = setup(config, 0, tmp_path / "calls.jsonl")
    provider = parts.providers[Trade.PROGRAMMING]
    assert provider.isolation is Isolation.NONE
    task = provider.part("roman_to_int")
    failed = await provider.assess(task, "def roman_to_int(value): return -1")
    assert not failed.passed
    assert failed.quality == 0
    source = """
def roman_to_int(value):
    digits = dict(I=1, V=5, X=10, L=50, C=100, D=500, M=1000)
    result = previous = 0
    for char in reversed(value):
        current = digits[char]
        result += -current if current < previous else current
        previous = max(previous, current)
    return result
"""
    passed = await provider.assess(task, source)
    assert passed.passed
    assert passed.quality == 1
