"""The economy: integer credit balances. Debt is allowed; there is no death in stage 1."""


class Economy:
    """Each agent's credit balance."""

    def __init__(self, balances: dict[str, int]) -> None:
        self.balances = balances

    def add(self, agent: str, amount: int) -> int:
        """Add `amount` (negative to charge) to `agent`'s balance and return the new balance."""
        self.balances[agent] += amount
        return self.balances[agent]
