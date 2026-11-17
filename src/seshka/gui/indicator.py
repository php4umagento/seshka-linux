"""Load a system tray indicator across Ubuntu / Debian / Fedora variants."""

from __future__ import annotations

import importlib

import gi


def load_appindicator():
    """Return the AppIndicator module (Ayatana preferred, then classic)."""
    errors: list[str] = []
    for namespace in ("AyatanaAppIndicator3", "AppIndicator3"):
        try:
            gi.require_version(namespace, "0.1")
            return importlib.import_module(f"gi.repository.{namespace}")
        except (ValueError, ImportError, ModuleNotFoundError) as exc:
            errors.append(f"{namespace}: {exc}")
    raise ImportError(
        "No AppIndicator library found. Install one of:\n"
        "  Ubuntu/Debian: sudo apt install gir1.2-ayatanaappindicator3-0.1\n"
        "  Fedora:        sudo dnf install libappindicator-gtk3\n"
        "  Arch:          sudo pacman -S libayatana-appindicator\n"
        + "\n".join(errors)
    )
