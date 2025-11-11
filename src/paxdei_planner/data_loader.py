from __future__ import annotations
import json, re
from pathlib import Path
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional, Set

from .schemas import Recipe, GameData, SkillXPTable, ItemMeta

def _as_bool(val: Any, default: bool = False) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        lower = val.strip().lower()
        if lower in ("true", "1", "yes", "y"):
            return True
        if lower in ("false", "0", "no", "n", ""):
            return False
        return default
    if isinstance(val, (int, float)):
        return val != 0
    return default

def _index_localization(loc: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}

    def record(k: Any, v: Any) -> None:
        if isinstance(k, str) and isinstance(v, str) and k:
            out[k] = v

    def visit(obj):
        if isinstance(obj, dict):
            key = obj.get('Key') or obj.get('key') or obj.get('_LocalizationNameKey') or obj.get('_LocalizationDescriptionKey')
            val = obj.get('Text') or obj.get('text') or obj.get('Name') or obj.get('name') or obj.get('Description') or obj.get('description')
            if key and val:
                record(key, val)
            for k, v in obj.items():
                # Many localisation files are simple key -> string dictionaries.
                if isinstance(v, str) and ('localization' in str(k).lower()):
                    record(k, v)
                visit(v)
        elif isinstance(obj, list):
            for v in obj:
                visit(v)

    visit(loc)
    return out

def _infer_skill_from_table_name(name: str) -> Optional[str]:
    low = name.lower()
    if "skill_" in low:
        idx = low.index("skill_")
        return low[idx:]
    return None


def _find_xp_tables(static: Dict[str, Any]) -> Dict[str, List[int]]:
    found: Dict[str, List[int]] = {}

    def record(skill: Optional[str], arr: List[Any]) -> None:
        if not skill or not isinstance(arr, list):
            return
        if not arr:
            return
        if not all(isinstance(x, (int, float)) for x in arr[: min(5, len(arr))]):
            return
        found[skill] = [int(x) for x in arr]

    def visit(obj):
        if isinstance(obj, dict):
            # Pattern 1: explicit skill + XpToLevel arrays
            if ('XpToLevel' in obj or 'XPToLevel' in obj or 'xpToLevel' in obj) and ('Skill' in obj or 'skill' in obj or 'SkillRequired' in obj):
                skill = obj.get('Skill') or obj.get('skill') or obj.get('SkillRequired')
                arr = obj.get('XpToLevel') or obj.get('XPToLevel') or obj.get('xpToLevel')
                record(skill if isinstance(skill, str) else None, arr)
            for k, v in obj.items():
                # Pattern 2: LOOKUP_TABLE -> leveling_table_skill_<name>
                if isinstance(k, str) and isinstance(v, dict) and 'Values' in v:
                    skill = _infer_skill_from_table_name(k)
                    if not skill and isinstance(v.get('Skill'), str):
                        skill = str(v['Skill'])
                    if skill:
                        record(skill, v.get('Values'))
                    else:
                        values = v.get('Values')
                        if isinstance(values, list):
                            found[str(k)] = [int(x) for x in values if isinstance(x, (int, float))]
                visit(v)
        elif isinstance(obj, list):
            for v in obj:
                visit(v)

    visit(static)
    return found

def _normalize_key(name: Optional[str]) -> str:
    if not name:
        return ""
    return "".join(ch for ch in str(name).lower() if ch.isalnum())

