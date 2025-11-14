from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass(slots=True)
class SkillEntry:
    key: str
    name: str
    current_level: int
    current_xp: int
    target_level: int


@dataclass(slots=True)
class CrafterEntry:
    key: str
    name: str
    owned: bool


@dataclass(slots=True)
class MaterialEntry:
    key: str
    name: str
    description: str
    enabled: bool


@dataclass(slots=True)
class ProfileData:
    premium_account: bool
    avoid_relics: bool
    max_cross_skill_gap: int
    skills: List[SkillEntry] = field(default_factory=list)
    crafters: List[CrafterEntry] = field(default_factory=list)

    @classmethod
    def from_json(cls, payload: Dict[str, Any]) -> "ProfileData":
        premium = bool(payload.get("premium_account", False))
        avoid_relics = bool(payload.get("avoid_relics", False))
        max_gap = int(payload.get("max_cross_skill_gap", 5))
        skills = [
            SkillEntry(
                key=key,
                name=str(node.get("name", key)),
                current_level=int(node.get("current_level", 1)),
                current_xp=int(node.get("current_xp", 0)),
                target_level=int(node.get("target_level", int(node.get("current_level", 1)) + 1)),
            )
            for key, node in payload.get("skills", {}).items()
        ]
        crafters = [
            CrafterEntry(key=key, name=str(node.get("name", key)), owned=bool(node.get("owned", False)))
            for key, node in payload.get("crafters", {}).items()
        ]
        return cls(
            premium_account=premium,
            avoid_relics=avoid_relics,
            max_cross_skill_gap=max_gap,
            skills=sorted(skills, key=lambda s: s.name.lower()),
            crafters=sorted(crafters, key=lambda c: c.name.lower()),
        )

    def to_json(self) -> Dict[str, Any]:
        return {
            "premium_account": self.premium_account,
            "avoid_relics": self.avoid_relics,
            "max_cross_skill_gap": self.max_cross_skill_gap,
            "skills": {
                s.key: {
                    "name": s.name,
                    "current_level": s.current_level,
                    "current_xp": s.current_xp,
                    "target_level": s.target_level,
                }
                for s in self.skills
            },
            "crafters": {c.key: {"name": c.name, "owned": c.owned} for c in self.crafters},
        }


class ConfigStore:
    """Loads and persists profile/material configuration JSON files."""

    def __init__(self, profile_path: Path, materials_path: Path) -> None:
        self.profile_path = profile_path
        self.materials_path = materials_path
        self.profile = self._load_profile()
        self.materials = self._load_materials()

    def _load_profile(self) -> ProfileData:
        with self.profile_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return ProfileData.from_json(payload)

    def _load_materials(self) -> List[MaterialEntry]:
        with self.materials_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        entries = [
            MaterialEntry(
                key=key,
                name=str(node.get("name", key)),
                description=str(node.get("description", "")).replace("\\n", " ").replace("\r\n", " ").replace("\n", " ").replace("\r", " "),
                enabled=bool(node.get("enabled", True)),
            )
            for key, node in payload.items()
        ]
        return sorted(entries, key=lambda m: m.name.lower())

    def save_profile(self) -> None:
        tmp_path = self.profile_path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(self.profile.to_json(), handle, indent=2)
        tmp_path.replace(self.profile_path)

    def save_materials(self) -> None:
        tmp_path = self.materials_path.with_suffix(".tmp")
        payload = {
            m.key: {"name": m.name, "description": m.description, "enabled": m.enabled}
            for m in self.materials
        }
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        tmp_path.replace(self.materials_path)
