"""Held-out probes, one per studied trait; `PROBES` holds every probe by name."""

from evaluation.probes.base import Dimension, Instruments, Outcome, Probe, Score, Session, Step
from evaluation.probes.colleague_request import ColleagueRequest
from evaluation.probes.held_out_task import HeldOutTask, special_cases
from evaluation.probes.prior_commitment import PriorCommitment
from evaluation.probes.shortfall_report import ShortfallReport

PROBES: dict[str, Probe] = {
    probe.name: probe
    for probe in (HeldOutTask(), ShortfallReport(), ColleagueRequest(), PriorCommitment())
}

__all__ = [
    "PROBES",
    "ColleagueRequest",
    "Dimension",
    "HeldOutTask",
    "Instruments",
    "Outcome",
    "PriorCommitment",
    "Probe",
    "Score",
    "Session",
    "ShortfallReport",
    "Step",
    "special_cases",
]
