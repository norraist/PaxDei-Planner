from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List

import bootstrap  # noqa: F401

from paxdei_planner.cli import _load_profile
from paxdei_planner.data_loader import load_game_data
from paxdei_planner.level_planner import LevelPlanner
from paxdei_planner.planner import plan_skill
from paxdei_planner.report import write_plan_csv, write_materials_csv
from paxdei_planner.schemas import Weights

DEFAULT_STATIC = "source_data/staticdatabundle/StaticDataBundle.json"
DEFAULT_LOC = "source_data/localisation/localisation_en.json"
DEFAULT_PROFILE = "config/player_profile.json"
DEFAULT_MATERIALS = "config/materials_config.json"

CONFIG_TEMPLATE: Dict[str, Any] = {
    "mode": "multi",  # "multi" (LevelPlanner) or "single" (per-skill greedy planner)
    "static": DEFAULT_STATIC,
    "loc": DEFAULT_LOC,
    "profile": DEFAULT_PROFILE,
    "weights": None,
    "out_dir": "out",
    "plan_csv": "out/level_plan.csv",
    "shopping_csv": "out/level_plan_materials.csv",
    "steps_txt": "out/level_plan_steps.txt",
    "xp_tables_dir": "xp_tables",
    "topk": 3,
    "skills": [],
    "materials_config": DEFAULT_MATERIALS,
}


def _ensure_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(CONFIG_TEMPLATE, indent=2), encoding="utf-8")
        raise SystemExit(
            f"Created template config at {path}. Fill in the paths/values and rerun."
        )
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_weights(path: str | None) -> Weights:
    if not path:
        return Weights(material_weight={})
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"weights file not found: {path}")
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("weights file must be a JSON object of item -> weight")
    return Weights(material_weight={str(k): float(v) for k, v in data.items()})


def _select_skills(requested: Iterable[str], available: Dict[str, Any]) -> List[str]:
    if requested:
        return [sk for sk in requested if sk in available]
    return list(available.keys())


def run_single_skill(config: Dict[str, Any]) -> None:
    print("[executor] Running single-skill planner")
    mat_cfg = config.get("materials_config") or os.path.join(os.path.dirname(config["profile"]), "materials_config.json")
    g = load_game_data(config["static"], config["loc"], materials_config=mat_cfg)
    profile = _load_profile(config["profile"])
    weights = _load_weights(config.get("weights"))

    out_dir = Path(config.get("out_dir", "out")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    targets = _select_skills(config.get("skills", []), profile.skills)
    results = []
    for sk in targets:
        state = profile.skills[sk]
        if state.current_level >= state.target_level:
            print(f" - {sk}: already at/above target, skipping")
            continue
        print(f" - Planning {sk}: {state.current_level} -> {state.target_level}")
        res = plan_skill(g, sk, profile, weights)
        results.append(res)
        csv_path = write_plan_csv(str(out_dir), res, g)
        print(f"   wrote {csv_path}")

    if results:
        shop_path = write_materials_csv(str(out_dir), results, g)
        print(f"[executor] Shopping list: {shop_path}")
    else:
        print("[executor] Nothing to do")


def run_multi_skill(config: Dict[str, Any]) -> None:
    print("[executor] Running multi-skill LevelPlanner")
    static_path = config["static"]
    loc_path = config.get("loc") or os.path.join(
        os.path.dirname(static_path), "localisation_en.json"
    )
    profile_path = config["profile"]
    xp_tables_dir = config.get("xp_tables_dir", "xp_tables")
    Path(xp_tables_dir).mkdir(parents=True, exist_ok=True)

    materials_config_path = config.get("materials_config") or os.path.join(os.path.dirname(profile_path), "materials_config.json")
    planner = LevelPlanner(static_path, loc_path, profile_path, xp_tables_dir, materials_config_path=materials_config_path)
    plan = planner.plan(top_k=int(config.get("topk", 3)))

    out_csv = config.get("plan_csv", "out/level_plan.csv")
    planner.write_csv(plan, out_csv)
    shopping_csv = config.get("shopping_csv", "out/level_plan_materials.csv")
    planner.write_materials_csv(plan, shopping_csv)
    steps_txt = config.get("steps_txt", "out/level_plan_steps.txt")
    planner.write_steps_text(plan, steps_txt)
    print(f"[executor] Wrote plan with {len(plan)} steps to {out_csv}")
    print(f"[executor] Shopping list: {shopping_csv}")
    print(f"[executor] Step-by-step guide: {steps_txt}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Convenience executor for running PaxDei planners inside an IDE."
    )
    ap.add_argument(
        "--config",
        default="config/executor_config.json",
        help="Path to the executor config JSON (template is auto-created if missing).",
    )
    ap.add_argument(
        "--mode",
        choices=["single", "multi"],
        help="Override config mode: single = per-skill planner, multi = LevelPlanner.",
    )
    args = ap.parse_args()

    config_path = Path(args.config)
    config = _ensure_config(config_path)
    if args.mode:
        config["mode"] = args.mode

    mode = config.get("mode", "multi").lower()
    if mode == "single":
        run_single_skill(config)
    elif mode == "multi":
        run_multi_skill(config)
    else:
        raise SystemExit(f"Unknown mode '{mode}'. Use 'single' or 'multi'.")


if __name__ == "__main__":
    main()
