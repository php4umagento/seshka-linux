from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

from . import procfs, session_info
from .models import Helper, Proc, RunningSession, SessionGroup

MIN_LIVE_AGE = 60


def scan(uid: int | None = None, *, self_pid: int | None = None) -> list[Proc]:
    """Find processes stamped by Claude Code (and their unmarked descendants)."""
    if uid is None:
        uid = os.getuid()
    if self_pid is None:
        self_pid = os.getpid()

    parents: dict[int, int] = {}
    comms: dict[int, str] = {}
    commands: dict[int, str] = {}
    paths: dict[int, str] = {}
    ages: dict[int, int] = {}
    rss: dict[int, int] = {}

    for pid in procfs.iter_user_pids(uid):
        ppid, mem = procfs.read_ppid_and_rss(pid)
        parents[pid] = ppid
        rss[pid] = mem
        comms[pid] = procfs.read_comm(pid)
        commands[pid] = procfs.read_cmdline(pid)
        paths[pid] = procfs.read_exe(pid)
        ages[pid] = procfs.read_age_seconds(pid)

    def is_claude(pid: int) -> bool:
        return comms.get(pid) == "claude"

    def has_claude_ancestor(start: int) -> bool:
        seen: set[int] = set()
        pid = start
        while pid > 1 and pid not in seen:
            seen.add(pid)
            pid = parents.get(pid, 0)
            if is_claude(pid):
                return True
        return False

    marked: list[Proc] = []
    marked_index: dict[int, int] = {}

    for pid, cmdline in commands.items():
        if pid == self_pid or is_claude(pid):
            continue
        env = procfs.read_environ(pid)
        if not env or env.get("CLAUDECODE") != "1":
            continue
        session_id = env.get("CLAUDE_CODE_SESSION_ID") or "no-session"
        raw = env.get("CLAUDE_PID")
        claude_pid = int(raw) if raw and raw.isdigit() else None
        alive = (claude_pid is not None and is_claude(claude_pid)) or has_claude_ancestor(pid)
        proc = Proc(
            pid=pid,
            ppid=parents.get(pid, 0),
            session_id=session_id,
            claude_pid=claude_pid,
            session_alive=alive,
            command=cmdline or "?",
            path=paths.get(pid, ""),
            age_s=ages.get(pid, 0),
            memory=rss.get(pid, 0),
            ports=procfs.listening_ports(pid),
            cwd=procfs.read_cwd(pid),
        )
        marked_index[pid] = len(marked)
        marked.append(proc)

    # Unmarked descendants of marked processes (Chrome often hides environ).
    for pid, cmdline in commands.items():
        if pid in marked_index or pid == self_pid or is_claude(pid):
            continue
        owner: int | None = None
        at = pid
        seen: set[int] = set()
        while at > 1 and at not in seen:
            seen.add(at)
            up = parents.get(at, 0)
            if up == self_pid or is_claude(up):
                break
            if up in marked_index:
                owner = marked_index[up]
                break
            at = up
        if owner is None:
            continue
        parent = marked[owner]
        marked.append(
            Proc(
                pid=pid,
                ppid=parents.get(pid, 0),
                session_id=parent.session_id,
                claude_pid=parent.claude_pid,
                session_alive=parent.session_alive,
                command=cmdline or "?",
                path=paths.get(pid, ""),
                age_s=ages.get(pid, 0),
                memory=rss.get(pid, 0),
                ports=procfs.listening_ports(pid),
                cwd=procfs.read_cwd(pid),
            )
        )

    return _fold_helpers(marked)


def _fold_helpers(procs: list[Proc]) -> list[Proc]:
    """Fold browser/Electron helper children into their parent row."""
    index = {p.pid: i for i, p in enumerate(procs)}
    folded: set[int] = set()

    for i, proc in enumerate(procs):
        app: int | None = None
        at = i
        seen: set[int] = set()
        while at not in seen:
            seen.add(at)
            parent_pid = procs[at].ppid
            if parent_pid not in index:
                break
            up = index[parent_pid]
            if _is_helper_of(procs[i], procs[up]):
                app = up
                at = up
            else:
                break
        if app is None:
            continue
        parent = procs[app]
        parent.helpers.append(Helper(pid=proc.pid, command=proc.command))
        parent.memory += proc.memory
        for port in proc.ports:
            if port not in parent.ports:
                parent.ports.append(port)
        folded.add(i)

    return [procs[i] for i in range(len(procs)) if i not in folded]


