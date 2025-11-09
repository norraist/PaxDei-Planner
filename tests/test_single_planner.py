import unittest

import bootstrap  # noqa: F401

from paxdei_planner.planner import plan_skill
from paxdei_planner.schemas import GameData, Profile, Recipe, SkillState, SkillXPTable, Weights


def _base_game(recipe: Recipe, skill_key: str) -> GameData:
    return GameData(
        recipes=[recipe],
        skills={skill_key: SkillXPTable(skill=skill_key, xp_to_level=[100] * 50)},
        item_names={},
        recipe_to_station={},
        item_meta={},
        materials_config={},
    )


class PlannerZeroXPTest(unittest.TestCase):
    def test_zero_xp_recipe_rejected(self) -> None:
        skill_key = "skill_tailoring"
        recipe = Recipe(
            key="recipe_thread",
            is_dev=False,
            skill=skill_key,
            unlock_at=0,
            difficulty=1,
            xp_multiplier=1.0,
            ingredients={"item_fiber": 1},
            outputs={},
            station=None,
            name="Thread",
            desc="",
            grants_xp=True,
        )
        game = _base_game(recipe, skill_key)
        profile = Profile(
            skills={
                skill_key: SkillState(
                    name="Tailoring",
                    current_level=20,
                    current_xp=0,
                    target_level=21,
                )
            },
            crafters={},
            premium_account=False,
            avoid_relics=False,
            max_cross_skill_gap=5,
        )
        weights = Weights(material_weight={"item_fiber": 1.0})

        with self.assertRaises(RuntimeError):
            plan_skill(game, skill_key, profile, weights)


if __name__ == "__main__":
    unittest.main()
