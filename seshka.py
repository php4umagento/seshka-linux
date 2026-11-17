#!/usr/bin/env python3
"""seshka-linux — find and kill leftovers from Claude Code sessions (Ubuntu PoC)."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

PROC = Path("/proc")
CLAUDE_HOME = Path.home() / ".claude"


@dataclass
class ProcInfo:
    pid: int
    ppid: int
    session_id: str
    claude_pid: int | None
    session_alive: bool
    command: str = ""
    age_s: int = 0
    rss_bytes: int = 0
    ports: list[str] = field(default_factory=list)
    cwd: str = ""

    @property
    def short_cmd(self) -> str:
        parts = self.command.split()
        if not parts:
            return "?"
        name = Path(parts[0]).name
        rest = " ".join(parts[1:])
        text = f"{name} {rest}".strip()
        return text if len(text) <= 72 else text[:69] + "..."


@dataclass
class SessionGroup:
    session_id: str
    project: str
    title: str | None
    alive: bool
    procs: list[ProcInfo]

    @property
    def short_id(self) -> str:
        return self.session_id[:8]

    @property
    def memory(self) -> int:
        return sum(p.rss_bytes for p in self.procs)

    @property
    def oldest(self) -> int:
        return max((p.age_s for p in self.procs), default=0)


@dataclass
class RunningSession:
    pid: int
    session_id: str | None
    project: str
    status: str
    age_s: int
    rss_bytes: int
    cwd: str
    child_count: int


def _read_environ(pid: int) -> dict[str, str] | None:
    try:
        raw = (PROC / str(pid) / "environ").read_bytes()
    except (OSError, PermissionError):
        return None
    env: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        env[key.decode(errors="replace")] = value.decode(errors="replace")
    return env


def _read_cmdline(pid: int) -> str:
    try:
        raw = (PROC / str(pid) / "cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode(errors="replace").strip()


def _read_comm(pid: int) -> str:
    try:
        return (PROC / str(pid) / "comm").read_text(errors="replace").strip()
    except OSError:
        return ""


def _read_ppid(pid: int) -> int:
    try:
        for line in (PROC / str(pid) / "status").read_text().splitlines():
            if line.startswith("PPid:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _read_rss(pid: int) -> int:
    try:
        for line in (PROC / str(pid) / "status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _read_start_age(pid: int) -> int:
    try:
        stat = (PROC / str(pid) / "stat").read_text()
        rparen = stat.rfind(")")
        fields = stat[rparen + 2 :].split()
        start_ticks = int(fields[19])
        hz = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        boot = float((PROC / "uptime").read_text().split()[0])
        now = time.time()
        start_epoch = now - boot + (start_ticks / hz)
        return max(0, int(now - start_epoch))
    except (OSError, ValueError, IndexError, KeyError):
        return 0


def _read_cwd(pid: int) -> str:
    try:
        return os.readlink(PROC / str(pid) / "cwd")
    except OSError:
        return ""


def _listening_ports(pid: int) -> list[str]:
    ports: list[str] = []
    fd_dir = PROC / str(pid) / "fd"
    try:
        entries = list(fd_dir.iterdir())
    except OSError:
        return ports

    inodes: set[str] = set()
    for entry in entries:
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if target.startswith("socket:["):
            inodes.add(target[8:-1])

    if not inodes:
        return ports

    for table in ("net/tcp", "net/tcp6"):
        try:
            lines = (PROC / str(pid) / table).read_text().splitlines()[1:]
        except OSError:
            try:
                lines = (PROC / table).read_text().splitlines()[1:]
            except OSError:
                continue
        for line in lines:
            parts = line.split()
            if len(parts) < 10:
                continue
            local, state, inode = parts[1], parts[3], parts[9]
            if state != "0A" or inode not in inodes:
                continue
            port_hex = local.rsplit(":", 1)[-1]
            try:
                port = str(int(port_hex, 16))
            except ValueError:
                continue
            if port not in ports:
                ports.append(port)
    return ports


def _is_claude_process(pid: int, comm_cache: dict[int, str] | None = None) -> bool:
    if comm_cache is not None and pid in comm_cache:
        return comm_cache[pid] == "claude"
    return _read_comm(pid) == "claude"


def _process_exists(pid: int) -> bool:
    return (PROC / str(pid)).exists()


def _human_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)}B"
            if unit == "KB":
                return f"{value:.0f}KB"
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}GB"


def _human_age(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        h, m = divmod(seconds // 60, 60)
        return f"{h}h{m:02d}m"
    d, rem = divmod(seconds, 86400)
    h = rem // 3600
    return f"{d}d{h}h"


def _session_meta(session_id: str) -> tuple[str, str | None]:
    root = CLAUDE_HOME / "projects"
    if not root.is_dir() or session_id in ("", "no-session"):
        return "unknown project", None

    home = str(Path.home())
    prefix = "".join(ch if ch.isalnum() else "-" for ch in home)

    for project_dir in root.iterdir():
        if not project_dir.is_dir():
            continue
        path = project_dir / f"{session_id}.jsonl"
        if not path.exists():
            continue
        name = project_dir.name
        if name.startswith(prefix):
            name = name[len(prefix) :].lstrip("-") or "~"
        return name, _tail_title(path)
    return "unknown project", None


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


def scan_marked(uid: int | None = None) -> list[ProcInfo]:
    if uid is None:
        uid = os.getuid()
    me = os.getpid()

    parents: dict[int, int] = {}
    comms: dict[int, str] = {}
    commands: dict[int, str] = {}
    for entry in PROC.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            if entry.stat().st_uid != uid:
                continue
        except OSError:
            continue
        parents[pid] = _read_ppid(pid)
        comms[pid] = _read_comm(pid)
        commands[pid] = _read_cmdline(pid)

    def has_claude_ancestor(start: int) -> bool:
        seen: set[int] = set()
        pid = start
        while pid > 1 and pid not in seen:
            seen.add(pid)
            pid = parents.get(pid, 0)
            if _is_claude_process(pid, comms):
                return True
        return False

    marked: list[ProcInfo] = []
    marked_index: dict[int, int] = {}

    for pid, cmdline in commands.items():
        if pid == me or _is_claude_process(pid, comms):
            continue
        env = _read_environ(pid)
        if not env or env.get("CLAUDECODE") != "1":
            continue
        session_id = env.get("CLAUDE_CODE_SESSION_ID") or "no-session"
        raw_cpid = env.get("CLAUDE_PID")
        claude_pid = int(raw_cpid) if raw_cpid and raw_cpid.isdigit() else None
        alive = (claude_pid is not None and _is_claude_process(claude_pid, comms)) or has_claude_ancestor(
            pid
        )
        info = ProcInfo(
            pid=pid,
            ppid=parents.get(pid, 0),
            session_id=session_id,
            claude_pid=claude_pid,
            session_alive=alive,
            command=cmdline or "?",
            age_s=_read_start_age(pid),
            rss_bytes=_read_rss(pid),
            ports=_listening_ports(pid),
            cwd=_read_cwd(pid),
        )
        marked_index[pid] = len(marked)
        marked.append(info)

    for pid, cmdline in commands.items():
        if pid in marked_index or pid == me or _is_claude_process(pid, comms):
            continue
        owner: int | None = None
        at = pid
        seen: set[int] = set()
        while at > 1 and at not in seen:
            seen.add(at)
            up = parents.get(at, 0)
            if up == me or _is_claude_process(up, comms):
                break
            if up in marked_index:
                owner = marked_index[up]
                break
            at = up
        if owner is None:
            continue
        parent_info = marked[owner]
        marked.append(
            ProcInfo(
                pid=pid,
                ppid=parents.get(pid, 0),
                session_id=parent_info.session_id,
                claude_pid=parent_info.claude_pid,
                session_alive=parent_info.session_alive,
                command=cmdline or "?",
                age_s=_read_start_age(pid),
                rss_bytes=_read_rss(pid),
                ports=_listening_ports(pid),
                cwd=_read_cwd(pid),
            )
        )

    return marked


def group_sessions(procs: Iterable[ProcInfo], leftovers_only: bool = True) -> list[SessionGroup]:
    by_session: dict[str, list[ProcInfo]] = defaultdict(list)
    for proc in procs:
        if leftovers_only and proc.session_alive:
            continue
        by_session[proc.session_id].append(proc)

    groups: list[SessionGroup] = []
    for sid, members in by_session.items():
        project, title = _session_meta(sid)
        groups.append(
            SessionGroup(
                session_id=sid,
                project=project,
                title=title,
                alive=any(m.session_alive for m in members),
                procs=sorted(members, key=lambda p: p.age_s, reverse=True),
            )
        )
    return sorted(groups, key=lambda g: g.oldest, reverse=True)


def scan_running_sessions(procs: list[ProcInfo]) -> list[RunningSession]:
    uid = os.getuid()
    sessions: list[RunningSession] = []
    for entry in PROC.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            if entry.stat().st_uid != uid:
                continue
        except OSError:
            continue
        if _read_comm(pid) != "claude":
            continue
        if _read_comm(_read_ppid(pid)) == "claude":
            continue

        record: dict = {}
        path = CLAUDE_HOME / "sessions" / f"{pid}.json"
        if path.exists():
            try:
                record = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                record = {}

        session_id = record.get("sessionId")
        cwd = record.get("cwd") or _read_cwd(pid)
        status = record.get("status") or "unknown"
        if session_id:
            project, _ = _session_meta(session_id)
            if project == "unknown project" and cwd:
                project = Path(cwd).name
        else:
            project = Path(cwd).name if cwd else "Claude Code"

        child_count = sum(
            1 for p in procs if p.session_alive and p.session_id == session_id and p.age_s >= 60
        )
        sessions.append(
            RunningSession(
                pid=pid,
                session_id=session_id,
                project=project,
                status=status,
                age_s=_read_start_age(pid),
                rss_bytes=_read_rss(pid),
                cwd=cwd,
                child_count=child_count,
            )
        )
    return sorted(sessions, key=lambda s: s.age_s, reverse=True)


def terminate(procs: list[ProcInfo], grace: float = 2.0) -> tuple[int, int]:
    targets: list[ProcInfo] = []
    for proc in procs:
        if not _process_exists(proc.pid):
            continue
        now = _read_cmdline(proc.pid)
        if now and now != proc.command:
            print(f"  skip pid {proc.pid}: command changed (possible PID reuse)", file=sys.stderr)
            continue
        targets.append(proc)

    for proc in targets:
        try:
            os.kill(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            print(f"  cannot signal {proc.pid}: {exc}", file=sys.stderr)

    deadline = time.time() + grace
    while time.time() < deadline:
        if not any(_process_exists(p.pid) for p in targets):
            break
        time.sleep(0.1)

    force = 0
    for proc in targets:
        if _process_exists(proc.pid):
            try:
                os.kill(proc.pid, signal.SIGKILL)
                force += 1
            except (ProcessLookupError, PermissionError):
                pass

    time.sleep(0.2)
    killed = sum(1 for p in targets if not _process_exists(p.pid))
    return killed, force


def cmd_list(args: argparse.Namespace) -> int:
    all_procs = scan_marked()
    leftovers = [p for p in all_procs if not p.session_alive]
    alive = [p for p in all_procs if p.session_alive]

    show = all_procs if args.all else leftovers
    groups = group_sessions(show, leftovers_only=not args.all)
    label = "Claude-tagged" if args.all else "leftover"

    if args.json:
        payload = {
            "leftovers": len(leftovers),
            "alive_tagged": len(alive),
            "sessions": [
                {
                    "session_id": g.session_id,
                    "project": g.project,
                    "title": g.title,
                    "alive": g.alive,
                    "memory": g.memory,
                    "procs": [
                        {
                            "pid": p.pid,
                            "command": p.command,
                            "age_s": p.age_s,
                            "rss": p.rss_bytes,
                            "ports": p.ports,
                            "session_alive": p.session_alive,
                        }
                        for p in g.procs
                    ],
                }
                for g in groups
            ],
        }
        print(json.dumps(payload, indent=2))
        return 0

    print(f"Found {len(leftovers)} leftover process(es), {len(alive)} still tied to open sessions.")
    if not show:
        print(f"No {label} processes.")
    else:
        print()
        for group in groups:
            mem = _human_bytes(group.memory)
            title = f" — {group.title}" if group.title else ""
            state = "open" if group.alive else "closed"
            print(f"session {group.short_id}  [{state}]  {group.project}{title}  ({mem})")
            for proc in group.procs:
                ports = f" :{','.join(proc.ports)}" if proc.ports else ""
                print(
                    f"  {proc.pid:>7}  {_human_age(proc.age_s):>7}  "
                    f"{_human_bytes(proc.rss_bytes):>8}{ports:>10}  {proc.short_cmd}"
                )
            print()

    running = scan_running_sessions(all_procs)
    if running:
        print("Open Claude Code sessions:")
        for s in running:
            sid = (s.session_id or "?")[:8]
            print(
                f"  pid {s.pid}  {sid}  {s.status:6}  "
                f"{_human_age(s.age_s):>7}  {_human_bytes(s.rss_bytes):>8}  "
                f"{s.project}  (+{s.child_count} bg)"
            )
    else:
        print("No open Claude Code sessions.")
    return 0


def cmd_kill(args: argparse.Namespace) -> int:
    all_procs = scan_marked()
    leftovers = [p for p in all_procs if not p.session_alive]

    if args.pid:
        wanted = set(args.pid)
        targets = [p for p in all_procs if p.pid in wanted]
        missing = wanted - {p.pid for p in targets}
        if missing:
            print(
                f"PID(s) not Claude-tagged (or gone): {', '.join(map(str, sorted(missing)))}",
                file=sys.stderr,
            )
    elif args.session:
        prefix = args.session
        pool = all_procs if args.force_alive else leftovers
        targets = [p for p in pool if p.session_id.startswith(prefix)]
        if not targets:
            print(f"No matching processes for session prefix {prefix!r}", file=sys.stderr)
            return 1
    elif args.all:
        targets = leftovers
        if not targets:
            print("Nothing leftover to kill.")
            return 0
    else:
        print("Specify --pid, --session, or --all", file=sys.stderr)
        return 2

    total_mem = sum(p.rss_bytes for p in targets)
    print(f"Killing {len(targets)} process(es) holding ~{_human_bytes(total_mem)}:")
    for proc in targets:
        print(f"  {proc.pid}  {proc.short_cmd}")

    if args.dry_run:
        print("Dry run — no signals sent.")
        return 0

    killed, force = terminate(targets)
    print(f"Done. Exited: {killed}. Force-killed: {force}. Freed ~{_human_bytes(total_mem)}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seshka",
        description="Kill what Claude Code left behind (Ubuntu PoC).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_p = sub.add_parser("list", help="List leftover (and optionally all) tagged processes")
    list_p.add_argument("--all", action="store_true", help="Include processes from open sessions")
    list_p.add_argument("--json", action="store_true", help="Machine-readable output")
    list_p.set_defaults(func=cmd_list)

    kill_p = sub.add_parser("kill", help="Terminate leftover processes")
    kill_p.add_argument("--pid", type=int, nargs="+", help="Kill specific PID(s)")
    kill_p.add_argument("--session", help="Kill leftovers matching session id prefix")
    kill_p.add_argument("--all", action="store_true", help="Kill every leftover")
    kill_p.add_argument(
        "--force-alive",
        action="store_true",
        help="With --session, also kill processes whose Claude session is still open",
    )
    kill_p.add_argument("-n", "--dry-run", action="store_true", help="Show targets only")
    kill_p.set_defaults(func=cmd_kill)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
