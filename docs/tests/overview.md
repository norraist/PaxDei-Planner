# Test Suite Overview

The test suite validates key planner behaviors in a fast, unit-style setup. It focuses on
recipe eligibility rules and the leveling planner's synergy calculations without requiring
real game data bundles.

## Covered behaviors

- Rejects recipes that yield zero XP when planning skill progression.
- Aggregates cross-skill synergy outputs from crafted item chains.
- Scores synergy lists so diversified support is favored.
- Filters pending synergy supports by target skill and completion status.
- Drives the "Check for data updates" button state and messaging in the Config page.
- Verifies the bundle update worker handles no-op updates and versioned bundle refreshes.
- Ensures the UI entry script can be executed without relative-import failures.

## Error and edge cases

- Zero-XP recipes raise a runtime error during planning.
- Synergy aggregation ignores recipes that do not grant XP or belong to the target skill.
- Pending synergy support excludes skills already at or above their target level.
- Update checks re-enable the button and surface success/failure messages.
- Bundle updates skip downloads when already up to date and invoke refreshes for newer versions.

## Test isolation

- Tests create temporary JSON fixtures for static data, localization, and profiles.
- `load_game_data` is monkeypatched to return small in-memory `GameData` stubs.
- No network calls or external services are used.

## Running the tests

- `.\.venv\Scripts\python.exe -m pytest`
- `.\.venv\Scripts\python.exe -m coverage run --branch -m pytest`
- `.\.venv\Scripts\python.exe -m coverage report -m`
