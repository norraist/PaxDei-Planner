import bootstrap
from collections import defaultdict
from paxdei_planner.level_planner import LevelPlanner
planner = LevelPlanner(''source_data/staticdatabundle/StaticDataBundle.json'',''source_data/localisation/localisation_en.json'',''config/player_profile.json'',''xp_tables'')
plan = planner.plan(top_k=3)
item_usage = defaultdict(list)
for idx, step in enumerate(plan, 1):
    if not step.options:
        continue
    opt = step.options[0]
    for item, qty in opt.materials:
        item_usage[item].append((idx, step.skill, step.from_level, step.to_level, qty))
links = defaultdict(list)
for idx, step in enumerate(plan, 1):
    if not step.options:
        continue
    opt = step.options[0]
    for _, (_, _, _, _, qty) in opt.craft_summary:
        pass
