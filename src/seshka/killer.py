from __future__ import annotations

import os
import signal
import time

from . import procfs
from .models import Proc


def is_running(pid: int) -> bool:
    if not procfs.process_exists(pid):
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def still_same(proc: Proc) -> bool:
    if not procfs.process_exists(proc.pid):
        return False
    now = procfs.read_cmdline(proc.pid)
    return bool(now) and now == proc.command


def terminate(procs: list[Proc], grace: float = 2.0) -> list[int]:
    """SIGTERM then SIGKILL. Returns PIDs that needed SIGKILL."""
    same = [p for p in procs if still_same(p)]
    targets = [p.pid for p in same]
    helper_cmds = {h.pid: h.command for p in same for h in p.helpers}

    for pid in targets:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    deadline = time.time() + grace
    while time.time() < deadline and any(is_running(pid) for pid in targets):
        time.sleep(0.05)

    stubborn = [pid for pid in targets if is_running(pid)]
    for pid in stubborn:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    reaped = time.time() + 1.0
    while time.time() < reaped and any(is_running(pid) for pid in stubborn):
        time.sleep(0.05)

    _sweep_helpers(same, helper_cmds)
    return stubborn


def _sweep_helpers(procs: list[Proc], helper_cmds: dict[int, str]) -> None:
    helpers = [h for p in procs if not is_running(p.pid) for h in p.helpers]
    if not helpers:
        return
    settled = time.time() + 1.0
    while time.time() < settled and any(is_running(h.pid) for h in helpers):
        time.sleep(0.05)
    for helper in helpers:
        if not is_running(helper.pid):
            continue
        now = procfs.read_cmdline(helper.pid)
        expected = helper_cmds.get(helper.pid, helper.command)
        if now and now == expected:
            try:
                os.kill(helper.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
