"""Reputation: peer ratings and the esteem derived from them.

The directed ledger of ratings (rater, target, score, reason, time) is the sequence of
truth-only `rating` events in the event log. What is kept here is only what esteem needs:
for each agent, the decayed sums of the scores it received.
"""

from collections.abc import Sequence

from core.environment.rejection import Rejected
from core.interaction import PeerRating
from infrastructure.config import StrictModel


class DecayedMean(StrictModel):
    """Sums of scores and of their weights, both decayed to `time`."""

    total: float
    weight: float
    time: int

    def add(self, score: int, time: int, half_life: float) -> "DecayedMean":
        decay = 0.5 ** ((time - self.time) / half_life)
        return DecayedMean(
            total=self.total * decay + score, weight=self.weight * decay + 1, time=time
        )


class Reputation:
    """Each agent's esteem: the mean of the scores it received, each weighted by
    `0.5 ** (age / half_life)` so that a rating counts half as much `half_life` minutes later.
    An agent nobody has rated has no esteem.
    """

    def __init__(self, half_life: float, means: dict[str, DecayedMean | None]) -> None:
        self.half_life = half_life
        self.means = means

    def rate(
        self, rater: str, ratings: Sequence[PeerRating], time: int
    ) -> tuple[list[PeerRating], list[PeerRating]]:
        """Record `rater`'s ratings at `time`, each agent's first: a later rating of an agent
        rated earlier in `ratings` is a repeat, not recorded. Returns the ratings recorded and
        the repeats.

        Raises Rejected, recording none, if any rating targets the rater or an unknown agent.
        """
        recorded: list[PeerRating] = []
        repeated: list[PeerRating] = []
        for rating in ratings:
            if rating.target == rater:
                raise Rejected("You cannot mark yourself in the clerk's ledger.")
            if rating.target not in self.means:
                raise Rejected(f"There is nobody called {rating.target!r} in town.")
            rated = any(earlier.target == rating.target for earlier in recorded)
            (repeated if rated else recorded).append(rating)
        for rating in recorded:
            mean = self.means[rating.target] or DecayedMean(total=0, weight=0, time=time)
            self.means[rating.target] = mean.add(rating.score, time, self.half_life)
        return recorded, repeated

    def esteem(self, agent: str) -> float | None:
        mean = self.means[agent]
        return None if mean is None else mean.total / mean.weight
