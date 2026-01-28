"""
Generate XP tables for every recipe using the PaxDei planner internals.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bootstrap  # noqa: F401
from paxdei_planner.data_loader import load_game_data
from paxdei_planner.schemas import GameData, Recipe
from paxdei_planner.xp_model import (
    success_chance,
    xp_expected,
    xp_failure_avg,
    xp_success_avg,
    xp_success_range,
    practical_unlock_level,
    mastery_level,
)

DEFAULT_CFG_PATH = Path("config/xp_tables_config.json")

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

def _levels_for_recipe(
    r: Recipe,
    extra_levels: int = 10,
    *,
    start_level: Optional[int] = None,
    mastery_level_limit: Optional[int] = None,
) -> list[int | str]:
    """
    Produce the list of levels to print rows for:
      from the first craftable level ... up to the mastery limit (or difficulty + extra),
      with a final "+ row".
    Matches the style we validated earlier.
    """
    start = start_level if start_level is not None else max(0, int(r.unlock_at))
    end = int(r.difficulty) + int(extra_levels)
    if mastery_level_limit is not None:
        end = min(end, mastery_level_limit)
    levels = list(range(start, end + 1))
    # Replace the last numeric level with a "+ row" label
    if levels:
        levels[-1] = f"{end}+"
    return levels

def _expected_from_chance(success_avg: float, failure_avg: float, chance: float) -> float:
    if not isinstance(failure_avg, (int, float)) or math.isnan(failure_avg):
        return success_avg
    return chance * success_avg + (1 - chance) * failure_avg


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
    ps_bless = success_chance(base + 1, r.difficulty)
    xs_min, xs_avg, xs_max = xp_success_range(base, r.difficulty, r.xp_multiplier, skill=r.skill)
    xf_avg = xp_failure_avg(base, r.difficulty, r.unlock_at, r.xp_multiplier, skill=r.skill)
    # For >= difficulty, xp_failure_avg() returns NaN; display as empty string.
    xf_display = "" if (not isinstance(xf_avg, float) or math.isnan(xf_avg)) else int(round(xf_avg))
    x_exp = xp_expected(base, r.difficulty, r.unlock_at, r.xp_multiplier, skill=r.skill)
    x_exp_bless = _expected_from_chance(xs_avg, xf_avg, ps_bless)

    return {
        "Skill Level": label,
        "Success Chance": f"{int(round(ps*100))}%",
        "XP (Success) Min": int(round(xs_min)),
        "XP (Success) Avg": int(round(xs_avg)),
        "XP (Success) Max": int(round(xs_max)),
        "XP (Failure) Avg": xf_display,
        "XP (Expected) Avg": int(round(x_exp)),
        "XP (Bless) Avg": int(round(x_exp_bless)),
    }

def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS recipe_meta (
            recipe_key TEXT PRIMARY KEY,
            recipe_name TEXT,
            skill TEXT,
            unlock_at INTEGER,
            practical_unlock INTEGER,
            difficulty INTEGER,
            mastery_level INTEGER,
            xp_multiplier REAL,
            station TEXT
        );
        CREATE TABLE IF NOT EXISTS recipe_xp (
            recipe_key TEXT NOT NULL,
            level INTEGER NOT NULL,
            chance REAL,
            success_min REAL,
            success_avg REAL,
            success_max REAL,
            failure_avg REAL,
            expected_avg REAL,
            bless_avg REAL,
            PRIMARY KEY (recipe_key, level)
        );
        CREATE INDEX IF NOT EXISTS idx_recipe_xp_key_level
            ON recipe_xp(recipe_key, level);
        """
    )


def _write_recipe_sqlite(conn: sqlite3.Connection, r: Recipe) -> None:
    practical_unlock = practical_unlock_level(r.unlock_at, r.difficulty)
    mastery_lvl = mastery_level(r.difficulty)
    conn.execute(
        """
        INSERT OR REPLACE INTO recipe_meta
            (recipe_key, recipe_name, skill, unlock_at, practical_unlock, difficulty,
             mastery_level, xp_multiplier, station)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            r.key,
            r.name or "",
            r.skill or "",
            int(r.unlock_at),
            int(practical_unlock),
            int(r.difficulty),
            int(mastery_lvl),
            float(r.xp_multiplier),
            r.station or "",
        ),
    )

    levels = _levels_for_recipe(
        r,
        extra_levels=10,
        start_level=practical_unlock,
        mastery_level_limit=mastery_lvl,
    )
    if not levels:
        levels = [practical_unlock]
    rows = []
    for lvl in levels:
        row = _row_for_level(lvl, r)
        level_label = row["Skill Level"]
        if isinstance(level_label, str):
            digits = "".join(ch for ch in level_label if ch.isdigit())
            level_val = int(digits) if digits else 0
        else:
            level_val = int(level_label)
        chance_str = str(row["Success Chance"]).strip().rstrip("%")
        try:
            chance = float(chance_str) / 100.0
        except ValueError:
            chance = 0.0
        def as_float(value) -> float:
            if value in ("", None):
                return float("nan")
            try:
                return float(value)
            except Exception:
                return float("nan")
        rows.append(
            (
                r.key,
                level_val,
                chance,
                as_float(row["XP (Success) Min"]),
                as_float(row["XP (Success) Avg"]),
                as_float(row["XP (Success) Max"]),
                as_float(row["XP (Failure) Avg"]),
                as_float(row["XP (Expected) Avg"]),
                as_float(row["XP (Bless) Avg"]),
            )
        )
    conn.executemany(
        """
        INSERT OR REPLACE INTO recipe_xp
            (recipe_key, level, chance, success_min, success_avg, success_max,
             failure_avg, expected_avg, bless_avg)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )

def run(static_path: str, loc_path: str, out_dir: str,
        include_dev: bool = False,
        only_skill: Optional[str] = None,
        name_filter: Optional[str] = None,
        materials_config: Optional[str] = None) -> None:
    os.makedirs(out_dir, exist_ok=True)
    g: GameData = load_game_data(static_path, loc_path, materials_config=materials_config)
    db_path = os.path.join(out_dir, "xp_tables.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    try:
        _init_db(conn)
        count = 0
        for r in _iter_recipes(
            g,
            include_dev=include_dev,
            only_skill=only_skill,
            name_filter=name_filter,
        ):
            _write_recipe_sqlite(conn, r)
            count += 1
        conn.commit()
    finally:
        conn.close()
    print(f"Wrote {count} recipe tables to {db_path}.")

def main():
    ap = argparse.ArgumentParser(description="Generate Crafting XP tables for every recipe (SQLite).")
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
                "static": "source_data/staticdatabundle/StaticDataBundle.json",
                "loc": "source_data/localisation/localisation_en.json",
                "out": "xp_tables",
                "include_dev": False,
                "only_skill": None,
                "name_filter": None,
            }
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(json.dumps(template, indent=2), encoding="utf-8")
            raise SystemExit(
                f"Config template written to {cfg_path}. Fill it out or pass CLI args."
            )
    else:
        auto_cfg = DEFAULT_CFG_PATH
        if auto_cfg.exists():
            with auto_cfg.open("r", encoding="utf-8") as f:
                cfg = json.load(f)
        elif not (args.static and args.loc and args.out):
            template = {
                "static": "source_data/staticdatabundle/StaticDataBundle.json",
                "loc": "source_data/localisation/localisation_en.json",
                "out": "xp_tables",
                "include_dev": False,
                "only_skill": None,
                "name_filter": None,
            }
            auto_cfg.parent.mkdir(parents=True, exist_ok=True)
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
