from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

_DIR = Path(__file__).resolve().parent / "icons"


def icon_file(kind: str, large: bool = False) -> str:
    name = "open.svg" if kind == "open" else "closed.svg"
    path = _DIR / name
    return str(path)


def pixbuf(kind: str, size: int = 36) -> GdkPixbuf.Pixbuf:
    path = icon_file(kind)
    return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True)
