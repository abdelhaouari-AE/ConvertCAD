"""
make_icon.py — regenerate the application icon files in assets/.

The icon is drawn once, as SVG, in convertcad/ui/icons.py (APP_ICON_SVG).
This script renders it to:

    assets/icon.svg   the source drawing (for the README, the web, ...)
    assets/icon.png   256 x 256 PNG
    assets/icon.ico   multi-size Windows icon (16 ... 256 px) used by
                      PyInstaller for ConvertCAD.exe

Only PySide6 is needed (already a dependency). Run from the repository root:

    python scripts/make_icon.py
"""

import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # no window needed

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

from convertcad.ui.icons import APP_ICON_SVG  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)   # sizes Windows asks for
ASSETS = os.path.join(ROOT, "assets")


def render_png(renderer: QSvgRenderer, px: int) -> bytes:
    """Render the SVG at px x px and return PNG bytes."""
    img = QImage(px, px, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(data)


def write_ico(path: str, images: dict) -> None:
    """Pack PNG images into one .ico file (PNG entries, Windows Vista+).

    ICO layout: 6-byte header, one 16-byte directory entry per image, then
    the PNG data. A width/height byte of 0 means 256 px.
    """
    sizes = sorted(images)
    offset = 6 + 16 * len(sizes)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    entries, blobs = b"", b""
    for px in sizes:
        png = images[px]
        dim = 0 if px >= 256 else px
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32,
                               len(png), offset)
        blobs += png
        offset += len(png)
    with open(path, "wb") as fh:
        fh.write(header + entries + blobs)


def main() -> int:
    app = QGuiApplication(sys.argv[:1])          # noqa: F841 (needed by Qt)
    os.makedirs(ASSETS, exist_ok=True)
    renderer = QSvgRenderer(QByteArray(APP_ICON_SVG.encode("utf-8")))
    if not renderer.isValid():
        print("ERROR: APP_ICON_SVG is not a valid SVG drawing.")
        return 1
    images = {px: render_png(renderer, px) for px in SIZES}
    with open(os.path.join(ASSETS, "icon.svg"), "w", encoding="utf-8") as fh:
        fh.write(APP_ICON_SVG + "\n")
    with open(os.path.join(ASSETS, "icon.png"), "wb") as fh:
        fh.write(images[256])
    write_ico(os.path.join(ASSETS, "icon.ico"), images)
    print("Written: assets/icon.svg, assets/icon.png, assets/icon.ico "
          f"({', '.join(str(s) for s in SIZES)} px)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
