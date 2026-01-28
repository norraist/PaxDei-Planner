# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

if "__file__" in globals():
    spec_path = Path(__file__).resolve()
else:
    spec_path = Path.cwd() / "packaging" / "windows" / "paxdei_ui.spec"

from PyInstaller.building.build_main import Analysis, COLLECT, EXE, PYZ
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

project_root = spec_path.parents[2]
bundle_dir = project_root / "data_bundle"
config_dir = project_root / "config"

bundle_data = [(str(bundle_dir), "data_bundle")] if bundle_dir.exists() else []
config_files = [(str(config_dir / "executor_config.json"), "config")] if (config_dir / "executor_config.json").exists() else []

hidden = collect_submodules("paxdei_planner") + collect_submodules("paxdei_ui")
datas = collect_data_files("PySide6")

a = Analysis(
    [str(project_root / "src" / "paxdei_ui" / "app.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas + bundle_data + config_files,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PaxDeiPlanner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "assets" / "icons" / "app.ico") if (project_root / "assets" / "icons" / "app.ico").exists() else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="paxdei_planner_ui",
)
