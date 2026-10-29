#!/usr/bin/env bash
# ConvertCAD — run from the source code on Linux / macOS.
#   ./scripts/run_from_source.sh [drawing.pdf]
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
exec "$PY" main.py "$@"
