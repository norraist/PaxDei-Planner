# planner/level_planner.py
from __future__ import annotations

import math, os, csv, json, time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Set, Iterable, Any, Callable

from .data_loader import load_game_data
from .xp_model import xp_expected, xp_success_avg, xp_failure_avg, success_chance  # expects (level, difficulty, unlock, xp_multiplier) OR adapt as needed
from .skills import get_skill_table

XP_EPS = 1e-6
PROGRESS_BAR_WIDTH = 24
PROGRESS_MIN_INTERVAL = 1.0

# ---- Utility safe accessors over unknown/variant schema ------------------------------------------

def _first_attr(obj: Any, names: Iterable[str], default=None):
    """Return the first present, non-None attribute by name from 'names' or default."""
    for n in names:
        if hasattr(obj, n):
            v = getattr(obj, n)
            if v is not None:
                return v
    return default

def _as_int(x, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default

def _as_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default

def _recipe_key(r) -> str:
    return _first_attr(r, ["key", "id", "recipe_key"], "unknown_recipe")

def _recipe_name(r) -> str:
    return _first_attr(r, ["name", "localized_name", "display_name"], _recipe_key(r))

def _recipe_skill(r) -> str:
    # common variants: "skill", "skill_required", "SkillRequired"
    return _first_attr(r, ["skill", "skill_required", "SkillRequired"], "")

def _recipe_unlock_at(r) -> int:
    # variants: unlock_at, unlock_level, UnlockLevel, UnlockAtSkillLevel
    return _as_int(_first_attr(r, ["unlock_at", "unlock_level", "UnlockLevel", "UnlockAtSkillLevel"], 0), 0)

def _recipe_difficulty(r) -> int:
    # variants: difficulty, skill_difficulty, SkillDifficulty
    return _as_int(_first_attr(r, ["difficulty", "skill_difficulty", "SkillDifficulty"], 0), 0)

def _recipe_xpmult(r) -> float:
    # variants: xp_multiplier, XPMultiplier, xpMult
    return _as_float(_first_attr(r, ["xp_multiplier", "XPMultiplier", "xpMult"], 1.0), 1.0)

def _recipe_station(r) -> Optional[str]:
    # variants: station, crafter, station_key, required_crafter, Station
    return _first_attr(r, ["station", "crafter", "station_key", "required_crafter", "Station"], None)

def _recipe_output_item(r) -> Optional[str]:
    # variants: output_item, output, product, produces, result_item, result
    return _first_attr(r, ["output_item", "output", "product", "produces", "result_item", "result"], None)

def _recipe_is_dev(r) -> bool:
    # variants: is_dev, IsDev
    v = _first_attr(r, ["is_dev", "IsDev"], False)
    return bool(v)

def _recipe_ingredients(r) -> List[Tuple[str, int]]:
    """
    Normalize ingredients to list[(item_key, qty)].
    Accepts:
      - r.ingredients as list[tuple] or list[dict {item, key, id, quantity, qty}]
      - r.inputs, r.materials as alternatives
      - dicts mapping item_key -> qty
    """
    raw = _first_attr(r, ["ingredients", "inputs", "materials"], []) or []
    if isinstance(raw, dict):
        raw_iter = list(raw.items())
    else:
        raw_iter = raw
    norm: List[Tuple[str, int]] = []
    for it in raw_iter:
        if isinstance(it, (list, tuple)) and len(it) >= 2:
            key = str(it[0])
            qty = _as_int(it[1], 0)
            if qty > 0:
                norm.append((key, qty))
        elif isinstance(it, dict):
            key = it.get("item") or it.get("key") or it.get("id") or it.get("Item") or it.get("Key")
            qty = it.get("quantity", it.get("qty", it.get("Quantity", 0)))
            key = str(key) if key is not None else None
            qty = _as_int(qty, 0)
            if key and qty > 0:
                norm.append((key, qty))
        # else: ignore unknown shapes
    return norm

def _recipe_outputs(r) -> Dict[str, int]:
    out = _first_attr(r, ["outputs", "deliverables", "ItemDeliverables"], {}) or {}
    if isinstance(out, dict):
        return {str(k): _as_int(v, 0) for k, v in out.items()}
    return {}

# Fallbacks if GameData doesn't expose helpers
def _recipes_for_skill(g, skill: str):
    if hasattr(g, "recipes_for_skill"):
        return g.recipes_for_skill(skill)
    # fallback: filter g.recipes by skill
    return [r for r in getattr(g, "recipes", []) if _recipe_skill(r) == skill]

def _xp_to_next_level(g, skill: str, level: int) -> int:
    if hasattr(g, "xp_to_next_level"):
        return g.xp_to_next_level(skill, level)
    # Fallback: consult GameData.skills table if present.
    skills = getattr(g, "skills", {})
    table = get_skill_table(skills, skill)
    if table:
        xp_seq = getattr(table, "xp_to_level", None) or []
        if level < len(xp_seq):
            return int(xp_seq[level])
        return 0
    # Last resort: assume a flat pacing so planner can proceed even without tables.
    return 1000

# --------------------------------------------------------------------------------------------------

class MissingCrafterError(RuntimeError):
    def __init__(self, crafter_key: str):
        super().__init__(crafter_key)
        self.crafter_key = crafter_key


@dataclass
class PlanStepOption:
    recipe_key: str
    recipe_name: str
    crafter: Optional[str]
    crafts: int
    xp_per_craft: float
    total_xp: float
    material_burden: float
    materials: List[Tuple[str, int]]
    materials_tree: str = ""
    craft_summary: List[Dict[str, Any]] = field(default_factory=list)
    prereq_gaps: List[Tuple[str, int, str, int]] = field(default_factory=list)
    xp_breakdown: List[Tuple[str, float, float, float, float, int]] = field(default_factory=list)

@dataclass
class PlanStep:
    skill: str
    from_level: int
    to_level: int
    options: List[PlanStepOption]
    note: str = ""

class LevelPlanner:
    """
    Multi-skill, dependency-aware leveling planner.
    - Prioritizes fewer/common materials via a rarity-weighted burden.
    - Prefers raw materials, penalizes relic/high-tier/high-item-level inputs when ranking options.
    - Inserts prerequisites (crafter unlocks / cross-skill levels) when needed.
    - Offers top-K recipe options per step.
    - Honors premium-account XP boosts (+50%) from the profile.
    """

    def __init__(self, static_path: str, loc_path: str, profile_path: str, xp_tables_dir: str, materials_config_path: Optional[str] = None):
        materials_config = materials_config_path or os.path.join(os.path.dirname(profile_path), "materials_config.json")
        self.g = load_game_data(static_path, loc_path, materials_config)
        self.item_meta = getattr(self.g, "item_meta", {})
        self.material_config = getattr(self.g, "materials_config", {})
        self.item_names = getattr(self.g, "item_names", {})
        self.recipe_crafters = getattr(self.g, "recipe_crafters", {})
        self.crafter_tiers = getattr(self.g, "crafter_tiers", {})
        self._last_missing_crafter: Optional[str] = None

        with open(profile_path, "r", encoding="utf-8") as f:
            self.profile = json.load(f)
        self.premium_account = bool(self.profile.get("premium_account", False))
        self.xp_boost = 1.5 if self.premium_account else 1.0
        self.avoid_relics = bool(self.profile.get("avoid_relics", False))
        self.max_cross_skill_gap = int(self.profile.get("max_cross_skill_gap", 5))

        # Current mutable world state
        self.cur_level: Dict[str, int] = {k: int(v["current_level"]) for k, v in self.profile["skills"].items()}
        self.cur_xp: Dict[str, int]    = {k: int(v["current_xp"]) for k, v in self.profile["skills"].items()}
        self.target_level: Dict[str, int] = {k: int(v["target_level"]) for k, v in self.profile["skills"].items()}
        self.owned_crafter: Dict[str, bool] = {k: bool(v["owned"]) for k, v in self.profile["crafters"].items()}

        # Build indices for rarity and feasibility
        self.producers: Dict[str, List[Any]] = {}   # item -> recipes that produce it
        self.usage_count: Dict[str, int] = {}       # item -> how many recipes consume it
        self._index_items()

        # Sanity: ensure xp accessor exists (or fallback already raises)
        _ = _xp_to_next_level(self.g, next(iter(self.cur_level.keys())), 1)

        self.recipe_xp_tables = self._load_recipe_xp_tables(xp_tables_dir)
        self.skill_crafters = self._map_skill_crafters()

        self._total_levels_needed = sum(
            max(0, self.target_level.get(sk, lvl) - lvl)
            for sk, lvl in self.cur_level.items()
        )
        self._progress_levels_done = 0
        self._last_progress_emit = 0.0
        self._progress_callback: Optional[Callable[[float, int, int], None]] = None

    # ---------- Indexing & rarity ----------

    def _load_recipe_xp_tables(self, xp_tables_dir: str) -> Dict[str, List[Tuple[int, float, float, float, float]]]:
        tables: Dict[str, List[Tuple[int, float, float, float, float]]] = {}
        base = Path(xp_tables_dir)
        if not base.exists():
            return tables
        for csv_path in base.rglob("*.csv"):
            try:
                with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                    reader = csv.reader(handle)
                    recipe_key: Optional[str] = None
                    data_started = False
                    rows: List[Tuple[int, float, float, float, float]] = []
                    for row in reader:
                        if not row:
                            continue
                        head = row[0].strip()
                        if head == "Recipe Key" and len(row) > 1:
                            recipe_key = row[1].strip()
                        elif head == "Skill Level":
                            data_started = True
                        elif data_started:
                            level_token = head
                            if not level_token:
                                continue
                            digits = "".join(ch for ch in level_token if ch.isdigit())
                            if not digits:
                                continue
                            level_val = int(digits)
                            chance_str = row[1].strip().rstrip("%") if len(row) > 1 else "0"
                            try:
                                chance = float(chance_str) / 100.0
                            except ValueError:
                                chance = 0.0

                            def parse(idx: int) -> float:
                                if len(row) <= idx:
                                    return float("nan")
                                token = row[idx].strip()
                                if not token:
                                    return float("nan")
                                try:
                                    return float(token)
                                except ValueError:
                                    return float("nan")

                            success_avg = parse(3)
                            failure_avg = parse(5)
                            expected_avg = parse(6)
                            rows.append((level_val, chance, success_avg, failure_avg, expected_avg))
                    if recipe_key and rows:
                        rows.sort(key=lambda r: r[0])
                        tables[recipe_key] = rows
            except Exception:
                continue
        return tables

    def _index_items(self) -> None:
        """Build producer and usage indices from self.g.recipes."""
        for r in getattr(self.g, "recipes", []):
            if _recipe_is_dev(r):
                continue

            out_item = _recipe_output_item(r)
            if out_item:
                self.producers.setdefault(out_item, []).append(r)
            for out_key in _recipe_outputs(r).keys():
                self.producers.setdefault(out_key, []).append(r)
            for out_key in _recipe_outputs(r).keys():
                self.producers.setdefault(out_key, []).append(r)

            for ing_key, qty in _recipe_ingredients(r):
                self.usage_count[ing_key] = self.usage_count.get(ing_key, 0) + 1

    def _map_skill_crafters(self) -> Dict[str, List[str]]:
        mapping: Dict[str, Set[str]] = {}
        for r in getattr(self.g, "recipes", []):
            if _recipe_is_dev(r):
                continue
            skill = _recipe_skill(r)
            if not skill:
                continue
            recipe_key = _recipe_key(r)
            for ck in self.recipe_crafters.get(recipe_key, []):
                mapping.setdefault(skill, set()).add(ck)
        ordered: Dict[str, List[str]] = {}
        for sk, cset in mapping.items():
            ordered[sk] = sorted(cset, key=lambda ck: self.crafter_tiers.get(ck, 0))
        return ordered

    def _is_leaf_item(self, item_key: str) -> bool:
        """True if no recipe in current dataset produces this item."""
        return item_key not in self.producers

    def _is_base_material(self, item_key: str) -> bool:
        meta = self.item_meta.get(item_key)
        if meta:
            if meta.is_raw or meta.is_relic:
                return True
        key_lower = item_key.lower()
        if "_raw_" in key_lower or "_relic_" in key_lower or key_lower.startswith("item_raw_"):
            return True
        return self._is_leaf_item(item_key)

    def _rarity_score(self, item_key: str, depth: int = 0) -> float:
        """
        Heuristic rarity: fewer usages -> rarer (higher burden).
        Leaf items count as common (bias down). Crafted chains get a penalty.
        """
        use = self.usage_count.get(item_key, 0)
        usage_weight = 1.0 / (1.0 + use)     # more usage -> more common -> smaller number
        rarity = max(0.2, usage_weight)

        if self._is_leaf_item(item_key):
            rarity *= 0.5                    # gatherable/common bias

        meta = self.item_meta.get(item_key)
        cat_lower: List[str] = []
        if meta:
            if meta.tier and meta.tier > 0:
                rarity *= 1.0 + max(0, meta.tier - 1) * 0.25
            if meta.item_level and meta.item_level > 0:
                rarity *= 1.0 + (meta.item_level / 60.0)
            cat_lower = [c.lower() for c in meta.categories]

        key_lower = item_key.lower()
        if "_raw_material" in key_lower or any("raw" in c for c in cat_lower):
            rarity *= 0.6
        if "_relic_" in key_lower or any("relic" in c for c in cat_lower):
            rarity *= 1.8

        rarity *= (1.0 + min(depth, 2) * 0.5)  # depth penalty up to x2.0
        return rarity

    def _choose_producer(self, item_key: str):
        candidates = self.producers.get(item_key, [])
        if not candidates:
            return None
        candidates = [r for r in candidates if not _recipe_is_dev(r)]
        if not candidates:
            return None
        candidates.sort(key=lambda r: (_recipe_difficulty(r), _recipe_unlock_at(r)))
        for r in candidates:
            missing = self._missing_crafters_for_recipe(r)
            if missing:
                continue
            skill = _recipe_skill(r)
            skill_level = self.cur_level.get(skill, 0)
            if self._recipe_unlocked(r, skill_level):
                return r
        missing_first = self._missing_crafters_for_recipe(candidates[0])
        if missing_first:
            raise MissingCrafterError(missing_first[0])
        return candidates[0]

    def _expand_recipe_full(self, recipe, crafts: int, target_skill: str) -> Tuple[List[Tuple[str, int]], List[str], List[Tuple[Any, int, str]]]:
        base_totals: Dict[str, int] = {}
        craft_steps: List[Tuple[Any, int, str]] = []
        lines: List[str] = [f"{_recipe_name(recipe)} x{crafts} (final)"]

        stock: Dict[str, int] = {}

        def helper(item_key: str, qty: int, depth: int, trail: Set[str]) -> None:
            if qty <= 0:
                return
            if item_key in trail or depth > 12:
                lines.append(self._tree_line(depth, self._item_label(item_key), qty, note="(cycle)"))
                base_totals[item_key] = base_totals.get(item_key, 0) + qty
                return

            available = stock.get(item_key, 0)
            if available:
                if available >= qty:
                    stock[item_key] = available - qty
                    return
                qty -= available
                stock[item_key] = 0

            if self._is_base_material(item_key):
                base_totals[item_key] = base_totals.get(item_key, 0) + qty
                lines.append(self._tree_line(depth, f"Gather {self._item_label(item_key)}", qty))
                return

            prods = self.producers.get(item_key, [])
            if not prods:
                base_totals[item_key] = base_totals.get(item_key, 0) + qty
                lines.append(self._tree_line(depth, f"Gather {self._item_label(item_key)}", qty))
                return

            producer = self._choose_producer(item_key)
            if not producer:
                base_totals[item_key] = base_totals.get(item_key, 0) + qty
                lines.append(self._tree_line(depth, f"Gather {self._item_label(item_key)}", qty))
                return

            outputs = _recipe_outputs(producer)
            out_qty = outputs.get(item_key)
            if out_qty is None and outputs:
                out_qty = next(iter(outputs.values()))
            per_craft = max(1, out_qty or 1)
            crafts_needed = math.ceil(qty / per_craft)
            actual_yield = crafts_needed * per_craft
            extra = max(0, actual_yield - qty)

            prod_skill = _recipe_skill(producer)
            station_label = self._recipe_station_label(producer)
            new_trail = set(trail)
            new_trail.add(item_key)
            for sub_key, sub_qty in _recipe_ingredients(producer):
                helper(sub_key, sub_qty * crafts_needed, depth + 1, new_trail)

            craft_steps.append((producer, crafts_needed, prod_skill))
            action = "Craft" if prod_skill == target_skill else f"External craft ({prod_skill or 'other'})"
            if station_label:
                action = f"{action} via {station_label}"
            if extra > 0:
                note = f"-> {self._item_label(item_key)} x{actual_yield} ({qty} req/{extra} extra)"
            else:
                note = f"-> {self._item_label(item_key)} x{actual_yield} ({qty} req/0 extra)"
            lines.append(self._tree_line(depth, f"{action} {_recipe_name(producer)}", crafts_needed, note=note))
            if extra > 0:
                stock[item_key] = stock.get(item_key, 0) + extra

        for item_key, qty in _recipe_ingredients(recipe):
            helper(item_key, qty * crafts, depth=1, trail=set())

        craft_steps.append((recipe, crafts, target_skill))
        lines.append(self._tree_line(0, f"Craft {_recipe_name(recipe)}", crafts, note="(final)"))

        return sorted(base_totals.items(), key=lambda kv: kv[0]), lines, craft_steps

    def _dependency_gaps(self, recipe, crafts: int, target_skill: str) -> List[Tuple[str, int, str, int]]:
        gaps: List[Tuple[str, int, str, int]] = []

        def helper(item_key: str, trail: Set[str]) -> None:
            if item_key in trail:
                return
            if self._is_base_material(item_key):
                return
            producer = self._choose_producer(item_key)
            if not producer:
                return
            skill = _recipe_skill(producer)
            need_level = max(_recipe_unlock_at(producer), _recipe_difficulty(producer))
            cur = self.cur_level.get(skill, 1)
            delta = need_level - cur
            if skill != target_skill and delta > 0:
                gaps.append((skill, need_level, item_key, delta))
                return
            if skill == target_skill:
                new_trail = set(trail)
                new_trail.add(item_key)
                for sub_key, _ in _recipe_ingredients(producer):
                    helper(sub_key, new_trail)

        for item_key, _ in _recipe_ingredients(recipe):
            helper(item_key, set())
        return gaps

    def _tree_line(self, depth: int, label: str, qty: int, note: str = "") -> str:
        indent = "  " * depth
        line = f"{indent}- {label} x{qty}"
        if note:
            line += f" {note}"
        return line

    def _xp_from_crafts(self, craft_steps: List[Tuple[Any, int, str]], level: int, skill: str) -> float:
        total = 0.0
        for rec, count, rec_skill in craft_steps:
            if rec_skill != skill:
                continue
            if not getattr(rec, "grants_xp", True):
                continue
            _, _, _, expected = self._recipe_xp_stats(rec, level, rec_skill)
            total += count * expected
        return total

    def _xp_breakdown(self, craft_steps: List[Tuple[Any, int, str]], level: int, skill: str) -> List[Tuple[str, float, float, float, float, int]]:
        entries: List[Tuple[str, float, float, float, float, int]] = []
        for rec, count, rec_skill in craft_steps:
            if rec_skill != skill:
                continue
            if not getattr(rec, "grants_xp", True):
                continue
            chance, success, failure, avg = self._recipe_xp_stats(rec, level, rec_skill)
            entries.append((_recipe_name(rec), chance, success, failure, avg, count))
        return entries

    def _recipe_xp_stats(self, recipe, level: int, skill: str) -> Tuple[float, float, float, float]:
        key = _recipe_key(recipe)
        table = self.recipe_xp_tables.get(key)
        if table:
            row = table[0]
            for entry in table:
                if level >= entry[0]:
                    row = entry
                else:
                    break
            chance = row[1]
            success = row[2] * self.xp_boost if not math.isnan(row[2]) else 0.0
            failure = row[3] * self.xp_boost if not math.isnan(row[3]) else float("nan")
            expected = row[4] * self.xp_boost if not math.isnan(row[4]) else success
            return chance, success, failure, expected

        diff = _recipe_difficulty(recipe)
        unlock = _recipe_unlock_at(recipe)
        xpm = _recipe_xpmult(recipe)
        chance = success_chance(level, diff)
        success = xp_success_avg(level, diff, xpm, skill=skill) * self.xp_boost
        failure = xp_failure_avg(level, diff, unlock, xpm, skill=skill)
        if isinstance(failure, float):
            failure = failure * self.xp_boost
        else:
            failure = float("nan")
        expected = xp_expected(level, diff, unlock, xpm, skill=skill) * self.xp_boost
        return chance, success, failure, expected

    def _summarize_crafts(self, craft_steps: List[Tuple[Any, int, str]]) -> List[Dict[str, Any]]:
        summary: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for rec, count, rec_skill in craft_steps:
            name = _recipe_name(rec)
            skill_name = rec_skill or ""
            station = self._recipe_station_label(rec)
            key = (_recipe_key(rec), skill_name, station)
            entry = summary.get(key)
            if not entry:
                entry = {
                    "name": name,
                    "skill": skill_name,
                    "station": station,
                    "count": 0,
                    "outputs": {}
                }
                summary[key] = entry
            entry["count"] += count
            for out_key, out_qty in _recipe_outputs(rec).items():
                entry["outputs"][out_key] = entry["outputs"].get(out_key, 0) + out_qty * count
        return list(summary.values())

    def _item_label(self, item_key: str) -> str:
        if item_key in self.item_names:
            return self.item_names[item_key]
        alt = f"{item_key}_LocalizationNameKey"
        return self.item_names.get(alt, item_key)

    def _station_label(self, station_key: Optional[str]) -> str:
        if not station_key:
            return ""
        if station_key in self.item_names:
            return self.item_names[station_key]
        alt = f"{station_key}_LocalizationNameKey"
        if alt in self.item_names:
            return self.item_names[alt]
        # fallback: humanize the key
        return station_key.replace("_", " ").title()

    def _recipe_station_label(self, recipe) -> str:
        candidates: List[str] = []
        station_key = _recipe_station(recipe)
        if station_key:
            candidates.append(station_key)
        recipe_key = _recipe_key(recipe)
        candidates.extend(self.recipe_crafters.get(recipe_key, []))
        if candidates:
            seen: List[str] = []
            for ck in candidates:
                if ck not in seen:
                    seen.append(ck)
            def sort_key(ck: str):
                owned_rank = 0 if self.owned_crafter.get(ck, False) else 1
                tier_rank = self.crafter_tiers.get(ck, 0)
                return (owned_rank, tier_rank, ck)
            chosen = min(seen, key=sort_key)
            label = self._station_label(chosen)
            if label:
                return label
        if not getattr(recipe, "grants_xp", True):
            return "Crafter (no XP)"
        return ""

    def _contains_relic_materials(self, materials: List[Tuple[str, int]]) -> bool:
        for item, _ in materials:
            meta = self.item_meta.get(item)
            if meta and meta.is_relic:
                return True
            if "relic" in item.lower():
                return True
        return False

    def _material_enabled(self, item_key: str) -> bool:
        entry = self.material_config.get(item_key)
        if entry is None:
            return True
        return bool(entry.get("enabled", True))

    def _contains_disabled_materials(self, materials: List[Tuple[str, int]]) -> bool:
        for item, _ in materials:
            if not self._material_enabled(item):
                return True
        return False
    # ---------- Feasibility & material burden ----------

    def _can_use_crafter(self, crafter_key: Optional[str]) -> bool:
        if not crafter_key:
            return True
        return bool(self.owned_crafter.get(crafter_key, False))

    def _recipe_crafter_keys(self, recipe) -> List[str]:
        keys: List[str] = []
        station = _recipe_station(recipe)
        if isinstance(station, str) and station.startswith("crafter_"):
            keys.append(station)
        keys.extend(self.recipe_crafters.get(_recipe_key(recipe), []))
        seen: List[str] = []
        for ck in keys:
            if ck and ck not in seen:
                seen.append(ck)
        return seen

    def _missing_crafters_for_recipe(self, recipe) -> List[str]:
        keys = self._recipe_crafter_keys(recipe)
        ignore: Set[str] = set()
        out_item = _recipe_output_item(recipe)
        if isinstance(out_item, str) and out_item.startswith("crafter_"):
            ignore.add(out_item)
        key = _recipe_key(recipe)
        if key.startswith("recipe_item_unlock_crafter_"):
            suffix = key[len("recipe_item_unlock_"):]
            ignore.add(f"crafter_{suffix}")
        owned = any(self.owned_crafter.get(ck, False) for ck in keys if ck not in ignore)
        if owned:
            return []
        result = []
        for ck in keys:
            if ck in ignore:
                continue
            if not self.owned_crafter.get(ck, False):
                result.append(ck)
        return result

    def _has_crafter_for_recipe(self, recipe) -> bool:
        keys = self._recipe_crafter_keys(recipe)
        if not keys:
            return True
        return any(self.owned_crafter.get(ck, False) for ck in keys)

    def _recipe_unlocked(self, recipe, skill_level: int) -> bool:
        unlock = _recipe_unlock_at(recipe)
        return skill_level >= unlock

    def _material_burden(self, recipe, crafts: int, depth: int = 0) -> Tuple[float, List[Tuple[str, int]]]:
        """
        Rarity-weighted material burden for 'crafts' copies of 'recipe'.
        Returns (burden_score, flat_requirements) for reporting.
        """
        reqs: Dict[str, int] = {}
        score = 0.0
        for item_key, qty in _recipe_ingredients(recipe):
            need = qty * crafts
            reqs[item_key] = reqs.get(item_key, 0) + need
            score += need * self._rarity_score(item_key, depth)
        flat = sorted(reqs.items(), key=lambda x: x[0])
        return score, flat

    def _feasible_now(self, recipe, state_levels: Dict[str, int]) -> bool:
        """
        A recipe is feasible if:
          - crafter is owned
          - unlock level is met in its skill
        """
        if not self._has_crafter_for_recipe(recipe):
            return False
        if not self._recipe_unlocked(recipe, state_levels.get(_recipe_skill(recipe), 0)):
            return False
        return True

    # ---------- Choosing best options for a single level ----------

    def _best_options_for_level(self, skill: str, level: int, top_k: int = 3, ignore_gap: bool = False) -> List[PlanStepOption]:
        """
        Among feasible recipes for 'skill' at 'level', return top-K options by
        score = xp_expected / (1 + material_burden_per_craft).
        """
        debug = False
        self._last_missing_crafter = None
        missing_seen: List[str] = []
        candidates = []
        for r in _recipes_for_skill(self.g, skill):
            if _recipe_is_dev(r):
                continue
            if hasattr(r, "grants_xp") and not r.grants_xp:
                continue
            if not self._feasible_now(r, self.cur_level):
                continue

            burden_one, _ = self._material_burden(r, crafts=1)
            try:
                materials_unit, _, crafts_unit = self._expand_recipe_full(r, 1, skill)
            except MissingCrafterError as err:
                missing_seen.append(err.crafter_key)
                if not self._last_missing_crafter:
                    self._last_missing_crafter = err.crafter_key
                continue
            if self.avoid_relics and self._contains_relic_materials(materials_unit):
                continue
            xpc_unit = self._xp_from_crafts(crafts_unit, level, skill)
            if xpc_unit <= 0:
                continue

            score = xpc_unit / (1.0 + burden_one)
            candidates.append((score, r, xpc_unit, burden_one))

        candidates.sort(key=lambda t: t[0], reverse=True)
        top: List[PlanStepOption] = []
        for score, r, xpc_unit, burden_one in candidates:
            # crafts to reach next level from current XP
            xp_needed = _xp_to_next_level(self.g, skill, level) - self.cur_xp.get(skill, 0)
            crafts = max(1, math.ceil(xp_needed / max(1e-9, xpc_unit)))
            try:
                materials_full, tree_lines, crafts_full = self._expand_recipe_full(r, crafts, skill)
            except MissingCrafterError as err:
                missing_seen.append(err.crafter_key)
                if not self._last_missing_crafter:
                    self._last_missing_crafter = err.crafter_key
                continue
            if self._contains_disabled_materials(materials_full):
                continue
            total_xp = self._xp_from_crafts(crafts_full, level, skill)
            prereq_gaps = self._dependency_gaps(r, crafts, skill)
            if (not ignore_gap) and self.max_cross_skill_gap >= 0 and any(delta > self.max_cross_skill_gap for *_, delta in prereq_gaps):
                continue
            craft_summary = self._summarize_crafts(crafts_full)
            xp_breakdown = self._xp_breakdown(crafts_full, level, skill)
            top.append(PlanStepOption(
                recipe_key=_recipe_key(r),
                recipe_name=_recipe_name(r),
                crafter=_recipe_station(r),
                crafts=crafts,
                xp_per_craft=xpc_unit,
                total_xp=total_xp,
                material_burden=burden_one * crafts,
                materials=materials_full,
                materials_tree="\n".join(tree_lines),
                craft_summary=craft_summary,
                prereq_gaps=prereq_gaps,
                xp_breakdown=xp_breakdown,
            ))
            if len(top) >= top_k:
                break
        if not top and missing_seen and not self._last_missing_crafter:
            self._last_missing_crafter = missing_seen[0]
        return top

    def _build_unlock_option(self, recipe, crafts: int = 1) -> Optional[PlanStepOption]:
        skill = _recipe_skill(recipe)
        level = self.cur_level.get(skill, 1)
        burden_one, _ = self._material_burden(recipe, crafts)
        materials_full, tree_lines, crafts_full = self._expand_recipe_full(recipe, crafts, skill)
        if self._contains_disabled_materials(materials_full):
            return None
        total_xp = self._xp_from_crafts(crafts_full, level, skill)
        craft_summary = self._summarize_crafts(crafts_full)
        prereq_gaps = self._dependency_gaps(recipe, crafts, skill)
        xp_breakdown = self._xp_breakdown(crafts_full, level, skill)
        return PlanStepOption(
            recipe_key=_recipe_key(recipe),
            recipe_name=_recipe_name(recipe),
            crafter=_recipe_station(recipe),
            crafts=crafts,
            xp_per_craft=total_xp / max(1, crafts),
            total_xp=total_xp,
            material_burden=burden_one * crafts,
            materials=materials_full,
            materials_tree="\n".join(tree_lines),
            craft_summary=craft_summary,
            prereq_gaps=prereq_gaps,
            xp_breakdown=xp_breakdown,
        )

    # ---------- Prereq resolution ----------

    def _missing_prereq(self, skill: str, level: int, required_crafter: Optional[str] = None) -> Optional[PlanStep]:
        """
        If no feasible recipe exists for (skill, level), return a prerequisite PlanStep to unlock options:
        - Prefer building/unlocking a missing crafter if one is close.
        - Else, level another skill minimally to make an intermediate ingredient.
        """
        # 1) Try crafter unlocks for the skill first
        for r in _recipes_for_skill(self.g, skill):
            if _recipe_is_dev(r):
                continue
            if self._recipe_unlocked(r, level):
                missing_crafters = self._missing_crafters_for_recipe(r)
                if missing_crafters:
                    for crafter_key in missing_crafters:
                        if required_crafter and crafter_key != required_crafter:
                            continue
                        step = self._plan_crafter_unlock_step(crafter_key, skill, level)
                        if step:
                            return step

        # 2) Cross-skill minimal leveling for an intermediate
        best: Optional[Tuple[PlanStep, int]] = None
        for r in _recipes_for_skill(self.g, skill):
            if _recipe_is_dev(r) or not self._recipe_unlocked(r, level):
                continue
            for item_key, _qty in _recipe_ingredients(r):
                prods = self.producers.get(item_key, [])
                for pr in prods:
                    need_skill = _recipe_skill(pr)
                    need_level = max(_recipe_unlock_at(pr), _recipe_difficulty(pr) - 1)
                    cur = self.cur_level.get(need_skill, 1)
                    if need_level > cur:
                        cost = need_level - cur
                        step = PlanStep(
                            skill=need_skill,
                            from_level=cur,
                            to_level=cur + 1,
                            options=self._best_options_for_level(need_skill, cur),
                            note=f"Prereq: level {need_skill} towards crafting {item_key}"
                        )
                        if step.options and (best is None or cost < best[1]):
                            best = (step, cost)
        if best:
            return best[0]

        return None

    def _crafter_unlock_recipes(self, crafter_key: str) -> List[Any]:
        unlockers = []
        for ur in getattr(self.g, "recipes", []):
            if _recipe_is_dev(ur):
                continue
            if _recipe_output_item(ur) == crafter_key:
                unlockers.append(ur)
                continue
            key = _recipe_key(ur)
            if key.startswith("recipe_item_unlock_crafter_") and crafter_key in key:
                unlockers.append(ur)
        unlockers.sort(key=lambda rec: _recipe_unlock_at(rec))
        return unlockers

    def _plan_crafter_unlock_step(
        self,
        crafter_key: str,
        target_skill: str,
        current_level: int,
        visited: Optional[Set[str]] = None,
    ) -> Optional[PlanStep]:
        if visited is None:
            visited = set()
        if crafter_key in visited:
            return None
        visited.add(crafter_key)
        unlockers = self._crafter_unlock_recipes(crafter_key)
        if not unlockers:
            return None
        label = self._station_label(crafter_key) or crafter_key
        note = f"Unlock {label}"
        for ur in unlockers:
            req_skill = _recipe_skill(ur) or target_skill
            req_unlock = _recipe_unlock_at(ur)
            current = self.cur_level.get(req_skill, 1)
            if req_skill == target_skill and current_level < req_unlock:
                opts = self._best_options_for_level(req_skill, current_level, ignore_gap=True)
                if opts:
                    return PlanStep(
                        skill=req_skill,
                        from_level=current_level,
                        to_level=req_unlock,
                        options=opts,
                        note=note,
                    )
            if req_unlock and current < req_unlock:
                opts = self._best_options_for_level(req_skill, current, ignore_gap=True)
                if opts:
                    return PlanStep(
                        skill=req_skill,
                        from_level=current,
                        to_level=req_unlock,
                        options=opts,
                        note=note,
                    )
            try:
                option = self._build_unlock_option(ur)
            except MissingCrafterError as err:
                step = self._plan_crafter_unlock_step(err.crafter_key, req_skill, self.cur_level.get(req_skill, 1), visited)
                if step:
                    return step
                continue
            if option:
                self.owned_crafter[crafter_key] = True
                return PlanStep(
                    skill=req_skill,
                    from_level=current,
                    to_level=current,
                    options=[option],
                    note=note,
                )
        return None

    def _plan_next_crafter(self, skill: str, level: int) -> Optional[PlanStep]:
        crafters = self.skill_crafters.get(skill, [])
        if not crafters:
            return None
        owned_tier = max(
            (self.crafter_tiers.get(ck, 0) for ck in crafters if self.owned_crafter.get(ck)),
            default=0,
        )
        for ck in crafters:
            if self.owned_crafter.get(ck):
                continue
            tier = self.crafter_tiers.get(ck, 0)
            if tier <= owned_tier:
                continue
            step = self._plan_crafter_unlock_step(ck, skill, level)
            if step:
                return step
        return None

    # ---------- Public API ----------

    def plan(
        self,
        top_k: int = 3,
        max_steps: int = 500,
        progress_cb: Optional[Callable[[float, int, int], None]] = None,
    ) -> List[PlanStep]:
        """
        Build a global, step-by-step plan to reach all target levels.
        Returns a list of PlanSteps; each has 'options' (top-K recipes).
        """
        self._progress_callback = progress_cb
        plan: List[PlanStep] = []
        steps = 0

        skill_queue = self._seed_skill_queue()
        stagnant_cycles = 0
        self._emit_progress(force=True)

        while steps < max_steps and skill_queue:
            if self._targets_complete():
                break
            skill = skill_queue.pop(0)
            if self.cur_level.get(skill, 1) >= self.target_level.get(skill, 1):
                continue
            lvl = self.cur_level[skill]

            options = self._best_options_for_level(skill, lvl, top_k=top_k)
            if options:
                gap_step = self._resolve_cross_skill_gap(options[0], skill)
                if gap_step:
                    prev_gap_level = self.cur_level.get(gap_step.skill, 1)
                    plan.append(gap_step)
                    if gap_step.options:
                        new_gap_level = max(prev_gap_level, gap_step.to_level)
                        self.cur_level[gap_step.skill] = new_gap_level
                        self.cur_xp[gap_step.skill] = 0
                        self._record_progress(gap_step.skill, prev_gap_level, new_gap_level)
                    steps += 1
                    skill_queue.append(skill)  # revisit after handling prereq
                    continue

                total_xp = float(options[0].total_xp) if options and options[0].total_xp is not None else 0.0
                xp_needed = max(0.0, _xp_to_next_level(self.g, skill, lvl) - self.cur_xp.get(skill, 0))
                overflow = max(0.0, total_xp - xp_needed)
                target_goal = self.target_level.get(skill, lvl + 1)
                goal_level = max(target_goal, lvl + 1)
                new_level = min(goal_level, lvl + 1)
                self.cur_level[skill] = new_level
                self.cur_xp[skill] = 0

                while overflow > XP_EPS and self.cur_level[skill] < goal_level:
                    need_next = _xp_to_next_level(self.g, skill, self.cur_level[skill])
                    if need_next <= 0:
                        break
                    if overflow + XP_EPS >= need_next:
                        overflow -= need_next
                        self.cur_level[skill] += 1
                    else:
                        self.cur_xp[skill] = int(round(overflow))
                        overflow = 0.0
                if self.cur_level[skill] >= goal_level:
                    self.cur_xp[skill] = 0

                self._record_progress(skill, lvl, self.cur_level[skill])

                plan.append(PlanStep(skill=skill, from_level=lvl, to_level=self.cur_level[skill], options=options))
                steps += 1
                stagnant_cycles = 0
                skill_queue.append(skill)
                continue

            # No feasible options: add a prerequisite step
            prereq = self._missing_prereq(skill, lvl, required_crafter=self._last_missing_crafter)
            if prereq:
                plan.append(prereq)
                if prereq.options:
                    prev_prereq_level = self.cur_level.get(prereq.skill, 1)
                    current_prereq_level = self.cur_level.get(prereq.skill, prev_prereq_level)
                    new_prereq_level = max(current_prereq_level, prereq.to_level)
                    self.cur_level[prereq.skill] = new_prereq_level
                    self.cur_xp[prereq.skill] = 0
                    self._record_progress(prereq.skill, prev_prereq_level, new_prereq_level)
                steps += 1
                skill_queue.append(skill)
                stagnant_cycles = 0
                continue

            crafter_step = self._plan_next_crafter(skill, lvl)
            if crafter_step:
                plan.append(crafter_step)
                steps += 1
                stagnant_cycles = 0
                skill_queue.append(skill)
                continue

            stagnant_cycles += 1
            if stagnant_cycles >= len(self.target_level):
                plan.append(PlanStep(skill=skill, from_level=lvl, to_level=lvl, options=[], note="Planner stalled; remaining skills may require manual intervention."))
                break
            skill_queue.append(skill)

        if steps >= max_steps and self._total_levels_needed > 0 and self._progress_levels_done < self._total_levels_needed:
            print(
                f"[planner] Warning: reached max steps ({max_steps}) before finishing targets "
                f"({self._progress_levels_done}/{self._total_levels_needed} levels).",
                flush=True,
            )
        self._emit_progress(force=True)
        self._progress_callback = None

        return plan

    def _seed_skill_queue(self) -> List[str]:
        # Start with all skills sorted by deficit, but keep order cycling
        return sorted(self.target_level.keys(), key=lambda sk: (self.target_level[sk] - self.cur_level.get(sk, 1)), reverse=True)

    def _targets_complete(self) -> bool:
        for skill, target in self.target_level.items():
            if self.cur_level.get(skill, 1) < target:
                return False
        return True

    def _resolve_cross_skill_gap(self, option: PlanStepOption, target_skill: str) -> Optional[PlanStep]:
        if not option.prereq_gaps:
            return None
        # choose gap with largest deficit
        best = None
        for skill, need, item, delta in option.prereq_gaps:
            if delta <= 0:
                continue
            if not best or delta > best[3]:
                best = (skill, need, item, delta)
        if not best:
            return None
        gap_skill, need_level, item_key, delta = best
        cur = self.cur_level.get(gap_skill, 1)
        to_level = min(need_level, cur + 1)
        options = self._best_options_for_level(gap_skill, cur, top_k=3)
        note = f"Prerequisite: advance {gap_skill} for crafting {self._item_label(item_key)} used in {target_skill}"
        return PlanStep(
            skill=gap_skill,
            from_level=cur,
            to_level=to_level,
            options=options,
            note=note
        )

    def write_csv(self, plan: List[PlanStep], path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["skill","from_level","to_level","note","option_rank","recipe_key","recipe_name","crafter","crafts","xp_per_craft","total_xp","material_burden","materials","materials_tree"])
            for step in plan:
                if not step.options:
                    w.writerow([step.skill, step.from_level, step.to_level, step.note, "", "", "", "", "", "", "", "", "", ""])
                    continue
                for i, opt in enumerate(step.options, start=1):
                    mats = [f"{self._item_label(k)}-{q}" for k, q in opt.materials]
                    mats_str = "; ".join(mats)
                    w.writerow([
                        step.skill, step.from_level, step.to_level, step.note,
                        i, opt.recipe_key, opt.recipe_name, opt.crafter or "",
                        opt.crafts, f"{opt.xp_per_craft:.1f}", f"{opt.total_xp:.1f}",
                        f"{opt.material_burden:.2f}", mats_str, opt.materials_tree
                    ])

    def write_materials_csv(self, plan: List[PlanStep], path: str) -> None:
        """
        Aggregate a simple shopping list by assuming the first option of each step
        is the one the player will execute.
        """
        totals: Dict[str, int] = {}
        for step in plan:
            if not step.options:
                continue
            for item, qty in step.options[0].materials:
                totals[item] = totals.get(item, 0) + qty

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["item_key","item_name","qty"])
            for item, qty in sorted(totals.items()):
                w.writerow([item, self._item_label(item), qty])

    def write_steps_text(self, plan: List[PlanStep], path: str) -> None:
        lines: List[str] = []
        for idx, step in enumerate(plan, start=1):
            lines.append(f"Step {idx}: {step.skill} {step.from_level} -> {step.to_level}")
            if step.note:
                lines.append(f"  Note: {step.note}")
            if not step.options:
                lines.append("  No feasible options. Review crafters or targets.")
                lines.append("")
                continue
            opt = step.options[0]
            lines.append(f"  Recommended: {opt.recipe_name} x{opt.crafts}")
            lines.append(f"  Estimated XP gain: {opt.total_xp:.1f}")
            if opt.xp_breakdown:
                lines.append("  XP breakdown:")
                for name, chance, xs, xf, avg, count in opt.xp_breakdown:
                    failure_str = "-" if (not isinstance(xf, float) or math.isnan(xf)) else f"{xf:.1f}"
                    lines.append(
                        f"    - {name} x{count}: {chance*100:5.1f}% success chance, success {xs:.1f}, failure {failure_str}, expected {avg:.1f}"
                    )
            lines.append("  Gather:")
            if opt.materials:
                for item, qty in opt.materials:
                    lines.append(f"    - {self._item_label(item)} x{qty}")
            else:
                lines.append("    (none)")
            lines.append("  Craft steps:")
            for entry in opt.craft_summary:
                name = entry["name"]
                count = entry["count"]
                skill_name = entry["skill"]
                station_label = entry["station"]
                outputs = entry.get("outputs", {})
                details: List[str] = []
                if skill_name:
                    details.append(skill_name)
                if station_label:
                    details.append(f"via {station_label}")
                suffix = f" ({', '.join(details)})" if details else ""
                if outputs:
                    yields = ", ".join(f"{self._item_label(o)} x{qty}" for o, qty in outputs.items())
                    lines.append(f"    - Craft {name} x{count}{suffix} -> {yields}")
                else:
                    lines.append(f"    - Craft {name} x{count}{suffix}")
            lines.append("  Dependency tree:")
            for tree_line in opt.materials_tree.splitlines():
                lines.append(f"    {tree_line}")
            lines.append("")

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines).strip() + "\n")

    def _record_progress(self, skill: str, prev_level: int, new_level: int) -> None:
        if self._total_levels_needed <= 0:
            return
        target = self.target_level.get(skill)
        if target is None or prev_level >= target:
            return
        before = min(target, prev_level)
        after = min(target, new_level)
        gained = max(0, after - before)
        if gained <= 0:
            return
        if self._progress_levels_done >= self._total_levels_needed:
            return
        prev = self._progress_levels_done
        self._progress_levels_done = min(
            self._total_levels_needed, self._progress_levels_done + gained
        )
        if self._progress_levels_done != prev:
            self._emit_progress()

    def _emit_progress(self, force: bool = False) -> None:
        if self._total_levels_needed <= 0:
            return
        now = time.time()
        if not force and (now - self._last_progress_emit) < PROGRESS_MIN_INTERVAL:
            return
        pct = min(1.0, self._progress_levels_done / self._total_levels_needed)
        filled = min(PROGRESS_BAR_WIDTH, int(round(pct * PROGRESS_BAR_WIDTH)))
        bar = "#" * filled + "-" * (PROGRESS_BAR_WIDTH - filled)
        done = self._progress_levels_done
        total = self._total_levels_needed
        if self._progress_callback:
            self._progress_callback(pct, done, total)
        else:
            print(
                f"[planner] [{bar}] {pct*100:5.1f}% ({done}/{total} levels)",
                flush=True,
            )
        self._last_progress_emit = now

