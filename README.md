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
python -m planner.cli   --static /mnt/data/StaticDataBundle.json   --loc /mnt/data/localisation_en.json   --profile /mnt/data/leveling_planner/sample_profile.json   --weights /mnt/data/leveling_planner/sample_weights.json   --targets /mnt/data/leveling_planner/sample_targets.json   --out /mnt/data/leveling_planner/out
```

The tool prints a summary and writes CSV files into `--out`.

## Inputs
- **StaticDataBundle.json**: game data (recipes, stations, skills, XP tables)
- **localisation_en.json**: names and descriptions for display
- **profile.json**: your current state per skill and owned stations
- **weights.json**: per-item material weights/prices (default 1.0 if missing)
- **targets.json**: desired target level per skill (omit to use +5 levels as default)

## Notes
- XP-to-level tables are auto-discovered from `StaticDataBundle.json`. If the tool cannot find them, it will fail with a helpful message reporting candidate paths.
- Only `IsDev=false` recipes are considered.
- The planner uses a universal shape with tier-aware constants that we fitted together.
