# planner/generate_xp_tables.py
from __future__ import annotations
import argparse, csv, os, math, json
from pathlib import Path
from typing import Iterable, Optional, Dict, Any

# local imports from your project
try:
    from .data_loader import load_game_data
    from .schemas import GameData, Recipe
    from .xp_model import (
        success_chance,
        xp_success_range,
        xp_success_avg,
        xp_failure_avg,
        xp_expected,
    )
except ImportError:
    import os
    import sys

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from paxdei_planner.data_loader import load_game_data  # type: ignore
    from paxdei_planner.schemas import GameData, Recipe  # type: ignore
    from paxdei_planner.xp_model import (  # type: ignore
        success_chance,
        xp_success_range,
        xp_success_avg,
        xp_failure_avg,
        xp_expected,
    )

def _iter_recipes(
    g: GameData,
    *,
    include_dev: bool = False,
    only_skill: Optional[str] = None,
    name_filter: Optional[str] = None,
) -> Iterable[Recipe]:
    materials_cfg = getattr(g, "materials_config", {})
    for r in g.recipes:
        if not include_dev and r.is_dev:
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
        if only_skill and r.skill != only_skill:
            continue
        if name_filter and name_filter.lower() not in r.key.lower():
            continue
        yield r

def _levels_for_recipe(r: Recipe, extra_levels: int = 10) -> list[int | str]:
    """
    Produce the list of levels to print rows for:
      from r.unlock_at ... (r.difficulty + extra_levels), with a final "+ row".
    Matches the style we validated earlier.
    """
    start = max(0, int(r.unlock_at))
    end = int(r.difficulty) + int(extra_levels)
    levels = list(range(start, end + 1))
    # Replace the last numeric level with a "+ row" label
    if levels:
        levels[-1] = f"{end}+"
    return levels

def _row_for_level(level, r: Recipe) -> dict:
    """
    Build the XP row for one displayed level. Handles the "+ row" label by using the numeric
    part for calculations, while leaving the label in the 'Skill Level' column.
    """
    label = level
    if isinstance(level, str) and level.endswith("+"):
        base = int(level[:-1])  # numeric
    else:
        base = int(level)

    ps = success_chance(base, r.difficulty)
    xs_min, xs_avg, xs_max = xp_success_range(base, r.difficulty, r.xp_multiplier)
    xf_avg = xp_failure_avg(base, r.difficulty, r.unlock_at, r.xp_multiplier)
    # For >= difficulty, xp_failure_avg() returns NaN; display as empty string.
    xf_display = "" if (not isinstance(xf_avg, float) or math.isnan(xf_avg)) else int(round(xf_avg))
    x_exp = xp_expected(base, r.difficulty, r.unlock_at, r.xp_multiplier)

    return {
        "Skill Level": label,
        "Success Chance": f"{int(round(ps*100))}%",
        "XP (Success) Min": int(round(xs_min)),
        "XP (Success) Avg": int(round(xs_avg)),
        "XP (Success) Max": int(round(xs_max)),
        "XP (Failure) Avg": xf_display,
        "XP (Expected) Avg": int(round(x_exp)),
    }

def _write_recipe_csv(out_dir: str, r: Recipe) -> str:
    """
    Write one CSV for a single recipe. Files are grouped by skill for easy browsing.
    """
    skill_dir = os.path.join(out_dir, r.skill or "unknown_skill")
    os.makedirs(skill_dir, exist_ok=True)
    filename = f"{r.key}.csv"
    path = os.path.join(skill_dir, filename)

    fieldnames = [
        "Skill Level",
        "Success Chance",
        "XP (Success) Min",
        "XP (Success) Avg",
        "XP (Success) Max",
        "XP (Failure) Avg",
        "XP (Expected) Avg",
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        # header block with context
        w.writerow([f"Recipe Key", r.key])
        w.writerow([f"Recipe Name", r.name or ""])
        w.writerow(["Skill", r.skill or ""])
        w.writerow(["UnlockAtSkillLevel", r.unlock_at])
        w.writerow(["SkillDifficulty", r.difficulty])
        w.writerow(["XPMultiplier", r.xp_multiplier])
        w.writerow(["Station", r.station or ""])
        w.writerow([])  # blank line
        w.writerow(fieldnames)

        for lvl in _levels_for_recipe(r, extra_levels=10):
            row = _row_for_level(lvl, r)
            w.writerow([row[h] for h in fieldnames])

    return path

def _write_master_index(out_dir: str, written: list[tuple[str, Recipe]]) -> str:
    """
    A master CSV listing all generated recipe tables with key metadata and file paths.
    """
    path = os.path.join(out_dir, "xp_tables_index.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "skill",
            "recipe_key",
            "recipe_name",
            "unlock_at",
            "difficulty",
            "xp_multiplier",
            "station",
            "csv_path",
        ])
        for csv_path, r in written:
            w.writerow([
                r.skill or "",
                r.key,
                r.name or "",
                r.unlock_at,
                r.difficulty,
                r.xp_multiplier,
                r.station or "",
                os.path.relpath(csv_path, out_dir),
            ])
    return path

