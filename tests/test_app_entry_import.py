import runpy
from pathlib import Path


def test_app_script_import_does_not_fail() -> None:
    app_path = Path(__file__).resolve().parents[1] / "src" / "paxdei_ui" / "app.py"
    runpy.run_path(str(app_path), run_name="__not_main__")
