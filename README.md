# seshka-linux

Ubuntu PoC of [seshka](https://github.com/jigjoy-ai/seshka): find and kill processes Claude Code left behind after a session closes.

## Quick start

```bash
./seshka.py list
./seshka.py list --all
./seshka.py kill --all -n          # dry-run leftovers
./seshka.py kill --pid 1234
./seshka.py kill --session 529d2a31
./seshka.py kill --all             # really kill leftovers
```

No dependencies beyond Python 3.10+.

## How it works

Claude Code stamps children with `CLAUDECODE=1`, `CLAUDE_CODE_SESSION_ID`, and often `CLAUDE_PID`. This tool reads those from `/proc/<pid>/environ`, treats a process as leftover when its Claude parent is gone, and can SIGTERM/SIGKILL them.