def _extract_skill_leveling(static: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    skills_block = (
        static.get("static_data", {})
        .get("SKILL", {})
    )
    if not isinstance(skills_block, dict):
        return out
    for key, node in skills_block.items():
        if not isinstance(node, dict):
            continue
        if _as_bool(node.get("IsDev")):
            continue
        lvl_table = (
            node.get("SkillLevelingTableId")
            or node.get("skill_leveling_table_id")
            or node.get("SkillLevelingTableID")
        )
        base_xp = node.get("SkillBaseXp") or node.get("skill_base_xp") or 0
        try:
            base_xp_int = int(base_xp)
        except Exception:
            base_xp_int = 0
        out[str(key)] = {
            "level_table": str(lvl_table) if isinstance(lvl_table, str) else None,
            "base_xp": base_xp_int,
        }
    return out

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

def _maybe_record_item_meta(store: Dict[str, ItemMeta], key: str, node: Dict[str, Any]) -> None:
    if not isinstance(node, dict):
        return
    tier = node.get("Tier") if isinstance(node.get("Tier"), (int, float)) else node.get("tier")
    item_level = node.get("ItemLevel") if isinstance(node.get("ItemLevel"), (int, float)) else node.get("itemLevel")
    categories = node.get("Categories") or node.get("categories")
    if tier is None and item_level is None and not isinstance(categories, list):
        return

    meta = store.get(key)
    if not meta:
        meta = ItemMeta(key=key)
        store[key] = meta

    if isinstance(tier, (int, float)):
        meta.tier = int(tier)
    if isinstance(item_level, (int, float)):
        meta.item_level = int(item_level)
    if isinstance(categories, list):
        cats = [str(c) for c in categories if isinstance(c, str)]
        if cats:
            meta.categories = cats
            for c in cats:
                lower = c.lower()
                if "raw" in lower:
                    meta.is_raw = True
                if "relic" in lower:
                    meta.is_relic = True

def _collect_processing_books(static: Dict[str, Any]) -> Set[str]:
    processing_books: Set[str] = set()
    book_children: Dict[str, List[str]] = {}
    book_recipes: Dict[str, List[str]] = {}

    def visit(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and isinstance(v, dict):
                    if k.startswith("crafter_"):
                        ctype = v.get("CrafterType") or v.get("crafter_type") or ""
                        book_id = v.get("ProvidesRecipeBookID") or v.get("provides_recipe_book_id")
                        if isinstance(book_id, str) and book_id != "None" and "CRAFTER_PROCESSING" in str(ctype):
                            processing_books.add(str(book_id))
                    if k.startswith("recipebook_"):
                        recipes = v.get("ContainsRecipeIds") or v.get("contains_recipe_ids") or []
                        books = v.get("ContainsRecipebook") or v.get("contains_recipebook") or []
                        book_recipes[k] = [str(r) for r in recipes if isinstance(r, str)]
                        children: List[str] = []
                        if isinstance(books, list):
                            children = [str(b) for b in books if isinstance(b, str)]
                        elif isinstance(books, str) and books != "None":
                            children = [books]
                        if children:
                            book_children[k] = children
                visit(v)
        elif isinstance(obj, list):
            for v in obj:
                visit(v)
    visit(static)

    queue = list(processing_books)
    while queue:
        book = queue.pop()
        for child in book_children.get(book, []):
            if child not in processing_books:
                processing_books.add(child)
                queue.append(child)

    no_xp_recipes: Set[str] = set()
    for book in processing_books:
        for rid in book_recipes.get(book, []):
            no_xp_recipes.add(rid)
    return no_xp_recipes


def _map_recipe_to_crafters(static: Dict[str, Any]) -> Tuple[Dict[str, List[str]], Dict[str, int]]:
    recipe_books = (
        static.get("static_data", {})
        .get("RECIPE_BOOK", {})
    )
    crafter_nodes = (
        static.get("static_data", {})
        .get("CRAFTER", {})
    )
    if not isinstance(recipe_books, dict) or not isinstance(crafter_nodes, dict):
        return {}, {}

    resolved_books: Dict[str, Set[str]] = {}

    def resolve_book(book_key: str, trail: Set[str]) -> Set[str]:
        if book_key in resolved_books:
            return resolved_books[book_key]
        if book_key in trail:
            return set()
        node = recipe_books.get(book_key)
        recipes: Set[str] = set()
        if isinstance(node, dict):
            ids = node.get("ContainsRecipeIds") or node.get("contains_recipe_ids") or []
            if isinstance(ids, list):
                for rid in ids:
                    if isinstance(rid, str):
                        recipes.add(rid)
            child_keys: List[str] = []
            nested = node.get("ContainsRecipebook") or node.get("contains_recipebook")
            if isinstance(nested, list):
                child_keys.extend([str(c) for c in nested if isinstance(c, str)])
            elif isinstance(nested, str) and nested and nested != "None":
                child_keys.append(nested)
            nested_many = node.get("ContainsRecipebooks") or node.get("contains_recipebooks")
            if isinstance(nested_many, list):
                child_keys.extend([str(c) for c in nested_many if isinstance(c, str)])
            for child in child_keys:
                recipes.update(resolve_book(child, trail | {book_key}))
        resolved_books[book_key] = recipes
        return recipes

    recipe_to_crafters: Dict[str, Set[str]] = {}
    crafter_tiers: Dict[str, int] = {}

    for crafter_key, node in crafter_nodes.items():
        if not isinstance(node, dict):
            continue
        if _as_bool(node.get("IsDev")):
            continue
        tier = node.get("Tier", 0)
        try:
            crafter_tiers[crafter_key] = int(tier)
        except Exception:
            crafter_tiers[crafter_key] = 0
        provided = node.get("ProvidesRecipeBookID") or node.get("provides_recipe_book_id")
        book_list: List[str] = []
        if isinstance(provided, list):
            book_list = [str(b) for b in provided if isinstance(b, str)]
        elif isinstance(provided, str) and provided and provided != "None":
            book_list = [provided]
        for book_key in book_list:
            recipes = resolve_book(book_key, set())
            for recipe_key in recipes:
                recipe_to_crafters.setdefault(recipe_key, set()).add(crafter_key)

    recipe_to_crafters_sorted: Dict[str, List[str]] = {
        recipe: sorted(crafters, key=lambda ck: crafter_tiers.get(ck, 0))
        for recipe, crafters in recipe_to_crafters.items()
    }
    return recipe_to_crafters_sorted, crafter_tiers


def _load_material_config(static: Dict[str, Any], loc_idx: Dict[str, str], config_path: Optional[str]) -> Dict[str, Dict[str, Any]]:
    if not config_path:
        return {}
    path = Path(config_path)
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    print(f"[materials] Generating {path} ... this may take a moment.")
    materials: Dict[str, Dict[str, str]] = {}
    items = (
        static.get("static_data", {})
        .get("ITEM", {})
    )
    total = len(items)
    if not isinstance(items, dict) or total == 0:
        print("[materials]   could not find ITEM block in static data; generated empty config.")
    for idx, (key, node) in enumerate(items.items(), 1):
        if not isinstance(node, dict):
            continue
        if _as_bool(node.get("IsDev")):
            continue
        cats = node.get("Categories") or []
        match = False
        for c in cats:
            if not isinstance(c, str):
                continue
            lower = c.lower()
            if (
                "category.items.raw" in lower
                or "category.items.material" in lower
                or "craftingcomponents" in lower
                or "raw_" in lower
            ):
                match = True
                break
        if not match:
            lower_key = key.lower()
            if lower_key.startswith("item_material_") or lower_key.startswith("item_raw_"):
                match = True
        if match:
            name = loc_idx.get(f"{key}_LocalizationNameKey", loc_idx.get(key, key))
            desc = loc_idx.get(f"{key}_LocalizationDescriptionKey", loc_idx.get(key, ""))
            materials[key] = {"name": name, "description": desc}
        if idx % 200 == 0 or idx == total:
            pct = int((idx / max(1, total)) * 100)
            print(f"[materials]   processed {idx:,}/{total:,} ({pct}%)", end="\r")

    print(f"[materials]   processed {total:,}/{total:,}. Found {len(materials)} materials.".ljust(80))
    config = {
        k: {
            "name": v["name"],
            "description": v["description"],
            "enabled": True,
        }
        for k, v in sorted(materials.items())
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"[materials] Wrote config to {path}")
    return config


def load_game_data(static_path: str, loc_path: str, materials_config: Optional[str] = None) -> GameData:
    with open(static_path, 'r', encoding='utf-8') as f:
        static = json.load(f)
    with open(loc_path, 'r', encoding='utf-8') as f:
        loc = json.load(f)

    loc_idx = _index_localization(loc)
    materials_cfg: Dict[str, Dict[str, Any]] = {}
    if materials_config:
        materials_cfg = _load_material_config(static, loc_idx, materials_config)

    recipes: List[Recipe] = []
    recipe_to_station: Dict[str, str] = {}
    item_meta: Dict[str, ItemMeta] = {}

    # Try to discover station+recipe mapping
    recipe_to_station = _discover_recipe_station_map(static)
    recipe_crafters_map, crafter_tiers = _map_recipe_to_crafters(static)

    no_xp_recipes = _collect_processing_books(static)

    # Traverse static to collect recipes
    def visit(obj):
        if isinstance(obj, dict):
            for k,v in obj.items():
                if isinstance(k, str) and isinstance(v, dict):
                    if k.startswith('recipe_'):
                        key = k
                        r = v
                        is_dev = _as_bool(r.get('IsDev', False))
                        skill = r.get('SkillRequired') or r.get('Skill') or ''
                        unlock_at = int(r.get('UnlockAtSkillLevel', 0))
                        difficulty = int(r.get('SkillDifficulty', r.get('Difficulty', 0)))
                        xp_mult = float(r.get('XPMultiplier', 1.0))
                        ingred = {}
                        for ing_k, ing_v in (r.get('ItemIngredients') or {}).items():
                            ingred[str(ing_k)] = int(ing_v)
                        outputs: Dict[str, int] = {}
                        for field in (
                            'ItemDeliverables',
                            'ActivatableDeliverables',
                            'ProjectileDeliverables',
                            'Deliverables',
                            'Outputs',
                        ):
                            block = r.get(field) or {}
                            if isinstance(block, dict):
                                for out_k, out_v in block.items():
                                    try:
                                        outputs[str(out_k)] = outputs.get(str(out_k), 0) + int(out_v)
                                    except Exception:
                                        continue
                        station = recipe_to_station.get(key) or r.get('CraftingStation') or None
                        name_key = r.get('LocalizationNameKey') or ''
                        desc_key = r.get('LocalizationDescriptionKey') or ''
                        name = loc_idx.get(str(name_key), key)
                        desc = loc_idx.get(str(desc_key), '')
                        grants_xp = key not in no_xp_recipes
                        recipes.append(Recipe(
                            key=key, is_dev=is_dev, skill=str(skill), unlock_at=unlock_at,
                            difficulty=difficulty, xp_multiplier=xp_mult, ingredients=ingred,
                            outputs=outputs,
                            station=station, name=name, desc=desc, grants_xp=grants_xp
                        ))
                    else:
                        _maybe_record_item_meta(item_meta, k, v)
                        visit(v)
                else:
                    visit(v)
        elif isinstance(obj, list):
            for v in obj:
                visit(v)
    visit(static)

    # XP tables
    xp_tables_raw = _find_xp_tables(static)
    skill_level_meta = _extract_skill_leveling(static)
    norm_lookup = {_normalize_key(name): arr for name, arr in xp_tables_raw.items()}

    skills: Dict[str, SkillXPTable] = {}

    for skill_key, meta in skill_level_meta.items():
        level_table = meta.get("level_table")
        base_xp = int(meta.get("base_xp", 0) or 0)
        seq: Optional[List[int]] = None
        if level_table:
            candidates = [level_table, level_table.lower()]
            lower = level_table.lower()
            for prefix in ("leveling_", "levelingtable_", "leveling_table_"):
                if lower.startswith(prefix):
                    candidates.append(level_table[len(prefix):])
                    candidates.append(lower[len(prefix):])
                    break
            for cand in candidates:
                seq = xp_tables_raw.get(cand)
                if seq:
                    break
                seq = norm_lookup.get(_normalize_key(cand))
                if seq:
                    break
        if seq is None:
            seq = xp_tables_raw.get(skill_key)
        if seq is None:
            seq = norm_lookup.get(_normalize_key(skill_key))
        xp_values = [int(x) for x in seq] if seq else []
        skills[skill_key] = SkillXPTable(skill=skill_key, xp_to_level=xp_values, base_xp=base_xp)

    # Include any tables we haven't linked yet (development/testing)
    for name, arr in xp_tables_raw.items():
        if name in skills:
            continue
        skills[name] = SkillXPTable(skill=name, xp_to_level=[int(x) for x in arr])

    # Basic names for anything with localisation keys (items, activatables, etc.)
    item_names: Dict[str, str] = {}
    for k, v in loc_idx.items():
        if not isinstance(k, str):
            continue
        lower = k.lower()
        if lower.endswith("_localizationnamekey"):
            base = k[: -len("_LocalizationNameKey")]
            item_names[base] = v
        elif lower.endswith("_localizationdescriptionkey"):
            base = k[: -len("_LocalizationDescriptionKey")]
            item_names.setdefault(base, v)
        else:
            item_names.setdefault(k, v)

    return GameData(
        recipes=recipes,
        skills=skills,
        item_names=item_names,
        recipe_to_station=recipe_to_station,
        item_meta=item_meta,
        materials_config=materials_cfg,
        recipe_crafters=recipe_crafters_map,
        crafter_tiers=crafter_tiers,
    )

