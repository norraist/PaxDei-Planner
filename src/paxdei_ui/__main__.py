from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    _pkg_root = Path(__file__).resolve().parents[1]
    if str(_pkg_root) not in sys.path:
        sys.path.insert(0, str(_pkg_root))
    __package__ = "paxdei_ui"

from .app import main


if __name__ == "__main__":
    raise SystemExit(main())
