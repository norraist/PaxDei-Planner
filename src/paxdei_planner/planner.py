from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

try:
    from .schemas import GameData, Profile, Weights, Recipe
    from .xp_model import success_chance, xp_success_avg, xp_failure_avg, practical_unlock_level, mastery_level
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
    from paxdei_planner.xp_model import success_chance, xp_success_avg, xp_failure_avg, practical_unlock_level, mastery_level  # type: ignore
    from paxdei_planner.costs import craft_cost  # type: ignore
    from paxdei_planner.skills import xp_to_next_level, get_skill_table  # type: ignore

def _recipe_grants_xp(recipe: Recipe) -> bool:
    if not getattr(recipe, "grants_xp", True):
        return False
    key = getattr(recipe, "key", "")
    if key.startswith("recipe_crafter_") or key.startswith("recipe_item_unlock_crafter_"):
        return False
    outputs = getattr(recipe, "outputs", {}) or {}
    for out_key in outputs.keys():
        if isinstance(out_key, str) and out_key.startswith("crafter_"):
            return False
    return True


def _expected_xp_for_recipe(level: int, recipe: Recipe, blessing: bool) -> Tuple[float, float]:
    """
    Returns (expected_xp, success_chance) using the premium-on baseline from xp_model.
    """
    chance_level = level + 1 if blessing else level
    chance = success_chance(chance_level, recipe.difficulty)
    success = xp_success_avg(level, recipe.difficulty, recipe.xp_multiplier, skill=recipe.skill)
    failure = xp_failure_avg(level, recipe.difficulty, recipe.unlock_at, recipe.xp_multiplier, skill=recipe.skill)
    if isinstance(failure, float) and not math.isnan(failure):
        expected = chance * success + (1 - chance) * failure
    else:
        expected = chance * success
    return expected, chance

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
        if not _recipe_grants_xp(r):
            continue
        if getattr(r, "key", "").startswith("recipe_building_piece_"):
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
        practical_unlock = practical_unlock_level(getattr(r, "unlock_at", 0), getattr(r, "difficulty", 0))
        if level < practical_unlock:
            continue
        mastery_lvl = mastery_level(getattr(r, "difficulty", 0))
        if level >= mastery_lvl:
            continue
        # If recipe requires a station and we don't own it, skip
        if r.station and r.station not in owned_stations:
            continue
        out.append(r)
    return out

def _best_recipe_now(
    g: GameData,
    rlist: List[Recipe],
    level: int,
    weights: Dict[str, float],
    blessing: bool,
) -> Tuple[Optional[Recipe], float, float, float, float]:
    best = None
    best_ratio = -1.0
    best_exp = 0.0
    best_cost = 0.0
    best_chance = 0.0
    for r in rlist:
        exp, chance = _expected_xp_for_recipe(level, r, blessing)
        if exp <= 0:
            continue
        cost = craft_cost(r, weights)
        ratio = exp / cost if cost > 0 else 0.0
        if ratio > best_ratio:
            best_ratio = ratio
            best = r
            best_exp = exp
            best_cost = cost
            best_chance = chance
    return best, best_exp, best_cost, best_ratio, best_chance

PREMIUM_XP_MULTIPLIER = 1.5


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

    xp_boost = 1.0 if prof.premium_account else (1.0 / PREMIUM_XP_MULTIPLIER)
    blessing = bool(getattr(state, "blessing", False))

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

        best, exp_per_base, cost_per, ratio, chance = _best_recipe_now(
            g, feas, curr_level, weights.material_weight, blessing
        )
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
            notes=f"{best.name or best.key} | p_succ~{chance:.2f}, exp/craft~{exp_per:.1f}, cost/craft~{cost_per:.1f}"
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
