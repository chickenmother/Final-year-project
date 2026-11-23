"""Human-editable gameplay configuration for the v2 game core.

The JSON file in the repository root (``game_config.json``) is the source of
truth for gameplay tuning. It is loaded by Z's local settings screen and sent
in every ``start`` message, so Cloud X and Middle Y always run the same values
even when they are on different machines.

``FYP_GAME_CONFIG`` may point at an alternative file (used by
``tools/autoplay_z.ps1`` to run an isolated immortal config without touching the
repository copy).
"""
from __future__ import annotations

import copy
import json
import math
import os
import warnings
from dataclasses import dataclass
from pathlib import Path

from .workload import WorkloadConfig


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "game_config.json"
CONFIG_ENV = "FYP_GAME_CONFIG"


def _config_path(path=None):
    """Explicit path > FYP_GAME_CONFIG override > repo game_config.json."""
    if path is not None:
        return Path(path)
    override = os.environ.get(CONFIG_ENV)
    return Path(override) if override else CONFIG_PATH

DEFAULT_CONFIG = {
    "default_workload": "medium",
    "world": {
        "width": 1280,
        "height": 720,
    },
    "player": {
        "max_hp": 100,
        "speed": 7.0,
        "size": 48,
        "obstacle_damage": 5,
        "obstacle_hit_cooldown": 0.4,
        "bot_damage": 8,
        "bot_hit_cooldown": 0.5,
        "bullet_velocity": 900.0,
        "bullet_damage": 20,
    },
    "bot": {
        "max_hp": 50,
        "speed": 2.2,
        "size": 44,
        "bullet_velocity": 700.0,
        "bullet_damage": 10,
        "fire_range": 720.0,
        "stop_range": 240.0,
        "retreat_range": 120.0,
        "fire_cooldown_min": 0.6,
        "fire_cooldown_max": 1.4,
        "initial_fire_min": 0.4,
        "initial_fire_max": 1.2,
        "spawn_clearance": 260,
    },
    "obstacle": {
        "max_hp": 100,
        "size_min": 30,
        "size_max": 80,
        "large_size_min": 18,
        "large_size_max": 70,
    },
    "effects": {
        "max_particles": 5000,
    },
    "profiles": {
        "light": {
            "bots": 0,
            "obstacles": 8,
            "bullets_per_second": 2.0,
            "particles_per_explosion": 20,
            "pathfinding_agents": 0,
            "raycast_checks": 0,
        },
        "medium": {
            "bots": 5,
            "obstacles": 40,
            "bullets_per_second": 20.0,
            "particles_per_explosion": 50,
            "pathfinding_agents": 5,
            "raycast_checks": 0,
        },
        "heavy": {
            "bots": 50,
            "obstacles": 500,
            "bullets_per_second": 200.0,
            "particles_per_explosion": 300,
            "pathfinding_agents": 50,
            "raycast_checks": 0,
        },
    },
}


class ConfigError(ValueError):
    """Raised when a configuration value cannot be used."""


@dataclass(frozen=True)
class FieldSpec:
    """One editable numeric field and the bounds used by the settings screen."""

    path: tuple
    label: str
    section: str
    minimum: float
    maximum: float
    step: float
    integer: bool = False
    unit: str = ""

