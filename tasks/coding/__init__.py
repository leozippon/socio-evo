"""Coding tasks: a YAML task bank, a sandbox for model-written code, and their provider."""

from pathlib import Path

from tasks.coding.provider import CodingTask, CodingTaskProvider, load_bank
from tasks.coding.sandbox import Check, CheckResult, Isolation, run_checks
from tasks.coding.special_cases import special_cases

BANK = Path(__file__).with_name("bank")
"""The in-simulation task bank."""

__all__ = [
    "BANK",
    "Check",
    "CheckResult",
    "CodingTask",
    "CodingTaskProvider",
    "Isolation",
    "load_bank",
    "run_checks",
    "special_cases",
]
