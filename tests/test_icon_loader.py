import bootstrap  # noqa: F401

from pathlib import Path

from PySide6 import QtWidgets

from paxdei_ui.icon_loader import IconRegistry

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
    b"\x00\x00\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _ensure_qapp() -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_icon_registry_loads_from_assets_dir(tmp_path: Path) -> None:
    _ensure_qapp()
    icon_path = tmp_path / "Config.png"
    icon_path.write_bytes(PNG_BYTES)

    registry = IconRegistry(tmp_path)
    icon = registry.icon_for("config")

    assert not icon.isNull()
