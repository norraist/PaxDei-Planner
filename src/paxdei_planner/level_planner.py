# planner/level_planner.py
from __future__ import annotations

import csv
import json
import math
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple, TypedDict

from .data_loader import load_game_data
from .xp_model import (
    mastery_level,
    practical_unlock_level,
    success_chance,
    xp_failure_avg,
    xp_success_avg,
)  # expects (level, difficulty, unlock, xp_multiplier) OR adapt as needed
from .skills import get_skill_table

XP_EPS = 1e-6
PROGRESS_BAR_WIDTH = 24
PROGRESS_MIN_INTERVAL = 1.0
PREMIUM_XP_MULTIPLIER = 1.5

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

RARITY_SUFFIXES = {
    "common": "Common",
    "uncommon": "Uncommon",
    "rare": "Rare",
    "epic": "Epic",
    "legendary": "Legendary",
    "mythic": "Mythic",
    "poor": "Poor",
    "exotic": "Exotic",
    "masterwork": "Masterwork",
}


def _recipe_variant_label(r) -> str | None:
    variant = _first_attr(r, ["rarity", "Rarity", "quality", "Quality"], None)
    if isinstance(variant, str) and variant.strip():
        token = variant.strip()
        if token:
            return token.title()
    key = _recipe_key(r)
    parts = key.split("_")
    for token in reversed(parts):
        label = RARITY_SUFFIXES.get(token.lower())
        if label:
            return label
    return None


def _recipe_display_name(r) -> str:
    name = _recipe_name(r)
    variant = _recipe_variant_label(r)
    if variant and variant.lower() not in name.lower():
        return f"{name} ({variant})"
    return name

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

def _recipe_crafter_deliverable(r) -> Optional[str]:
    return _first_attr(r, ["CrafterDeliverable", "crafter_deliverable", "crafterDeliverable"], None)

def _recipe_is_dev(r) -> bool:
    # variants: is_dev, IsDev
    v = _first_attr(r, ["is_dev", "IsDev"], False)
    return bool(v)

def _recipe_grants_xp(recipe) -> bool:
    rkey = _recipe_key(recipe)
    if hasattr(recipe, "_zero_xp") and getattr(recipe, "_zero_xp"):
        return False
    if not getattr(recipe, "grants_xp", True):
        return False
    if rkey.startswith("recipe_crafter_"):
        return False
    out_item = _recipe_output_item(recipe)
    if isinstance(out_item, str) and out_item.startswith("crafter_"):
        return False
    crafter_deliverable = _recipe_crafter_deliverable(recipe)
    if isinstance(crafter_deliverable, str) and crafter_deliverable.startswith("crafter_"):
        return False
    return True

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


class LockedRecipeError(RuntimeError):
    def __init__(self, skill_key: str, required_level: int):
        super().__init__(skill_key)
        self.skill_key = skill_key
        self.required_level = required_level


class IngredientBreakdown(TypedDict, total=False):
    item: str
    label: str
    required: int
    source: str
    stock_used: int
    crafts: int
    attempts: int
    success_rate: float
    produced: int
    extra: int
    recipe: Optional[str]
    station: Optional[str]
    skill: Optional[str]
    children: List["IngredientBreakdown"]


@dataclass
class PlanStepOption:
    recipe_key: str
    recipe_name: str
    crafter: Optional[str]
    crafts: int
    xp_per_craft: float
    total_xp: float
    total_xp_chain: float
    material_burden: float
    materials: List[Tuple[str, int]]
    materials_qty: int
    materials_tree: str = ""
    craft_summary: List[Dict[str, Any]] = field(default_factory=list)
    ingredient_breakdown: List[IngredientBreakdown] = field(default_factory=list)
    prereq_gaps: List[Tuple[str, int, str, int]] = field(default_factory=list)
    xp_breakdown: List[Tuple[str, float, float, float, float, int]] = field(default_factory=list)
    synergy_support: List[Tuple[str, str, int]] = field(default_factory=list)
    blessing_active: bool = False

@dataclass
class PlanStep:
    skill: str
    from_level: int
    to_level: int
    options: List[PlanStepOption]
    category_options: Dict[str, List[PlanStepOption]] = field(default_factory=dict)
    note: str = ""

@dataclass
class RecipeEntry:
    recipe_key: str
    recipe_name: str
    skill: str
    success_chance: float
    expected_xp: float
    can_craft: bool
    materials_blocked: bool
    missing_crafter: bool
    dependency_blocked: bool
    blessing_active: bool = False
    missing_crafters: List[str] = field(default_factory=list)
    blocked_materials: List[str] = field(default_factory=list)
    prereq_gaps: List[Tuple[str, int, str, int]] = field(default_factory=list)

