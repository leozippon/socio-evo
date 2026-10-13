"""Concrete work: task providers implementing the work protocol of `core.environment`, one for
each trade, a kind of work with its own banks and its own way of checking.

`PROVIDERS` names each trade's provider class, built alike over a bank directory; the shared
layout of banks is `tasks.bank`, the isolation of delivered work `tasks.sandbox`, and the
calibration of banks against a model `tasks.calibrate`. The words of each trade (what a worker
hands in, what it is tried against) are the environment's, which tells them.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from core.environment import Part, TaskProvider, Trade
from tasks.calculation import CalculationProvider
from tasks.coding import CodingTaskProvider
from tasks.queries import QueryProvider
from tasks.sandbox import Isolation


class Provider(TaskProvider, Protocol):
    """What every trade's provider offers besides the work protocol: its bank by task name,
    a task of it as a part, and whether a delivery writes out what the visible checks look
    for instead of working it out. Every provider is built over its bank with the seconds
    each check of a delivery may run and how a delivery is separated from the machine, which
    a trade that runs nothing does not use."""

    bank: Mapping[str, object]

    def __init__(self, path: Path, *, timeout: float, isolation: Isolation) -> None: ...

    def part(self, name: str) -> Part: ...

    def special_cased(self, part: Part, solution: str) -> bool: ...


PROVIDERS: dict[Trade, type[Provider]] = {
    Trade.PROGRAMMING: CodingTaskProvider,
    Trade.QUERIES: QueryProvider,
    Trade.CALCULATION: CalculationProvider,
}
