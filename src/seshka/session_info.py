from __future__ import annotations

import json
from pathlib import Path

UNKNOWN_PROJECT = "unknown project"

# Overridable for tests.
CLAUDE_HOME = Path.home() / ".claude"


def set_claude_home(path: Path | str) -> None:
    global CLAUDE_HOME
    CLAUDE_HOME = Path(path)


def lookup(session_id: str) -> tuple[str, str | None]:
    root = CLAUDE_HOME / "projects"
    if not root.is_dir() or session_id in ("", "no-session"):
        return UNKNOWN_PROJECT, None

    home = str(Path.home())
    prefix = "".join(ch if ch.isalnum() else "-" for ch in home)

    try:
        dirs = list(root.iterdir())
    except OSError:
        return UNKNOWN_PROJECT, None

    for project_dir in dirs:
        if not project_dir.is_dir():
            continue
        path = project_dir / f"{session_id}.jsonl"
        if not path.exists():
            continue
        name = project_dir.name
        if name.startswith(prefix):
            name = name[len(prefix) :].lstrip("-") or "~"
        return name, _tail_title(path)
    return UNKNOWN_PROJECT, None


def _tail_title(path: Path) -> str | None:
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            chunk = 2 * 1024 * 1024
            if size > chunk:
                fh.seek(size - chunk)
            text = fh.read().decode(errors="replace")
    except OSError:
        return None
    for line in reversed(text.splitlines()):
        if "ai-title" not in line and "aiTitle" not in line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        title = data.get("aiTitle") or data.get("ai-title")
        if isinstance(title, str) and title:
            return title
    return None


def read_session_record(pid: int) -> dict:
    path = CLAUDE_HOME / "sessions" / f"{pid}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
