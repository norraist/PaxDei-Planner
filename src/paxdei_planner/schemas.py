from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

@dataclass
class Recipe:
    key: str
    is_dev: bool
    skill: str
    unlock_at: int
    difficulty: int
    xp_multiplier: float
    ingredients: Dict[str, int]
    outputs: Dict[str, int]
    station: str | None  # crafting station / crafter key if known
    name: str = ""
    desc: str = ""
    grants_xp: bool = True

@dataclass
class SkillXPTable:
    skill: str
    xp_to_level: list[int]  # XP needed to advance from level L to L+1
    base_xp: int = 0

@dataclass
class ItemMeta:
    key: str
    tier: Optional[int] = None
    item_level: Optional[int] = None
    categories: List[str] = field(default_factory=list)
    is_raw: bool = False
    is_relic: bool = False
    is_raw: bool = False
    is_relic: bool = False

@dataclass
class GameData:
    recipes: list[Recipe]
    skills: Dict[str, SkillXPTable]
    item_names: Dict[str, str]
    recipe_to_station: Dict[str, str]
    item_meta: Dict[str, ItemMeta]
    materials_config: Dict[str, Dict[str, Any]]
    recipe_crafters: Dict[str, List[str]] = field(default_factory=dict)
    crafter_tiers: Dict[str, int] = field(default_factory=dict)

# New nested profile shape (matches your final JSON)
@dataclass
class SkillState:
    name: str
    current_level: int
    current_xp: int
    target_level: int

@dataclass
class Profile:
    # "skills": { "skill_tailoring": SkillState(...), ... }
    skills: Dict[str, SkillState]
    # "crafters": { "crafter_xxx": { "name": "...", "owned": True/False }, ... }
    crafters: Dict[str, Dict[str, Any]]
    premium_account: bool = False
    avoid_relics: bool = False
    max_cross_skill_gap: int = 5

@dataclass
class Weights:
    material_weight: Dict[str, float]  # item key -> weight/price
