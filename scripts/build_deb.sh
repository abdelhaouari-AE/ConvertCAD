#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# ConvertCAD — .deb package for Debian, Ubuntu, Linux Mint ...
#
#   ./scripts/build_deb.sh   ->  dist/convertcad_<version>_amd64.deb
#
# Users install it with:   sudo apt install ./convertcad_<version>_amd64.deb
# (apt also installs the few system libraries Qt needs). Menu entry
# "ConvertCAD"; commands "convertcad" (application) and "convertcad-cli"
# (command line).
#
# Uses dist/ConvertCAD/ (runs scripts/build_linux.sh first when missing).
# Needs dpkg-deb (Debian / Ubuntu). Set DEB_MAINTAINER="Name <email>" to
# change the maintainer field.
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
[ -x dist/ConvertCAD/ConvertCAD ] || bash scripts/build_linux.sh
VER=$("$PY" -c "import convertcad; print(convertcad.APP_VERSION)")
MAINTAINER="${DEB_MAINTAINER:-abdelhaouari <abdelhaouari-AE@users.noreply.github.com>}"
# the program needs at least the glibc it was built with
GLIBC=$(ldd --version | head -n1 | grep -oE '[0-9]+\.[0-9]+$')

PKG="build/deb/convertcad_${VER}_amd64"
rm -rf "$PKG"
mkdir -p "$PKG/DEBIAN" "$PKG/opt/convertcad" "$PKG/usr/bin" \
         "$PKG/usr/share/applications" \
         "$PKG/usr/share/icons/hicolor/256x256/apps" \
         "$PKG/usr/share/doc/convertcad"

# ---- files ------------------------------------------------------------------
cp -a dist/ConvertCAD/. "$PKG/opt/convertcad/"
ln -s /opt/convertcad/ConvertCAD "$PKG/usr/bin/convertcad"
ln -s /opt/convertcad/ConvertCAD-cli "$PKG/usr/bin/convertcad-cli"
sed 's|^Exec=.*|Exec=/usr/bin/convertcad %F|' packaging/linux/convertcad.desktop \
    > "$PKG/usr/share/applications/convertcad.desktop"
cp assets/icon.png "$PKG/usr/share/icons/hicolor/256x256/apps/convertcad.png"
gzip -9n -c CHANGELOG.md > "$PKG/usr/share/doc/convertcad/changelog.gz"
cat > "$PKG/usr/share/doc/convertcad/copyright" <<EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: ConvertCAD
Source: https://github.com/abdelhaouari-AE/ConvertCAD

Files: *
Copyright: $(date +%Y) abdelhaouari
License: AGPL-3.0-only
 The full text is in /opt/convertcad/LICENSE. The licences of the bundled
 components (Qt, PyMuPDF, ezdxf, GNU LibreDWG, RapidOCR, ONNX Runtime, ...)
 are listed in /opt/convertcad/THIRD_PARTY_NOTICES.md.
EOF
# group/other must not write anything (lintian, security)
chmod -R go-w "$PKG"

# ---- control ------------------------------------------------------------------
SIZE=$(du -sk --exclude=DEBIAN "$PKG" | cut -f1)
cat > "$PKG/DEBIAN/control" <<EOF
Package: convertcad
Version: ${VER}
Section: graphics
Priority: optional
Architecture: amd64
Maintainer: ${MAINTAINER}
Installed-Size: ${SIZE}
Depends: libc6 (>= ${GLIBC}), libgl1, libegl1, libfontconfig1, libfreetype6, libdbus-1-3, libxkbcommon0, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-keysyms1, libxcb-shape0
Homepage: https://github.com/abdelhaouari-AE/ConvertCAD
Description: PDF to DXF/DWG converter for engineering drawings
 ConvertCAD turns vector and scanned PDF drawings into editable DXF and DWG
 files built with real CAD entities: lines, polylines, arcs, circles,
 hatches, texts, dimensions, leaders, blocks and layers. It reads the
 drawing scale, rebuilds dashed lines and hatch patterns, recovers AutoCAD
 SHX texts and runs OCR on scanned sheets (English, French and the other
 Latin languages built in; Arabic, Cyrillic, Greek... downloaded from the
 program). Everything works offline.
EOF

mkdir -p dist
dpkg-deb --root-owner-group --build "$PKG" "dist/convertcad_${VER}_amd64.deb"
echo "SUCCESS: dist/convertcad_${VER}_amd64.deb"
