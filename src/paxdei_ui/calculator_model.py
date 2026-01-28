from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from paxdei_planner.level_planner import LevelPlanner, PlanStepOption, RecipeEntry


@dataclass
class RecipeGroup:
    skill_key: Optional[str]
    recipes: List[RecipeEntry]


class RecipeCalculator:
    def __init__(
        self,
        static_path: str,
        loc_path: str,
        profile_path: str,
        xp_tables_dir: str,
        materials_config_path: str,
    ) -> None:
        self._planner = LevelPlanner(
            static_path,
            loc_path,
            profile_path,
            xp_tables_dir,
            materials_config_path=materials_config_path,
        )

    @property
    def skill_names(self) -> Dict[str, str]:
        return dict(self._planner.skill_names)

    def item_label(self, key: str) -> str:
        return self._planner.item_label(key)

    def skill_label(self, key: str) -> str:
        return self._planner.skill_label(key)

    def recipes_for_skill(
        self,
        skill_key: Optional[str] = None,
        include_building: bool = False,
    ) -> List[RecipeEntry]:
        return self._planner.list_recipes(
            skill_key,
            include_building=include_building,
            building_only=False,
        )

    def building_recipes(self) -> List[RecipeEntry]:
        return self._planner.list_recipes(
            None,
            include_building=True,
            building_only=True,
        )

    def option_for_recipe(self, recipe_key: str, crafts: int) -> PlanStepOption:
        return self._planner.build_recipe_option(recipe_key, crafts)

    def is_skill_blessed(self, skill_key: str) -> bool:
        return bool(self._planner.skill_blessing.get(skill_key, False))


class CalculatorSnapshot:
    def __init__(self, calculator: RecipeCalculator) -> None:
        self._calculator = calculator

    def skill_label(self, key: str) -> str:
        return self._calculator.skill_label(key)

    def item_label(self, key: str) -> str:
        return self._calculator.item_label(key)
