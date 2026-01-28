import json
from pathlib import Path

import pytest

import bootstrap  # noqa: F401

from paxdei_ui.paths import load_executor_config


def test_load_executor_config_falls_back_to_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    appdata = tmp_path / "appdata"
    appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.chdir(tmp_path)

    cfg = load_executor_config(Path("config/executor_config.json"))

    assert cfg.profile.parent == appdata / "PaxDeiPlanner"
    assert cfg.plan_json.name == "level_plan.json"


def test_load_executor_config_uses_bundle_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    appdata = tmp_path / "appdata"
    appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))

    bundle_cfg = tmp_path / "data_bundle" / "config"
    bundle_cfg.mkdir(parents=True)
    config_path = bundle_cfg / "executor_config.json"
    config_path.write_text(
        json.dumps(
            {
                "bundle_root": ".",
                "static": "data_bundle/source_data/staticdatabundle/StaticDataBundle.json",
                "loc": "data_bundle/source_data/localisation/localisation_en.json",
                "profile": "%APPDATA%/PaxDeiPlanner/profile.json",
                "materials_config": "%APPDATA%/PaxDeiPlanner/materials_config.json",
                "out_dir": "%APPDATA%/PaxDeiPlanner/out",
                "plan_json": "%APPDATA%/PaxDeiPlanner/out/custom_plan.json",
                "shopping_json": "%APPDATA%/PaxDeiPlanner/out/level_plan_materials.json",
                "steps_json": "%APPDATA%/PaxDeiPlanner/out/level_plan_steps.json",
                "xp_tables_dir": "%APPDATA%/PaxDeiPlanner/xp_tables",
                "topk": 3,
                "skills": [],
                "default_snapshot": "data_bundle/default_snapshot.json",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    cfg = load_executor_config(Path("config/executor_config.json"))

    assert cfg.plan_json.name == "custom_plan.json"


def test_load_executor_config_uses_internal_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    appdata = tmp_path / "appdata"
    appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))

    internal_cfg = tmp_path / "_internal" / "config"
    internal_cfg.mkdir(parents=True)
    config_path = internal_cfg / "executor_config.json"
    config_path.write_text(
        json.dumps(
            {
                "bundle_root": ".",
                "static": "data_bundle/source_data/staticdatabundle/StaticDataBundle.json",
                "loc": "data_bundle/source_data/localisation/localisation_en.json",
                "profile": "%APPDATA%/PaxDeiPlanner/profile.json",
                "materials_config": "%APPDATA%/PaxDeiPlanner/materials_config.json",
                "out_dir": "%APPDATA%/PaxDeiPlanner/out",
                "plan_json": "%APPDATA%/PaxDeiPlanner/out/internal_plan.json",
                "shopping_json": "%APPDATA%/PaxDeiPlanner/out/level_plan_materials.json",
                "steps_json": "%APPDATA%/PaxDeiPlanner/out/level_plan_steps.json",
                "xp_tables_dir": "%APPDATA%/PaxDeiPlanner/xp_tables",
                "topk": 3,
                "skills": [],
                "default_snapshot": "data_bundle/default_snapshot.json",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    cfg = load_executor_config(Path("config/executor_config.json"))

    assert cfg.bundle_root == tmp_path / "_internal"
    assert cfg.plan_json.name == "internal_plan.json"