def _is_helper_of(child: Proc, parent: Proc) -> bool:
    child_cmd = child.command.lower()
    parent_exe = parent.executable.lower()
    # Chromium / Electron / Playwright pattern
    if "--type=" in child_cmd:
        if parent_exe in child_cmd or any(
            name in parent_exe for name in ("chrome", "chromium", "brave", "msedge", "electron")
        ):
            return True
        if any(name in child_cmd for name in ("chrome", "chromium", "brave", "msedge", "electron")):
            return True
    # Same executable path
    if parent.path and child.path and child.path == parent.path:
        return True
    # Helper binary next to parent
    if parent.path and child.path:
        if Path(child.path).parent == Path(parent.path).parent:
            if child.executable.lower().startswith(parent_exe[: min(4, len(parent_exe))]):
                return True
    return False


def group(procs: list[Proc]) -> list[SessionGroup]:
    by_session: dict[str, list[Proc]] = defaultdict(list)
    for proc in procs:
        by_session[proc.session_id].append(proc)
    groups: list[SessionGroup] = []
    for sid, members in by_session.items():
        project, title = session_info.lookup(sid)
        groups.append(
            SessionGroup(
                session_id=sid,
                project=project,
                title=title,
                procs=sorted(members, key=lambda p: p.age_s, reverse=True),
            )
        )
    return sorted(groups, key=lambda g: g.oldest, reverse=True)


def sessions(procs: list[Proc], uid: int | None = None) -> list[RunningSession]:
    if uid is None:
        uid = os.getuid()

    claude: list[tuple[int, int, int]] = []
    for pid in procfs.iter_user_pids(uid):
        if procfs.read_comm(pid) != "claude":
            continue
        ppid, _ = procfs.read_ppid_and_rss(pid)
        if procfs.read_comm(ppid) == "claude":
            continue
        claude.append((pid, ppid, procfs.read_age_seconds(pid)))

    result: list[RunningSession] = []
    for pid, ppid, age in claude:
        record = session_info.read_session_record(pid)
        session_id = record.get("sessionId")
        if not isinstance(session_id, str):
            session_id = None
        cwd = record.get("cwd") if isinstance(record.get("cwd"), str) else procfs.read_cwd(pid)
        status_raw = record.get("status")
        if status_raw in ("busy", "idle"):
            status = status_raw
        elif isinstance(status_raw, str):
            status = status_raw
        else:
            status = "unknown"

        since = record.get("statusUpdatedAt")
        since_ms: float | None
        if isinstance(since, (int, float)):
            since_ms = float(since)
        elif isinstance(since, str):
            try:
                since_ms = float(since)
            except ValueError:
                since_ms = None
        else:
            since_ms = None

        if session_id:
            project, title = session_info.lookup(session_id)
            if project == session_info.UNKNOWN_PROJECT and cwd:
                from pathlib import Path

                project = Path(cwd).name
        else:
            from pathlib import Path

            project = Path(cwd).name if cwd else "Claude Code"
            title = None

        _, mem = procfs.read_ppid_and_rss(pid)
        process = Proc(
            pid=pid,
            ppid=ppid,
            session_id=session_id or "no-session",
            claude_pid=pid,
            session_alive=True,
            command=procfs.read_cmdline(pid) or "claude",
            path=procfs.read_exe(pid),
            age_s=age,
            memory=mem,
            cwd=cwd or "",
        )
        bg = [
            p
            for p in procs
            if p.session_alive and p.age_s >= MIN_LIVE_AGE and p.session_id == session_id
        ]
        result.append(
            RunningSession(
                process=process,
                session_id=session_id,
                project=project,
                title=title,
                status=status,
                status_since_ms=since_ms,
                procs=bg,
            )
        )
    return result
