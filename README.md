# Pax Dei – Crafting Leveling Planner

This tool computes material-efficient leveling plans per crafting skill using your game's static JSON data.

## Features
- Parses `StaticDataBundle.json` and `localisation_en.json`
- Uses a calibrated XP simulator (success chance, pre-cap success XP, trivial post-cap, failure XP)
- Respects unlocks (`UnlockAtSkillLevel`), `SkillDifficulty`, `IsDev`, stations/recipes mapping
- Greedy + 1-step lookahead planner; optional Dijkstra *hook* (stub for extension)
- Outputs per-skill step plans and a global shopping list (CSV + console)

## Quick start

```bash
python -m paxdei_planner.cli   --static /mnt/data/StaticDataBundle.json   --loc /mnt/data/localisation_en.json   --profile /mnt/data/leveling_planner/sample_profile.json   --weights /mnt/data/leveling_planner/sample_weights.json   --targets /mnt/data/leveling_planner/sample_targets.json   --out /mnt/data/leveling_planner/out
```

> Tip: run `python -m pip install -e .` from the repository root (or set `PYTHONPATH=src`) so the `paxdei_planner` package is importable when launching modules directly.

The tool prints a summary and writes CSV files into `--out`.

## IDE-friendly executor

To avoid juggling CLI flags inside your IDE, run:

```bash
python executor.py
```

The first run generates `executor_config.json`; edit the paths/mode (single-skill vs. multi-skill LevelPlanner), then re-run to execute with those settings. Multi-skill mode now also emits a `shopping_csv` file that aggregates the top option per step.

For XP table generation you can also run `python -m paxdei_planner.generate_xp_tables` without CLI flags: the first run writes `xp_tables_config.json`, which you can edit and re-run from the IDE. The multi-skill executor additionally writes a `steps_txt` file that lists every gather/craft sub-step (with nested breakdowns) for quick reference inside your IDE.

## Inputs
- **StaticDataBundle.json**: game data (recipes, stations, skills, XP tables)
- **localisation_en.json**: names and descriptions for display
- **profile.json**: your current state per skill and owned stations
- **premium_account** (in profile): boolean flag for +50% XP boost from a premium account
- **avoid_relics** (in profile): boolean flag to skip any plan steps that require relic-tier materials
- **max_cross_skill_gap** (in profile): maximum allowed difference between current and required level when another skill is needed as a prerequisite (default 5)
- **materials_config.json**: generated automatically (next to your profile) on first run; lists every material with name/description and an `enabled` flag so you can globally disable items you never want planned
- **weights.json**: per-item material weights/prices (default 1.0 if missing)
- **targets.json**: desired target level per skill (omit to use +5 levels as default)

## Notes
- XP-to-level tables are auto-discovered from `StaticDataBundle.json`. If the tool cannot find them, it will fail with a helpful message reporting candidate paths.
- Only `IsDev=false` recipes are considered.
- The planner uses a universal shape with tier-aware constants that we fitted together.
