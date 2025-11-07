from __future__ import annotations
import json, re
from typing import Dict, Any, List, Tuple, Optional
from .schemas import Recipe, GameData, SkillXPTable

def _index_localization(loc: Dict[str, Any]) -> Dict[str, str]:
    out = {}
    def visit(obj):
        if isinstance(obj, dict):
            key = obj.get('Key') or obj.get('key') or obj.get('_LocalizationNameKey') or obj.get('_LocalizationDescriptionKey')
            val = obj.get('Text') or obj.get('text') or obj.get('Name') or obj.get('name') or obj.get('Description') or obj.get('description')
            if key and val:
                out[str(key)] = str(val)
            for v in obj.values():
                visit(v)
        elif isinstance(obj, list):
            for v in obj:
                visit(v)
    visit(loc)
    return out

def _find_xp_tables(static: Dict[str, Any]) -> Dict[str, List[int]]:
    # Heuristic: find dicts/lists that look like { 'skill': 'skill_tailoring', 'XpToLevel': [ ... ] } or per-skill arrays.
    found = {}
    def visit(obj):
        if isinstance(obj, dict):
            # Case 1: explicit per-skill entries
            if ('XpToLevel' in obj or 'XPToLevel' in obj or 'xpToLevel' in obj) and ('Skill' in obj or 'skill' in obj or 'SkillRequired' in obj):
                skill = obj.get('Skill') or obj.get('skill') or obj.get('SkillRequired')
                arr = obj.get('XpToLevel') or obj.get('XPToLevel') or obj.get('xpToLevel')
                if isinstance(skill, str) and isinstance(arr, list) and all(isinstance(x,(int,float)) for x in arr[:5]):
                    found[skill] = [int(x) for x in arr]
            for v in obj.values():
                visit(v)
        elif isinstance(obj, list):
            for v in obj:
                visit(v)
    visit(static)
    # Fallback: look for top-level skills dicts
    if not found:
        # Try keys named like 'Skills', 'skills'
        for k,v in static.items():
            if isinstance(v, dict) and 'Skills' in k or 'skills' in k.lower():
                for sk, sv in v.items():
                    if isinstance(sv, dict):
                        arr = sv.get('XpToLevel') or sv.get('XPToLevel') or sv.get('xpToLevel')
                        if isinstance(arr, list):
                            found[sk] = [int(x) for x in arr]
    return found

def _discover_recipe_station_map(static: Dict[str, Any]) -> Dict[str, str]:
    # If the JSON encodes station categories -> recipe keys, capture mapping; else leave empty and infer later.
    mapping = {}
    def visit(obj, path=""):
        if isinstance(obj, dict):
            # Heuristic: nodes named like 'CraftingStations', 'Stations', 'Tables'
            for k, v in obj.items():
                name = str(k).lower()
                if any(tag in name for tag in ['station','stations','tables','crafting']):
                    # try to record entries listing recipes
                    if isinstance(v, (dict, list)):
                        _collect_from_node(v, k, mapping)
                visit(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                visit(v, f"{path}[{i}]")
    def _collect_from_node(node, station_name, mapping):
        if isinstance(node, dict):
            for rk, rv in node.items():
                if isinstance(rk, str) and rk.startswith('recipe_'):
                    mapping[rk] = station_name
                _collect_from_node(rv, station_name, mapping)
        elif isinstance(node, list):
            for rv in node:
                _collect_from_node(rv, station_name, mapping)
    visit(static)
    return mapping

def load_game_data(static_path: str, loc_path: str) -> GameData:
    with open(static_path, 'r', encoding='utf-8') as f:
        static = json.load(f)
    with open(loc_path, 'r', encoding='utf-8') as f:
        loc = json.load(f)

    loc_idx = _index_localization(loc)

    recipes: List[Recipe] = []
    recipe_to_station: Dict[str, str] = {}

    # Try to discover station→recipe mapping
    recipe_to_station = _discover_recipe_station_map(static)

    # Traverse static to collect recipes
    def visit(obj):
        if isinstance(obj, dict):
            for k,v in obj.items():
                if isinstance(k, str) and k.startswith('recipe_') and isinstance(v, dict):
                    key = k
                    r = v
                    is_dev = bool(r.get('IsDev', False))
                    skill = r.get('SkillRequired') or r.get('Skill') or ''
                    unlock_at = int(r.get('UnlockAtSkillLevel', 0))
                    difficulty = int(r.get('SkillDifficulty', r.get('Difficulty', 0)))
                    xp_mult = float(r.get('XPMultiplier', 1.0))
                    ingred = {}
                    for ing_k, ing_v in (r.get('ItemIngredients') or {}).items():
                        ingred[str(ing_k)] = int(ing_v)
                    station = recipe_to_station.get(key) or r.get('CraftingStation') or None
                    name_key = r.get('LocalizationNameKey') or ''
                    desc_key = r.get('LocalizationDescriptionKey') or ''
                    name = loc_idx.get(str(name_key), key)
                    desc = loc_idx.get(str(desc_key), '')
                    recipes.append(Recipe(
                        key=key, is_dev=is_dev, skill=str(skill), unlock_at=unlock_at,
                        difficulty=difficulty, xp_multiplier=xp_mult, ingredients=ingred,
                        station=station, name=name, desc=desc
                    ))
                else:
                    visit(v)
        elif isinstance(obj, list):
            for v in obj:
                visit(v)
    visit(static)

    # XP tables
    xp_tables_raw = _find_xp_tables(static)
    skills = {}
    for sk, arr in xp_tables_raw.items():
        skills[str(sk)] = SkillXPTable(skill=str(sk), xp_to_level=[int(x) for x in arr])

    # Basic names for items from localisation
    item_names = {}
    for k in list(loc_idx.keys()):
        if 'item_' in k.lower():
            item_names[k] = loc_idx[k]

    return GameData(recipes=recipes, skills=skills, item_names=item_names, recipe_to_station=recipe_to_station)
