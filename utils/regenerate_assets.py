#!/usr/bin/env python3
"""
Helper CLI to refresh derived artifacts (profile, materials config, XP tables)
after updating the raw `source_data` dumps.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import bootstrap  # noqa: F401
from paxdei_planner.data_loader import load_game_data

ROOT = Path(__file__).resolve().parent.parent
UTILS_DIR = Path(__file__).resolve().parent
DEFAULT_STATIC = ROOT / "source_data" / "staticdatabundle" / "StaticDataBundle.json"
DEFAULT_LOC = ROOT / "source_data" / "localisation" / "localisation_en.json"
DEFAULT_PROFILE = ROOT / "config" / "player_profile.json"
DEFAULT_MATERIALS = ROOT / "config" / "materials_config.json"
DEFAULT_XP_CFG = ROOT / "config" / "xp_tables_config.json"


def _run(cmd: list[str]) -> None:
    print(f"[run] {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def _generate_profile(static: Path, loc: Path, out_profile: Path, base: Path | None) -> None:
    cmd = [
        sys.executable,
        str(UTILS_DIR / "generate_profile.py"),
        "--static",
        str(static),
        "--loc",
        str(loc),
        "--out",
        str(out_profile),
    ]
    if base:
        cmd.extend(["--base", str(base)])
    _run(cmd)


def _ensure_materials(static: Path, loc: Path, materials_cfg: Path) -> None:
    load_game_data(str(static), str(loc), materials_config=str(materials_cfg))


def _generate_xp_tables(cfg_path: Path) -> None:
    cmd = [
        sys.executable,
        str(UTILS_DIR / "generate_xp_tables.py"),
        "--config",
        str(cfg_path),
    ]
    _run(cmd)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Regenerate config + XP table artifacts after updating source data.")
    ap.add_argument("--static", default=str(DEFAULT_STATIC), help="Path to StaticDataBundle.json")
    ap.add_argument("--loc", default=str(DEFAULT_LOC), help="Path to localisation_en.json")
    ap.add_argument("--profile-out", default=str(DEFAULT_PROFILE), help="Output player_profile.json path")
    ap.add_argument("--materials-config", default=str(DEFAULT_MATERIALS), help="materials_config.json path")
    ap.add_argument("--xp-config", default=str(DEFAULT_XP_CFG), help="xp_tables_config.json path")
    ap.add_argument("--base-profile", default=None, help="Optional existing profile to merge when regenerating")
    ap.add_argument("--skip-profile", action="store_true", help="Skip regenerating player_profile.json")
    ap.add_argument("--skip-materials", action="store_true", help="Skip materials_config refresh")
    ap.add_argument("--skip-xp", action="store_true", help="Skip XP table generation")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    static = Path(args.static)
    loc = Path(args.loc)
    profile_out = Path(args.profile_out)
    materials_cfg = Path(args.materials_config)
    xp_cfg = Path(args.xp_config)
    base_profile = Path(args.base_profile) if args.base_profile else None

    if not args.skip_profile:
        profile_out.parent.mkdir(parents=True, exist_ok=True)
        _generate_profile(static, loc, profile_out, base_profile)
    else:
        print("[skip] profile regeneration")

    if not args.skip_materials:
        materials_cfg.parent.mkdir(parents=True, exist_ok=True)
        _ensure_materials(static, loc, materials_cfg)
        print(f"[ok] materials_config ensured at {materials_cfg}")
    else:
        print("[skip] materials_config regeneration")

    if not args.skip_xp:
        xp_cfg.parent.mkdir(parents=True, exist_ok=True)
        _generate_xp_tables(xp_cfg)
    else:
        print("[skip] XP table generation")


if __name__ == "__main__":
    main()
