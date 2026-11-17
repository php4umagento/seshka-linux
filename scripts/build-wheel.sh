#!/usr/bin/env bash
# Build pip sdist + wheel into dist/
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pip install --user -q build
rm -rf dist build *.egg-info src/*.egg-info
python3 -m build
ls -la dist/
