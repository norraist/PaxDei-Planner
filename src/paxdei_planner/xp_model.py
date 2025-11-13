from __future__ import annotations

import math
from typing import Tuple

# Tier-aware constants (baseline tuned around ~100 base XP)
TIER_CONST = {
    "low": {"A0": 112.0, "B0": 12.0, "C0": 15.0, "slope_trivial": 3.0, "failure_base": 35.0},
    "mid": {"A0": 110.0, "B0": 12.0, "C0": 15.0, "slope_trivial": 3.0, "failure_base": 38.0},
    "high": {"A0": 108.0, "B0": 12.0, "C0": 15.0, "slope_trivial": 3.0, "failure_base": 40.0},
}
SPREAD = 0.08  # ±8% success min/max

# Per-skill XP scaling overrides (1.0 = baseline)
SKILL_SCALE = {
    "skill_winery_and_brewing": 0.88,  # Autumn Heat success ≈225 at level 9
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
    a = 0.606
    s0 = difficulty - 5.26
    z = a * (level - s0)
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
    base = const["failure_base"] + max(0, level - unlock)
    scaled = min(50.0, max(20.0, base)) * xp_mult * _skill_scale(skill)
    return scaled


def xp_expected(level: int, difficulty: int, unlock: int, xp_mult: float, *, skill: str | None = None) -> float:
    p = success_chance(level, difficulty)
    xs = xp_success_avg(level, difficulty, xp_mult, skill=skill)
    if level >= difficulty:
        return xs
    xf = xp_failure_avg(level, difficulty, unlock, xp_mult, skill=skill)
    return p * xs + (1 - p) * xf
