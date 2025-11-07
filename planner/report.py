from __future__ import annotations
import csv, os
from typing import Dict, List
from .schemas import GameData
from .planner import PlanResult

def write_plan_csv(out_dir: str, result: PlanResult, g: GameData):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"plan_{result.skill}.csv")
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['Action','Key','Name','Count','XP Gain','Cost','Notes'])
        for s in result.steps:
            name = s.key
            for r in g.recipes:
                if r.key == s.key:
                    name = r.name or s.key
                    break
            w.writerow([s.action, s.key, name, s.count, f"{s.exp_gain:.1f}", f"{s.cost:.1f}", s.notes])
    return path

def write_materials_csv(out_dir: str, results: List[PlanResult], g: GameData):
    agg: Dict[str,int] = {}
    # naive aggregation: multiply recipe ingredient counts by crafts from craft steps
    recipe_map = {r.key: r for r in g.recipes}
    for res in results:
        for s in res.steps:
            if s.action != 'craft':
                continue
            r = recipe_map.get(s.key)
            if not r: continue
            for item, qty in (r.ingredients or {}).items():
                agg[item] = agg.get(item, 0) + qty * s.count

    path = os.path.join(out_dir, "shopping_list.csv")
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['ItemKey','Qty'])
        for k,v in sorted(agg.items()):
            w.writerow([k, v])
    return path
