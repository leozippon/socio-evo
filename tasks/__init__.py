"""Concrete work: task providers implementing the work protocol of `core.environment`, one for
each trade, a kind of work with its own banks and its own way of checking.

`PROVIDERS` names each trade's provider class, built over a bank directory; the shared layout of
banks is `tasks.bank`, the isolation of delivered work `tasks.sandbox`, and the calibration of
banks against a model `tasks.calibrate`.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar, Protocol

from core.environment import Part, TaskProvider
from tasks.bank import Trade
from tasks.calculation import CalculationProvider
from tasks.coding import CodingTaskProvider
from tasks.queries import QueryProvider


class Provider(TaskProvider, Protocol):
    """What every trade's provider offers besides the work protocol: its bank by task name,
    a task of it as a part, and whether a delivery writes out what the visible checks look
    for instead of working it out."""

    delivery: ClassVar[str]
    """What a worker hands in, in the town's words."""

    bank: Mapping[str, object]

    def __init__(self, path: Path) -> None: ...

    def part(self, name: str) -> Part: ...

    def special_cased(self, part: Part, solution: str) -> bool: ...


PROVIDERS: dict[Trade, type[Provider]] = {
    Trade.PROGRAMMING: CodingTaskProvider,
    Trade.QUERIES: QueryProvider,
    Trade.CALCULATION: CalculationProvider,
}
