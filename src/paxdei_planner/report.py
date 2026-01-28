from __future__ import annotations

import json
import os
from typing import Dict, List

from .planner import PlanResult
from .schemas import GameData


def write_plan_json(out_dir: str, result: PlanResult, g: GameData):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"plan_{result.skill}.json")
    steps = []
    for s in result.steps:
        name = s.key
        for r in g.recipes:
            if r.key == s.key:
                name = r.name or s.key
                break
        steps.append(
            {
                "action": s.action,
                "key": s.key,
                "name": name,
                "count": s.count,
                "xp_gain": float(f"{s.exp_gain:.1f}"),
                "cost": float(f"{s.cost:.1f}"),
                "notes": s.notes,
            }
        )
    payload = {"skill": result.skill, "steps": steps, "totals": result.totals}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


def write_materials_json(out_dir: str, results: List[PlanResult], g: GameData):
    agg: Dict[str, int] = {}
    # naive aggregation: multiply recipe ingredient counts by crafts from craft steps
    recipe_map = {r.key: r for r in g.recipes}
    for res in results:
        for s in res.steps:
            if s.action != "craft":
                continue
            r = recipe_map.get(s.key)
            if not r:
                continue
            for item, qty in (r.ingredients or {}).items():
                agg[item] = agg.get(item, 0) + qty * s.count

    path = os.path.join(out_dir, "shopping_list.json")
    payload = [
        {"item_key": key, "qty": qty} for key, qty in sorted(agg.items())
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path
