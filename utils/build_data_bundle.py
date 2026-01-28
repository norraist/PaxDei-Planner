from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import zipfile
from pathlib import Path
from typing import Dict, Iterable

from paxdei_planner.bundle import compute_sha256, DEFAULT_BUNDLE_DIR
from paxdei_planner.level_planner import LevelPlanner
from paxdei_ui.plan_service import PlanSnapshot
from paxdei_ui.snapshot_store import save_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble the distributable data bundle.")
    parser.add_argument("--bundle-dir", default=DEFAULT_BUNDLE_DIR, help="Destination directory for the bundle contents.")
    parser.add_argument("--archive", help="Optional zip archive path (relative paths resolve next to bundle dir).")
    parser.add_argument("--version", help="Bundle version string (defaults to YYYYMMDDHHMM).")
    parser.add_argument("--static-root", default="source_data/staticdatabundle", help="Directory containing StaticDataBundle.json.")
    parser.add_argument("--loc-root", default="source_data/localisation", help="Directory containing localisation files.")
    parser.add_argument("--xp-dir", default="xp_tables", help="XP tables directory to copy into the bundle.")
    parser.add_argument("--icons-dir", default="assets/icons", help="Icons directory to copy into the bundle.")
    parser.add_argument("--materials", default="config/materials_config.json", help="Materials config JSON path.")
    parser.add_argument("--profile", default="config/player_profile.json", help="Source profile JSON used as template.")
    parser.add_argument("--premium", action="store_true", help="Keep premium_account enabled (defaults to false).")
    parser.add_argument("--start-level", type=int, default=0, help="Default current level for every skill in the bundled profile.")
    parser.add_argument("--target-level", type=int, default=40, help="Default target level for every skill in the bundled profile.")
    parser.add_argument("--plan-topk", type=int, default=3, help="Top-K options to compute when generating the default snapshot.")
    parser.add_argument("--clean", action="store_true", help="Remove bundle dir before rebuilding.")
    return parser.parse_args()


def _copy_path(src: Path, dest: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(f"Source path missing: {src}")
    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def _sanitize_profile(profile_path: Path, premium: bool, start_level: int, target_level: int) -> Dict[str, object]:
    with profile_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["premium_account"] = bool(premium)
    payload["avoid_relics"] = bool(payload.get("avoid_relics", False))
    payload["max_cross_skill_gap"] = int(payload.get("max_cross_skill_gap", 5))
    skills = payload.get("skills", {})
    for node in skills.values():
        node["current_level"] = start_level
        node["current_xp"] = 0
        node["target_level"] = target_level
    payload["skills"] = skills
    return payload


def _write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    tmp.replace(path)


def _build_manifest(bundle_root: Path, version: str) -> Path:
    now = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    files: Dict[str, Dict[str, object]] = {}
    for file_path in _iter_files(bundle_root):
        rel = file_path.relative_to(bundle_root).as_posix()
        if rel == "manifest.json":
            continue
        files[rel] = {"size": file_path.stat().st_size, "sha256": compute_sha256(file_path)}
    manifest = {"version": version, "generated_at": now, "files": files}
    manifest_path = bundle_root / "manifest.json"
    _write_json(manifest_path, manifest)
    return manifest_path


def _iter_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file():
            yield path


def _generate_snapshot(bundle_root: Path, topk: int, snapshot_path: Path) -> None:
    static_path = bundle_root / "source_data" / "staticdatabundle" / "StaticDataBundle.json"
    loc_path = bundle_root / "source_data" / "localisation" / "localisation_en.json"
    profile_path = bundle_root / "config" / "player_profile.json"
    materials_path = bundle_root / "config" / "materials_config.json"
    xp_dir = bundle_root / "xp_tables"
    xp_dir.mkdir(parents=True, exist_ok=True)
    planner = LevelPlanner(
        str(static_path),
        str(loc_path),
        str(profile_path),
        str(xp_dir),
        materials_config_path=str(materials_path),
    )
    plan = planner.plan(top_k=topk)
    profile_data = getattr(planner, "profile", {})
    skill_names = {k: str(node.get("name", k)) for k, node in profile_data.get("skills", {}).items()}
    item_names = getattr(planner, "item_names", {})
    snapshot = PlanSnapshot(plan, skill_names, item_names)
    save_snapshot(snapshot, snapshot_path)


def _write_archive(bundle_root: Path, archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in _iter_files(bundle_root):
            rel = path.relative_to(bundle_root).as_posix()
            zf.write(path, arcname=rel)


def main() -> None:
    args = parse_args()
    bundle_root = Path(args.bundle_dir).resolve()
    if bundle_root.exists():
        if not args.clean:
            raise SystemExit(f"Bundle dir {bundle_root} already exists. Pass --clean to rebuild.")
        shutil.rmtree(bundle_root)
    bundle_root.mkdir(parents=True, exist_ok=True)

    _copy_path(Path(args.static_root), bundle_root / "source_data" / "staticdatabundle")
    _copy_path(Path(args.loc_root), bundle_root / "source_data" / "localisation")
    xp_src = Path(args.xp_dir)
    if xp_src.is_file():
        db_path = xp_src
    else:
        db_path = xp_src / "xp_tables.db"
    if not db_path.exists():
        raise FileNotFoundError(
            f"XP tables database not found: {db_path}. "
            "Regenerate with utils/generate_xp_tables.py to create xp_tables.db."
        )
    _copy_path(db_path, bundle_root / "xp_tables" / "xp_tables.db")
    _copy_path(Path(args.icons_dir), bundle_root / "assets" / "icons")
    _copy_path(Path(args.materials), bundle_root / "config" / "materials_config.json")

    sanitized_profile = _sanitize_profile(Path(args.profile), args.premium, args.start_level, args.target_level)
    _write_json(bundle_root / "config" / "player_profile.json", sanitized_profile)

    snapshot_path = bundle_root / "default_snapshot.json"
    _generate_snapshot(bundle_root, args.plan_topk, snapshot_path)

    version = args.version or dt.datetime.utcnow().strftime("%Y%m%d%H%M")
    manifest_path = _build_manifest(bundle_root, version)

    if args.archive:
        archive_path = Path(args.archive)
        if not archive_path.is_absolute():
            archive_path = bundle_root.parent / archive_path
        _write_archive(bundle_root, archive_path)
        print(f"[bundle] Wrote archive to {archive_path}")

    print(f"[bundle] Generated manifest at {manifest_path}")
    print(f"[bundle] Bundle ready under {bundle_root}")


if __name__ == "__main__":
    main()