_COMMON_FIELDS = (
    FieldSpec(("world", "width"), "World width", "World", 640, 1920, 16, True, "px"),
    FieldSpec(("world", "height"), "World height", "World", 480, 1080, 16, True, "px"),
    FieldSpec(("player", "max_hp"), "Player max HP", "Player", 1, 1000, 1, True),
    FieldSpec(("player", "speed"), "Player speed", "Player", 1, 30, 0.5, unit="px/tick"),
    FieldSpec(("player", "size"), "Player size", "Player", 16, 128, 2, True, "px"),
    FieldSpec(("player", "obstacle_damage"), "Obstacle hit damage", "Player", 0, 100, 1, True),
    FieldSpec(("player", "obstacle_hit_cooldown"), "Obstacle hit cooldown", "Player", 0.05, 5, 0.05, unit="s"),
    FieldSpec(("player", "bot_damage"), "Bot collision damage", "Player", 0, 100, 1, True),
    FieldSpec(("player", "bot_hit_cooldown"), "Bot hit cooldown", "Player", 0.05, 5, 0.05, unit="s"),
    FieldSpec(("player", "bullet_velocity"), "Player bullet speed", "Player", 100, 3000, 25, unit="px/s"),
    FieldSpec(("player", "bullet_damage"), "Player bullet damage", "Player", 1, 100, 1, True),
    FieldSpec(("bot", "max_hp"), "Bot max HP", "Bot", 1, 1000, 1, True),
    FieldSpec(("bot", "speed"), "Bot speed", "Bot", 0, 20, 0.1, unit="px/tick"),
    FieldSpec(("bot", "size"), "Bot size", "Bot", 16, 128, 2, True, "px"),
    FieldSpec(("bot", "bullet_velocity"), "Bot bullet speed", "Bot", 100, 3000, 25, unit="px/s"),
    FieldSpec(("bot", "bullet_damage"), "Bot bullet damage", "Bot", 0, 100, 1, True),
    FieldSpec(("bot", "fire_range"), "Bot fire range", "Bot", 100, 2000, 10, unit="px"),
    FieldSpec(("bot", "stop_range"), "Bot stop distance", "Bot", 20, 1000, 10, unit="px"),
    FieldSpec(("bot", "retreat_range"), "Bot retreat distance", "Bot", 20, 1000, 10, unit="px"),
    FieldSpec(("bot", "fire_cooldown_min"), "Bot fire cooldown min", "Bot", 0.05, 10, 0.05, unit="s"),
    FieldSpec(("bot", "fire_cooldown_max"), "Bot fire cooldown max", "Bot", 0.05, 10, 0.05, unit="s"),
    FieldSpec(("bot", "initial_fire_min"), "Bot initial fire min", "Bot", 0, 10, 0.05, unit="s"),
    FieldSpec(("bot", "initial_fire_max"), "Bot initial fire max", "Bot", 0, 10, 0.05, unit="s"),
    FieldSpec(("bot", "spawn_clearance"), "Bot spawn clearance", "Bot", 0, 1000, 10, True, "px"),
    FieldSpec(("obstacle", "max_hp"), "Obstacle max HP", "Obstacle", 1, 1000, 1, True),
    FieldSpec(("obstacle", "size_min"), "Obstacle size min", "Obstacle", 8, 200, 2, True, "px"),
    FieldSpec(("obstacle", "size_max"), "Obstacle size max", "Obstacle", 8, 300, 2, True, "px"),
    FieldSpec(("obstacle", "large_size_min"), "Large-map size min", "Obstacle", 8, 200, 2, True, "px"),
    FieldSpec(("obstacle", "large_size_max"), "Large-map size max", "Obstacle", 8, 300, 2, True, "px"),
    FieldSpec(("effects", "max_particles"), "Particle cap", "Effects", 0, 50000, 100, True),
)

_PROFILE_FIELDS = (
    ("bots", "Bots", 0, 500, 1, True, ""),
    ("obstacles", "Obstacles", 0, 2000, 1, True, ""),
    ("bullets_per_second", "Player shots/sec", 0.1, 500, 0.1, False, "/s"),
    ("particles_per_explosion", "Particles/explosion", 0, 1000, 1, True, ""),
    ("pathfinding_agents", "Pathfinding agents", 0, 500, 1, True, ""),
    ("raycast_checks", "Raycast checks", 0, 5000, 1, True, ""),
)


def profile_fields(name):
    """Return the editable fields for one workload profile."""
    return tuple(
        FieldSpec(("profiles", name, key), label, f"Profile: {name}", lo, hi, step,
                  integer, unit)
        for key, label, lo, hi, step, integer, unit in _PROFILE_FIELDS
    )


def all_fields(profile):
    """Common tuning followed by the currently selected profile."""
    return _COMMON_FIELDS + profile_fields(profile)


