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

## Repository layout
- `source_data/staticdatabundle` and `source_data/localisation`: raw game dumps that feed every CLI.
- `config/`: checked-in `player_profile.json` + the generated `materials_config.json` that planners expect.
- `out/`: level-plan CSV/TXT artifacts only (multi-skill executor default output).
- `xp_tables/`: generated XP table CSVs (written by `utils/generate_xp_tables.py` or the executor).
- `tests/web_validation/`: XP table validation harness (`run_web_validation.py`, cached golden data, and results).
- `utils/`: helper CLIs such as `generate_profile.py` and troubleshooting scripts (`scan_keys.py`, etc.).

## IDE-friendly executor

To avoid juggling CLI flags inside your IDE, run:

```bash
python executor.py
```

The first run generates `config/executor_config.json`; edit the paths/mode (single-skill vs. multi-skill LevelPlanner), then re-run to execute with those settings. Multi-skill mode now also emits a `shopping_csv` file that aggregates the top option per step.

For XP table generation you can also run `python utils/generate_xp_tables.py` without CLI flags: the first run writes `config/xp_tables_config.json`, which you can edit and re-run from the IDE. The generator now writes into the top-level `xp_tables/` directory (and the executor defaults there as well). The multi-skill executor additionally writes a `steps_txt` file that lists every gather/craft sub-step (with nested breakdowns) for quick reference inside your IDE.

To refresh *all* derived artifacts after dropping in a new `StaticDataBundle.json`/`localisation_en.json`, use:

```bash
python utils/regenerate_assets.py
```

It regenerates `config/player_profile.json`, ensures `config/materials_config.json`, and re-runs the XP-table generator (customize paths or skip steps with the provided flags).

## XP table validation

Use the harness under `tests/web_validation` to compare generated XP tables against the golden web data:

```bash
python tests/web_validation/run_web_validation.py --pred-dir xp_tables
```

It reuses the cached CDN fetcher (`web_golden_fetch_json.py`) and writes diffs into `tests/web_validation/results/`. Pass `--skip-fetch` when you only want to diff against the last downloaded golden tables.

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
