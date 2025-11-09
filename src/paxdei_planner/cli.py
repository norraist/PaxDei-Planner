from __future__ import annotations
import argparse, json, os, sys
from typing import Dict, Any
from .data_loader import load_game_data
from .schemas import Profile, Weights, SkillState
from .planner import plan_skill
from .report import write_plan_csv, write_materials_csv

def _load_profile(profile_path: str) -> Profile:
    with open(profile_path, "r", encoding="utf-8") as f:
        pj = json.load(f)

    # Preferred (new) nested shape
    if "skills" in pj and "crafters" in pj:
        premium = bool(pj.get("premium_account", False))
        avoid_relics = bool(pj.get("avoid_relics", False))
        max_gap = int(pj.get("max_cross_skill_gap", 5))
        skills: Dict[str, SkillState] = {}
        for sk, node in pj["skills"].items():
            skills[sk] = SkillState(
                name=node.get("name", sk),
                current_level=int(node.get("current_level", 1)),
                current_xp=int(node.get("current_xp", 0)),
                target_level=int(node.get("target_level", 40)),
            )
        crafters = pj["crafters"]
        return Profile(skills=skills, crafters=crafters, premium_account=premium, avoid_relics=avoid_relics, max_cross_skill_gap=max_gap)

    # Backward-compat: old flat format (current_level/current_xp/targets + owned_stations)
    current_level = pj.get("current_level", {})
    current_xp     = pj.get("current_xp", {})
    targets        = pj.get("target_level", pj.get("targets", {}))
    owned_stations = pj.get("owned_stations", [])
    skills: Dict[str, SkillState] = {}
    for sk, lvl in current_level.items():
        skills[sk] = SkillState(
            name=sk,
            current_level=int(lvl),
            current_xp=int(current_xp.get(sk, 0)),
            target_level=int(targets.get(sk, int(lvl) + 5)),
        )
    # Synthesize crafters dict from owned_stations list
    crafters: Dict[str, Dict[str, Any]] = {s: {"name": s, "owned": True} for s in owned_stations}
    return Profile(
        skills=skills,
        crafters=crafters,
        premium_account=bool(pj.get("premium_account", False)),
        avoid_relics=bool(pj.get("avoid_relics", False)),
        max_cross_skill_gap=int(pj.get("max_cross_skill_gap", 5)),
    )

def main():
    p = argparse.ArgumentParser(description='Pax Dei – Crafting Leveling Planner')
    p.add_argument('--static', required=True, help='Path to StaticDataBundle.json')
    p.add_argument('--loc', required=True, help='Path to localisation_en.json')
    p.add_argument('--profile', required=True, help='Path to profile.json (nested skills + crafters)')
    p.add_argument('--weights', required=False, help='Path to weights.json', default=None)
    p.add_argument('--out', required=True, help='Output directory for CSVs')
    args = p.parse_args()

    g = load_game_data(args.static, args.loc, materials_config=os.path.join(os.path.dirname(args.profile), "materials_config.json"))
    profile = _load_profile(args.profile)

    weights = Weights(material_weight={})
    if args.weights and os.path.exists(args.weights):
        with open(args.weights,'r',encoding='utf-8') as f:
            weights = Weights(material_weight=json.load(f))

    results = []
    for sk, state in profile.skills.items():
        if state.current_level >= state.target_level:
            # already at/above target; skip gracefully
            continue
        print(f"Planning for {sk} ({state.name}): {state.current_level} -> {state.target_level}")
        res = plan_skill(g, sk, profile, weights)
        results.append(res)
        path = write_plan_csv(args.out, res, g)
        print(f"  wrote: {path}")

    shop_path = write_materials_csv(args.out, results, g)
    print(f"Shopping list: {shop_path}")

if __name__ == '__main__':
    main()
