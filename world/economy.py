"""The town's things and money: the holders of both, each resident's inventory, the town's
treasury and the Store's orders.

Every unit of an item is held by exactly one `Holder`, which keeps the units of each item it
holds and the money that is with them: a resident, by its `Inventory`; a place, by what is left
there; at the Store and the Restaurant, what the business keeps there (`SHELVES`, the Store's
shelves; `COUNTER`, where the kitchen's dishes stand ready; `LARDER`, the kitchen's ingredients);
or the `Supplier`, outside the town, who holds whatever it sells without end. Units and money
change hands as a resident takes or gives them (`world.holders.transfer`), and by nothing else
but the world's own sources and sinks.

Money is a whole number of the town's currency (`TownConfig.money` writes it), named `MONEY`
where things are named, and no item of the catalogue: every holder holds some, never below zero,
so that it is given, taken and left like any other thing. A resident's `Inventory` keeps
`moves` besides, the movements of its money since its last midnight statement, which the
statement tells; the world keeps no other account of who gave what for what.

Money is held by the holders and by the town's `Treasury`, and nothing else. It enters the town
only when a client pays for a task accepted, into the purses of those it pays, and leaves it only
when the shopkeeper pays the supplier; every other movement is from one holder of money to
another, so that the holders and the treasury together change only by what clients pay and the
supplier is paid. The treasury takes in the tax withheld from whatever a resident is paid for its
work (a client's payment, and any money given to it while it is at work) and, at midnight, the
rent of the homes and the daily charges, from each purse only above what it `spares`
(`Treasury.settle`), the rest owed to it (`arrears`) and taken at later midnights; it pays each
salaried occupation's salary at midnight as far as it holds the money, owing the rest (`owed`),
and the mayor's grants. Its `ledger` keeps its movements since the last midnight by kind (`TAKEN`
and `PAID`), which the mayor's statement tells at midnight, and `yesterday` those of the day the
last midnight closed.

The `Store` keeps the orders on their way, its shelves being a holder (the businesses' prices are
`world.businesses`'). The holders, the treasury and the Store are checkpointed whole.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Literal

TAKEN = {"tax": "in taxes", "rent": "in rent and daily charges"}
"""The kinds of money the treasury takes in, with how the mayor's statement words each."""
PAID = {"salary": "in salary", "grant": "in grants"}
"""The kinds of money the treasury pays out, with how the mayor's statement words each."""


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


Move = Literal[
    "earned", "tax", "granted", "received", "gave", "left", "took", "lost", "went", "paid"
]
"""The kinds of movement of a resident's money: what it earned for its work and the tax withheld
from it, a grant from the treasury, money another resident gave it and money it gave another,
money it left somewhere, money it took and money taken from it, money that fell from it unnoticed
(`world.incidents`), and a payment (the supplier)."""
MOVES: dict[Move, str] = {
    "earned": "received {money} {about}",
    "tax": "{money} of it in tax",
    "granted": "received {money} from the treasury, {about}",
    "received": "received {money} from {about}",
    "gave": "gave {money} to {about}",
    "left": "left {money} {about}",
    "took": "took {money} {about}",
    "lost": "{money} was taken from you",
    "went": "{money} went from your purse",
    "paid": "paid {money} for {about}",
}
"""How the statement tells each kind of movement of an inventory's money (`Inventory.moves`); the
tax withheld from what was earned is told with it."""

SHELVES, COUNTER, LARDER, SUPPLIER = "shelves", "counter", "larder", "supplier"
"""The holders that are neither a resident nor what is left at a place, by their names: in the
log and the checkpoint, and as a resident names where it takes from or gives to; no place may
take them."""
HERE = "here"
"""How a resident names what is left at the place where it is; no place may be called so."""
MONEY = "money"
"""What money is named by wherever a thing is named; no item may be called so."""


@dataclass
class Holder:
    """Units of items and money, held by one holder (see the module docstring): `items`, the
    units of each item it holds, an item it no longer holds leaving it; and `money`."""

    items: dict[str, int] = field(default_factory=dict)
    money: int = 0

    def units(self, item: str) -> int:
        return self.items.get(item, 0)

    def has(self, what: str) -> int:
        """How much it holds of `what`: the units of an item, or its money."""
        return self.money if what == MONEY else self.units(what)

    def add(self, item: str, units: int) -> None:
        add(self.items, item, units)

    def take(self, item: str, units: int) -> None:
        take(self.items, item, units)

    def receive(self, amount: int, kind: Move, about: str) -> None:
        """`amount` of money into it; what an inventory records of it, nothing else does."""
        self.money += amount

    def spend(self, amount: int, kind: Move, about: str) -> None:
        """`amount` of money out of it, which it must hold."""
        if amount > self.money:
            raise ValueError(f"only {self.money} held to spend {amount} from")
        self.money -= amount


