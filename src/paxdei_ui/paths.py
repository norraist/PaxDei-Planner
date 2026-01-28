from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_EXECUTOR_CONFIG = Path("config/executor_config.json")


def _default_executor_config() -> Dict[str, Any]:
    return {
        "bundle_root": ".",
        "static": "data_bundle/source_data/staticdatabundle/StaticDataBundle.json",
        "loc": "data_bundle/source_data/localisation/localisation_en.json",
        "profile": "%APPDATA%/PaxDeiPlanner/profile.json",
        "materials_config": "%APPDATA%/PaxDeiPlanner/materials_config.json",
        "out_dir": "%APPDATA%/PaxDeiPlanner/out",
        "plan_json": "%APPDATA%/PaxDeiPlanner/out/level_plan.json",
        "shopping_json": "%APPDATA%/PaxDeiPlanner/out/level_plan_materials.json",
        "steps_json": "%APPDATA%/PaxDeiPlanner/out/level_plan_steps.json",
        "xp_tables_dir": "%APPDATA%/PaxDeiPlanner/xp_tables",
        "topk": 3,
        "skills": [],
        "default_snapshot": "data_bundle/default_snapshot.json",
    }


@dataclass(slots=True)
class ExecutorConfig:
    bundle_root: Path
    static: Path
    loc: Path
    profile: Path
    materials_config: Path
    plan_json: Path
    shopping_json: Path
    steps_json: Path
    xp_tables_dir: Path
    out_dir: Path
    topk: int = 3
    bundle_manifest_url: Optional[str] = None
    bundle_archive_url: Optional[str] = None
    default_snapshot: Optional[Path] = None

    @classmethod
    def from_json(cls, data: Dict[str, Any], root: Path) -> "ExecutorConfig":
        def _expand(value: str) -> Path:
            expanded = os.path.expandvars(os.path.expanduser(value))
            return Path(expanded)

        def _resolve(value: str | None, default: str) -> Path:
            raw = value or default
            p = _expand(raw)
            return p if p.is_absolute() else (root / p)

        bundle_root = _resolve(data.get("bundle_root"), ".")

        def _bundle(value: str | None, default: str) -> Path:
            raw = value or default
            p = _expand(raw)
            return p if p.is_absolute() else (bundle_root / p)

        static = _bundle(data.get("static"), "source_data/staticdatabundle/StaticDataBundle.json")
        loc_value = data.get("loc")
        if loc_value:
            loc = Path(loc_value)
            if not loc.is_absolute():
                loc = _bundle(loc_value, "source_data/localisation/localisation_en.json")
        else:
            loc = _bundle(None, "source_data/localisation/localisation_en.json")
        profile = _bundle(data.get("profile"), "config/player_profile.json")
        materials_config = _bundle(data.get("materials_config"), "config/materials_config.json")
        plan_value = data.get("plan_json") or data.get("plan_csv")
        shopping_value = data.get("shopping_json") or data.get("shopping_csv")
        steps_value = data.get("steps_json") or data.get("steps_txt")
        plan_json = _resolve(plan_value, "out/level_plan.json")
        shopping_json = _resolve(shopping_value, "out/level_plan_materials.json")
        steps_json = _resolve(steps_value, "out/level_plan_steps.json")
        xp_tables_dir = _resolve(data.get("xp_tables_dir"), "xp_tables")
        out_dir = _resolve(data.get("out_dir"), "out")
        topk = int(data.get("topk", 3))
        manifest_url = data.get("bundle_manifest_url")
        archive_url = data.get("bundle_archive_url")
        default_snapshot = None
        snapshot_value = data.get("default_snapshot")
        if snapshot_value:
            snap_path = _expand(snapshot_value)
            if snap_path.is_absolute():
                default_snapshot = snap_path
            else:
                default_snapshot = _bundle(snapshot_value, snapshot_value)
        return cls(
            bundle_root=bundle_root,
            static=static,
            loc=loc,
            profile=profile,
            materials_config=materials_config,
            plan_json=plan_json,
            shopping_json=shopping_json,
            steps_json=steps_json,
            xp_tables_dir=xp_tables_dir,
            out_dir=out_dir,
            topk=topk,
            bundle_manifest_url=manifest_url,
            bundle_archive_url=archive_url,
            default_snapshot=default_snapshot,
        )


def load_executor_config(path: Path | None = None) -> ExecutorConfig:
    cfg_path = Path(path or DEFAULT_EXECUTOR_CONFIG)
    if not cfg_path.is_absolute():
        cfg_path = (Path.cwd() / cfg_path).resolve()
    root = cfg_path.parent
    if root.name == "config":
        root = root.parent

    if not cfg_path.exists():
        fallback_paths = [
            root / "data_bundle" / "config" / "executor_config.json",
            root / "config" / "executor_config.json",
        ]
        for candidate in fallback_paths:
            if candidate.exists():
                cfg_path = candidate
                root = cfg_path.parent
                if root.name == "config":
                    root = root.parent
                break
        else:
            return ExecutorConfig.from_json(_default_executor_config(), root.resolve())

    with cfg_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return ExecutorConfig.from_json(data, root.resolve())
