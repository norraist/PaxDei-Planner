import runpy
from pathlib import Path

import pytest


def test_app_script_import_does_not_fail() -> None:
    app_path = Path(__file__).resolve().parents[1] / "src" / "paxdei_ui" / "app.py"
    runpy.run_path(str(app_path), run_name="__not_main__")


def test_main_module_imports() -> None:
    module_path = Path(__file__).resolve().parents[1] / "src" / "paxdei_ui" / "__main__.py"
    runpy.run_path(str(module_path), run_name="__not_main__")


def test_app_script_import_from_non_repo_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app_path = Path(__file__).resolve().parents[1] / "src" / "paxdei_ui" / "app.py"
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(app_path), run_name="__not_main__")


def test_main_module_import_from_non_repo_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module_path = Path(__file__).resolve().parents[1] / "src" / "paxdei_ui" / "__main__.py"
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(module_path), run_name="__not_main__")
