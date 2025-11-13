from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

try:
    from .schemas import GameData, Profile, Weights, Recipe
    from .xp_model import success_chance, xp_expected
    from .costs import craft_cost
    from .skills import xp_to_next_level, get_skill_table
except ImportError:
    # Allow running this module directly without installing the package.
    import os
    import sys

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from paxdei_planner.schemas import GameData, Profile, Weights, Recipe  # type: ignore
    from paxdei_planner.xp_model import success_chance, xp_expected  # type: ignore
    from paxdei_planner.costs import craft_cost  # type: ignore
    from paxdei_planner.skills import xp_to_next_level, get_skill_table  # type: ignore

@dataclass
class PlanStep:
    action: str   # 'craft' or 'build_station'
    key: str      # recipe key or station name
    count: int    # number of crafts (or 1 for build)
    exp_gain: float
    cost: float
    notes: str

@dataclass
class PlanResult:
    skill: str
    steps: List[PlanStep]
    totals: Dict[str, float]  # 'exp', 'cost', 'crafts'

def _feasible_recipes(g: GameData, skill: str, level: int, owned_stations: set[str]) -> List[Recipe]:
    out = []
    materials_cfg = getattr(g, "materials_config", {})
    for r in g.recipes:
        if r.is_dev:
            continue
        if not getattr(r, "grants_xp", True):
            continue
        if materials_cfg:
            disabled = False
            for item in (r.ingredients or {}):
                entry = materials_cfg.get(item)
                if entry is not None and not entry.get("enabled", True):
                    disabled = True
                    break
            if disabled:
                continue
        if r.skill != skill:
            continue
        if level < r.unlock_at:
            continue
        # If recipe requires a station and we don't own it, skip
        if r.station and r.station not in owned_stations:
            continue
        out.append(r)
    return out

def _best_recipe_now(g: GameData, rlist: List[Recipe], level: int, weights: Dict[str, float]) -> Tuple[Optional[Recipe], float, float, float]:
    best = None
    best_ratio = -1.0
    best_exp = 0.0
    best_cost = 0.0
    for r in rlist:
        exp = xp_expected(level, r.difficulty, r.unlock_at, r.xp_multiplier, skill=r.skill)
        if exp <= 0:
            continue
        cost = craft_cost(r, weights)
        ratio = exp / cost if cost > 0 else 0.0
        if ratio > best_ratio:
            best_ratio = ratio
            best = r
            best_exp = exp
            best_cost = cost
    return best, best_exp, best_cost, best_ratio

def plan_skill(g: GameData, skill: str, prof: Profile, weights: Weights, lookahead: int = 1) -> PlanResult:
    # Pull current & target from the new nested profile
    if skill not in prof.skills:
        raise ValueError(f"No profile entry for skill '{skill}'.")
    state = prof.skills[skill]
    curr_level = int(state.current_level)
    curr_xp_into = int(state.current_xp)
    target_level = int(state.target_level)

    table = get_skill_table(g.skills, skill)
    if not table:
        raise ValueError(f"No XP table found for skill '{skill}'.")

    # Owned stations are the crafter keys with owned == True
    owned_stations = {ck for ck, cv in prof.crafters.items() if isinstance(cv, dict) and cv.get("owned") is True}

    steps: List[PlanStep] = []
    total_exp = 0.0
    total_cost = 0.0
    total_crafts = 0

    xp_boost = 1.5 if prof.premium_account else 1.0

    while curr_level < target_level:
        feas = _feasible_recipes(g, skill, curr_level, owned_stations)
        if not feas:
            # Suggest building any relevant station not owned yet (that has recipes unlockable at <= curr_level)
            needed = {r.station for r in g.recipes
                      if r.skill == skill and not r.is_dev and r.station and (r.unlock_at <= curr_level) and (r.station not in owned_stations)}
            if needed:
                st = sorted(needed)[0]
                steps.append(PlanStep(action='build_station', key=st, count=1, exp_gain=0, cost=0, notes='Build to unlock better recipes'))
                owned_stations.add(st)
                continue
            else:
                raise RuntimeError(f"No feasible recipes for {skill} at level {curr_level}. Consider building a station or revising targets.")

        best, exp_per_base, cost_per, ratio = _best_recipe_now(g, feas, curr_level, weights.material_weight)
        if not best:
            raise RuntimeError(f"No best recipe found for {skill} at level {curr_level}.")
        exp_per = exp_per_base * xp_boost

        need = xp_to_next_level(table, curr_level, curr_xp_into)
        if need <= 0:
            curr_level += 1
            curr_xp_into = 0
            continue

        crafts = max(1, int((need / exp_per) + 0.999))
        step_cost = crafts * cost_per
        step_exp = crafts * exp_per
        total_cost += step_cost
        total_exp += step_exp
        total_crafts += crafts

        steps.append(PlanStep(
            action='craft',
            key=best.key,
            count=crafts,
            exp_gain=step_exp,
            cost=step_cost,
            notes=f"{best.name or best.key} | p_succ~{success_chance(curr_level, best.difficulty):.2f}, exp/craft~{exp_per:.1f}, cost/craft~{cost_per:.1f}"
        ))

        # Advance levels
        gained = step_exp
        while gained > 0 and curr_level < target_level:
            need = xp_to_next_level(table, curr_level, curr_xp_into)
            if gained >= need:
                gained -= need
                curr_level += 1
                curr_xp_into = 0
            else:
                curr_xp_into += int(gained)
                gained = 0

    return PlanResult(skill=skill, steps=steps, totals={'exp': total_exp, 'cost': total_cost, 'crafts': total_crafts})
