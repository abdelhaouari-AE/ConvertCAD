#!/usr/bin/env bash
# ConvertCAD — create the development environment on Linux / macOS.
#   ./scripts/setup_venv.sh
# Linux also needs the Qt runtime libraries, e.g. on Ubuntu:
#   sudo apt install libegl1 libxkbcommon-x11-0 libxcb-cursor0 tesseract-ocr
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install -r requirements-dev.txt
echo
echo "Done. Next steps:"
echo "  ./scripts/run_from_source.sh     start the application"
echo "  .venv/bin/python -m pytest       run the tests"