class LevelPlanner:
    """
    Multi-skill, dependency-aware leveling planner.
    - Prioritizes fewer/common materials via a rarity-weighted burden.
    - Prefers raw materials, penalizes relic/high-tier/high-item-level inputs when ranking options.
    - Inserts prerequisites (crafter unlocks / cross-skill levels) when needed.
    - Offers top-K recipe options per step.
    - Assumes xp tables already include premium boosts; scales XP down when premium is disabled.
    """

    def __init__(self, static_path: str, loc_path: str, profile_path: str, xp_tables_dir: str, materials_config_path: Optional[str] = None):
        materials_config = materials_config_path or os.path.join(os.path.dirname(profile_path), "materials_config.json")
        self.g = load_game_data(static_path, loc_path, materials_config)
        self.item_meta = getattr(self.g, "item_meta", {})
        self.material_config = getattr(self.g, "materials_config", {})
        self.item_names = getattr(self.g, "item_names", {})
        self.recipe_crafters = getattr(self.g, "recipe_crafters", {})
        self.crafter_tiers = getattr(self.g, "crafter_tiers", {})
        self.processing_crafters: Set[str] = set()
        self.zero_xp_recipes: Set[str] = set()
        try:
            with open(static_path, "r", encoding="utf-8") as handle:
                static_raw = json.load(handle)
            crafter_block = static_raw.get("static_data", {}).get("CRAFTER", {}) or {}
            for key, node in crafter_block.items():
                ctype = str(node.get("CrafterType", "")) if isinstance(node, dict) else ""
                if ctype == "ECrafterTypes::CRAFTER_PROCESSING":
                    self.processing_crafters.add(key)
            for rkey, crafters in self.recipe_crafters.items():
                if any(c in self.processing_crafters for c in crafters):
                    self.zero_xp_recipes.add(rkey)
        except Exception:
            # Fallback: no processing metadata; proceed without the extra guard.
            self.processing_crafters = set()
            self.zero_xp_recipes = set()
        self._last_missing_crafter: Optional[str] = None

        with open(profile_path, "r", encoding="utf-8") as f:
            self.profile = json.load(f)
        self.premium_account = bool(self.profile.get("premium_account", False))
        self.xp_boost = 1.0 if self.premium_account else (1.0 / PREMIUM_XP_MULTIPLIER)
        self.avoid_relics = bool(self.profile.get("avoid_relics", False))
        self.max_cross_skill_gap = int(self.profile.get("max_cross_skill_gap", 5))

        # Current mutable world state
        self.cur_level: Dict[str, int] = {k: int(v["current_level"]) for k, v in self.profile["skills"].items()}
        self.cur_xp: Dict[str, int]    = {k: int(v["current_xp"]) for k, v in self.profile["skills"].items()}
        self.target_level: Dict[str, int] = {k: int(v["target_level"]) for k, v in self.profile["skills"].items()}
        self.skill_blessing: Dict[str, bool] = {k: bool(v.get("blessing", False)) for k, v in self.profile["skills"].items()}
        self.owned_crafter: Dict[str, bool] = {k: bool(v["owned"]) for k, v in self.profile["crafters"].items()}
        self.crafter_unlock_gap = int(self.profile.get("crafter_unlock_gap", 3))
        self.skill_names: Dict[str, str] = {}
        for key, node in self.profile.get("skills", {}).items():
            if isinstance(node, dict):
                name = node.get("name")
                if isinstance(name, str) and name:
                    self.skill_names[key] = name

        # Build indices for rarity and feasibility
        self.producers: Dict[str, List[Any]] = {}   # item -> recipes that produce it
        self.usage_count: Dict[str, int] = {}       # item -> how many recipes consume it
        self._index_items()
        self.recipe_map: Dict[str, Any] = { _recipe_key(r): r for r in getattr(self.g, "recipes", []) if _recipe_key(r)}

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
        self._synergy_deferrals: Set[str] = set()

    # ---------- Indexing & rarity ----------

    def _load_recipe_xp_tables(self, xp_tables_dir: str) -> Dict[str, List[Dict[str, float]]]:
        tables: Dict[str, List[Dict[str, float]]] = {}
        base = Path(xp_tables_dir)
        if not base.exists():
            return tables

        db_path: Optional[Path] = None
        if base.is_file() and base.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
            db_path = base
        elif base.is_dir():
            candidate = base / "xp_tables.db"
            if candidate.exists():
                db_path = candidate

        if db_path:
            try:
                with sqlite3.connect(str(db_path)) as conn:
                    cur = conn.execute(
                        """
                        SELECT recipe_key, level, chance, success_avg, failure_avg, expected_avg, bless_avg
                        FROM recipe_xp
                        ORDER BY recipe_key, level
                        """
                    )
                    for recipe_key, level, chance, success_avg, failure_avg, expected_avg, bless_avg in cur.fetchall():
                        rows = tables.setdefault(str(recipe_key), [])
                        rows.append(
                            {
                                "level": int(level),
                                "chance": float(chance or 0.0),
                                "success": float(success_avg) if success_avg is not None else float("nan"),
                                "failure": float(failure_avg) if failure_avg is not None else float("nan"),
                                "expected": float(expected_avg) if expected_avg is not None else float("nan"),
                                "expected_bless": float(bless_avg) if bless_avg is not None else float("nan"),
                            }
                        )
                return tables
            except Exception:
                pass

        for csv_path in base.rglob("*.csv"):
            try:
                with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                    reader = csv.reader(handle)
                    recipe_key: Optional[str] = None
                    data_started = False
                    rows: List[Dict[str, float]] = []
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
                            bless_avg = parse(7) if len(row) > 7 else float("nan")
                            rows.append(
                                {
                                    "level": level_val,
                                    "chance": chance,
                                    "success": success_avg,
                                    "failure": failure_avg,
                                    "expected": expected_avg,
                                    "expected_bless": bless_avg,
                                }
                            )
                    if recipe_key and rows:
                        rows.sort(key=lambda r: r["level"])
                        tables[recipe_key] = rows
            except Exception:
                continue
        return tables

    def _recipe_table_row(self, recipe_key: str, level: int) -> Optional[Dict[str, float]]:
        rows = self.recipe_xp_tables.get(recipe_key)
        if not rows:
            return None
        best: Optional[Dict[str, float]] = None
        for entry in rows:
            if entry["level"] <= level:
                best = entry
            else:
                break
        if best:
            return best
        return rows[0]

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
        key_lower = item_key.lower()
        if "water" in key_lower:
            return True
        meta = self.item_meta.get(item_key)
        if meta:
            if meta.is_raw or meta.is_relic:
                return True
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
        missing_first: Optional[str] = None
        locked_need: Optional[Tuple[str, int]] = None
        for r in candidates:
            missing = self._missing_crafters_for_recipe(r)
            if missing:
                if not missing_first:
                    missing_first = missing[0]
                continue
            skill = _recipe_skill(r)
            skill_level = self.cur_level.get(skill, 0)
            if self._recipe_unlocked(r, skill_level):
                return r
            if not locked_need:
                locked_need = (skill or "", _recipe_unlock_at(r))
        if locked_need:
            raise LockedRecipeError(locked_need[0], locked_need[1])
        if missing_first:
            raise MissingCrafterError(missing_first)
        return None

    def _expand_recipe_full(
        self, recipe, crafts: int, target_skill: str
    ) -> Tuple[List[Tuple[str, int]], List[str], List[Tuple[Any, int, str]], List[IngredientBreakdown]]:
        base_totals: Dict[str, int] = {}
        craft_steps: List[Tuple[Any, int, str]] = []
        lines: List[str] = [f"{_recipe_display_name(recipe)} x{crafts} (final)"]
        stock: Dict[str, int] = {}
        breakdown_nodes: List[IngredientBreakdown] = []

        def make_node(
            item_key: str,
            required: int,
            source: str,
            *,
            stock_used: int = 0,
            crafts_used: int = 0,
            attempts: int = 0,
            success_rate: float = 1.0,
            produced: int = 0,
            extra: int = 0,
            recipe_name: Optional[str] = None,
            station_label: Optional[str] = None,
            skill_key: Optional[str] = None,
            children: Optional[List[IngredientBreakdown]] = None,
        ) -> IngredientBreakdown:
            return {
                "item": item_key,
                "label": self._item_label(item_key),
                "required": required,
                "source": source,
                "stock_used": stock_used,
                "crafts": crafts_used,
                "attempts": attempts or crafts_used,
                "success_rate": success_rate,
                "produced": produced,
                "extra": extra,
                "recipe": recipe_name,
                "station": station_label,
                "skill": skill_key,
                "children": children or [],
            }

        def helper(item_key: str, qty: int, depth: int, trail: Set[str]) -> Optional[IngredientBreakdown]:
            if qty <= 0:
                return None
            required_total = qty
            if item_key in trail or depth > 12:
                lines.append(self._tree_line(depth, self._item_label(item_key), qty, note="(cycle)"))
                base_totals[item_key] = base_totals.get(item_key, 0) + qty
                return make_node(
                    item_key,
                    required_total,
                    "cycle",
                    produced=qty,
                    success_rate=1.0,
                )
            stock_used = 0
            available = stock.get(item_key, 0)
            if available:
                use = min(available, qty)
                stock_used += use
                qty -= use
                remaining = max(0, available - use)
                stock[item_key] = remaining
                if qty <= 0:
                    return make_node(
                        item_key,
                        required_total,
                        "stock",
                        stock_used=stock_used,
                        success_rate=1.0,
                    )

            if self._is_base_material(item_key):
                base_totals[item_key] = base_totals.get(item_key, 0) + qty
                lines.append(self._tree_line(depth, f"Gather {self._item_label(item_key)}", qty))
                return make_node(
                    item_key,
                    required_total,
                    "gather",
                    stock_used=stock_used,
                    produced=qty,
                    success_rate=1.0,
                )

            prods = self.producers.get(item_key, [])
            if not prods:
                base_totals[item_key] = base_totals.get(item_key, 0) + qty
                lines.append(self._tree_line(depth, f"Gather {self._item_label(item_key)}", qty))
                return make_node(
                    item_key,
                    required_total,
                    "gather",
                    stock_used=stock_used,
                    produced=qty,
                    success_rate=1.0,
                )

            producer = self._choose_producer(item_key)
            if not producer:
                base_totals[item_key] = base_totals.get(item_key, 0) + qty
                lines.append(self._tree_line(depth, f"Gather {self._item_label(item_key)}", qty))
                return make_node(
                    item_key,
                    required_total,
                    "gather",
                    stock_used=stock_used,
                    produced=qty,
                    success_rate=1.0,
                )

            outputs = _recipe_outputs(producer)
            out_qty = outputs.get(item_key)
            if out_qty is None and outputs:
                out_qty = next(iter(outputs.values()))
            per_craft = max(1, out_qty or 1)
            crafts_min = math.ceil(qty / per_craft)
            prod_skill = _recipe_skill(producer)
            success_rate = self._recipe_success_rate(producer, prod_skill)
            effective_output = max(1e-6, per_craft * success_rate)
            crafts_needed = max(crafts_min, math.ceil(qty / effective_output))

            station_label = self._recipe_station_label(producer)
            new_trail = set(trail)
            new_trail.add(item_key)
            child_nodes: List[IngredientBreakdown] = []
            for sub_key, sub_qty in _recipe_ingredients(producer):
                child = helper(sub_key, sub_qty * crafts_needed, depth + 1, new_trail)
                if child:
                    child_nodes.append(child)

            craft_steps.append((producer, crafts_needed, prod_skill))
            action = "Craft" if prod_skill == target_skill else f"External craft ({prod_skill or 'other'})"
            if station_label:
                action = f"{action} via {station_label}"
            attempt_note = f"{crafts_needed} craft{'s' if crafts_needed != 1 else ''}"
            if success_rate < 0.999:
                attempt_note = f"~{crafts_needed} attempts @ {success_rate*100:.1f}%"
            note = f"-> {self._item_label(item_key)} x{qty} ({attempt_note})"
            lines.append(self._tree_line(depth, f"{action} {_recipe_display_name(producer)}", crafts_needed, note=note))
            return make_node(
                item_key,
                required_total,
                "craft",
                stock_used=stock_used,
                crafts_used=crafts_needed,
                attempts=crafts_needed,
                success_rate=success_rate,
                produced=qty,
                extra=0,
                recipe_name=_recipe_display_name(producer),
                station_label=station_label or None,
                skill_key=prod_skill or None,
                children=child_nodes,
            )

        for item_key, qty in _recipe_ingredients(recipe):
            node = helper(item_key, qty * crafts, depth=1, trail=set())
            if node:
                breakdown_nodes.append(node)

        craft_steps.append((recipe, crafts, target_skill))
        lines.append(self._tree_line(0, f"Craft {_recipe_display_name(recipe)}", crafts, note="(final)"))

        return sorted(base_totals.items(), key=lambda kv: kv[0]), lines, craft_steps, breakdown_nodes

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
            need_level = _recipe_unlock_at(producer)
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

    def _expected_recipe_xp(self, recipe, level: int, skill: str) -> float:
        """Expected XP for a single craft of the target recipe (ignores sub-crafts)."""
        _, _success, _failure, expected = self._recipe_xp_stats(recipe, level, skill)
        return expected if isinstance(expected, (int, float)) else 0.0

    def _xp_from_crafts(self, craft_steps: List[Tuple[Any, int, str]], level: int, skill: str) -> float:
        total = 0.0
        for rec, count, rec_skill in craft_steps:
            if rec_skill != skill:
                continue
            if not _recipe_grants_xp(rec):
                continue
            chance, success, failure, expected = self._recipe_xp_stats(
                rec, level, rec_skill
            )
            total += count * expected
        return total

    def _xp_breakdown(self, craft_steps: List[Tuple[Any, int, str]], level: int, skill: str) -> List[Tuple[str, float, float, float, float, int]]:
        entries: List[Tuple[str, float, float, float, float, int]] = []
        for rec, count, rec_skill in craft_steps:
            if rec_skill != skill:
                continue
            if not _recipe_grants_xp(rec):
                continue
            chance, success, failure, expected = self._recipe_xp_stats(
                rec, level, rec_skill
            )
            entries.append((_recipe_display_name(rec), chance, success, failure, expected, count))
        return entries

    def _recipe_xp_stats(
        self, recipe, level: int, skill: str
    ) -> Tuple[float, float, float, float]:
        key = _recipe_key(recipe)
        diff = _recipe_difficulty(recipe)
        unlock = _recipe_unlock_at(recipe)
        blessing_active = self.skill_blessing.get(skill, False)
        chance_level = level + 1 if blessing_active else level
        if key in self.zero_xp_recipes:
            return 1.0, 0.0, 0.0, 0.0
        mastery_lvl = self._recipe_mastery_level(recipe, skill)
        if level >= mastery_lvl:
            chance = success_chance(chance_level, diff)
            return chance, 0.0, 0.0, 0.0
        if not _recipe_grants_xp(recipe):
            table_row = self._recipe_table_row(key, level)
            chance = (
                table_row.get("chance")
                if table_row and not math.isnan(table_row.get("chance", float("nan")))
                else success_chance(chance_level, diff)
            )
            return chance, 0.0, float("nan"), 0.0

        table_row = self._recipe_table_row(key, level)
        if table_row and not math.isnan(table_row.get("chance", float("nan"))):
            chance = table_row.get("chance", 0.0)
        else:
            chance = success_chance(chance_level, diff)
        success: float
        failure: float
        expected: float

        def _scale(value: float) -> float:
            if not isinstance(value, (int, float)) or math.isnan(value):
                return float("nan")
            return float(value) * self.xp_boost

        if table_row:
            success = _scale(table_row.get("success", float("nan")))
            failure = _scale(table_row.get("failure", float("nan")))
            base_expected_key = "expected_bless" if blessing_active else "expected"
            base_expected = table_row.get(base_expected_key, float("nan"))
            if not isinstance(base_expected, (int, float)) or math.isnan(base_expected):
                base_expected = table_row.get("expected", float("nan"))
            expected = _scale(base_expected) if not math.isnan(base_expected) else float("nan")
        else:
            xpm = _recipe_xpmult(recipe)
            success = xp_success_avg(level, diff, xpm, skill=skill) * self.xp_boost
            failure = xp_failure_avg(level, diff, unlock, xpm, skill=skill)
            if isinstance(failure, float):
                failure = failure * self.xp_boost
            else:
                failure = float("nan")
            expected = float("nan")

        if math.isnan(expected):
            if math.isnan(failure):
                expected = chance * success
            else:
                expected = chance * success + (1 - chance) * failure
        return chance, success, failure, expected

    def _recipe_success_rate(self, recipe, skill: Optional[str]) -> float:
        if not skill:
            return 1.0
        level = self.cur_level.get(skill, 1)
        if self.skill_blessing.get(skill, False):
            level += 1
        diff = _recipe_difficulty(recipe)
        unlock = _recipe_unlock_at(recipe)
        if level < unlock:
            return 0.0
        table_row = self._recipe_table_row(_recipe_key(recipe), level)
        if table_row and not math.isnan(table_row.get("chance", float("nan"))):
            chance = table_row.get("chance", 0.0)
        else:
            chance = success_chance(level, diff)
        if not isinstance(chance, (int, float)) or math.isnan(chance):
            return 1.0
        if _recipe_key(recipe) in self.zero_xp_recipes:
            return 1.0
        return max(0.0, min(1.0, float(chance)))

    def _summarize_crafts(self, craft_steps: List[Tuple[Any, int, str]]) -> List[Dict[str, Any]]:
        summary: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for rec, count, rec_skill in craft_steps:
            name = _recipe_display_name(rec)
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

    def _synergy_support_from_steps(self, craft_steps: List[Tuple[Any, int, str]], target_skill: str) -> List[Tuple[str, str, int]]:
        totals: Dict[Tuple[str, str], int] = {}
        for rec, count, rec_skill in craft_steps:
            if not rec_skill or rec_skill == target_skill:
                continue
            if not _recipe_grants_xp(rec):
                continue
            outputs = _recipe_outputs(rec)
            if not outputs:
                continue
            for item_key, qty in outputs.items():
                if qty <= 0:
                    continue
                totals[(rec_skill, item_key)] = totals.get((rec_skill, item_key), 0) + qty * count
        results = [(skill_key, item_key, qty) for (skill_key, item_key), qty in totals.items() if qty > 0]
        results.sort(key=lambda entry: (entry[0], entry[1]))
        return results

    def _synergy_score(self, synergy_support: List[Tuple[str, str, int]]) -> float:
        if not synergy_support:
            return 0.0
        unique_skills = {skill for skill, _, _ in synergy_support}
        qty_bonus = sum(math.log10(max(2, qty)) for _, _, qty in synergy_support) * 0.01
        return len(unique_skills) * 0.05 + len(synergy_support) * 0.02 + qty_bonus

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
        if not _recipe_grants_xp(recipe):
            return "Crafter (no XP)"
        return ""

    def item_label(self, item_key: str) -> str:
        if item_key.startswith("crafter_"):
            return self._station_label(item_key) or item_key
        return self._item_label(item_key)

    def skill_label(self, skill_key: str) -> str:
        return self._skill_label(skill_key)

    def _skill_label(self, skill_key: str) -> str:
        if skill_key in self.skill_names:
            return self.skill_names[skill_key]
        node = self.profile.get("skills", {}).get(skill_key)
        if isinstance(node, dict):
            name = node.get("name")
            if isinstance(name, str) and name:
                self.skill_names[skill_key] = name
                return name
        return skill_key

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

    def _skill_level_cap(self, skill: Optional[str]) -> int:
        if not skill:
            return 40
        table = get_skill_table(getattr(self.g, "skills", {}), skill)
        if table and table.xp_to_level:
            return len(table.xp_to_level)
        return 40

    def _recipe_practical_unlock(self, recipe) -> int:
        return practical_unlock_level(_recipe_unlock_at(recipe), _recipe_difficulty(recipe))

    def _recipe_mastery_level(self, recipe, skill: Optional[str] = None) -> int:
        cap = self._skill_level_cap(skill)
        return mastery_level(_recipe_difficulty(recipe), cap)

    def _recipe_unlocked(self, recipe, skill_level: int) -> bool:
        required = _recipe_unlock_at(recipe)
        return skill_level >= required

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

    # ---------- Choosing best options for a single level ----------

    def _best_options_for_level(self, skill: str, level: int, top_k: int = 3, ignore_gap: bool = False) -> Tuple[List[PlanStepOption], List[str], Dict[str, List[PlanStepOption]]]:
        """
        Among feasible recipes for 'skill' at 'level', return top-K options by
        score = xp_expected / (1 + material_burden_per_craft).
        """
        self._last_missing_crafter = None
        missing_seen: List[str] = []
        candidates = []
        option_candidates: List[Tuple[PlanStepOption, float, float]] = []
        for r in _recipes_for_skill(self.g, skill):
            if _recipe_is_dev(r):
                continue
            if not _recipe_grants_xp(r):
                continue
            rkey = _recipe_key(r)
            if rkey.startswith("recipe_crafter_") or rkey.startswith("recipe_item_unlock_crafter_"):
                continue
            if not self._recipe_unlocked(r, level):
                continue
            mastery_lvl = self._recipe_mastery_level(r, skill)
            if level >= mastery_lvl:
                continue
            missing_crafters = self._missing_crafters_for_recipe(r)
            if missing_crafters:
                for ck in missing_crafters:
                    missing_seen.append(ck)
                if not self._last_missing_crafter:
                    self._last_missing_crafter = missing_crafters[0]
                continue

            burden_one, _ = self._material_burden(r, crafts=1)
            try:
                materials_unit, _, crafts_unit, _ = self._expand_recipe_full(r, 1, skill)
            except MissingCrafterError as err:
                missing_seen.append(err.crafter_key)
                if not self._last_missing_crafter:
                    self._last_missing_crafter = err.crafter_key
                continue
            except LockedRecipeError:
                continue
            if self.avoid_relics and self._contains_relic_materials(materials_unit):
                continue
            xpc_unit = self._expected_recipe_xp(r, level, skill)
            chain_xp_unit = self._xp_from_crafts(crafts_unit, level, skill)
            if xpc_unit <= 0:
                continue

            synergy_unit = self._synergy_support_from_steps(crafts_unit, skill)
            synergy_boost = self._synergy_score(synergy_unit)
            score = xpc_unit / (1.0 + burden_one)
            if synergy_boost > 0:
                score *= (1.0 + synergy_boost)
            candidates.append((score, r, xpc_unit, burden_one))

        candidates.sort(key=lambda t: t[0], reverse=True)
        for score, r, xpc_unit, burden_one in candidates:
            # crafts to reach next level from current XP
            xp_needed = _xp_to_next_level(self.g, skill, level) - self.cur_xp.get(skill, 0)
            # Use chain XP per unit if it exceeds final-recipe XP so subcraft XP reduces the required attempts.
            try:
                _, _, crafts_unit, _ = self._expand_recipe_full(r, 1, skill)
                chain_xp_unit = self._xp_from_crafts(crafts_unit, level, skill)
            except Exception:
                chain_xp_unit = xpc_unit
            xp_unit_for_crafts = max(xpc_unit, chain_xp_unit)
            crafts = max(1, math.ceil(xp_needed / max(1e-9, xp_unit_for_crafts)))
            try:
                materials_full, tree_lines, crafts_full, breakdown = self._expand_recipe_full(r, crafts, skill)
            except MissingCrafterError as err:
                missing_seen.append(err.crafter_key)
                if not self._last_missing_crafter:
                    self._last_missing_crafter = err.crafter_key
                continue
            except LockedRecipeError:
                continue
            if self._contains_disabled_materials(materials_full):
                continue
            total_xp_final = xpc_unit * crafts
            total_xp_chain = self._xp_from_crafts(crafts_full, level, skill)
            materials_qty = sum(max(0, int(qty)) for _item, qty in materials_full)
            prereq_gaps = self._dependency_gaps(r, crafts, skill)
            craft_summary = self._summarize_crafts(crafts_full)
            synergy_support = self._synergy_support_from_steps(crafts_full, skill)
            xp_breakdown = [
                (_recipe_display_name(r), *self._recipe_xp_stats(r, level, skill), crafts)
            ]
            option_candidates.append((
                PlanStepOption(
                    recipe_key=_recipe_key(r),
                    recipe_name=_recipe_display_name(r),
                    crafter=_recipe_station(r),
                    crafts=crafts,
                    xp_per_craft=xpc_unit,
                    total_xp=total_xp_final,
                    total_xp_chain=total_xp_chain,
                    material_burden=burden_one * crafts,
                    materials=materials_full,
                    materials_qty=materials_qty,
                    materials_tree="\n".join(tree_lines),
                    craft_summary=craft_summary,
                    ingredient_breakdown=breakdown,
                    prereq_gaps=prereq_gaps,
                    xp_breakdown=xp_breakdown,
                    synergy_support=synergy_support,
                    blessing_active=self.skill_blessing.get(skill, False),
                ),
                total_xp_chain,
                materials_qty,
            ))
        if missing_seen and not self._last_missing_crafter:
            self._last_missing_crafter = missing_seen[0]
        def _take_sorted(opts: List[PlanStepOption], key_fn, reverse: bool = True) -> List[PlanStepOption]:
            return sorted(opts, key=key_fn, reverse=reverse)[: max(1, top_k)]

        opts_only = [opt for opt, _chain, _matqty in option_candidates]
        chain_sorted = _take_sorted(opts_only, key_fn=lambda o: o.total_xp_chain, reverse=True) if opts_only else []
        final_sorted = _take_sorted(opts_only, key_fn=lambda o: o.total_xp, reverse=True) if opts_only else []
        economy_sorted = _take_sorted(opts_only, key_fn=lambda o: (o.materials_qty, o.material_burden), reverse=False) if opts_only else []

        category_options: Dict[str, List[PlanStepOption]] = {
            "chain": chain_sorted,
            "final": final_sorted,
            "economy": economy_sorted,
        }

        visible: List[PlanStepOption] = []
        seen_keys: Set[str] = set()
        for cat in ("chain", "final", "economy"):
            for opt in category_options.get(cat, []):
                if opt.recipe_key in seen_keys:
                    continue
                visible.append(opt)
                seen_keys.add(opt.recipe_key)
                break
        return visible, missing_seen, category_options

    def _build_unlock_option(self, recipe, crafts: int = 1) -> Optional[PlanStepOption]:
        skill = _recipe_skill(recipe)
        level = self.cur_level.get(skill, 1)
        burden_one, _ = self._material_burden(recipe, crafts)
        try:
            materials_full, tree_lines, crafts_full, breakdown = self._expand_recipe_full(recipe, crafts, skill)
        except (MissingCrafterError, LockedRecipeError):
            return None
        if self._contains_disabled_materials(materials_full):
            return None
        per_craft_xp = self._expected_recipe_xp(recipe, level, skill)
        total_xp = per_craft_xp * crafts
        total_xp_chain = self._xp_from_crafts(crafts_full, level, skill)
        materials_qty = sum(max(0, int(qty)) for _item, qty in materials_full)
        craft_summary = self._summarize_crafts(crafts_full)
        synergy_support = self._synergy_support_from_steps(crafts_full, skill)
        prereq_gaps = self._dependency_gaps(recipe, crafts, skill)
        xp_breakdown = [
            (_recipe_display_name(recipe), *self._recipe_xp_stats(recipe, level, skill), crafts)
        ]
        return PlanStepOption(
            recipe_key=_recipe_key(recipe),
            recipe_name=_recipe_display_name(recipe),
            crafter=_recipe_station(recipe),
            crafts=crafts,
            xp_per_craft=per_craft_xp,
            total_xp=total_xp,
            total_xp_chain=total_xp_chain,
            material_burden=burden_one * crafts,
            materials=materials_full,
            materials_qty=materials_qty,
            materials_tree="\n".join(tree_lines),
            craft_summary=craft_summary,
            ingredient_breakdown=breakdown,
            prereq_gaps=prereq_gaps,
            xp_breakdown=xp_breakdown,
            synergy_support=synergy_support,
            blessing_active=self.skill_blessing.get(skill, False),
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
                        opts, _, cat_opts = self._best_options_for_level(need_skill, cur)
                        if not opts:
                            continue
                        step = PlanStep(
                            skill=need_skill,
                            from_level=cur,
                            to_level=cur + 1,
                            options=opts,
                            category_options=cat_opts,
                            note=f"Prereq: level {need_skill} towards crafting {item_key}"
                        )
                        if best is None or cost < best[1]:
                            best = (step, cost)
        if best:
            return best[0]

        return None

    def _crafter_unlock_recipes(self, crafter_key: str) -> List[Any]:
        unlockers: List[Any] = []
        suffix = crafter_key[len("crafter_"):] if crafter_key.startswith("crafter_") else crafter_key
        candidate_keys = [
            f"recipe_item_unlock_{crafter_key}",
            f"recipe_item_unlock_{suffix}",
            f"recipe_crafter_{crafter_key}",
            f"recipe_crafter_{suffix}",
        ]
        seen: Set[str] = set()
        for key in candidate_keys:
            rec = self.recipe_map.get(key)
            if rec and key not in seen:
                unlockers.append(rec)
                seen.add(key)
        if not unlockers:
            for rec_key, rec in self.recipe_map.items():
                if rec_key.endswith(suffix) and rec_key not in seen:
                    unlockers.append(rec)
                    seen.add(rec_key)
        unlockers.sort(key=lambda rec: _recipe_unlock_at(rec))
        return unlockers

    def _plan_crafter_unlock_step(
        self,
        crafter_key: str,
        target_skill: str,
        current_level: int,
        visited: Optional[Set[str]] = None,
        force: bool = False,
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
                if not force and req_unlock - current_level > self.crafter_unlock_gap:
                    return None
                opts, _, cat_opts = self._best_options_for_level(req_skill, current_level, ignore_gap=True)
                if opts:
                    return PlanStep(
                        skill=req_skill,
                        from_level=current_level,
                        to_level=req_unlock,
                        options=opts,
                        category_options=cat_opts,
                        note=note,
                    )
            if req_unlock and current < req_unlock:
                if not force and req_unlock - current > self.crafter_unlock_gap:
                    return None
                opts, _, cat_opts = self._best_options_for_level(req_skill, current, ignore_gap=True)
                if opts:
                    return PlanStep(
                        skill=req_skill,
                        from_level=current,
                        to_level=req_unlock,
                        options=opts,
                        category_options=cat_opts,
                        note=note,
                    )
            try:
                option = self._build_unlock_option(ur)
            except MissingCrafterError as err:
                step = self._plan_crafter_unlock_step(err.crafter_key, req_skill, self.cur_level.get(req_skill, 1), visited, force=force)
                if step:
                    return step
                continue
            if option:
                if _recipe_key(ur).startswith("recipe_crafter_"):
                    self.owned_crafter[crafter_key] = True
                return PlanStep(
                    skill=req_skill,
                    from_level=current,
                    to_level=current,
                    options=[option],
                    category_options={"final": [option], "chain": [option], "economy": [option]},
                    note=note,
                )
        return None

    def _plan_next_crafter(self, skill: str, level: int, force: bool = False) -> Optional[PlanStep]:
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
            step = self._plan_crafter_unlock_step(ck, skill, level, force=force)
            if step:
                return step
        return None

    # ---------- Recipe catalogue ----------

    def list_recipes(
        self,
        skill_filter: Optional[str] = None,
        include_building: bool = True,
        building_only: bool = False,
    ) -> List[RecipeEntry]:
        results: List[RecipeEntry] = []
        for recipe in getattr(self.g, "recipes", []):
            key = _recipe_key(recipe)
            if _recipe_is_dev(recipe):
                continue
            is_building = key.startswith("recipe_building_piece_")
            if not include_building and is_building:
                continue
            if building_only and not is_building:
                continue
            recipe_skill = _recipe_skill(recipe)
            if not recipe_skill:
                continue
            if skill_filter and recipe_skill != skill_filter:
                continue
            level = self.cur_level.get(recipe_skill, 1)
            unlock = _recipe_unlock_at(recipe)
            if level < unlock:
                continue
            chance, _, _, base_expected = self._recipe_xp_stats(recipe, level, recipe_skill)
            expected = base_expected * self.xp_boost
            if chance <= 0.0:
                continue
            missing_crafters = self._missing_crafters_for_recipe(recipe)
            materials_blocked = False
            rel_block = False
            prereq_gaps: List[Tuple[str, int, str, int]] = []
            dependency_blocked = False
            blocked_materials_set: Set[str] = set()
            try:
                materials_full, _, _, _ = self._expand_recipe_full(recipe, 1, recipe_skill)
                rel_block = self._contains_relic_materials(materials_full) if self.avoid_relics else False
                materials_blocked = self._contains_disabled_materials(materials_full)
                prereq_gaps = self._dependency_gaps(recipe, 1, recipe_skill)
                dependency_blocked = any(delta > 0 for _, _, _, delta in prereq_gaps)
                for item_key, _qty in materials_full:
                    if not self._material_enabled(item_key):
                        blocked_materials_set.add(item_key)
            except MissingCrafterError as err:
                materials_full = []
                dependency_blocked = True
                if err.crafter_key not in missing_crafters:
                    missing_crafters.append(err.crafter_key)
            except LockedRecipeError as err:
                # Item requires a skill level we don't meet yet; flag as dependency-blocked instead of crashing the UI.
                materials_full = []
                dependency_blocked = True
                gap_skill = err.skill_key or recipe_skill
                cur_level = self.cur_level.get(gap_skill, 0)
                need_level = err.required_level
                delta = max(0, need_level - cur_level)
                prereq_gaps = [(gap_skill, need_level, "", delta)]
            if rel_block:
                continue
            can_craft = not missing_crafters and not materials_blocked and not dependency_blocked
            results.append(
                RecipeEntry(
                    recipe_key=_recipe_key(recipe),
                    recipe_name=_recipe_display_name(recipe),
                    skill=recipe_skill,
                    success_chance=chance,
                    expected_xp=expected,
                    can_craft=can_craft,
                    materials_blocked=materials_blocked,
                    missing_crafter=bool(missing_crafters),
                    dependency_blocked=dependency_blocked,
                    blessing_active=self.skill_blessing.get(recipe_skill, False),
                    missing_crafters=list(missing_crafters),
                    blocked_materials=sorted(blocked_materials_set),
                    prereq_gaps=prereq_gaps,
                )
            )
        return results

    def build_recipe_option(self, recipe_key: str, crafts: int) -> PlanStepOption:
        if crafts <= 0:
            raise ValueError("craft count must be positive")
        recipe = self.recipe_map.get(recipe_key)
        if not recipe:
            raise KeyError(f"unknown recipe {recipe_key}")
        skill = _recipe_skill(recipe)
        level = self.cur_level.get(skill, 1)
        burden_one, _ = self._material_burden(recipe, crafts=1)
        materials_full, tree_lines, crafts_full, breakdown = self._expand_recipe_full(recipe, crafts, skill)
        per_craft_xp = self._expected_recipe_xp(recipe, level, skill)
        total_xp = per_craft_xp * crafts
        total_xp_chain = self._xp_from_crafts(crafts_full, level, skill)
        materials_qty = sum(max(0, int(qty)) for _item, qty in materials_full)
        craft_summary = self._summarize_crafts(crafts_full)
        prereq_gaps = self._dependency_gaps(recipe, crafts, skill)
        xp_breakdown = [
            (_recipe_display_name(recipe), *self._recipe_xp_stats(recipe, level, skill), crafts)
        ]
        synergy_support = self._synergy_support_from_steps(crafts_full, skill)
        return PlanStepOption(
            recipe_key=_recipe_key(recipe),
            recipe_name=_recipe_display_name(recipe),
            crafter=_recipe_station(recipe),
            crafts=crafts,
            xp_per_craft=per_craft_xp,
            total_xp=total_xp,
            total_xp_chain=total_xp_chain,
            material_burden=burden_one * crafts,
            materials=materials_full,
            materials_qty=materials_qty,
            materials_tree="\n".join(tree_lines),
            craft_summary=craft_summary,
            ingredient_breakdown=breakdown,
            prereq_gaps=prereq_gaps,
            xp_breakdown=xp_breakdown,
            synergy_support=synergy_support,
            blessing_active=self.skill_blessing.get(skill, False),
        )

    def _pending_synergy_supports(self, option: PlanStepOption, target_skill: str) -> List[str]:
        pending: List[str] = []
        for support_skill, _, _ in option.synergy_support:
            if support_skill == target_skill:
                continue
            if self.cur_level.get(support_skill, 0) >= self.target_level.get(support_skill, 0):
                continue
            if support_skill not in pending:
                pending.append(support_skill)
        return pending

    def _clear_synergy_deferral(self, skill: str) -> None:
        self._synergy_deferrals.discard(skill)

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

            options, missing_crafters, category_options = self._best_options_for_level(skill, lvl, top_k=top_k)
            if missing_crafters and not self._last_missing_crafter:
                self._last_missing_crafter = missing_crafters[0]
            if missing_crafters and len(options) < top_k:
                step = self._plan_crafter_unlock_step(missing_crafters[0], skill, lvl, force=False)
                if not step and not options:
                    step = self._plan_crafter_unlock_step(missing_crafters[0], skill, lvl, force=True)
                if step:
                    plan.append(step)
                    self._clear_synergy_deferral(step.skill)
                    if step.options:
                        prev_lvl = self.cur_level.get(step.skill, 1)
                        new_lvl = max(prev_lvl, step.to_level)
                        self.cur_level[step.skill] = new_lvl
                        self.cur_xp[step.skill] = 0
                        self._record_progress(step.skill, prev_lvl, new_lvl)
                    steps += 1
                    skill_queue.append(skill)
                    continue
            if options:
                pending_supports = self._pending_synergy_supports(options[0], skill)
                if pending_supports and skill not in self._synergy_deferrals:
                    for support in reversed(pending_supports):
                        if support in skill_queue:
                            skill_queue.remove(support)
                        skill_queue.insert(0, support)
                    skill_queue.insert(len(pending_supports), skill)
                    self._synergy_deferrals.add(skill)
                    continue
                gap_step = self._resolve_cross_skill_gap(options[0], skill)
                if gap_step:
                    prev_gap_level = self.cur_level.get(gap_step.skill, 1)
                    plan.append(gap_step)
                    if gap_step.options:
                        new_gap_level = max(prev_gap_level, gap_step.to_level)
                        self.cur_level[gap_step.skill] = new_gap_level
                        self.cur_xp[gap_step.skill] = 0
                        self._record_progress(gap_step.skill, prev_gap_level, new_gap_level)
                    self._clear_synergy_deferral(gap_step.skill)
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

                step_entry = PlanStep(
                    skill=skill,
                    from_level=lvl,
                    to_level=self.cur_level[skill],
                    options=options,
                    category_options=category_options,
                )
                plan.append(step_entry)
                self._clear_synergy_deferral(skill)
                steps += 1
                stagnant_cycles = 0
                skill_queue.append(skill)
                continue

            # No feasible options: add a prerequisite step
            prereq = self._missing_prereq(skill, lvl, required_crafter=self._last_missing_crafter)
            if prereq:
                plan.append(prereq)
                self._clear_synergy_deferral(prereq.skill)
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

            crafter_step = self._plan_next_crafter(skill, lvl, force=True)
            if crafter_step:
                plan.append(crafter_step)
                self._clear_synergy_deferral(crafter_step.skill)
                steps += 1
                stagnant_cycles = 0
                skill_queue.append(skill)
                continue

            stagnant_cycles += 1
            if stagnant_cycles >= len(self.target_level):
                plan.append(PlanStep(skill=skill, from_level=lvl, to_level=lvl, options=[], category_options={}, note="Planner stalled; remaining skills may require manual intervention."))
                self._clear_synergy_deferral(skill)
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
        options, _, category_options = self._best_options_for_level(gap_skill, cur, top_k=3)
        note = f"Prerequisite: advance {gap_skill} for crafting {self._item_label(item_key)} used in {target_skill}"
        return PlanStep(
            skill=gap_skill,
            from_level=cur,
            to_level=to_level,
            options=options,
            category_options=category_options,
            note=note
        )

    def write_csv(self, plan: List[PlanStep], path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["skill","from_level","to_level","note","option_rank","recipe_key","recipe_name","crafter","crafts","xp_per_craft","total_xp","material_burden","materials","materials_tree","synergy_support"])
            for step in plan:
                if not step.options:
                    w.writerow([step.skill, step.from_level, step.to_level, step.note, "", "", "", "", "", "", "", "", "", "", ""])
                    continue
                for i, opt in enumerate(step.options, start=1):
                    mats = [f"{self._item_label(k)}-{q}" for k, q in opt.materials]
                    mats_str = "; ".join(mats)
                    synergy_str = "; ".join(
                        f"{self._skill_label(sk)} -> {self._item_label(item)} x{qty}"
                        for sk, item, qty in opt.synergy_support
                    )
                    w.writerow([
                        step.skill, step.from_level, step.to_level, step.note,
                        i, opt.recipe_key, opt.recipe_name, opt.crafter or "",
                        opt.crafts, f"{opt.xp_per_craft:.1f}", f"{opt.total_xp:.1f}",
                        f"{opt.material_burden:.2f}", mats_str, opt.materials_tree, synergy_str
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
            if opt.synergy_support:
                lines.append("  Synergy boosts:")
                for support_skill, item_key, qty in opt.synergy_support:
                    lines.append(f"    - {self._skill_label(support_skill)} supplies {self._item_label(item_key)} x{qty}")
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
            msg = f"[planner] [{bar}] {pct*100:5.1f}% ({done}/{total} levels)\n"
            try:
                sys.stdout.write(msg)
                sys.stdout.flush()
            except OSError:
                pass
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
