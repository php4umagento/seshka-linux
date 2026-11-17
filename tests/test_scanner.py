from __future__ import annotations

import json
import os

from seshka import scanner
from seshka.models import Proc


def test_detects_orphan_and_live(fake_proc):
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    # Closed session: CLAUDE_PID points at missing process
    fake_proc.add(
        200,
        comm="python3",
        cmdline="python3 -m http.server 8765",
        environ={
            "CLAUDECODE": "1",
            "CLAUDE_CODE_SESSION_ID": sid,
            "CLAUDE_PID": "199",
        },
        age_s=600,
        rss_kb=4096,
        listen_inode="111",
        listen_port=8765,
    )
    # Open session
    fake_proc.add(300, comm="claude", cmdline="claude", age_s=900, rss_kb=80000)
    fake_proc.add(
        301,
        ppid=300,
        comm="node",
        cmdline="node server.js",
        environ={
            "CLAUDECODE": "1",
            "CLAUDE_CODE_SESSION_ID": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "CLAUDE_PID": "300",
        },
        age_s=800,
        rss_kb=20000,
    )

    project = fake_proc.claude_home / "projects" / "home-demo-app"
    project.mkdir(parents=True)
    (project / f"{sid}.jsonl").write_text(
        json.dumps({"type": "x", "aiTitle": "Demo leftover"}) + "\n"
    )
    (fake_proc.claude_home / "sessions" / "300.json").write_text(
        json.dumps(
            {
                "sessionId": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "cwd": "/home/demo/app",
                "status": "idle",
                "statusUpdatedAt": 0,
            }
        )
    )

    procs = scanner.scan(uid=os.getuid(), self_pid=-1)
    by_pid = {p.pid: p for p in procs}
    assert 200 in by_pid
    assert by_pid[200].session_alive is False
    assert "8765" in by_pid[200].ports
    assert 301 in by_pid
    assert by_pid[301].session_alive is True

    orphans = scanner.group([p for p in procs if not p.session_alive])
    assert len(orphans) == 1
    assert orphans[0].title == "Demo leftover"

    sessions = scanner.sessions(procs, uid=os.getuid())
    assert any(s.pid == 300 for s in sessions)
    live = next(s for s in sessions if s.pid == 300)
    assert live.status == "idle"
    assert any(p.pid == 301 for p in live.procs)


def test_folds_chrome_helpers(fake_proc):
    sid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    fake_proc.add(
        400,
        comm="chrome",
        cmdline="/usr/bin/google-chrome --new-window",
        exe="/usr/bin/google-chrome",
        environ={"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": sid, "CLAUDE_PID": "1"},
        age_s=300,
    )
    fake_proc.add(
        401,
        ppid=400,
        comm="chrome",
        cmdline="/usr/bin/google-chrome --type=renderer",
        exe="/usr/bin/google-chrome",
        age_s=299,
        rss_kb=50000,
    )
    procs = scanner.scan(uid=os.getuid(), self_pid=-1)
    assert len(procs) == 1
    assert procs[0].pid == 400
    assert len(procs[0].helpers) == 1
    assert procs[0].helpers[0].pid == 401
    assert procs[0].memory >= 50000 * 1024


def test_unmarked_descendant_inherits_session(fake_proc):
    sid = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    fake_proc.add(
        500,
        comm="node",
        cmdline="node playwright.js",
        environ={"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": sid, "CLAUDE_PID": "1"},
        age_s=200,
    )
    # Child with unreadable/empty environ still belongs to session
    fake_proc.add(
        501,
        ppid=500,
        comm="chromium",
        cmdline="chromium --type=zygote",
        exe="/usr/bin/chromium",
        age_s=199,
        rss_kb=10000,
    )
    procs = scanner.scan(uid=os.getuid(), self_pid=-1)
    # zygote may fold into chromium-less parent differently; at least session is detected
    assert any(p.session_id == sid for p in procs)
    assert all(p.session_id == sid for p in procs)
