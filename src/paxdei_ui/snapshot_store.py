from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

from paxdei_planner.level_planner import PlanStep, PlanStepOption

from .plan_service import PlanSnapshot


def _serialize_xp_breakdown(xp_rows: List[Tuple[str, float, float, float, float, int]]) -> List[Dict[str, Any]]:
    rows = []
    for name, chance, success, failure, expected, count in xp_rows:
        failure_val = None
        if isinstance(failure, (int, float)) and not math.isnan(failure):
            failure_val = float(failure)
        rows.append(
            {
                "name": name,
                "chance": chance,
                "success": success,
                "failure": failure_val,
                "expected": expected,
                "count": count,
            }
        )
    return rows


def _serialize_option(opt: PlanStepOption) -> Dict[str, Any]:
    return {
        "recipe_key": opt.recipe_key,
        "recipe_name": opt.recipe_name,
        "crafter": opt.crafter,
        "crafts": opt.crafts,
        "xp_per_craft": opt.xp_per_craft,
        "total_xp": opt.total_xp,
        "total_xp_chain": opt.total_xp_chain,
        "material_burden": opt.material_burden,
        "materials": list(opt.materials),
        "materials_qty": opt.materials_qty,
        "materials_tree": opt.materials_tree,
        "craft_summary": opt.craft_summary,
        "ingredient_breakdown": opt.ingredient_breakdown,
        "prereq_gaps": opt.prereq_gaps,
        "xp_breakdown": _serialize_xp_breakdown(opt.xp_breakdown),
        "synergy_support": [[skill, item, qty] for skill, item, qty in opt.synergy_support],
        "blessing_active": opt.blessing_active,
    }


def _serialize_step(step: PlanStep) -> Dict[str, Any]:
    return {
        "skill": step.skill,
        "from_level": step.from_level,
        "to_level": step.to_level,
        "note": step.note,
        "options": [_serialize_option(opt) for opt in step.options],
        "category_options": {k: [_serialize_option(opt) for opt in v] for k, v in (step.category_options or {}).items()},
    }


def snapshot_to_dict(snapshot: PlanSnapshot) -> Dict[str, Any]:
    return {
        "skill_names": snapshot.skill_names,
        "item_names": snapshot.item_names,
        "steps": [_serialize_step(step) for step in snapshot.steps],
    }


def _deserialize_option(data: Dict[str, Any]) -> PlanStepOption:
    xp_rows = []
    for entry in data.get("xp_breakdown", []):
        xp_rows.append(
            (
                entry.get("name", ""),
                float(entry.get("chance", 0.0)),
                float(entry.get("success", 0.0)),
                float(entry.get("failure", float("nan"))) if entry.get("failure") is not None else float("nan"),
                float(entry.get("expected", 0.0)),
                int(entry.get("count", 0)),
            )
        )
    return PlanStepOption(
        recipe_key=data.get("recipe_key", ""),
        recipe_name=data.get("recipe_name", ""),
        crafter=data.get("crafter"),
        crafts=int(data.get("crafts", 0)),
        xp_per_craft=float(data.get("xp_per_craft", 0.0)),
        total_xp=float(data.get("total_xp", 0.0)),
        total_xp_chain=float(data.get("total_xp_chain", 0.0)),
        material_burden=float(data.get("material_burden", 0.0)),
        materials=[(str(item), int(qty)) for item, qty in data.get("materials", [])],
        materials_qty=int(data.get("materials_qty", 0)),
        materials_tree=data.get("materials_tree", ""),
        craft_summary=data.get("craft_summary", []),
        ingredient_breakdown=data.get("ingredient_breakdown", []),
        prereq_gaps=data.get("prereq_gaps", []),
        xp_breakdown=xp_rows,
        synergy_support=[(str(entry[0]), str(entry[1]), int(entry[2])) for entry in data.get("synergy_support", []) if isinstance(entry, (list, tuple)) and len(entry) >= 3],
        blessing_active=bool(data.get("blessing_active", False)),
    )


def _deserialize_step(data: Dict[str, Any]) -> PlanStep:
    options = [_deserialize_option(opt) for opt in data.get("options", [])]
    category_options: dict[str, list[PlanStepOption]] = {}
    for key, entries in (data.get("category_options") or {}).items():
        category_options[str(key)] = [_deserialize_option(opt) for opt in entries]
    return PlanStep(
        skill=data.get("skill", ""),
        from_level=int(data.get("from_level", 0)),
        to_level=int(data.get("to_level", 0)),
        options=options,
        category_options=category_options,
        note=data.get("note", ""),
    )


def snapshot_from_dict(data: Dict[str, Any]) -> PlanSnapshot:
    steps = [_deserialize_step(step) for step in data.get("steps", [])]
    skill_names = {str(k): str(v) for k, v in data.get("skill_names", {}).items()}
    item_names = {str(k): str(v) for k, v in data.get("item_names", {}).items()}
    return PlanSnapshot(steps, skill_names, item_names)


def save_snapshot(snapshot: PlanSnapshot, path: Path) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = snapshot_to_dict(snapshot)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    tmp.replace(path)


def load_snapshot(path: Path) -> PlanSnapshot | None:
    if not path or not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return None
    try:
        return snapshot_from_dict(data)
    except Exception:
        return None
