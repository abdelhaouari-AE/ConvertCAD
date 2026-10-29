#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# ConvertCAD — build the portable Linux program (x86-64).
#
#   ./scripts/build_linux.sh   ->  dist/ConvertCAD/ConvertCAD (+ ConvertCAD-cli)
#                                  dist/ConvertCAD-<version>-linux-x86_64.tar.gz
#
# Then, for the packages (they reuse dist/ConvertCAD/):
#   ./scripts/build_appimage.sh    one-file AppImage, any distribution
#   ./scripts/build_deb.sh         .deb for Debian / Ubuntu / Mint
#
# Included automatically: GNU LibreDWG (DWG output, built here the first
# time, about 5 minutes), RapidOCR and its built-in OCR model (English,
# French and the other Latin languages). Other OCR languages and the maximum
# accuracy models are downloaded by the users from the program (offline
# build: python scripts/get_ocr_models.py --all --dest vendor/ocr_models).
#
# Build on the OLDEST distribution you want to support: programs built
# against a recent glibc do not start on older systems.
# Needs: python3 (3.10+), gcc, make, xz-utils.  Skip the tests with
# CONVERTCAD_NO_TESTS=1.
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi

echo "[1/5] Python packages"
"$PY" -m pip install -r requirements-dev.txt --quiet

echo "[2/5] DWG converter (GNU LibreDWG)"
if [ ! -x vendor/libredwg/linux-x86_64/dxf2dwg ]; then
    bash scripts/build_libredwg.sh linux
else
    echo "    already built: vendor/libredwg/linux-x86_64"
fi

echo "[3/5] Tests"
if [ "${CONVERTCAD_NO_TESTS:-0}" = "1" ]; then
    echo "    skipped (CONVERTCAD_NO_TESTS=1)"
else
    QT_QPA_PLATFORM=offscreen "$PY" -m pytest -q
fi

echo "[4/5] Building (2 to 5 minutes)"
"$PY" scripts/make_icon.py
CONVERTCAD_ONEFILE=0 "$PY" -m PyInstaller --noconfirm --clean ConvertCAD.spec
cp README.md LICENSE THIRD_PARTY_NOTICES.md CHANGELOG.md assets/icon.png \
   dist/ConvertCAD/
# the bundled converter must be executable after PyInstaller's copy
chmod +x dist/ConvertCAD/_internal/libredwg/dxf2dwg \
         dist/ConvertCAD/_internal/libredwg/dwg2dxf 2>/dev/null || true

echo "[5/5] Check and archive"
dist/ConvertCAD/ConvertCAD-cli --version
VER=$("$PY" -c "import convertcad; print(convertcad.APP_VERSION)")
tar -C dist -czf "dist/ConvertCAD-${VER}-linux-x86_64.tar.gz" ConvertCAD
echo "SUCCESS: dist/ConvertCAD/ConvertCAD  and  dist/ConvertCAD-${VER}-linux-x86_64.tar.gz"
