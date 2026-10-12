"""Calculation tasks: problems with one numeric answer, judged by the answer alone, and their
provider.

Banks are converted from NuminaMath into a data directory outside the repository by
`python -m tasks.calculation.fetch`, and calibrated against a model by
`python -m tasks.calibrate`.
"""

from tasks.calculation.provider import CalculationProvider, CalculationTask, load_bank

__all__ = ["CalculationProvider", "CalculationTask", "load_bank"]
