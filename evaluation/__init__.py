"""Held-out evaluation: character and safety probes run offline on frozen agent snapshots.

`evaluate` is the entry point: given a run directory, days, an `EvaluationConfig` (by default
`DEFAULT_CONFIG`), a client for the evaluated agents and one for the judge, it writes one
result file per agent and day; `read_scores` reads them back as tidy rows.
"""

from evaluation.config import BANK, DEFAULT_CONFIG, EvaluationConfig
from evaluation.judge import Judge, Verdict
from evaluation.probes import PROBES, Dimension, Outcome, Probe, Step
from evaluation.results import AgentResult, ProbeResult, ScoreRow, label, read_scores
from evaluation.runner import evaluate
from evaluation.snapshots import frozen, version_at

__all__ = [
    "BANK",
    "DEFAULT_CONFIG",
    "PROBES",
    "AgentResult",
    "Dimension",
    "EvaluationConfig",
    "Judge",
    "Outcome",
    "Probe",
    "ProbeResult",
    "ScoreRow",
    "Step",
    "Verdict",
    "evaluate",
    "frozen",
    "label",
    "read_scores",
    "version_at",
]
