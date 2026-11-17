from __future__ import annotations

import os
import time
from pathlib import Path

# Overridable for tests.
PROC_ROOT = Path("/proc")


def set_proc_root(path: Path | str) -> None:
    global PROC_ROOT
    PROC_ROOT = Path(path)


def read_environ(pid: int) -> dict[str, str] | None:
    try:
        raw = (PROC_ROOT / str(pid) / "environ").read_bytes()
    except (OSError, PermissionError):
        return None
    env: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        env[key.decode(errors="replace")] = value.decode(errors="replace")
    return env


def read_cmdline(pid: int) -> str:
    try:
        raw = (PROC_ROOT / str(pid) / "cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode(errors="replace").strip()


def read_comm(pid: int) -> str:
    try:
        return (PROC_ROOT / str(pid) / "comm").read_text(errors="replace").strip()
    except OSError:
        return ""


def read_exe(pid: int) -> str:
    try:
        return os.readlink(PROC_ROOT / str(pid) / "exe")
    except OSError:
        return ""


def read_cwd(pid: int) -> str:
    try:
        return os.readlink(PROC_ROOT / str(pid) / "cwd")
    except OSError:
        return ""


def read_ppid_and_rss(pid: int) -> tuple[int, int]:
    ppid, rss = 0, 0
    try:
        for line in (PROC_ROOT / str(pid) / "status").read_text().splitlines():
            if line.startswith("PPid:"):
                ppid = int(line.split()[1])
            elif line.startswith("VmRSS:"):
                rss = int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return ppid, rss


def read_age_seconds(pid: int, *, now: float | None = None, uptime: float | None = None) -> int:
    try:
        stat = (PROC_ROOT / str(pid) / "stat").read_text()
        rparen = stat.rfind(")")
        fields = stat[rparen + 2 :].split()
        start_ticks = int(fields[19])
        hz = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        if uptime is None:
            uptime = float((PROC_ROOT / "uptime").read_text().split()[0])
        if now is None:
            now = time.time()
        start_epoch = now - uptime + (start_ticks / hz)
        return max(0, int(now - start_epoch))
    except (OSError, ValueError, IndexError, KeyError):
        return 0


def listening_ports(pid: int) -> list[str]:
    ports: list[str] = []
    fd_dir = PROC_ROOT / str(pid) / "fd"
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
        lines: list[str] = []
        for candidate in (PROC_ROOT / str(pid) / table, PROC_ROOT / table):
            try:
                lines = candidate.read_text().splitlines()[1:]
                break
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


def iter_user_pids(uid: int | None = None) -> list[int]:
    if uid is None:
        uid = os.getuid()
    pids: list[int] = []
    try:
        entries = list(PROC_ROOT.iterdir())
    except OSError:
        return pids
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
        except OSError:
            continue
        pids.append(int(entry.name))
    return pids


def process_exists(pid: int) -> bool:
    return (PROC_ROOT / str(pid)).exists()
