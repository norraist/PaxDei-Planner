# Pax Dei - Crafting Leveling Planner

## Overview
Pax Dei - Crafting Leveling Planner is a desktop companion that analyzes the official Static Data Bundle and localisation files to build efficient skill-by-skill leveling plans. It highlights the best recipes, required materials, and crafter prerequisites, then presents the results in an interactive UI with both a global checklist and per-skill breakdowns.

The application installs with a curated data bundle (static game data, localisation strings, XP tables, icons, default profile, and a sample plan). Users can refresh that bundle at any time without reinstalling the app, keeping leveling recommendations aligned with the latest game changes.

## Key Capabilities
- Imports the Pax Dei StaticDataBundle and localisation files to discover skills, recipes, stations, and XP tables.
- Evaluates recipe efficiency using success chance, XP multipliers, crafter ownership, and rarity penalties to produce multi-step plans.
- Provides a PySide-based UI with editable player profile, crafter ownership, and material toggles.
- Presents the best options per step, plus a consolidated shopping list and step-by-step checklist view.
- Bundles icons, materials metadata, and a default snapshot so the UI shows a plan immediately after installation.
- Supports on-demand data updates through a single "Check for data updates" button that downloads the latest bundle from GitHub releases.

## Getting Started
1. **Install** - Download the latest release from GitHub and run the Windows installer. It places the application under `Program Files\PaxDeiPlanner` and seeds user-editable config files under `%APPDATA%\PaxDeiPlanner`.
2. **Launch** - Start "Pax Dei Planner" from the Start menu. The application opens to the Config page.
3. **Configure** - Adjust current levels, target levels, and per-material toggles on the Config page. Crafter ownership can also be set here.
4. **Save** - Click **Save** to persist modifications. Configuration is stored in JSON files under `%APPDATA%\PaxDeiPlanner` so future updates and reinstallations keep personal data intact.
5. **Plan** - Use the toolbar's **Refresh plan** action. Progress is displayed in the status bar while the Level Planner evaluates every skill.
6. **Review** - Navigate between the global Checklist and individual skill pages to inspect options, nested material breakdowns, and XP details. JSON exports are written to the `out/` directory defined in `config/executor_config.json`.

## Updating Data
- Open the Config page and select **Check for data updates**. The application compares the local manifest with the latest GitHub release. If a newer bundle exists, a download prompt appears. Confirming the update replaces the bundled StaticDataBundle, localisation, XP tables, icons, default profile, and sample snapshot without touching saved personal configs.
- When a data update requires profile resets (for example, major skill tree revisions), the manifest will flag the requirement. The UI surfaces a warning before proceeding and offers to back up existing profile/material files.
- Manual updates are also possible: download the `data_bundle.zip` from the latest release, extract it into `%APPDATA%\PaxDeiPlanner\data_bundle`, and restart the application.

## Managing Profiles and Materials
- **Player profile** (`player_profile.json`) stores per-skill levels, XP, targets, premium flag, relic avoidance, and cross-skill gap settings. The Config page edits all of these fields. Advanced users can edit the JSON directly; the UI re-reads changes on launch.
- **Materials config** (`materials_config.json`) contains a catalog of materials with names, descriptions, and enabled flags. Disable any material that should be excluded from planning.
- **Snapshots** - The UI saves the most recent plan to `%APPDATA%\PaxDeiPlanner\out\level_plan.ui_plan.json`. On startup it restores this snapshot, falling back to the bundled default if none exists.

## Frequently Asked Questions
- **Where are exports saved?** The executor writes JSON files (`level_plan.json`, `level_plan_materials.json`, `level_plan_steps.json`) into the `out/` directory specified in `config/executor_config.json`. The default location is `%APPDATA%\PaxDeiPlanner\out`.
- **Does the application work offline?** Yes. The installer packages a complete data bundle and default plan. Internet access is only required when fetching updates.
- **How are planner updates delivered?** Code updates arrive through new installer releases. Data updates (StaticDataBundle, localisation, XP tables, icons, default profile, snapshot) arrive through the in-app updater or manual bundle download.
- **Can multiple profiles be maintained?** Duplicate `player_profile.json` and `materials_config.json` under `%APPDATA%\PaxDeiPlanner`, then swap them manually or via script before launching the UI. Future versions may add profile management directly within the app.

## Support
- Report issues or request features on the project's GitHub issue tracker. Attach planner logs (`out/level_plan_steps.json`), profile JSON, and manifest version to help reproduce problems.

## Known Issues
- XP calculations struggle with "impossible" recipes that are technically available but not actually craftable yet. 

## Disclaimer

Pax Dei and all related trademarks, assets, and intellectual property are the
property of Mainframe Industries. This project is a fan-made tool and is not
affiliated with or endorsed by Mainframe Industries.

## License

The source code of this project is licensed under the MIT License.

The distributed executable includes data derived from Pax Dei and is provided
for personal, non-commercial fan use only. Redistribution or commercial use of
the bundled data is not permitted.

Pax Dei and all related assets and data are the property of Mainframe Industries.
This project is fan-made and not affiliated with or endorsed by Mainframe Industries.
