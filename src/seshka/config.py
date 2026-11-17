from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "seshka"
CONFIG_PATH = CONFIG_DIR / "config.json"

MINIMUM_IDLE_LIMIT = 30
DEFAULT_IDLE_LIMIT = 120
DEFAULT_INTERVAL = 30
DEFAULT_PROTECTED = ["limactl"]


@dataclass
class Settings:
    protected_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_PROTECTED))
    refresh_interval: int = DEFAULT_INTERVAL
    idle_limit_minutes: int = DEFAULT_IDLE_LIMIT
    ends_idle_sessions: bool = False

    def clamp(self) -> None:
        if self.idle_limit_minutes < MINIMUM_IDLE_LIMIT:
            self.idle_limit_minutes = MINIMUM_IDLE_LIMIT
        if self.refresh_interval < 5:
            self.refresh_interval = 5


def load_settings(path: Path | None = None) -> Settings:
    cfg_path = path or CONFIG_PATH
    if not cfg_path.exists():
        return Settings()
    try:
        data = json.loads(cfg_path.read_text())
    except (OSError, json.JSONDecodeError):
        return Settings()
    settings = Settings(
        protected_patterns=list(data.get("protected_patterns", DEFAULT_PROTECTED)),
        refresh_interval=int(data.get("refresh_interval", DEFAULT_INTERVAL)),
        idle_limit_minutes=int(data.get("idle_limit_minutes", DEFAULT_IDLE_LIMIT)),
        ends_idle_sessions=bool(data.get("ends_idle_sessions", False)),
    )
    settings.clamp()
    return settings


def save_settings(settings: Settings, path: Path | None = None) -> None:
    cfg_path = path or CONFIG_PATH
    settings.clamp()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(asdict(settings), indent=2) + "\n")
