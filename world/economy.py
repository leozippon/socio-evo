"""The town's things and money: the holders of items, each resident's inventory, the town's one
fund, the Store's orders, and the daybook of what the report tells.

Every unit of an item is held by exactly one `Holder`, which keeps the units of each item it
holds: a resident, by its `Inventory`; a place, by what is left there for anyone to take and, at the
Store and the Restaurant, by what the business keeps there (`SHELVES`, the Store's shelves;
`LARDER`, the kitchen's ingredients; `PORTIONS`, the dishes cooked and not yet served); or the
`Supplier`, outside the town, who holds whatever it sells without end. Units change hands only by
the world's move (`World.move`), which refuses what the source does not hold.

Money is a whole number of the town's currency (`TownConfig.money` writes it), and no item: a
resident's `Inventory` is its money, never below zero, besides its items (one of a durable, the
helpings of ready food, the units of an ingredient), with `moves`, the movements of its money since
its last midnight statement, which the statement tells. A purchase is paid in cash from the
inventory, and the world refuses one that its money does not cover; money and items pass between
residents as they hand them over, of which the world keeps no account beyond the hand-over.

The `Fund` is the town's money: the employer, the landlord and the owner of the Store, the
Restaurant and the Hospital. Money enters the town only from clients, whose payment for a task
accepted goes to the fund, and leaves it only to the supplier, whom the fund pays at once for what
the Store orders; everything else moves between the fund and the residents, so that the fund, its
tax account and the inventories together change only by what clients pay and the supplier is
paid. What the chef
buys at the Store for the kitchen is taken in as a sale and paid out for the kitchen, a movement
within the fund. The fund pays what it has. A sum per service goes into the inventory at once
(`Fund.service`); the day's wages are paid at midnight with the tax, the rent and the daily
charges taken out of them (`Fund.settle`), so that money in hand is never touched by rent, and
only by the tax the wages do not cover. What
the fund cannot pay it owes (`owed`) and pays with the next wages; the rent and charges the wages
did not cover are owed to it (`arrears`) and taken from the next wages. Its `ledger` keeps its
movements since the last midnight by kind (`TAKEN` and `PAID`, and the tax account's `TAX` and
`TAX_WAGE`), and `yesterday` those of the day the last midnight closed.

The fund's tax account (`Fund.taxes`) is money apart from the fund's own `balance`: every
resident's tax goes into it, and it pays the wages of the occupations paid from taxes (the
mayor's), as far as it has them; what it lacks it owes them, and the fund's own money never makes
it up.

The `Store` keeps the orders on their way, its shelves being a holder (the businesses' prices are
`world.businesses`'). The `Daybook` keeps, day by day, the fund's balance and its net, what the
Store sold, the dishes served, the patients seen, the tasks accepted and the hours at work, for
the mayor's report. All are checkpointed whole.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Literal

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
TAX, TAX_WAGE = "tax", "tax_wage"
"""The tax account's kinds in the ledger: the taxes it takes in and the wages it pays out."""


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


SHELVES, LARDER, PORTIONS, SUPPLIER = "shelves", "larder", "portions", "supplier"
"""The holders that are neither a resident nor what is left at a place, by their names in the
log and the checkpoint, which no place may take."""


@dataclass
class Holder:
    """Units of items, held by one holder (see the module docstring): `items`, the units of each
    item it holds; an item it no longer holds leaves it."""

    items: dict[str, int] = field(default_factory=dict)

    def units(self, item: str) -> int:
        return self.items.get(item, 0)

    def add(self, item: str, units: int) -> None:
        add(self.items, item, units)

    def take(self, item: str, units: int) -> None:
        take(self.items, item, units)


class Supplier(Holder):
    """The supplier outside the town: it holds as many units of what it sells as are taken from
    it, and nothing goes back to it."""

    def units(self, item: str) -> int:
        return sys.maxsize

    def add(self, item: str, units: int) -> None:
        raise ValueError("nothing goes back to the supplier")

    def take(self, item: str, units: int) -> None:
        pass


Move = Literal["service", "received", "gave", "bought", "paid"]
"""The kinds of movement of a resident's money: a sum for a service, money received from and
given to another resident, a purchase, and a fee paid at the Hospital."""
MOVES: dict[Move, str] = {
    "service": "received {money} for {about}",
    "received": "received {money} from {about}",
    "gave": "gave {money} to {about}",
    "bought": "bought {about} for {money}",
    "paid": "paid {money} for {about}",
}
"""How the statement tells each kind of movement of an inventory's money (`Inventory.moves`)."""


@dataclass
class Inventory(Holder):
    """What a resident has, checkpointed whole (see the module docstring); `moves` holds each
    movement of its money since the last statement as `[kind, amount, about]`, of a kind of
    `Move`. Money moves in and out of a purse only by `receive` and `spend`, which record it, but
    for the midnight's wages and tax, which the statement tells apart."""

    money: int = 0
    moves: list[list[str | int]] = field(default_factory=list)

    def receive(self, amount: int, kind: Move, about: str) -> None:
        """`amount` into the purse, recorded as a movement of `kind` concerning `about`."""
        self.money += amount
        self.moves.append([kind, amount, about])

    def spend(self, amount: int, kind: Move, about: str) -> None:
        """`amount` out of the purse, which must hold it, recorded as a movement of `kind`
        concerning `about`."""
        if amount > self.money:
            raise ValueError(f"only {self.money} in the purse to spend {amount} from")
        self.money -= amount
        self.moves.append([kind, amount, about])


