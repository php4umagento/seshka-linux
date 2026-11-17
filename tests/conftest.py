from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from seshka import config, procfs, session_info


@dataclass
class FakeProc:
    root: Path
    claude_home: Path
    config_path: Path

    def add(
        self,
        pid: int,
        *,
        ppid: int = 1,
        comm: str = "python3",
        cmdline: str | None = None,
        environ: dict[str, str] | None = None,
        uid: int | None = None,
        rss_kb: int = 1024,
        age_s: int = 120,
        exe: str | None = None,
        cwd: str | None = None,
        listen_inode: str | None = None,
        listen_port: int | None = None,
    ) -> Path:
        if uid is None:
            uid = os.getuid()
        pdir = self.root / str(pid)
        pdir.mkdir()
        (pdir / "comm").write_text(comm + "\n")
        cmd = cmdline if cmdline is not None else comm
        (pdir / "cmdline").write_bytes(cmd.replace(" ", "\0").encode() + b"\0")
        if environ:
            blob = b"\0".join(f"{k}={v}".encode() for k, v in environ.items()) + b"\0"
            (pdir / "environ").write_bytes(blob)
        else:
            (pdir / "environ").write_bytes(b"\0")
        (pdir / "status").write_text(f"Name:\t{comm}\nPPid:\t{ppid}\nVmRSS:\t{rss_kb} kB\n")
        hz = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        start_ticks = int((1000 - age_s) * hz)
        post = ["S"] + ["0"] * 18 + [str(start_ticks)] + ["0"] * 30
        (pdir / "stat").write_text(f"{pid} ({comm}) " + " ".join(post) + "\n")
        if exe:
            # Create a dummy target so symlink is valid
            target = Path(exe)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                # Prefer linking into tmp tree if absolute path isn't writable
                local = self.root / "bin" / target.name
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_text("")
                (pdir / "exe").symlink_to(local)
            else:
                (pdir / "exe").symlink_to(exe)
        if cwd:
            cwd_path = Path(cwd)
            cwd_path.mkdir(parents=True, exist_ok=True)
            (pdir / "cwd").symlink_to(cwd_path)
        fd = pdir / "fd"
        fd.mkdir()
        if listen_inode and listen_port is not None:
            (fd / "3").symlink_to(f"socket:[{listen_inode}]")
            port_hex = f"{listen_port:04X}"
            line = (
                f" 0: 0100007F:{port_hex} 00000000:0000 0A 00000000:00000000 "
                f"00:00000000 00000000  1000        0 {listen_inode} 1 0000000000000000 100 0 0 10 0\n"
            )
            tcp = self.root / "net"
            tcp.mkdir(exist_ok=True)
            path = tcp / "tcp"
            if path.exists():
                path.write_text(path.read_text() + line)
            else:
                path.write_text("sl local_address rem_address st ...\n" + line)
        try:
            os.chown(pdir, uid, -1)
        except PermissionError:
            pass
        return pdir


@pytest.fixture
def fake_proc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeProc:
    root = tmp_path / "proc"
    root.mkdir()
    (root / "uptime").write_text("1000.0 0.0\n")
    procfs.set_proc_root(root)

    claude_home = tmp_path / ".claude"
    (claude_home / "projects").mkdir(parents=True)
    (claude_home / "sessions").mkdir(parents=True)
    session_info.set_claude_home(claude_home)

    cfg = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", cfg)

    yield FakeProc(root=root, claude_home=claude_home, config_path=cfg)

    procfs.set_proc_root("/proc")
    session_info.set_claude_home(Path.home() / ".claude")


@pytest.fixture(autouse=True)
def _restore_proc_root():
    yield
    procfs.set_proc_root("/proc")
