from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from . import config, killer, scanner
from .models import Proc, RunningSession, SessionGroup


@dataclass
class Freed:
    bytes: int
    count: int
    stamp: float = field(default_factory=time.time)


@dataclass
class AutoEnd:
    count: int
    date: float = field(default_factory=time.time)


class Store:
    """Application state shared by CLI helpers and the GUI."""

    def __init__(self, settings: config.Settings | None = None) -> None:
        self.settings = settings or config.load_settings()
        self.orphans: list[SessionGroup] = []
        self.live: list[SessionGroup] = []
        self.sessions: list[RunningSession] = []
        self.killing: set[int] = set()
        self.last_scan: float | None = None
        self.scanning = False
        self.freed: Freed | None = None
        self.last_auto_end: AutoEnd | None = None
        self._lock = threading.RLock()
        self._rescan_when_done = False
        self._listeners: list = []

    def subscribe(self, callback) -> None:
        self._listeners.append(callback)

    def _notify(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                pass

    @property
    def orphan_count(self) -> int:
        return sum(len(g.procs) for g in self.orphans)

    @property
    def orphan_memory(self) -> int:
        return sum(g.memory for g in self.orphans)

    @property
    def idle_sessions(self) -> list[RunningSession]:
        return self.idle_sessions_list()

    def idle_sessions_list(self) -> list[RunningSession]:
        limit = self.settings.idle_limit_minutes * 60
        out: list[RunningSession] = []
        for s in self.sessions:
            idle = s.idle_seconds()
            if idle is not None and idle >= limit:
                out.append(s)
        return out

    def is_protected(self, proc: Proc) -> bool:
        command = proc.command.lower()
        return any(p and p.lower() in command for p in self.settings.protected_patterns)

    def killable_orphans(self) -> list[Proc]:
        return [p for g in self.orphans for p in g.procs if not self.is_protected(p)]

    def protect(self, proc: Proc) -> None:
        name = proc.executable
        if name not in self.settings.protected_patterns:
            self.settings.protected_patterns.append(name)
            config.save_settings(self.settings)
            self._notify()

    def unprotect(self, proc: Proc) -> None:
        command = proc.command.lower()
        self.settings.protected_patterns = [
            p for p in self.settings.protected_patterns if p.lower() not in command
        ]
        config.save_settings(self.settings)
        self._notify()

    def save_settings(self) -> None:
        config.save_settings(self.settings)
        self._notify()

    def refresh(self) -> None:
        with self._lock:
            if self.scanning:
                self._rescan_when_done = True
                return
            self.scanning = True
        self._notify()

        def work() -> None:
            try:
                procs = scanner.scan()
                orphans = scanner.group([p for p in procs if not p.session_alive])
                running = scanner.sessions(procs=procs)
                running.sort(
                    key=lambda s: (s.idle_seconds() if s.idle_seconds() is not None else -1, s.process.age_s),
                    reverse=True,
                )
                matched = {s.session_id for s in running if s.session_id}
                live = scanner.group(
                    [
                        p
                        for p in procs
                        if p.session_alive
                        and p.age_s >= scanner.MIN_LIVE_AGE
                        and p.session_id not in matched
                    ]
                )
                with self._lock:
                    self.orphans = orphans
                    self.live = live
                    self.sessions = running
                    self.last_scan = time.time()
                    self.scanning = False
                    auto = False
                    if self.settings.ends_idle_sessions:
                        due = [
                            s
                            for s in self.idle_sessions_list()
                            if s.process.pid not in self.killing
                        ]
                        if due:
                            self.last_auto_end = AutoEnd(count=len(due))
                            auto = True
                    again = self._rescan_when_done
                    self._rescan_when_done = False
                self._notify()
                if auto:
                    self.kill_idle_sessions()
                if again:
                    self.refresh()
            except Exception:
                with self._lock:
                    self.scanning = False
                self._notify()
                raise

        threading.Thread(target=work, daemon=True).start()

    def refresh_sync(self) -> None:
        """Synchronous refresh for CLI / tests."""
        procs = scanner.scan()
        self.orphans = scanner.group([p for p in procs if not p.session_alive])
        running = scanner.sessions(procs=procs)
        running.sort(
            key=lambda s: (s.idle_seconds() if s.idle_seconds() is not None else -1, s.process.age_s),
            reverse=True,
        )
        matched = {s.session_id for s in running if s.session_id}
        self.live = scanner.group(
            [
                p
                for p in procs
                if p.session_alive and p.age_s >= scanner.MIN_LIVE_AGE and p.session_id not in matched
            ]
        )
        self.sessions = running
        self.last_scan = time.time()
        self._notify()

    def kill(self, procs: list[Proc]) -> None:
        targets = [p for p in procs if p.pid not in self.killing]
        if not targets:
            return
        self.killing.update(p.pid for p in targets)
        self._notify()

        def work() -> None:
            killer.terminate(targets)
            gone = [p for p in targets if not killer.is_running(p.pid)]
            bytes_freed = sum(p.memory for p in gone)
            with self._lock:
                self.killing.difference_update(p.pid for p in targets)
                if gone:
                    prev = self.freed
                    self.freed = Freed(
                        bytes=(prev.bytes if prev else 0) + bytes_freed,
                        count=(prev.count if prev else 0) + len(gone),
                    )
                pids = {p.pid for p in gone}
                self.orphans = _removing(pids, self.orphans)
                self.live = _removing(pids, self.live)
                self.sessions = [s for s in self.sessions if s.process.pid not in pids]
                for s in self.sessions:
                    s.procs = [p for p in s.procs if p.pid not in pids]
            self._notify()
            self.refresh()

        threading.Thread(target=work, daemon=True).start()

    def kill_sync(self, procs: list[Proc]) -> tuple[int, int]:
        targets = [p for p in procs if not self.is_protected(p)]
        forced = killer.terminate(targets)
        gone = [p for p in targets if not killer.is_running(p.pid)]
        return len(gone), len(forced)

    def kill_session(self, group: SessionGroup) -> None:
        self.kill([p for p in group.procs if not self.is_protected(p)])

    def kill_all_orphans(self) -> None:
        self.kill(self.killable_orphans())

    def kill_running(self, session: RunningSession) -> None:
        self.kill([session.process] + [p for p in session.procs if not self.is_protected(p)])

    def kill_idle_sessions(self) -> None:
        procs: list[Proc] = []
        for s in self.idle_sessions_list():
            procs.append(s.process)
            procs.extend(p for p in s.procs if not self.is_protected(p))
        self.kill(procs)


def _removing(pids: set[int], groups: list[SessionGroup]) -> list[SessionGroup]:
    out: list[SessionGroup] = []
    for group in groups:
        procs = [p for p in group.procs if p.pid not in pids]
        if procs:
            out.append(
                SessionGroup(
                    session_id=group.session_id,
                    project=group.project,
                    title=group.title,
                    procs=procs,
                )
            )
    return out
