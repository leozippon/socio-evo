"""Ratings at night: who may rate whom, and the anonymous delivery the night after.

A resident may rate, once a night, each resident it spoke with that day: one spoke to the other
by name, or in a conversation both were part of (`meet`, as the speech is said). The ratings
given in the night of a day become readable at the day's checkpoint, and the rated resident
reads them, without names and in an order that says nothing of who gave them, when it next goes
to bed.
"""

from __future__ import annotations

from collections.abc import Iterable


class Ratings:
    def __init__(self, names: Iterable[str]) -> None:
        names = list(names)
        self.met: dict[str, set[str]] = {name: set() for name in names}
        self.tonight: dict[str, dict[str, list[int | str]]] = {name: {} for name in names}
        self.unread: dict[str, list[list[int | str]]] = {name: [] for name in names}

    def meet(self, a: str, b: str) -> None:
        self.met[a].add(b)
        self.met[b].add(a)

    def refusal(self, rater: str, rated: str) -> str | None:
        if rated not in self.met[rater]:
            return f"You did not speak with {rated} today."
        if rated in self.tonight[rater]:
            return f"You have already rated {rated} tonight."
        return None

    def rate(self, rater: str, rated: str, score: int, reason: str) -> None:
        self.tonight[rater][rated] = [score, reason]

    def take_unread(self, name: str) -> list[list[int | str]]:
        taken = sorted(self.unread[name], key=lambda rating: (rating[0], str(rating[1])))
        self.unread[name] = []
        return taken

    def end_day(self) -> None:
        """Make tonight's ratings readable and start a new day of meetings."""
        for given in self.tonight.values():
            for rated, rating in given.items():
                self.unread[rated].append(rating)
            given.clear()
        for met in self.met.values():
            met.clear()


def tell_ratings(ratings: list[list[int | str]]) -> str:
    """The ratings a resident reads in bed, in its own words."""
    if not ratings:
        return "Nobody rated you last night."
    told = "; ".join(f"{score} of 5, saying “{reason}”" for score, reason in ratings)
    return f"Last night others rated you, without their names: {told}."
