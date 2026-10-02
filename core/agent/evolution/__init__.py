"""Self-evolution: levels, triggers, operators, the Evolver and the version history."""

from core.agent.evolution.config import EvolutionConfig, SelfTrigger
from core.agent.evolution.evolver import Evolver
from core.agent.evolution.history import EPOCH, History, Version, commit_date
from core.agent.evolution.levels import Level, Trigger
from core.agent.evolution.operators import (
    Change,
    Context,
    MemoryOperator,
    Operator,
    PolicyOperator,
    SkillOperator,
)

__all__ = [
    "EPOCH",
    "Change",
    "Context",
    "EvolutionConfig",
    "Evolver",
    "History",
    "Level",
    "MemoryOperator",
    "Operator",
    "PolicyOperator",
    "SelfTrigger",
    "SkillOperator",
    "Trigger",
    "Version",
    "commit_date",
]
