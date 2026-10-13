"""Concrete work: task providers implementing the work protocol of `core.environment`, one for
each trade, a kind of work with its own banks and its own way of checking.

`PROVIDERS` names each trade's provider class, built alike over a bank directory, and
`BUILT_IN` each trade's built-in bank, a few tasks kept in the repository, on which dry runs
and tests work without a fetched bank; the shared layout of banks is `tasks.bank`, the
isolation of delivered work `tasks.sandbox`, and the calibration of banks against a model
`tasks.calibrate`. The words of each trade (what a worker hands in, what it is tried against)
are the environment's, which tells them.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from core.environment import Part, TaskProvider, Trade
from tasks import calculation, coding, queries
from tasks.sandbox import Isolation


class Provider(TaskProvider, Protocol):
    """What every trade's provider offers besides the work protocol: its bank by task name
    and a task of it as a part. Every provider is built over its bank with the seconds each
    check of a delivery may run and how a delivery is separated from the machine, which a
    trade that runs nothing does not use."""

    bank: Mapping[str, object]

    def __init__(self, path: Path, *, timeout: float, isolation: Isolation) -> None: ...

    def part(self, name: str) -> Part: ...


PROVIDERS: dict[Trade, type[Provider]] = {
    Trade.PROGRAMMING: coding.CodingTaskProvider,
    Trade.QUERIES: queries.QueryProvider,
    Trade.CALCULATION: calculation.CalculationProvider,
}

BUILT_IN: dict[Trade, Path] = {
    Trade.PROGRAMMING: coding.BANK,
    Trade.QUERIES: queries.BANK,
    Trade.CALCULATION: calculation.BANK,
}
