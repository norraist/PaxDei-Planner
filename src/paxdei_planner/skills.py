from __future__ import annotations
from typing import Dict, Optional
from .schemas import SkillXPTable

def level_to_total_xp(table: SkillXPTable, level: int) -> int:
    # total XP required to reach given level from 0
    level = max(0, level)
    return sum(table.xp_to_level[:level])

def xp_to_next_level(table: SkillXPTable, current_level: int, current_xp_into_level: int) -> int:
    req = table.xp_to_level[current_level] if current_level < len(table.xp_to_level) else 0
    return max(0, req - current_xp_into_level)

def _normalize_skill_key(key: str) -> str:
    """Lowercase alphanumeric key without underscores so armorsmith variants match."""
    return "".join(ch for ch in key.lower() if ch.isalnum())

def get_skill_table(skills: Dict[str, SkillXPTable], skill_key: str) -> Optional[SkillXPTable]:
    table = skills.get(skill_key)
    if table:
        return table
    target = _normalize_skill_key(skill_key)
    for key, tbl in skills.items():
        if _normalize_skill_key(key) == target:
            return tbl
    return None
