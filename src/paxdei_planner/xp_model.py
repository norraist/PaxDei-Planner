from __future__ import annotations

import math
from typing import Tuple

# Tier-aware constants (baseline tuned around ~100 base XP)
TIER_CONST = {
    "low": {
        "A0": 112.0,
        "B0": 12.0,
        "C0": 15.0,
        "slope_trivial": 3.0,
        "failure_base": 9.0,
        "failure_slope": 0.55,
    },
    "mid": {
        "A0": 129.9,
        "B0": 10.21,
        "C0": 15.0,
        "slope_trivial": 3.0,
        "failure_base": 9.6,
        "failure_slope": 0.55,
    },
    "high": {
        "A0": 108.0,
        "B0": 12.0,
        "C0": 15.0,
        "slope_trivial": 3.0,
        "failure_base": 11.5,
        "failure_slope": 0.6,
    },
}
SPREAD = 0.08  # ~8% success min/max
SUCCESS_CHANCE_FLOOR = 0.04

MASTER_GAP_TABLE: list[tuple[int, int]] = [
    (0, 1),   # trivial recipes
    (2, 3),
    (3, 4),
    (4, 5),
    (5, 6),
    (6, 7),
    (8, 8),
    (9, 9),
    (13, 10),
    (16, 11),
    (21, 12),
]

SUCCESS_SIGMOID_A = 0.57
SUCCESS_SIGMOID_OFFSET = 6.5

# Per-skill XP scaling overrides (1.0 = baseline)
SKILL_SCALE = {
    "skill_winery_and_brewing": 0.88,  # Autumn Heat success ~225 at level 9
}


def _tier_bucket(difficulty: int) -> str:
    if difficulty <= 24:
        return "low"
    if difficulty <= 40:
        return "mid"
    return "high"


def success_chance(level: int, difficulty: int) -> float:
    if level >= difficulty:
        return 1.0
    s0 = difficulty - SUCCESS_SIGMOID_OFFSET
    z = SUCCESS_SIGMOID_A * (level - s0)
    p = 1.0 / (1.0 + math.exp(-z))
    return max(0.04, min(1.0, p))


def _skill_scale(skill: str | None) -> float:
    if not skill:
        return 1.0
    return SKILL_SCALE.get(skill, 1.0)


def xp_success_avg(level: int, difficulty: int, xp_mult: float, *, skill: str | None = None) -> float:
    const = TIER_CONST[_tier_bucket(difficulty)]
    if level < difficulty:
        d = difficulty - level
        base = (const["A0"] + const["B0"] * d) * xp_mult
    else:
        start = difficulty + const["C0"]
        base = max(0.0, start - const["slope_trivial"] * (level - difficulty))
    return base * _skill_scale(skill)


def xp_success_range(level: int, difficulty: int, xp_mult: float, *, skill: str | None = None) -> Tuple[float, float, float]:
    avg = xp_success_avg(level, difficulty, xp_mult, skill=skill)
    return avg * (1.0 - SPREAD), avg, avg * (1.0 + SPREAD)


def xp_failure_avg(level: int, difficulty: int, unlock: int, xp_mult: float, *, skill: str | None = None) -> float:
    if level >= difficulty:
        return float("nan")
    const = TIER_CONST[_tier_bucket(difficulty)]
    slope = const.get("failure_slope", 1.0)
    base = const["failure_base"] + slope * max(0, level - unlock)
    base = max(0.0, base)
    scaled = base * xp_mult * _skill_scale(skill)
    return scaled


def xp_expected(level: int, difficulty: int, unlock: int, xp_mult: float, *, skill: str | None = None) -> float:
    p = success_chance(level, difficulty)
    xs = xp_success_avg(level, difficulty, xp_mult, skill=skill)
    if level >= difficulty:
        return xs
    xf = xp_failure_avg(level, difficulty, unlock, xp_mult, skill=skill)
    return p * xs + (1 - p) * xf


def practical_unlock_level(unlock_level: int | float | None, difficulty: int | float | None) -> int:
    """
    Return the first level where the recipe is realistically craftable.
    We treat unlock levels whose success chance equals the floor (~4%) as "impossible"
    and bump by 1 until the chance rises.
    """
    if unlock_level is None:
        return 0
    level = int(unlock_level)
    if difficulty is None:
        return level
    difficulty_int = int(difficulty)
    for _ in range(6):
        chance = success_chance(level, difficulty_int)
        if level >= difficulty_int or chance > SUCCESS_CHANCE_FLOOR + 1e-6:
            return level
        level += 1
    return level


def mastery_level(difficulty: int | float | None, skill_cap: int = 40) -> int:
    """
    Approximate the level where XP drops to zero (mastery) purely from difficulty.
    """
    if difficulty is None:
        return skill_cap
    diff = max(0, int(difficulty))
    gap = 1
    for threshold, value in MASTER_GAP_TABLE:
        if diff >= threshold:
            gap = value
        else:
            break
    return min(skill_cap, diff + gap)
