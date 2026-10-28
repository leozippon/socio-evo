"""A resident's body: the arithmetic of its three needs, in the manner of a life game's motives.

Each need is a number from 0 to 100 on the resident's `Living`, read in the bands of plain words
the configuration (`Needs`) gives it, from the top band down to the lowest, where the
consequences lie. Satiety falls by the hour, asleep or awake, and rises by the nourishment of
what is eaten. Energy falls by the hour awake, faster at work and on the road, and rises by the
hour asleep in proportion to the home's comfort, up to the resident's health (or to a configured
least, so that illness limits the day without trapping it), so that health sets the day's energy.
Health is the slow integral, reckoned once at midnight from the
day: it falls for a midnight found starving (satiety in its lowest band), for one found
exhausted (energy in its lowest band), for a home of comfort below 1 and for a night ill, and
rises when neither starving nor exhausted nor ill; treatment restores it. Illness
(`Living.ill`) comes by chance at midnight, the likelier the lower one's band of health and the
poorer one's home (`illness_chance`); while it lasts, sleep restores half as much energy, and
it passes after its nights or with treatment. Health's floor is 0, where the resident takes to
its bed (`Living.bedridden`) until treated; the other needs go on being reckoned there and never
bring it lower. The world drives the clock, the activities, the chance and the telling; this
module only moves the numbers and words them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from world.config import Band, Need, Needs
from world.telling import cap, counted, listed

NEEDS = ("satiety", "energy", "health")
"""The needs, in the order they are told."""
Activity = Literal["awake", "work", "walk", "sleep"]
"""What a resident is doing as the hours pass: awake (idle, in conversation, in bed), at work,
on the road, or asleep."""
LABELS = {"satiety": "Food", "energy": "Energy", "health": "Health"}
"""How the examination heads each need."""
CAUSES = {
    "starving": "{who} {were} starving at midnight",
    "exhausted": "{who} {were} exhausted at midnight",
    "poor_home": "{whose} home has little comfort",
    "illness": "{who} {were} ill",
    "recovery": "{who} had eaten and rested",
}
"""Why health moved at midnight, by the key of `Living.night`, as the examination tells it."""
ILL_SLEEP = 0.5
"""The share of its energy sleep restores to one who is ill."""


def clamp(value: float) -> float:
    return min(100.0, max(0.0, value))


@dataclass
class Living:
    """A resident's living, checkpointed whole: `eaten` the units of each food good it has
    eaten since the last midnight, the day's record of nourishment; the three needs; `night`,
    how health moved at the last midnight, by cause; `ill`, the midnights of illness still to
    come, 0 when well; and `bedridden`, set when health reaches its floor at midnight and
    cleared by treatment. A new resident is full in every need and well. What it has to eat is
    in its inventory (`world.economy`)."""

    eaten: dict[str, int] = field(default_factory=dict)
    satiety: float = 100.0
    energy: float = 100.0
    health: float = 100.0
    night: dict[str, float] = field(default_factory=dict)
    ill: int = 0
    bedridden: bool = False


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
        """Whether `value` is in the lowest band of the need `name`: starving, exhausted, or
        gravely ill."""
        return self.band(name, value) is self.need(name).lowest

    def hungry(self, living: Living) -> bool:
        """Whether the resident could eat: its satiety is below the top band."""
        return self.band("satiety", living.satiety) is not self.needs.satiety.bands[0]

    def elapse(self, living: Living, seconds: int, activity: Activity, comfort: float) -> None:
        """`seconds` pass in `activity`, in a home of `comfort`: satiety falls, energy falls or,
        asleep, rises (half as fast for one ill) towards the resident's health, or towards the
        configured least if that is higher."""
        hours = seconds / 3600
        living.satiety = clamp(living.satiety - self.needs.satiety.per_hour * hours)
        energy = self.needs.energy
        if activity == "sleep":
            share = ILL_SLEEP if living.ill else 1.0
            gained = living.energy + energy.sleep_per_hour * comfort * hours * share
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
        cause for the examination; a night ill counts towards the illness's end. Returns it."""
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
        if living.ill:
            night["illness"] = -health.illness.per_night
            living.ill -= 1
        elif not starving and not exhausted:
            night["recovery"] = health.recovery
        living.health = clamp(living.health + sum(night.values()))
        living.night = night
        return night

    def illness_chance(self, living: Living, comfort: float) -> float:
        """The chance that one not ill falls ill at this midnight: its band of health's, and the
        poor home's on top."""
        illness = self.needs.health.illness
        band = self.needs.health.bands.index(self.band("health", living.health))
        chance = (illness.chance, illness.run_down, illness.unwell)[min(band, 2)]
        return chance + (illness.poor_home if comfort < 1 else 0)

    def fall_ill(self, living: Living) -> None:
        living.ill = self.needs.health.illness.nights

    def treat(self, living: Living, restores: float) -> None:
        """Treatment restores `restores` of health and ends an illness."""
        living.health = clamp(living.health + restores)
        living.ill = 0

    def told(self, name: str, value: float) -> str:
        """The need `name` at `value`, as the resident reads it: `You are hungry.`"""
        return f"You are {self.band(name, value).name}."

    def condition(self, living: Living) -> str:
        """How the resident is, in the bands' words: one sentence a need, and one if it is ill."""
        told = [self.told(name, getattr(living, name)) for name in NEEDS]
        return " ".join(told + (["You are ill."] if living.ill else []))

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

    def examination(self, living: Living, patient: str | None = None) -> str:
        """What the doctor's examination finds, told to the patient or, given its name
        `patient`, to the doctor: each need's number and band, the illness and how many nights
        it has left, and why health moved at the last midnight."""
        words = (
            {"who": "you", "were": "were", "whose": "your", "are": "are"}
            if patient is None
            else {"who": patient, "were": "was", "whose": f"{patient}'s", "are": "is"}
        )
        who, are = words["who"], words["are"]
        parts = []
        for name in NEEDS:
            value = getattr(living, name)
            band = self.band(name, value).name
            parts.append(f"{LABELS[name]}: {round(value)} of 100, {who} {are} {band}.")
        if living.ill:
            nights = counted(living.ill, "more night")
            parts.append(f"{cap(who)} {are} ill; untreated, it passes after {nights}.")
        if living.night:
            change = sum(living.night.values())
            moved = (
                f"fell by {round(-change)}"
                if change < 0
                else f"rose by {round(change)}"
                if change > 0
                else "stayed as it was"
            )
            causes = listed([CAUSES[cause].format(**words) for cause in living.night], "and")
            parts.append(f"Last night {words['whose']} health {moved}: {causes}.")
        return " ".join(parts)
