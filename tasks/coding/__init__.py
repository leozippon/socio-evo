"""Coding tasks: YAML task banks, a sandbox for model-written code, and their provider.

The built-in bank is `BANK`. Larger banks are converted from LiveCodeBench into a data
directory outside the repository by `python -m tasks.coding.fetch`, and calibrated against a
model by `python -m tasks.coding.calibrate`.
"""

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
