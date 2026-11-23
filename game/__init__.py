"""Task-oriented game core (WS0.1; originally Milestone 1).

The legacy deterministic game remains in ``common/game.py``. This package is
the new core used by the task-placement experiments.

``Game`` is loaded lazily so importing the lightweight settings module on Z
does not pull in pygame's headless renderer or set SDL_VIDEODRIVER=dummy.
"""
from .workload import WorkloadConfig, get_profile, PROFILES

__all__ = ["Game", "WorkloadConfig", "get_profile", "PROFILES"]


def __getattr__(name):
    if name == "Game":
        from .simulation import Game
        return Game
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
