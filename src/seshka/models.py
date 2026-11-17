from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Helper:
    pid: int
    command: str


@dataclass
class Proc:
    pid: int
    ppid: int
    session_id: str
    claude_pid: int | None
    session_alive: bool
    command: str = ""
    path: str = ""
    age_s: int = 0
    memory: int = 0
    ports: list[str] = field(default_factory=list)
    cwd: str = ""
    helpers: list[Helper] = field(default_factory=list)

    @property
    def executable(self) -> str:
        if self.path:
            return Path(self.path).name
        parts = self.command.split()
        return Path(parts[0]).name if parts else "?"

    @property
    def short_command(self) -> str:
        parts = self.command.split()
        if not parts:
            return "?"
        name = self.executable
        rest = " ".join(parts[1:])
        text = f"{name} {rest}".strip() if rest else name
        return text if len(text) <= 72 else text[:69] + "..."

    @property
    def all_pids(self) -> list[int]:
        return [self.pid, *[h.pid for h in self.helpers]]


@dataclass
class SessionGroup:
    session_id: str
    project: str
    title: str | None
    procs: list[Proc]

    @property
    def short_id(self) -> str:
        return self.session_id[:8] if self.session_id else "?"

    @property
    def memory(self) -> int:
        return sum(p.memory for p in self.procs)

    @property
    def oldest(self) -> int:
        return max((p.age_s for p in self.procs), default=0)


@dataclass
class RunningSession:
    process: Proc
    session_id: str | None
    project: str
    title: str | None
    status: str  # busy | idle | unknown | other
    status_since_ms: float | None
    procs: list[Proc]

    @property
    def pid(self) -> int:
        return self.process.pid

    @property
    def memory(self) -> int:
        return self.process.memory + sum(p.memory for p in self.procs)

    def idle_seconds(self, now_ms: float | None = None) -> int | None:
        if self.status != "idle" or self.status_since_ms is None:
            return None
        if now_ms is None:
            import time

            now_ms = time.time() * 1000
        return max(0, int((now_ms - self.status_since_ms) / 1000))
