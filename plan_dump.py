import bootstrap
from paxdei_planner.level_planner import LevelPlanner

def main() -> None:
    planner = LevelPlanner(
        "source_data/staticdatabundle/StaticDataBundle.json",
        "source_data/localisation/localisation_en.json",
        "config/player_profile.json",
        "xp_tables",
    )
    plan = planner.plan(top_k=3)
    for idx, step in enumerate(plan, 1):
        print(f"Step {idx}: {step.skill} {step.from_level}->{step.to_level} note={step.note}")
        if step.options:
            for opt in step.options[:3]:
                print("   ", opt.recipe_key, opt.recipe_name, opt.materials[:3])

if __name__ == "__main__":
    main()
