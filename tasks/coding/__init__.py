"""Coding tasks: a YAML task bank, a sandbox for model-written code, and their provider."""

from pathlib import Path

from tasks.coding.provider import CodingTask, CodingTaskProvider, load_bank
from tasks.coding.sandbox import CheckResult, run_checks

BANK = Path(__file__).with_name("bank")
"""The in-simulation task bank."""

__all__ = ["BANK", "CheckResult", "CodingTask", "CodingTaskProvider", "load_bank", "run_checks"]
