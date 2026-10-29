#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# ConvertCAD — Linux AppImage: ONE file that runs on most x86-64
# distributions, nothing to install.
#
#   ./scripts/build_appimage.sh   ->  dist/ConvertCAD-<version>-x86_64.AppImage
#
# Uses dist/ConvertCAD/ (runs scripts/build_linux.sh first when missing) and
# appimagetool, downloaded once into build/tools/ (or set APPIMAGETOOL to
# an appimagetool you already have).
#
# Users:   chmod +x ConvertCAD-<version>-x86_64.AppImage
#          ./ConvertCAD-<version>-x86_64.AppImage              the application
#          ./ConvertCAD-<version>-x86_64.AppImage --cli a.pdf  command line
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
[ -x dist/ConvertCAD/ConvertCAD ] || bash scripts/build_linux.sh
VER=$("$PY" -c "import convertcad; print(convertcad.APP_VERSION)")

# ---- appimagetool -----------------------------------------------------------
TOOL="${APPIMAGETOOL:-build/tools/appimagetool-x86_64.AppImage}"
if [ ! -x "$TOOL" ]; then
    mkdir -p build/tools
    echo "Downloading appimagetool ..."
    curl -fL -o "$TOOL" \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$TOOL"
fi

# ---- AppDir -----------------------------------------------------------------
APPDIR=build/AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib/convertcad" \
         "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a dist/ConvertCAD/. "$APPDIR/usr/lib/convertcad/"
install -m 755 packaging/linux/AppRun "$APPDIR/AppRun"
cp packaging/linux/convertcad.desktop "$APPDIR/convertcad.desktop"
cp packaging/linux/convertcad.desktop "$APPDIR/usr/share/applications/"
cp assets/icon.png "$APPDIR/convertcad.png"
cp assets/icon.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/convertcad.png"
ln -sf convertcad.png "$APPDIR/.DirIcon"

# ---- pack -------------------------------------------------------------------
OUT="dist/ConvertCAD-${VER}-x86_64.AppImage"
# --appimage-extract-and-run: works without FUSE (containers, CI)
ARCH=x86_64 "$TOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "$OUT"
chmod +x "$OUT"
echo "SUCCESS: $OUT"
