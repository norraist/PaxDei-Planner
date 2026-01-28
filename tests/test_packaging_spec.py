from pathlib import Path


def test_pyinstaller_spec_includes_src_path() -> None:
    spec_path = Path(__file__).resolve().parents[1] / "packaging" / "windows" / "paxdei_ui.spec"
    text = spec_path.read_text(encoding="utf-8")
    assert "src_root" in text
    assert "pathex" in text
    assert "src_root" in text.split("pathex", 1)[1]