class Supplier(Holder):
    """The supplier outside the town: it holds as many units of what it sells as are taken from
    it, and nothing goes back to it."""

    def units(self, item: str) -> int:
        return sys.maxsize

    def add(self, item: str, units: int) -> None:
        raise ValueError("nothing goes back to the supplier")

    def take(self, item: str, units: int) -> None:
        pass


@dataclass
class Inventory(Holder):
    """What a resident has, checkpointed whole (see the module docstring); `moves` holds each
    movement of its money since the last statement as `[kind, amount, about]`, of a kind of
    `Move`. Money moves in and out of a purse only by `receive` and `spend`, which record it, but
    for the midnight's salary and rent, which the statement tells apart."""

    moves: list[list[str | int]] = field(default_factory=list)

    def receive(self, amount: int, kind: Move, about: str) -> None:
        """`amount` into the purse, recorded as a movement of `kind` concerning `about`."""
        super().receive(amount, kind, about)
        self.moves.append([kind, amount, about])

    def spend(self, amount: int, kind: Move, about: str) -> None:
        """`amount` out of the purse, which must hold it, recorded as a movement of `kind`
        concerning `about`."""
        super().spend(amount, kind, about)
        self.moves.append([kind, amount, about])


@dataclass(frozen=True)
class Settled:
    """What one resident's midnight settled: its `salary` for the day and what the treasury
    `owed_before`, of which it paid `salary_paid` into the purse and `owed` the rest; then the
    `rent`, the daily `charges` and the `arrears_before`, of which `rent_paid` came out of the
    purse, as far as it held more than it spares, and `arrears` are owed."""

    salary: int
    owed_before: int
    salary_paid: int
    owed: int
    rent: int
    charges: int
    arrears_before: int
    rent_paid: int
    arrears: int


@dataclass
class Treasury:
    """The town's treasury, checkpointed whole (see the module docstring): its `balance`, its
    movements by kind since the last midnight (`ledger`) and on the day the last midnight closed
    (`yesterday`), the salaries it owes (`owed`) and the rent owed to it (`arrears`), by
    resident."""

    balance: int
    ledger: dict[str, int] = field(default_factory=dict)
    yesterday: dict[str, int] = field(default_factory=dict)
    owed: dict[str, int] = field(default_factory=dict)
    arrears: dict[str, int] = field(default_factory=dict)

    def take(self, kind: str, amount: int) -> None:
        """Money of `kind` into the treasury: a tax withheld."""
        if kind not in TAKEN:
            raise ValueError(f"the treasury takes no {kind!r}")
        self.balance += amount
        self._note(kind, amount)

    def pay(self, kind: str, amount: int) -> None:
        """Money of `kind` out of the treasury, which must hold it: a grant."""
        if kind not in PAID:
            raise ValueError(f"the treasury pays no {kind!r}")
        if amount > self.balance:
            raise ValueError(f"the treasury holds only {self.balance} to pay {amount}")
        self.balance -= amount
        self._note(kind, amount)

    def settle(
        self, name: str, *, purse: int, spares: int, salary: int, rent: int, charges: int
    ) -> Settled:
        """`name`'s midnight, with `purse` the money it holds: its `salary` and what the treasury
        owed it are paid as far as the treasury holds the money, the rest owed; then its `rent`,
        its daily `charges` and its arrears are taken from its purse, salary paid included, as
        far as it holds more than `spares`, the rest owed. The caller moves the purse's money."""
        owed_before = self.owed.pop(name, 0)
        salary_paid = min(salary + owed_before, self.balance)
        self.balance -= salary_paid
        self._note("salary", salary_paid)
        self._owe(self.owed, name, salary + owed_before - salary_paid)
        arrears_before = self.arrears.pop(name, 0)
        due = rent + charges + arrears_before
        rent_paid = min(due, max(purse + salary_paid - spares, 0))
        self.take("rent", rent_paid)
        self._owe(self.arrears, name, due - rent_paid)
        return Settled(
            salary=salary,
            owed_before=owed_before,
            salary_paid=salary_paid,
            owed=self.owed.get(name, 0),
            rent=rent,
            charges=charges,
            arrears_before=arrears_before,
            rent_paid=rent_paid,
            arrears=self.arrears.get(name, 0),
        )

    def close_day(self) -> None:
        """The last midnight's settlements are done: the ledger becomes yesterday's."""
        self.yesterday, self.ledger = self.ledger, {}

    def _note(self, kind: str, amount: int) -> None:
        if amount:
            self.ledger[kind] = self.ledger.get(kind, 0) + amount

    @staticmethod
    def _owe(book: dict[str, int], name: str, amount: int) -> None:
        if amount:
            book[name] = amount


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