# ----------------------------- CLI -------------------------------------------

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Generate a multi-skill, dependency-aware leveling plan with top-K recipe options.")
    ap.add_argument("--static", required=True, help="Path to StaticDataBundle.json")
    ap.add_argument("--loc", required=False, help="Path to localisation_en.json (if omitted, inferred from --static folder)")
    ap.add_argument("--profile", required=True, help="Path to your profile JSON")
    ap.add_argument("--xpdir", required=False, default="xp_tables", help="(Optional) XP tables dir if your xp_model needs it")
    ap.add_argument("--out", required=True, help="Path to write the CSV plan, e.g., out/level_plan.csv")
    ap.add_argument("--topk", type=int, default=3, help="How many options per step")
    ap.add_argument("--materials-config", required=False, help="Optional materials_config.json path (defaults next to profile)")
    args = ap.parse_args()

    # Infer loc path if not provided
    loc_path = args.loc or os.path.join(os.path.dirname(args.static), "localisation_en.json")

    planner = LevelPlanner(args.static, loc_path, args.profile, args.xpdir, materials_config_path=args.materials_config)
    plan = planner.plan(top_k=args.topk)
    planner.write_csv(plan, args.out)
    print(f"âœ… Plan written to {args.out} with {len(plan)} steps.")

if __name__ == "__main__":
    main()



