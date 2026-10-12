"""Measures derived from a run directory, the one place where the event log becomes numbers.

`read_run` reads a run, finished or in progress; `measure` derives the per-agent, per-society
and per-pair measures of every day from its event log, and `meetings` how each meeting was
answered; `traits` derives what residents did in
the dilemmas of the town, how they chose partners and how often their words speak of the
machinery; `analysis.study` compares the arms of a study; `run_usage` and `evaluation_usage`
aggregate the model-call logs; `results` and `scores` read the held-out evaluation.
"""

from analysis.measures import (
    AgentDay,
    Edge,
    Measures,
    MeetingCount,
    SocietyDay,
    gini,
    measure,
    meetings,
)
from analysis.run import RunData, complete_lines, read_records, read_run
from analysis.scores import Score, results, scores
from analysis.traits import PairDay, TraitDay, Traits, recorded_with_parts, traits
from analysis.usage import Usage, evaluation_usage, run_usage, usage

__all__ = [
    "AgentDay",
    "Edge",
    "Measures",
    "MeetingCount",
    "PairDay",
    "RunData",
    "Score",
    "SocietyDay",
    "TraitDay",
    "Traits",
    "Usage",
    "complete_lines",
    "evaluation_usage",
    "gini",
    "measure",
    "meetings",
    "read_records",
    "read_run",
    "recorded_with_parts",
    "results",
    "run_usage",
    "scores",
    "traits",
    "usage",
]
