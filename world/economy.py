"""Purses: payments, money handed over, purchases, and the midnight charges with a statement.

Money is a whole number of the town's currency. A purse may go below zero when rent and fees are
charged; the statement then says how deep in debt the resident is. A purchase is paid in cash:
`cannot_pay` is the refusal when the purse does not cover the price, in debt or not. The ledger
keeps each resident's purse movements since its last statement, for the next one; the world keeps
no account of what passes between residents beyond the hand-over itself.
"""

from __future__ import annotations

from collections.abc import Sequence


class Economy:
    def __init__(self, currency: str, purses: dict[str, int]) -> None:
        self.currency = currency
        self.purses = dict(purses)
        self.ledger: dict[str, list[list[str | int]]] = {name: [] for name in purses}

    def money(self, amount: int) -> str:
        return f"-{self.currency}{-amount}" if amount < 0 else f"{self.currency}{amount}"

    def purse(self, name: str) -> str:
        """The resident's purse in its own words."""
        balance = self.purses[name]
        if balance < 0:
            return f"You are {self.money(-balance)} in debt."
        return f"Your purse holds {self.money(balance)}."

    def cannot_pay(self, name: str, amount: int) -> str | None:
        """Why `name` cannot pay `amount` in cash now, or None if it can."""
        if amount > self.purses[name]:
            return f"You do not have {self.money(amount)}. {self.purse(name)}"
        return None

    def pay(self, name: str, amount: int, task: int) -> None:
        self.purses[name] += amount
        self.ledger[name].append(["payment", amount, str(task)])

    def give(self, giver: str, recipient: str, amount: int) -> None:
        self.purses[giver] -= amount
        self.purses[recipient] += amount
        self.ledger[giver].append(["gave", amount, recipient])
        self.ledger[recipient].append(["received", amount, giver])

    def buy(self, name: str, amount: int, what: str) -> None:
        """`name` pays `amount` for `what` (the good as a sentence names it)."""
        self.purses[name] -= amount
        self.ledger[name].append(["bought", amount, what])

    def settle(self, name: str, charges: Sequence[tuple[str, int]]) -> list[str]:
        """Take the midnight `charges` ((what, amount) each) from the purse and return the
        statement's items: the day's movements, then the charges; the ledger starts afresh."""
        told = {
            "payment": "paid {money} for task {about}",
            "received": "received {money} from {about}",
            "gave": "gave {money} to {about}",
            "bought": "bought {about} for {money}",
        }
        items = [
            told[str(kind)].format(money=self.money(int(amount)), about=about)
            for kind, amount, about in self.ledger[name]
        ]
        for what, amount in charges:
            self.purses[name] -= amount
            items.append(f"{what} {self.money(amount)}")
        self.ledger[name] = []
        return items
