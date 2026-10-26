"""A resident's body: the arithmetic of its three needs, in the manner of a life game's motives.

Each need is a number from 0 to 100 on the resident's `Living`, read in the bands of plain words
the configuration (`Needs`) gives it, from the top band down to the lowest, where the
consequences lie. Satiety falls by the hour, asleep or awake, and rises by the nourishment of
what is eaten. Energy falls by the hour awake, faster at work and on the road, and rises by the
hour asleep in proportion to the home's comfort, up to the resident's health (or to a configured
least, so that illness limits the day without trapping it), so that health sets the day's energy.
Health is the slow integral, reckoned once at midnight from the
day: it falls for a midnight found starving (satiety in its lowest band), for one found
exhausted (energy in its lowest band) and for a home of comfort below 1, and rises when neither
starving nor exhausted; treatment restores it; at 0 the resident dies. The world drives the
clock, the activities and the telling; this module only moves the numbers and words them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from world.config import Band, Need, Needs
from world.telling import listed

NEEDS = ("satiety", "energy", "health")
"""The needs, in the order they are told."""
Activity = Literal["awake", "work", "walk", "sleep"]
"""What a resident is doing as the hours pass: awake (idle, in conversation, in bed), at work,
on the road, or asleep."""
LABELS = {"satiety": "Food", "energy": "Energy", "health": "Health"}
"""How the examination heads each need."""
CAUSES = {
    "starving": "you were starving at midnight",
    "exhausted": "you were exhausted at midnight",
    "poor_home": "your home has little comfort",
    "recovery": "you had eaten and rested",
}
"""Why health moved at midnight, by the key of `Living.night`, as the examination tells it."""


def clamp(value: float) -> float:
    return min(100.0, max(0.0, value))


@dataclass
class Living:
    """A resident's living, checkpointed whole: `things` is what it owns, by the good's id (1
    for a durable, the units left of a consumable); `eaten` the units of each food good it has
    eaten since the last midnight, the day's record of nourishment; the three needs; and
    `night`, how health moved at the last midnight, by cause. A new resident is full in every
    need; one whose health has reached 0 is dead."""

    things: dict[str, int] = field(default_factory=dict)
    eaten: dict[str, int] = field(default_factory=dict)
    satiety: float = 100.0
    energy: float = 100.0
    health: float = 100.0
    night: dict[str, float] = field(default_factory=dict)

    @property
    def alive(self) -> bool:
        return self.health > 0


class Body:
    def __init__(self, needs: Needs) -> None:
        self.needs = needs

    def need(self, name: str) -> Need:
        return getattr(self.needs, name)

    def band(self, name: str, value: float) -> Band:
        """The band of the need `name` that `value` falls in."""
        return next(band for band in self.need(name).bands if value >= band.floor)

    def bands(self, living: Living) -> dict[str, Band]:
        return {name: self.band(name, getattr(living, name)) for name in NEEDS}

    def lowest(self, name: str, value: float) -> bool:
        """Whether `value` is in the lowest band of the need `name`: starving, exhausted, or at
        health's end."""
        return self.band(name, value) is self.need(name).lowest

    def hungry(self, living: Living) -> bool:
        """Whether the resident could eat: its satiety is below the top band."""
        return self.band("satiety", living.satiety) is not self.needs.satiety.bands[0]

    def elapse(self, living: Living, seconds: int, activity: Activity, comfort: float) -> None:
        """`seconds` pass in `activity`, in a home of `comfort`: satiety falls, energy falls or,
        asleep, rises towards the resident's health, or towards the configured least if that is
        higher."""
        hours = seconds / 3600
        living.satiety = clamp(living.satiety - self.needs.satiety.per_hour * hours)
        energy = self.needs.energy
        if activity == "sleep":
            gained = living.energy + energy.sleep_per_hour * comfort * hours
            rested = max(living.health, energy.rested_at_least)
            living.energy = clamp(max(living.energy, min(gained, rested)))
            return
        rate = energy.awake_per_hour
        if activity == "work":
            rate += energy.work_per_hour
        elif activity == "walk":
            rate += energy.walk_per_minute * 60
        living.energy = clamp(living.energy - rate * hours)

    def eat(self, living: Living, nourishment: float) -> None:
        living.satiety = clamp(living.satiety + nourishment)

    def night(self, living: Living, comfort: float) -> dict[str, float]:
        """Midnight: health moves by the day's wear and recovery, kept in `Living.night` by
        cause for the examination; returns it."""
        health = self.needs.health
        night: dict[str, float] = {}
        starving = self.lowest("satiety", living.satiety)
        exhausted = self.lowest("energy", living.energy)
        if starving:
            night["starving"] = -health.starving
        if exhausted:
            night["exhausted"] = -health.exhausted
        if comfort < 1:
            night["poor_home"] = -health.poor_home
        if not starving and not exhausted:
            night["recovery"] = health.recovery
        living.health = clamp(living.health + sum(night.values()))
        living.night = night
        return night

    def treat(self, living: Living, restores: float) -> None:
        living.health = clamp(living.health + restores)

    def told(self, name: str, value: float) -> str:
        """The need `name` at `value`, as the resident reads it: `You are hungry.`"""
        return f"You are {self.band(name, value).name}."

    def condition(self, living: Living) -> str:
        """How the resident is, in the bands' words: one sentence a need."""
        return " ".join(self.told(name, getattr(living, name)) for name in NEEDS)

    def warnings(self, living: Living) -> list[str]:
        """The sentences of the needs in their lowest band, where the consequences lie."""
        return [
            self.told(name, value)
            for name in NEEDS
            if self.lowest(name, value := getattr(living, name))
        ]

    def seen(self, living: Living) -> str | None:
        """How the resident's health shows to others, if its band shows."""
        return self.band("health", living.health).seen

    def examination(self, living: Living) -> str:
        """What the clinic's examination tells: each need's number and band, and why health
        moved at the last midnight."""
        parts = ["The doctor looks you over."]
        for name in NEEDS:
            value = getattr(living, name)
            parts.append(
                f"{LABELS[name]}: {round(value)} of 100, you are {self.band(name, value).name}."
            )
        if living.night:
            change = sum(living.night.values())
            moved = (
                f"fell by {round(-change)}"
                if change < 0
                else f"rose by {round(change)}"
                if change > 0
                else "stayed as it was"
            )
            causes = listed([CAUSES[cause] for cause in living.night], "and")
            parts.append(f"Last night your health {moved}: {causes}.")
        return " ".join(parts)
