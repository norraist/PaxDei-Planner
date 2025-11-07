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
