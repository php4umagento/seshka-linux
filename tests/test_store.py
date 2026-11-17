from __future__ import annotations

import json
import os

from seshka.config import Settings, load_settings, save_settings
from seshka.store import Store


def test_settings_roundtrip(fake_proc):
    s = Settings(
        protected_patterns=["docker"],
        refresh_interval=15,
        idle_limit_minutes=45,
        ends_idle_sessions=True,
    )
    save_settings(s, fake_proc.config_path)
    loaded = load_settings(fake_proc.config_path)
    assert loaded.protected_patterns == ["docker"]
    assert loaded.refresh_interval == 15
    assert loaded.idle_limit_minutes == 45
    assert loaded.ends_idle_sessions is True


def test_store_refresh_and_protect(fake_proc):
    sid = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    fake_proc.add(
        600,
        comm="limactl",
        cmdline="limactl start default",
        environ={"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": sid, "CLAUDE_PID": "1"},
        age_s=400,
    )
    fake_proc.add(
        601,
        comm="python3",
        cmdline="python3 -m http.server 9",
        environ={"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": sid, "CLAUDE_PID": "1"},
        age_s=400,
    )
    store = Store(Settings(protected_patterns=["limactl"]))
    store.refresh_sync()
    assert store.orphan_count == 2
    killable = store.killable_orphans()
    assert {p.pid for p in killable} == {601}
    assert store.is_protected(next(p for g in store.orphans for p in g.procs if p.pid == 600))
