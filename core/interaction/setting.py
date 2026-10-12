"""The world a town is set in: its name, what every resident knows of it, its money and its
calendar.

Reality and the residents' own minds tell money and days by it alike, which is why it belongs
to the protocol between them: `Currency.tell` is the one definition of how an amount is told,
and `Setting.start_date` the one source of the date of day 1, from which every weekday a
resident reads and the date of every commit in its history follow.
"""

from datetime import date

from pydantic import Field

from core.interaction.time import DAY_ONE
from infrastructure.config import StrictModel


class Currency(StrictModel):
    """The town's money: `unit` and `units`, its name for one and for several (`dollar`,
    `dollars`), and the `symbol` written before an amount in their place, if it has one
    (`$`). Amounts are whole numbers."""

    unit: str = Field(min_length=1)
    units: str = Field(min_length=1)
    symbol: str | None = Field(default=None, min_length=1)

    def tell(self, amount: int) -> str:
        """`amount` as a resident reads it: `$30` or `-$5` with a symbol, else `30 crowns` or
        `1 crown`."""
        if self.symbol is not None:
            return f"-{self.symbol}{-amount}" if amount < 0 else f"{self.symbol}{amount}"
        return f"{amount} {self.unit if abs(amount) == 1 else self.units}"


class Setting(StrictModel):
    """The town's `name`, if it has one; its `backdrop`, prose that opens what every resident
    knows of the town, written in the town's voice (and so under invariants 1 and 8 like every
    other text a resident reads); its `currency`; and the `start_date` of day 1. Every part is
    optional, and a part left out means what the town meant before it could be configured: a
    town without a name or backdrop, money in crowns, and day 1 on Monday, 1 January 2001."""

    name: str | None = Field(default=None, min_length=1)
    backdrop: str = ""
    currency: Currency = Currency(unit="crown", units="crowns")
    start_date: date = DAY_ONE