def field_by_path(path):
    """Find the spec for a path, including profile paths."""
    path = tuple(path)
    for spec in _COMMON_FIELDS:
        if spec.path == path:
            return spec
    if len(path) == 3 and path[0] == "profiles":
        for spec in profile_fields(path[1]):
            if spec.path == path:
                return spec
    return None


def _merge_defaults(base, raw):
    """Copy known keys from raw, filling anything missing from base."""
    out = {}
    raw = raw if isinstance(raw, dict) else {}
    for key, default in base.items():
        if isinstance(default, dict):
            out[key] = _merge_defaults(default, raw.get(key, {}))
        else:
            out[key] = raw.get(key, copy.deepcopy(default))
    return out


def _coerce(value, spec):
    try:
        if spec.integer:
            number = int(round(float(value)))
        else:
            number = float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{'.'.join(spec.path)} must be a number") from None
    if not math.isfinite(number):
        raise ConfigError(f"{'.'.join(spec.path)} must be finite")
    number = max(spec.minimum, min(spec.maximum, number))
    return int(number) if spec.integer else round(number, 4)


def _get(cfg, path):
    value = cfg
    for key in path:
        value = value[key]
    return value


def _set(cfg, path, value):
    target = cfg
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def normalize_config(raw=None):
    """Return a complete, validated config (unknown keys are ignored)."""
    cfg = _merge_defaults(DEFAULT_CONFIG, raw if isinstance(raw, dict) else {})
    profiles = cfg.get("profiles", {})
    default = str(cfg.get("default_workload", "medium")).lower()
    cfg["default_workload"] = default if default in profiles else "medium"

    for spec in _COMMON_FIELDS:
        _set(cfg, spec.path, _coerce(_get(cfg, spec.path), spec))
    for name in profiles:
        for spec in profile_fields(name):
            _set(cfg, spec.path, _coerce(_get(cfg, spec.path), spec))

    # Keep paired ranges in a sensible order.
    pairs = (
        (("obstacle", "size_min"), ("obstacle", "size_max")),
        (("obstacle", "large_size_min"), ("obstacle", "large_size_max")),
        (("bot", "fire_cooldown_min"), ("bot", "fire_cooldown_max")),
        (("bot", "initial_fire_min"), ("bot", "initial_fire_max")),
    )
    for low_path, high_path in pairs:
        low, high = _get(cfg, low_path), _get(cfg, high_path)
        if low > high:
            _set(cfg, high_path, low)
    return cfg


def load_config(path=None):
    """Load a config, creating the file with defaults if it does not exist.

    A malformed file is reported and replaced by defaults in memory; the file
    itself is left untouched so the user can fix it.
    """
    path = _config_path(path)
    try:
        if not path.exists():
            return save_config(DEFAULT_CONFIG, path)
        with open(path, "r", encoding="utf-8") as f:
            return normalize_config(json.load(f))
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        warnings.warn(f"could not load {path}: {exc}; using defaults", RuntimeWarning)
        return normalize_config(None)


