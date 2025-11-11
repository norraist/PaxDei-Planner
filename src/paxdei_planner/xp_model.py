from __future__ import annotations
import math
from typing import Tuple

# Tier-aware constants (fitted during our session)
TIER_CONST = {
    'low':  {'A0':80.0, 'B0':8.0, 'C0':12.0, 'slope_trivial':4.0, 'failure_base':13.0},
    'mid':  {'A0':78.0, 'B0':8.0, 'C0':12.0, 'slope_trivial':4.0, 'failure_base':16.0},
    'high': {'A0':76.0, 'B0':8.0, 'C0':12.0, 'slope_trivial':4.0, 'failure_base':18.0},
}
SPREAD = 0.08  # ±8% success min/max

def _tier_bucket(difficulty: int) -> str:
    if difficulty <= 24: return 'low'
    if difficulty <= 40: return 'mid'
    return 'high'

def success_chance(level: int, difficulty: int) -> float:
    if level >= difficulty:
        return 1.0
    a = 0.606
    s0 = difficulty - 5.26
    z = a * (level - s0)
    p = 1.0 / (1.0 + math.exp(-z))
    return max(0.04, min(1.0, p))

def xp_success_avg(level: int, difficulty: int, xp_mult: float) -> float:
    const = TIER_CONST[_tier_bucket(difficulty)]
    if level < difficulty:
        d = difficulty - level
        return (const['A0'] + const['B0'] * d) * xp_mult
    # trivial schedule
    start = difficulty + const['C0']
    return max(0.0, start - const['slope_trivial'] * (level - difficulty))

def xp_success_range(level: int, difficulty: int, xp_mult: float) -> Tuple[float,float,float]:
    avg = xp_success_avg(level, difficulty, xp_mult)
    return avg*(1.0-SPREAD), avg, avg*(1.0+SPREAD)

def xp_failure_avg(level: int, difficulty: int, unlock: int, xp_mult: float) -> float:
    if level >= difficulty:
        return float('nan')
    const = TIER_CONST[_tier_bucket(difficulty)]
    base = const['failure_base'] + max(0, level - unlock)
    return min(50.0, max(20.0, base))

def xp_expected(level: int, difficulty: int, unlock: int, xp_mult: float) -> float:
    p = success_chance(level, difficulty)
    xs = xp_success_avg(level, difficulty, xp_mult)
    if level >= difficulty:
        return xs
    xf = xp_failure_avg(level, difficulty, unlock, xp_mult)
    return p * xs + (1 - p) * xf
