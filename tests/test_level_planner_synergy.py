import json
from pathlib import Path

import pytest

import bootstrap  # noqa: F401

from paxdei_planner import level_planner
from paxdei_planner.level_planner import PlanStepOption, LevelPlanner
from paxdei_planner.schemas import GameData, Recipe, SkillXPTable


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture()
def planner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LevelPlanner:
    static_path = tmp_path / "static.json"
    loc_path = tmp_path / "loc.json"
    profile_path = tmp_path / "profile.json"

    _write_json(static_path, {"static_data": {"CRAFTER": {}}})
    _write_json(loc_path, {})
    _write_json(
        profile_path,
        {
            "skills": {
                "skill_target": {
                    "name": "Target",
                    "current_level": 1,
                    "current_xp": 0,
                    "target_level": 2,
                },
                "skill_support": {
                    "name": "Support",
                    "current_level": 1,
                    "current_xp": 0,
                    "target_level": 2,
                },
                "skill_done": {
                    "name": "Done",
                    "current_level": 2,
                    "current_xp": 0,
                    "target_level": 2,
                },
            },
            "crafters": {},
            "premium_account": False,
            "avoid_relics": False,
            "max_cross_skill_gap": 5,
        },
    )

    game = GameData(
        recipes=[],
        skills={
            "skill_target": SkillXPTable(skill="skill_target", xp_to_level=[100, 100]),
            "skill_support": SkillXPTable(skill="skill_support", xp_to_level=[100, 100]),
            "skill_done": SkillXPTable(skill="skill_done", xp_to_level=[100, 100]),
        },
        item_names={},
        recipe_to_station={},
        item_meta={},
        materials_config={},
        recipe_crafters={},
        crafter_tiers={},
    )

    monkeypatch.setattr(level_planner, "load_game_data", lambda *_args, **_kwargs: game)

    return LevelPlanner(
        str(static_path),
        str(loc_path),
        str(profile_path),
        str(tmp_path),
    )


def _make_recipe(key: str, outputs: dict, grants_xp: bool = True) -> Recipe:
    return Recipe(
        key=key,
        is_dev=False,
        skill="skill_support",
        unlock_at=0,
        difficulty=1,
        xp_multiplier=1.0,
        ingredients={},
        outputs=outputs,
        station=None,
        name=key,
        desc="",
        grants_xp=grants_xp,
    )


def test_synergy_support_from_steps_aggregates_support(planner: LevelPlanner) -> None:
    support_recipe = _make_recipe("recipe_support", {"item_support": 3})
    target_recipe = _make_recipe("recipe_target", {"item_target": 2})
    no_xp_recipe = _make_recipe("recipe_no_xp", {"item_no": 5}, grants_xp=False)

    craft_steps = [
        (support_recipe, 2, "skill_support"),
        (target_recipe, 1, "skill_target"),
        (no_xp_recipe, 1, "skill_support"),
    ]

    result = planner._synergy_support_from_steps(craft_steps, "skill_target")

    assert result == [("skill_support", "item_support", 6)]


def test_synergy_score_rewards_diversity(planner: LevelPlanner) -> None:
    assert planner._synergy_score([]) == 0.0
    one = planner._synergy_score([("skill_support", "item_support", 2)])
    two = planner._synergy_score(
        [
            ("skill_support", "item_support", 2),
            ("skill_done", "item_other", 10),
        ]
    )

    assert one > 0.0
    assert two > one


def test_pending_synergy_supports_filters_completed(planner: LevelPlanner) -> None:
    option = PlanStepOption(
        recipe_key="recipe_support",
        recipe_name="Support",
        crafter=None,
        crafts=1,
        xp_per_craft=10.0,
        total_xp=10.0,
        total_xp_chain=10.0,
        material_burden=0.0,
        materials=[],
        materials_qty=0,
        synergy_support=[
            ("skill_support", "item_support", 1),
            ("skill_target", "item_target", 1),
            ("skill_done", "item_done", 1),
        ],
    )

    pending = planner._pending_synergy_supports(option, "skill_target")

    assert pending == ["skill_support"]
