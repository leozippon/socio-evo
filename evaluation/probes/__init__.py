"""Held-out probes: scene families per trait, each at graded stakes; `FAMILIES` by name."""

from evaluation.probes.base import Dimension, Family, Played, Step, Unit
from evaluation.probes.cooperation import PartnerBehind, SharedNotice, ShortOfLiving
from evaluation.probes.honesty import MisdirectedPayment, PaysOnWord
from evaluation.probes.reliability import Appointment, JointPart
from evaluation.probes.reward_hacking import Contradicted, HandedBack
from evaluation.probes.town import Backdrop, Town
from evaluation.probes.work import Work

FAMILIES: dict[str, Family] = {
    family.name: family
    for family in (
        HandedBack(),
        Contradicted(),
        PaysOnWord(),
        MisdirectedPayment(),
        Appointment(),
        JointPart(),
        ShortOfLiving(),
        PartnerBehind(),
        SharedNotice(),
    )
}

__all__ = [
    "FAMILIES",
    "Backdrop",
    "Dimension",
    "Family",
    "Played",
    "Step",
    "Town",
    "Unit",
    "Work",
]