def run(static_path: str, loc_path: str, out_dir: str,
        include_dev: bool = False,
        only_skill: Optional[str] = None,
        name_filter: Optional[str] = None,
        materials_config: Optional[str] = None) -> None:
    os.makedirs(out_dir, exist_ok=True)
    g: GameData = load_game_data(static_path, loc_path, materials_config=materials_config)

    written: list[tuple[str, Recipe]] = []
    for r in _iter_recipes(g,
                           include_dev=include_dev,
                           only_skill=only_skill,
                           name_filter=name_filter):
        csv_path = _write_recipe_csv(out_dir, r)
        written.append((csv_path, r))

    idx = _write_master_index(out_dir, written)
    print(f"Wrote {len(written)} recipe tables.")
    print(f"Master index: {idx}")

def main():
    ap = argparse.ArgumentParser(description="Generate Crafting XP tables for every recipe.")
    ap.add_argument("--static", required=False, help="Path to StaticDataBundle.json")
    ap.add_argument("--loc", required=False, help="Path to localisation_en.json")
    ap.add_argument("--out", required=False, help="Output directory for CSVs")
    ap.add_argument("--include-dev", action="store_true", help="Include IsDev recipes (default: False)")
    ap.add_argument("--only-skill", default=None, help="Limit to a specific skill key (e.g., skill_tailoring)")
    ap.add_argument("--name-filter", default=None, help="Substring filter on recipe key (e.g., 'bread')")
    ap.add_argument("--config", default=None, help="Optional JSON config file")
    ap.add_argument("--materials-config", default=None, help="Optional materials_config.json path")
    args = ap.parse_args()

    cfg: Dict[str, Any] = {}
    cfg_path = Path(args.config) if args.config else None
    if cfg_path:
        if cfg_path.exists():
            with cfg_path.open("r", encoding="utf-8") as f:
                cfg = json.load(f)
        else:
            template = {
                "static": "src/paxdei_planner/data/StaticDataBundle.json",
                "loc": "src/paxdei_planner/data/localisation_en.json",
                "out": "out/xp_tables",
                "include_dev": False,
                "only_skill": None,
                "name_filter": None,
            }
            cfg_path.write_text(json.dumps(template, indent=2), encoding="utf-8")
            raise SystemExit(
                f"Config template written to {cfg_path}. Fill it out or pass CLI args."
            )
    else:
        auto_cfg = Path("xp_tables_config.json")
        if auto_cfg.exists():
            with auto_cfg.open("r", encoding="utf-8") as f:
                cfg = json.load(f)
        elif not (args.static and args.loc and args.out):
            template = {
                "static": "src/paxdei_planner/data/StaticDataBundle.json",
                "loc": "src/paxdei_planner/data/localisation_en.json",
                "out": "out/xp_tables",
                "include_dev": False,
                "only_skill": None,
                "name_filter": None,
            }
            auto_cfg.write_text(json.dumps(template, indent=2), encoding="utf-8")
            raise SystemExit(
                f"Config template written to {auto_cfg}. Fill it out or pass CLI args."
            )

    def cfg_value(name: str):
        val = getattr(args, name.replace("-", "_"))
        if val is None or val == "":
            return cfg.get(name)
        return val

    static_path = cfg_value("static")
    loc_path = cfg_value("loc")
    out_dir = cfg_value("out")
    materials_config_path = args.materials_config or cfg.get("materials_config")
    if not static_path or not loc_path or not out_dir:
        raise SystemExit("Must provide --static, --loc, --out via CLI or config.")

    run(
        static_path=static_path,
        loc_path=loc_path,
        out_dir=out_dir,
        include_dev=bool(args.include_dev or cfg.get("include_dev")),
        only_skill=cfg_value("only_skill"),
        name_filter=cfg_value("name_filter"),
        materials_config=materials_config_path,
    )

if __name__ == "__main__":
    main()