def save_config(cfg, path=None):
    """Validate and write cfg atomically, returning the normalized copy."""
    path = _config_path(path)
    cfg = normalize_config(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return cfg


def get_value(cfg, path):
    return _get(cfg, tuple(path))


def set_value(cfg, path, value):
    path = tuple(path)
    spec = field_by_path(path)
    if spec is None:
        raise ConfigError(f"unknown config path {'.'.join(path)}")
    value = _coerce(value, spec)
    _set(cfg, path, value)
    return value


def adjust_value(cfg, path, delta):
    """Move a value by delta, respecting its step and bounds."""
    spec = field_by_path(tuple(path))
    if spec is None:
        return None
    current = get_value(cfg, path)
    return set_value(cfg, path, current + delta)


def format_value(value, spec=None):
    if spec is not None and spec.integer:
        return f"{int(value)}{spec.unit}"
    text = f"{float(value):g}"
    return f"{text}{spec.unit}" if spec is not None else text


def profile_from_config(cfg, name):
    """Build the WorkloadConfig for a named profile."""
    cfg = normalize_config(cfg)
    name = str(name).lower()
    if name not in cfg["profiles"]:
        raise ConfigError(f"unknown workload {name!r}; choose one of {sorted(cfg['profiles'])}")
    values = cfg["profiles"][name]
    return WorkloadConfig(
        name=name,
        bots=int(values["bots"]),
        obstacles=int(values["obstacles"]),
        bullets_per_second=float(values["bullets_per_second"]),
        particles_per_explosion=int(values["particles_per_explosion"]),
        pathfinding_agents=int(values["pathfinding_agents"]),
        raycast_checks=int(values["raycast_checks"]),
        width=int(cfg["world"]["width"]),
        height=int(cfg["world"]["height"]),
        tick_rate=60,
    )


def profiles_from_config(cfg):
    cfg = normalize_config(cfg)
    return {name: profile_from_config(cfg, name) for name in cfg["profiles"]}


@dataclass(frozen=True)
class PlayerTuning:
    max_hp: int
    speed: float
    size: int
    obstacle_damage: int
    obstacle_hit_cooldown: float
    bot_damage: int
    bot_hit_cooldown: float
    bullet_velocity: float
    bullet_damage: int


@dataclass(frozen=True)
class BotTuning:
    max_hp: int
    speed: float
    size: int
    bullet_velocity: float
    bullet_damage: int
    fire_range: float
    stop_range: float
    retreat_range: float
    fire_cooldown_min: float
    fire_cooldown_max: float
    initial_fire_min: float
    initial_fire_max: float
    spawn_clearance: int


@dataclass(frozen=True)
class ObstacleTuning:
    max_hp: int
    size_min: int
    size_max: int
    large_size_min: int
    large_size_max: int


@dataclass(frozen=True)
class GameTuning:
    player: PlayerTuning
    bot: BotTuning
    obstacle: ObstacleTuning
    max_particles: int


def tuning_from_config(cfg):
    cfg = normalize_config(cfg)
    p, b, o = cfg["player"], cfg["bot"], cfg["obstacle"]
    return GameTuning(
        player=PlayerTuning(
            max_hp=int(p["max_hp"]), speed=float(p["speed"]), size=int(p["size"]),
            obstacle_damage=int(p["obstacle_damage"]),
            obstacle_hit_cooldown=float(p["obstacle_hit_cooldown"]),
            bot_damage=int(p["bot_damage"]),
            bot_hit_cooldown=float(p["bot_hit_cooldown"]),
            bullet_velocity=float(p["bullet_velocity"]),
            bullet_damage=int(p["bullet_damage"]),
        ),
        bot=BotTuning(
            max_hp=int(b["max_hp"]), speed=float(b["speed"]), size=int(b["size"]),
            bullet_velocity=float(b["bullet_velocity"]),
            bullet_damage=int(b["bullet_damage"]),
            fire_range=float(b["fire_range"]),
            stop_range=float(b["stop_range"]),
            retreat_range=float(b["retreat_range"]),
            fire_cooldown_min=float(b["fire_cooldown_min"]),
            fire_cooldown_max=float(b["fire_cooldown_max"]),
            initial_fire_min=float(b["initial_fire_min"]),
            initial_fire_max=float(b["initial_fire_max"]),
            spawn_clearance=int(b["spawn_clearance"]),
        ),
        obstacle=ObstacleTuning(
            max_hp=int(o["max_hp"]), size_min=int(o["size_min"]),
            size_max=int(o["size_max"]), large_size_min=int(o["large_size_min"]),
            large_size_max=int(o["large_size_max"]),
        ),
        max_particles=int(cfg["effects"]["max_particles"]),
    )


__all__ = [
    "CONFIG_PATH", "DEFAULT_CONFIG", "ConfigError", "FieldSpec", "GameTuning",
    "adjust_value", "all_fields", "field_by_path", "format_value", "get_value",
    "load_config", "normalize_config", "profile_fields", "profile_from_config",
    "profiles_from_config", "save_config", "set_value", "tuning_from_config",
]

