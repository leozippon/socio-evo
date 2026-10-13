"""Calculation tasks: problems with one numeric answer, judged by the answer alone, and their
provider.

The built-in bank is `BANK`, three problems. Larger banks are converted from NuminaMath into
a data directory outside the repository by `python -m tasks.calculation.fetch`, and
calibrated against a model by `python -m tasks.calibrate`.
"""

from pathlib import Path

from tasks.calculation.provider import CalculationProvider, CalculationTask, load_bank

BANK = Path(__file__).with_name("bank")
"""The built-in calculation bank."""

__all__ = ["BANK", "CalculationProvider", "CalculationTask", "load_bank"]
