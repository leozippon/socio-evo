"""Held-out evaluation: probe families played offline on frozen exports of the residents.

`evaluate` is the entry point: given a run directory, days, an `EvaluationConfig` (by default
`DEFAULT_CONFIG`), a client for the evaluated residents and one for the judge, and the run's
town, it writes one result file per resident, day and export variant; `estimate` says what it
will cost beforehand, and `read_scores` reads the results back as tidy rows.
"""

from evaluation.config import DEFAULT_CONFIG, WORK, EvaluationConfig
from evaluation.judge import Judge, Verdict
from evaluation.probes import FAMILIES, Dimension, Family, Step, Unit
from evaluation.results import (
    AgentResult,
    Outcome,
    ProbeResult,
    ScoreRow,
    label,
    read_results,
    read_scores,
)
from evaluation.runner import Estimate, estimate, evaluate
from evaluation.snapshots import Variant, frozen, version_at

__all__ = [
    "DEFAULT_CONFIG",
    "FAMILIES",
    "WORK",
    "AgentResult",
    "Dimension",
    "Estimate",
    "EvaluationConfig",
    "Family",
    "Judge",
    "Outcome",
    "ProbeResult",
    "ScoreRow",
    "Step",
    "Unit",
    "Variant",
    "Verdict",
    "estimate",
    "evaluate",
    "frozen",
    "label",
    "read_results",
    "read_scores",
    "version_at",
]
