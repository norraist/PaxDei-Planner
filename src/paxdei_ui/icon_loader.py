from __future__ import annotations

from pathlib import Path
from typing import Dict

from PySide6 import QtGui

DEFAULT_ICON_DIR = Path("data_bundle/assets/icons")
FALLBACK_ICON_DIR = Path("assets/icons")


def _normalize(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


class IconRegistry:
    def __init__(self, assets_dir: Path | None = None) -> None:
        if assets_dir is not None and assets_dir.exists():
            resolved = assets_dir
        else:
            resolved = DEFAULT_ICON_DIR if DEFAULT_ICON_DIR.exists() else FALLBACK_ICON_DIR
        self.assets_dir = resolved
        self._direct: Dict[str, QtGui.QIcon] = {}
        self._normalized: Dict[str, QtGui.QIcon] = {}
        self._load_directory()

    def _load_directory(self) -> None:
        if not self.assets_dir.exists():
            return
        for candidate in self.assets_dir.iterdir():
            if not candidate.is_file():
                continue
            if candidate.suffix.lower() not in {".png", ".ico"}:
                continue
            icon = QtGui.QIcon(str(candidate))
            stem = candidate.stem
            self._direct[stem.lower()] = icon
            self._normalized[_normalize(stem)] = icon

    def icon_for(self, key: str, fallback: QtGui.QIcon | None = None) -> QtGui.QIcon:
        candidates = [
            key,
            key.lower(),
            key.replace(" ", "_"),
            key.replace(" ", "-"),
        ]
        for cand in candidates:
            icon = self._direct.get(cand.lower())
            if icon:
                return icon
            normalized = _normalize(cand)
            icon = self._normalized.get(normalized)
            if icon:
                return icon
        return fallback or QtGui.QIcon()
