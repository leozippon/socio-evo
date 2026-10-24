"""Purses: payment, gifts, and the living cost charged at midnight with a statement.

Money is a whole number of the town's currency. A purse may go below zero; the statement then
says how deep in debt the resident is. The ledger keeps each resident's purse movements since
its last statement, for the next one.
"""

from __future__ import annotations


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

    def pay(self, name: str, amount: int, task: int) -> None:
        self.purses[name] += amount
        self.ledger[name].append(["payment", amount, str(task)])

    def give(self, giver: str, recipient: str, amount: int) -> None:
        self.purses[giver] -= amount
        self.purses[recipient] += amount
        self.ledger[giver].append(["gave", amount, recipient])
        self.ledger[recipient].append(["received", amount, giver])

    def settle(self, name: str, living_cost: int, date: str) -> str:
        """Charge the living cost and return the statement since the last one."""
        self.purses[name] -= living_cost
        told = {
            "payment": "paid {money} for task {about}",
            "received": "received {money} from {about}",
            "gave": "gave {money} to {about}",
        }
        parts = [
            told[str(kind)].format(money=self.money(int(amount)), about=about)
            for kind, amount, about in self.ledger[name]
        ]
        parts.append(f"living cost {self.money(living_cost)}")
        self.ledger[name] = []
        return f"Your statement for {date}: {'; '.join(parts)}. {self.purse(name)}"
