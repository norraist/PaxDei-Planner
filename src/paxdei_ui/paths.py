from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

DEFAULT_EXECUTOR_CONFIG = Path("config/executor_config.json")


@dataclass(slots=True)
class ExecutorConfig:
    static: Path
    loc: Path
    profile: Path
    materials_config: Path
    plan_csv: Path
    shopping_csv: Path
    steps_txt: Path
    xp_tables_dir: Path
    out_dir: Path
    topk: int = 3

    @classmethod
    def from_json(cls, data: Dict[str, Any], root: Path) -> "ExecutorConfig":
        def _resolve(value: str | None, default: str) -> Path:
            raw = value or default
            p = Path(raw)
            return p if p.is_absolute() else (root / p)

        static = _resolve(data.get("static"), "source_data/staticdatabundle/StaticDataBundle.json")
        loc = _resolve(
            data.get("loc"),
            "source_data/localisation/localisation_en.json",
        )
        profile = _resolve(data.get("profile"), "config/player_profile.json")
        materials_config = _resolve(data.get("materials_config"), "config/materials_config.json")
        plan_csv = _resolve(data.get("plan_csv"), "out/level_plan.csv")
        shopping_csv = _resolve(data.get("shopping_csv"), "out/level_plan_materials.csv")
        steps_txt = _resolve(data.get("steps_txt"), "out/level_plan_steps.txt")
        xp_tables_dir = _resolve(data.get("xp_tables_dir"), "xp_tables")
        out_dir = _resolve(data.get("out_dir"), "out")
        topk = int(data.get("topk", 3))
        return cls(
            static=static,
            loc=loc,
            profile=profile,
            materials_config=materials_config,
            plan_csv=plan_csv,
            shopping_csv=shopping_csv,
            steps_txt=steps_txt,
            xp_tables_dir=xp_tables_dir,
            out_dir=out_dir,
            topk=topk,
        )


def load_executor_config(path: Path | None = None) -> ExecutorConfig:
    cfg_path = Path(path or DEFAULT_EXECUTOR_CONFIG)
    if not cfg_path.is_absolute():
        cfg_path = (Path.cwd() / cfg_path).resolve()
    root = cfg_path.parent
    if root.name == "config":
        root = root.parent
    with cfg_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return ExecutorConfig.from_json(data, root.resolve())
