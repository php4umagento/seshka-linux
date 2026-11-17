from __future__ import annotations

import os
import signal
import subprocess
import time

from seshka import procfs
from seshka.killer import is_running, terminate
from seshka.models import Proc


def test_terminate_sigterm():
    procfs.set_proc_root("/proc")
    proc = subprocess.Popen(["sleep", "60"])
    try:
        time.sleep(0.1)
        cmdline = procfs.read_cmdline(proc.pid)
        assert cmdline.startswith("sleep")
        target = Proc(
            pid=proc.pid,
            ppid=os.getppid(),
            session_id="test",
            claude_pid=None,
            session_alive=False,
            command=cmdline,
        )
        forced = terminate([target], grace=2.0)
        deadline = time.time() + 2
        while time.time() < deadline and proc.poll() is None:
            time.sleep(0.05)
        assert proc.poll() is not None
        assert forced == [] or not is_running(proc.pid)
        assert not is_running(proc.pid)
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGKILL)
            proc.wait()
