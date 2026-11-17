from __future__ import annotations

import json
import os

from seshka.cli import main


def test_cli_list_json(fake_proc, capsys):
    sid = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    fake_proc.add(
        700,
        comm="python3",
        cmdline="python3 -m http.server 1",
        environ={"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": sid, "CLAUDE_PID": "1"},
        age_s=100,
    )
    code = main(["list", "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["leftovers"] == 1
    assert data["orphans"][0]["procs"][0]["pid"] == 700


def test_cli_kill_dry_run(fake_proc, capsys):
    sid = "11111111-1111-1111-1111-111111111111"
    fake_proc.add(
        701,
        comm="python3",
        cmdline="python3 -m http.server 2",
        environ={"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": sid, "CLAUDE_PID": "1"},
        age_s=100,
    )
    code = main(["kill", "--all", "-n"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Dry run" in out
    assert "701" in out
