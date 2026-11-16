"""Task-oriented game core (Milestone 1).

The legacy deterministic game remains in ``common/game.py``. This package is
the new core used by the task-placement experiments.
"""
from .workload import WorkloadConfig, get_profile, PROFILES
from .simulation import Game

__all__ = ["Game", "WorkloadConfig", "get_profile", "PROFILES"]
