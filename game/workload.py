"""Workload profiles for the task-based game core."""
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkloadConfig:
    """Knobs that scale simulation and rendering cost.

    ``light`` keeps the game close to the original prototype; ``heavy`` is for
    task-placement experiments where compute must be visible.
    """
    name: str = "light"
    bots: int = 0
    obstacles: int = 8
    bullets_per_second: float = 2.0
    particles_per_explosion: int = 20
    pathfinding_agents: int = 0
    raycast_checks: int = 0
    width: int = 1600
    height: int = 900
    tick_rate: int = 60


PROFILES = {
    "light": WorkloadConfig(
        name="light", bots=0, obstacles=8, bullets_per_second=2.0,
        particles_per_explosion=20, pathfinding_agents=0,
    ),
    "medium": WorkloadConfig(
        name="medium", bots=5, obstacles=40, bullets_per_second=20.0,
        particles_per_explosion=50, pathfinding_agents=5,
    ),
    "heavy": WorkloadConfig(
        name="heavy", bots=50, obstacles=500, bullets_per_second=200.0,
        particles_per_explosion=300, pathfinding_agents=50,
    ),
}


def get_profile(name):
    """Return a workload profile by name, or raise a clear ValueError."""
    try:
        return PROFILES[str(name).lower()]
    except KeyError:
        raise ValueError(
            f"unknown workload profile {name!r}; choose one of {sorted(PROFILES)}"
        ) from None
