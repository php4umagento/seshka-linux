# Contributing

Thanks for helping improve seshka-linux.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

GUI needs system packages (Ubuntu/Debian):

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
```

## Tests

```bash
pytest
```

Scanner/killer tests use a fake `/proc` tree (see `tests/conftest.py`). Prefer fixtures over live process assertions except for the SIGTERM smoke test.

## Design notes

- Core library is stdlib-only so the CLI works without GTK.
- Detection mirrors [seshka](https://github.com/jigjoy-ai/seshka): `CLAUDECODE=1`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_PID`.
- Never kill processes matching user-configured protected patterns.
- PID reuse: compare `/proc/<pid>/cmdline` before signalling.

## Pull requests

- Keep changes focused.
- Add or update tests for scanner/killer behaviour.
- Run `pytest` before opening a PR.
