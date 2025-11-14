"""
Qt-based desktop UI for the Pax Dei leveling planner.

The package exposes ``paxdei_planner_ui`` entry points that orchestrate Qt widgets,
load profile/materials JSON files, run ``LevelPlanner`` in the background, and
render the "top three next steps" cards per skill.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
