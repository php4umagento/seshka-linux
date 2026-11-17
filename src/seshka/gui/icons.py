from __future__ import annotations

import tempfile
from pathlib import Path

# Simple SVG icons: closed nest (clean) vs open nest (leftovers).
CLOSED_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
  <ellipse cx="32" cy="40" rx="18" ry="16" fill="#c4784a"/>
  <ellipse cx="32" cy="26" rx="14" ry="14" fill="#d99262"/>
  <circle cx="27" cy="24" r="2" fill="#3b2a1f"/>
  <circle cx="37" cy="24" r="2" fill="#3b2a1f"/>
  <path d="M28 30 Q32 34 36 30" stroke="#3b2a1f" stroke-width="1.5" fill="none"/>
</svg>
"""

OPEN_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
  <ellipse cx="32" cy="44" rx="18" ry="14" fill="#c4784a"/>
  <ellipse cx="32" cy="22" rx="14" ry="12" fill="#d99262"/>
  <rect x="18" y="30" width="28" height="8" rx="2" fill="#a85f35"/>
  <circle cx="27" cy="20" r="2" fill="#3b2a1f"/>
  <circle cx="37" cy="20" r="2" fill="#3b2a1f"/>
  <circle cx="32" cy="36" r="3" fill="#f0c36a"/>
</svg>
"""

_cache: dict[str, str] = {}


def icon_path(kind: str) -> str:
    """Write SVG to a temp file once and return its path (AppIndicator wants a file)."""
    if kind in _cache and Path(_cache[kind]).exists():
        return _cache[kind]
    svg = OPEN_SVG if kind == "open" else CLOSED_SVG
    directory = Path(tempfile.gettempdir()) / "seshka-linux-icons"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{kind}.svg"
    path.write_text(svg)
    _cache[kind] = str(path)
    return str(path)
