"""The town's money: each resident's inventory and the town's one fund.

Money is a whole number of the town's currency (`money` writes it). A resident's `Inventory` is
what it has: its money, never below zero, and its items, the units it keeps of each good (one of
a durable, the helpings left of a stock), with `moves`, the movements of its money since its
last midnight statement, which the statement tells. A purchase is paid in cash from the
inventory, and the world refuses one that its money does not cover; money and items pass between
residents as they hand them over, of which the world keeps no account beyond the hand-over.

The `Fund` is the town's money: the employer, the landlord and the owner of the shops. Money
enters the town only from clients, whose payment for a task accepted goes to the fund, and would
leave it only to a supplier, whom this town does not yet pay; everything else moves between the
fund and the residents, so that the fund and the inventories together change only by what clients
pay. The fund pays what it has. A sum per service goes into the inventory at once
(`Fund.service`); the day's wages are paid at midnight with the rent and the daily charges taken
out of them (`Fund.settle`), so that money in hand is never touched by rent. What the fund cannot
pay it owes (`owed`) and pays with the next wages; the rent and charges the wages did not cover
are owed to it (`arrears`) and taken from the next wages. Its `ledger` keeps its movements since
the last midnight by kind (`TAKEN` and `PAID`), and `yesterday` those of the day the last
midnight closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TAKEN = {"client": "from clients", "rent": "in rent and daily charges", "sale": "in sales"}
"""The kinds of money the fund takes in, with how the report words each."""
PAID = {"wage": "in wages", "service": "in sums for services"}
"""The kinds of money the fund pays out, with how the report words each."""


def money(currency: str, amount: int) -> str:
    """`amount` of `currency`, as the town writes it: `$40`."""
    return f"{currency}{amount}"


@dataclass
class Inventory:
    """What a resident has, checkpointed whole (see the module docstring); `moves` holds each
    movement as `[kind, amount, about]`: `service`, `received`, `gave` or `bought`."""

    money: int = 0
    items: dict[str, int] = field(default_factory=dict)
    moves: list[list[str | int]] = field(default_factory=list)

    def units(self, item: str) -> int:
        return self.items.get(item, 0)

    def add(self, item: str, units: int) -> None:
        self.items[item] = self.units(item) + units

    def remove(self, item: str, units: int) -> None:
        left = self.units(item) - units
        if left < 0:
            raise ValueError(f"only {self.units(item)} of {item} to take {units} from")
        if left:
            self.items[item] = left
        else:
            del self.items[item]


@dataclass(frozen=True)
class Settled:
    """What one resident's midnight settled: the day's `wages` and what the fund `owed_before`
    are set against the `rent`, the daily `charges` and the `arrears_before`; the `remainder`,
    if positive, is `paid` into the inventory as far as the fund has it and the rest is `owed`,
    and if negative becomes the `arrears`."""

    wages: int
    owed_before: int
    rent: int
    charges: int
    arrears_before: int
    remainder: int
    paid: int
    owed: int
    arrears: int


@dataclass
class Fund:
    """The town's fund, checkpointed whole (see the module docstring)."""

    balance: int
    ledger: dict[str, int] = field(default_factory=dict)
    yesterday: dict[str, int] = field(default_factory=dict)
    owed: dict[str, int] = field(default_factory=dict)
    arrears: dict[str, int] = field(default_factory=dict)

    def take(self, kind: str, amount: int) -> None:
        """Money of `kind` into the fund: a client's payment or a sale."""
        if kind not in TAKEN:
            raise ValueError(f"the fund takes no {kind!r}")
        self.balance += amount
        self._note(kind, amount)

    def pay(self, kind: str, amount: int) -> int:
        """Money of `kind` out of the fund, as far as the balance goes; returns what was paid."""
        if kind not in PAID:
            raise ValueError(f"the fund pays no {kind!r}")
        paid = min(amount, self.balance)
        self.balance -= paid
        self._note(kind, paid)
        return paid

    def service(self, name: str, amount: int) -> int:
        """`name`'s sum `amount` for a service, paid at once as far as the fund has it, the rest
        owed; returns what was paid."""
        paid = self.pay("service", amount)
        self._owe(name, amount - paid)
        return paid

    def settle(self, name: str, wages: int, rent: int, charges: int) -> Settled:
        """`name`'s midnight: its `wages` for the day and what the fund owed it, less its `rent`,
        its daily `charges` and its arrears (see the module docstring). What the wages cover of
        the rent and charges is noted as taken in rent and paid in wages; it moves no money."""
        owed_before, arrears_before = self.owed.pop(name, 0), self.arrears.pop(name, 0)
        earned, due = wages + owed_before, rent + charges + arrears_before
        covered = min(earned, due)
        self._note("rent", covered)
        self._note("wage", covered)
        remainder = earned - due
        paid = self.pay("wage", remainder) if remainder > 0 else 0
        self._owe(name, max(remainder, 0) - paid)
        if remainder < 0:
            self.arrears[name] = -remainder
        return Settled(
            wages=wages,
            owed_before=owed_before,
            rent=rent,
            charges=charges,
            arrears_before=arrears_before,
            remainder=remainder,
            paid=paid,
            owed=self.owed.get(name, 0),
            arrears=self.arrears.get(name, 0),
        )

    def close_day(self) -> None:
        """The last midnight's settlements are done: the ledger becomes yesterday's."""
        self.yesterday, self.ledger = self.ledger, {}

    def _note(self, kind: str, amount: int) -> None:
        if amount:
            self.ledger[kind] = self.ledger.get(kind, 0) + amount

    def _owe(self, name: str, amount: int) -> None:
        if amount:
            self.owed[name] = self.owed.get(name, 0) + amount
