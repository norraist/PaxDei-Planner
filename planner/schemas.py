from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class Recipe:
    key: str
    is_dev: bool
    skill: str
    unlock_at: int
    difficulty: int
    xp_multiplier: float
    ingredients: Dict[str, int]
    station: str | None  # crafting station / crafter key if known
    name: str = ""
    desc: str = ""

@dataclass
class SkillXPTable:
    skill: str
    xp_to_level: list[int]  # XP needed to advance from level L to L+1

@dataclass
class GameData:
    recipes: list[Recipe]
    skills: Dict[str, SkillXPTable]
    item_names: Dict[str, str]
    recipe_to_station: Dict[str, str]

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

@dataclass
class Weights:
    material_weight: Dict[str, float]  # item key -> weight/price
