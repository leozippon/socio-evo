"""Self-evolution: levels, triggers, operators, the Evolver and the version history."""

from core.agent.evolution.config import EvolutionConfig, Mode, SelfTrigger
from core.agent.evolution.evolver import Evolver, Lapse
from core.agent.evolution.history import History, Version, commit_date
from core.agent.evolution.levels import Level, Trigger
from core.agent.evolution.operators import (
    Change,
    Context,
    MemoryOperator,
    Operator,
    PolicyOperator,
    RevisionOperator,
    SkillOperator,
)

__all__ = [
    "Change",
    "Context",
    "EvolutionConfig",
    "Evolver",
    "History",
    "Lapse",
    "Level",
    "MemoryOperator",
    "Mode",
    "Operator",
    "PolicyOperator",
    "RevisionOperator",
    "SelfTrigger",
    "SkillOperator",
    "Trigger",
    "Version",
    "commit_date",
]