@dataclass(frozen=True)
class Settled:
    """What one resident's midnight settled: the day's `wages` and what its payer `owed_before`,
    less the day's `tax` but for what was paid of it from the purse (`tax_from_purse`), are set
    against the `rent`, the daily `charges` and the `arrears_before`; the `remainder`, if
    positive, is `paid` into the inventory as far as the payer has it and the rest is `owed`,
    and if negative becomes the `arrears`. A tax account short even of what the rent and charges
    take leaves both `owed` and `arrears`."""

    wages: int
    tax: int
    tax_from_purse: int
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
    """The town's fund and its tax account, checkpointed whole (see the module docstring)."""

    balance: int
    ledger: dict[str, int] = field(default_factory=dict)
    yesterday: dict[str, int] = field(default_factory=dict)
    owed: dict[str, int] = field(default_factory=dict)
    arrears: dict[str, int] = field(default_factory=dict)
    taxes: int = 0

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

    def settle(
        self,
        name: str,
        *,
        wages: int,
        tax: int,
        purse: int,
        rent: int,
        charges: int,
        from_taxes: bool,
    ) -> Settled:
        """`name`'s midnight: its `wages` for the day and what its payer owed it, less its `tax`,
        its `rent`, its daily `charges` and its arrears (see the module docstring). The tax comes
        out of the wages first, as far as they go: the fund pays it into the tax account as far
        as it has the money; the tax account, paying `name` itself (`from_taxes`), keeps it.
        What the wages leave of the tax is paid into the account from the `purse`, and what the
        purse lacks joins the arrears, as unpaid rent does. What the wages cover of the rent and
        charges is noted as taken in rent and paid in wages; from the fund it moves no money,
        while the tax account pays it into the fund, and pays the rest of the wages into the
        inventory, only as far as it has the money."""
        owed_before, arrears_before = self.owed.pop(name, 0), self.arrears.pop(name, 0)
        earned = wages + owed_before
        if from_taxes:
            taxed = min(tax, earned)
            self._note(TAX_WAGE, taxed)
        else:
            taxed = min(tax, earned, self.balance)
            self.balance -= taxed
            self._note("wage", taxed)
        from_purse = min(tax - taxed, purse)
        self.taxes += taxed * (not from_taxes) + from_purse
        self._note(TAX, taxed + from_purse)
        due = tax - taxed - from_purse + rent + charges + arrears_before
        if from_taxes:
            got = min(earned - taxed, self.taxes)
        else:
            got = min(earned - taxed, due + self.balance)  # the rent is the fund's own
        covered, paid = min(got, due), max(got - due, 0)
        self._note("rent", covered)
        if from_taxes:
            self.taxes -= covered + paid
            self.balance += covered
            self._note(TAX_WAGE, covered + paid)
        else:
            self.balance -= paid
            self._note("wage", covered + paid)
        self._owe(name, earned - taxed - got)
        if due > covered:
            self.arrears[name] = due - covered
        return Settled(
            wages=wages,
            tax=tax,
            tax_from_purse=from_purse,
            owed_before=owed_before,
            rent=rent,
            charges=charges,
            arrears_before=arrears_before,
            remainder=earned - taxed - due,
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
    """The Store's orders from the supplier (see the module docstring): `pending`, each `[item,
    units, the time it arrives]`."""

    pending: list[list[str | int]] = field(default_factory=list)

    def order(self, item: str, units: int, arrives: int) -> None:
        """`units` of `item` ordered, to arrive at `arrives`."""
        self.pending.append([item, units, arrives])

    def due(self, now: int) -> dict[str, int]:
        """The orders that have arrived by `now`, no longer pending: the units of each item."""
        came: dict[str, int] = {}
        waiting = []
        for item, units, t in self.pending:
            assert isinstance(item, str) and isinstance(units, int) and isinstance(t, int)
            if t <= now:
                add(came, item, units)
            else:
                waiting.append([item, units, t])
        self.pending = waiting
        return came


WEEK = 7
"""The closed days the daybook keeps."""


def new_day() -> dict[str, Any]:
    """A day of the daybook with nothing in it yet."""
    return {"sales": {}, "dishes": {}, "patients": [], "accepted": [], "hours": {}}


@dataclass
class Daybook:
    """What the report tells of the town's days, checkpointed whole: for the day since the last
    midnight (`today`) and for each of the last `WEEK` days closed (`days`, the latest last), the
    units of each item sold at the Store, for a resident or for the kitchen (`sales`), the
    portions of each dish served (`dishes`), the patients the doctor saw, each `[name, service]`
    with the service `examination` or `treatment` (`patients`), the tasks accepted, each `[name,
    task]` (`accepted`), and, set as the day closes, its calendar day (`day`), each resident's
    seconds at work (`hours`), the fund's balance (`fund`) and what it took in less what it paid
    out that day (`net`)."""

    today: dict[str, Any] = field(default_factory=new_day)
    days: list[dict[str, Any]] = field(default_factory=list)

    def close_day(self, day: int, hours: dict[str, int], fund: Fund) -> None:
        """Midnight that ends calendar day `day`, before the fund's day closes: today, with each
        resident's `hours` at work and the `fund`'s balance and net, becomes the latest closed
        day."""
        taken = sum(fund.ledger.get(kind, 0) for kind in TAKEN)
        paid = sum(fund.ledger.get(kind, 0) for kind in PAID)
        self.today |= {"day": day, "hours": hours, "fund": fund.balance, "net": taken - paid}
        self.days = [*self.days, self.today][-WEEK:]
        self.today = new_day()

    @property
    def yesterday(self) -> dict[str, Any]:
        """The day the last midnight closed; empty before the first."""
        return self.days[-1] if self.days else new_day()
