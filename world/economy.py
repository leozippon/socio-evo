"""The town's money and what it owns: each resident's inventory, the town's one fund, the Store
and the Restaurant's kitchen, and the daybook of what the report tells.

Money is a whole number of the town's currency (`money` writes it). A resident's `Inventory` is
what it has: its money, never below zero, and its items, the units it keeps of each good (one of
a durable, the helpings of ready food, the units of an ingredient), with `moves`, the movements
of its money since its last midnight statement, which the statement tells. A purchase is paid in
cash from the inventory, and the world refuses one that its money does not cover; money and
items pass between residents as they hand them over, of which the world keeps no account beyond
the hand-over.

The `Fund` is the town's money: the employer, the landlord and the owner of the Store, the
Restaurant and the Hospital. Money enters the town only from clients, whose payment for a task
accepted goes to the fund, and leaves it only to the supplier, whom the fund pays at once for what
the Store orders; everything else moves between the fund and the residents, so that the fund and
the inventories together change only by what clients pay and the supplier is paid. What the chef
buys at the Store for the kitchen is taken in as a sale and paid out for the kitchen, a movement
within the fund. The fund pays what it has. A sum per service goes into the inventory at once
(`Fund.service`); the day's wages are paid at midnight with the rent and the daily charges taken
out of them (`Fund.settle`), so that money in hand is never touched by rent. What the fund cannot
pay it owes (`owed`) and pays with the next wages; the rent and charges the wages did not cover are
owed to it (`arrears`) and taken from the next wages. Its `ledger` keeps its movements since the
last midnight by kind (`TAKEN` and `PAID`), and `yesterday` those of the day the last midnight
closed.

The `Store` keeps its stock of each good, its prices and the orders on their way; the `Kitchen`
keeps the Restaurant's stock of ingredients, the menu's prices and the portions cooked and not yet
served. The `Daybook` keeps, day by day, what the Store sold, the dishes served, the patients seen,
the tasks accepted and the hours at work, for the mayor's report. All are checkpointed whole.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TAKEN = {
    "client": "from clients",
    "rent": "in rent and daily charges",
    "sale": "in sales",
    "dish": "for dishes",
    "fee": "in the Hospital's fees",
}
"""The kinds of money the fund takes in, with how the report words each."""
PAID = {
    "wage": "in wages",
    "service": "in sums for services",
    "supplier": "to the supplier",
    "kitchen": "for the kitchen",
}
"""The kinds of money the fund pays out, with how the report words each."""


def money(currency: str, amount: int) -> str:
    """`amount` of `currency`, as the town writes it: `$40`."""
    return f"{currency}{amount}"


def add(stock: dict[str, int], item: str, units: int) -> None:
    """Put `units` of `item` into `stock`."""
    stock[item] = stock.get(item, 0) + units


def take(stock: dict[str, int], item: str, units: int) -> None:
    """Take `units` of `item` out of `stock`, which must hold them; what is used up leaves it."""
    left = stock.get(item, 0) - units
    if left < 0:
        raise ValueError(f"only {stock.get(item, 0)} of {item} to take {units} from")
    if left:
        stock[item] = left
    else:
        del stock[item]


@dataclass
class Inventory:
    """What a resident has, checkpointed whole (see the module docstring); `moves` holds each
    movement as `[kind, amount, about]`: `service`, `received`, `gave`, `bought` or `paid` (a
    fee at the Hospital)."""

    money: int = 0
    items: dict[str, int] = field(default_factory=dict)
    moves: list[list[str | int]] = field(default_factory=list)

    def units(self, item: str) -> int:
        return self.items.get(item, 0)

    def add(self, item: str, units: int) -> None:
        add(self.items, item, units)

    def remove(self, item: str, units: int) -> None:
        take(self.items, item, units)


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
        """Money of `kind` into the fund: a client's payment, a sale or a dish."""
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


@dataclass
class Store:
    """The Store (see the module docstring): the units of each good in `stock`, the price of a
    unit of each in `prices`, and the orders `pending`, each `[good, units, the time it
    arrives]`."""

    stock: dict[str, int]
    prices: dict[str, int]
    pending: list[list[str | int]] = field(default_factory=list)

    def receive(self, now: int) -> dict[str, int]:
        """The orders that have arrived by `now` go into the stock; returns what came."""
        came: dict[str, int] = {}
        waiting = []
        for good, units, t in self.pending:
            assert isinstance(good, str) and isinstance(units, int) and isinstance(t, int)
            if t <= now:
                add(came, good, units)
            else:
                waiting.append([good, units, t])
        self.pending = waiting
        for good, units in came.items():
            add(self.stock, good, units)
        return came


@dataclass
class Kitchen:
    """The Restaurant's kitchen (see the module docstring): the units of each ingredient in
    `stock`, the price of each dish on the `menu`, and the `portions` of each cooked and not yet
    served, which are gone at midnight."""

    menu: dict[str, int]
    stock: dict[str, int] = field(default_factory=dict)
    portions: dict[str, int] = field(default_factory=dict)


WEEK = 7
"""The closed days the daybook keeps."""


def new_day() -> dict[str, Any]:
    """A day of the daybook with nothing in it yet."""
    return {"sales": {}, "dishes": {}, "patients": [], "accepted": [], "hours": {}}


@dataclass
class Daybook:
    """What the report tells of the town's days, checkpointed whole: for the day since the last
    midnight (`today`) and for each of the last `WEEK` days closed (`days`, the latest last), the
    units of each good sold at the Store, for a resident or for the kitchen (`sales`), the portions
    of each dish served (`dishes`), the patients the doctor saw, each `[name, service]` with the
    service `examination` or `treatment` (`patients`), the tasks accepted, each `[name, task]`
    (`accepted`), and, set as the day closes, each resident's seconds at work at its workplace
    (`hours`)."""

    today: dict[str, Any] = field(default_factory=new_day)
    days: list[dict[str, Any]] = field(default_factory=list)

    def close_day(self, hours: dict[str, int]) -> None:
        """Midnight: today, with each resident's `hours` at work, becomes the latest closed day."""
        self.today["hours"] = hours
        self.days = [*self.days, self.today][-WEEK:]
        self.today = new_day()

    @property
    def yesterday(self) -> dict[str, Any]:
        """The day the last midnight closed; empty before the first."""
        return self.days[-1] if self.days else new_day()
