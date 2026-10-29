#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# build_libredwg.sh — build the DWG converter bundled with ConvertCAD.
#
# ConvertCAD writes DWG files with GNU LibreDWG (GPL-3.0-or-later). Version
# 0.13.4 needs three small fixes to its DXF reader (src/in_dxf.c), kept in
# vendor/libredwg/patches/:
#   01-ltype-control-entries.patch  every linetype was listed twice in the
#                                   DWG linetype table (readers reject it)
#   02-dxf-read-string-speed.patch  reading a big DXF was quadratic
#                                   (4 minutes instead of 9 seconds)
#   03-point-keeps-own-values.patch a point given without its Y / Z (e.g.
#                                   the scale of a mirrored block) took the
#                                   Y / Z of the previous point
#
# This script rebuilds that converter from the vendored, unmodified upstream
# source (vendor/libredwg/libredwg-0.13.4.tar.xz) plus the patches:
#
#   ./scripts/build_libredwg.sh linux     -> vendor/libredwg/linux-x86_64/
#   ./scripts/build_libredwg.sh windows   -> vendor/libredwg/win64/
#                                            (cross-compiled with MinGW-w64)
#
# Requirements: gcc, make, xz (linux); gcc-mingw-w64-x86-64 (windows).
# The Windows binaries are already in the repository, so Windows users never
# need to run this. Linux builds (scripts/build_linux.sh) call it.
# ---------------------------------------------------------------------------
set -euo pipefail

TARGET="${1:-linux}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$ROOT/vendor/libredwg"
VERSION="0.13.4"
TARBALL="$VENDOR/libredwg-$VERSION.tar.xz"
SHA256="7e153ea4dac4cbf3dc9c50b9ef7a5604e09cdd4c5520bcf8017877bbe1422cd5"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "== LibreDWG $VERSION for $TARGET"
echo "$SHA256  $TARBALL" | sha256sum -c -
tar -xf "$TARBALL" -C "$WORK"
cd "$WORK/libredwg-$VERSION"
for p in "$VENDOR"/patches/*.patch; do
  echo "   applying $(basename "$p")"
  patch -p1 --quiet < "$p"
done

COMMON=(--disable-bindings --disable-python --disable-shared --enable-static
        --disable-dependency-tracking)
case "$TARGET" in
  linux)
    ./configure "${COMMON[@]}" --prefix="$WORK/install" > "$WORK/configure.log"
    OUT="$VENDOR/linux-x86_64"
    EXE=""
    STRIP=strip
    ;;
  windows)
    ./configure "${COMMON[@]}" --host=x86_64-w64-mingw32 \
        --prefix="$WORK/install" LDFLAGS="-static -static-libgcc" \
        > "$WORK/configure.log"
    OUT="$VENDOR/win64"
    EXE=".exe"
    STRIP=x86_64-w64-mingw32-strip
    ;;
  *)
    echo "usage: $0 linux|windows" >&2
    exit 2
    ;;
esac

make -j"$(nproc)" > "$WORK/make.log"
make install > "$WORK/install.log"
mkdir -p "$OUT"
for tool in dxf2dwg dwg2dxf; do
  "$STRIP" -o "$OUT/$tool$EXE" "$WORK/install/bin/$tool$EXE"
done
if [ "$TARGET" = "windows" ]; then
  # stack-protector runtime used by the MinGW build
  SSP="$(find /usr/lib/gcc/x86_64-w64-mingw32 -name libssp-0.dll | head -n1)"
  cp "$SSP" "$OUT/"
fi
cp "$VENDOR/COPYING" "$OUT/COPYING"
echo "== done: $OUT"
ls -la "$OUT"
