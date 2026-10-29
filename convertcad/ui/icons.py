"""
icons.py — the interface icons, drawn as small SVG line art.

Original drawings on a 24 x 24 grid (stroke 1.6, round caps). They are
coloured at run time with the current theme colour, so they stay crisp at
any screen scaling (100 %, 125 %, 150 %, 200 %) and follow the theme.

    icon("measure")                 -> QIcon in the normal text colour
    icon("convert", "#FFFFFF")      -> QIcon in a given colour
"""

import os
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import theme

_S = ('fill="none" stroke="{c}" stroke-width="1.6" stroke-linecap="round" '
      'stroke-linejoin="round"')

PATHS = {
    "open": '<path d="M3 7.5V18a1.5 1.5 0 0 0 1.5 1.5h15A1.5 1.5 0 0 0 21 18V9.5A1.5 1.5 0 0 0 19.5 8H12l-2-2.5H4.5A1.5 1.5 0 0 0 3 7z"/>',
    "recent": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "sample": '<rect x="4" y="3.5" width="16" height="17" rx="1"/><path d="M4 15.5h16M13 15.5v5M7 7.5h7M7 10.5h4"/>',
    "pan": '<path d="M12 3v18M3 12h18M12 3l-2.5 2.5M12 3l2.5 2.5M12 21l-2.5-2.5M12 21l2.5-2.5M3 12l2.5-2.5M3 12l2.5 2.5M21 12l-2.5-2.5M21 12l-2.5 2.5"/>',
    "calibrate": '<circle cx="5" cy="17" r="2"/><circle cx="19" cy="7" r="2"/><path d="M6.7 15.8 17.3 8.2"/><path d="M9 6.5l1.5 2M12.5 4.5 13.5 6M4 10.5l1.5 2"/>',
    "measure": '<path d="M3 8v8M21 8v8M3 12h18"/><path d="M1.8 13.2 4.2 10.8M19.8 13.2l2.4-2.4"/><path d="M9 9.5h6"/>',
    "fit": '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/><rect x="8" y="8" width="8" height="8" rx="0.5"/>',
    "zoom_in": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 21 21M10.5 7.5v6M7.5 10.5h6"/>',
    "zoom_out": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 21 21M7.5 10.5h6"/>',
    "convert": '<path d="M4 4.5h7v15H4z"/><path d="M14 12h6.5M17.5 9l3 3-3 3"/><path d="M6.5 8h2M6.5 11h2"/>',
    "save": '<path d="M12 3.5v11M7.5 10l4.5 4.5 4.5-4.5"/><path d="M4 15.5V19a1.5 1.5 0 0 0 1.5 1.5h13A1.5 1.5 0 0 0 20 19v-3.5"/>',
    "batch": '<rect x="7" y="3" width="13" height="14" rx="1"/><path d="M4 7v12.5A1.5 1.5 0 0 0 5.5 21H16"/><path d="M10.5 8h6M10.5 11h4"/>',
    "theme": '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" fill="{c}"/>',
    "help": '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.5a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.7"/><path d="M12 16.8v.1"/>',
    "layers": '<path d="M12 3.5 21 8l-9 4.5L3 8z"/><path d="M3 12l9 4.5 9-4.5"/><path d="M3 16l9 4.5 9-4.5"/>',
    "report": '<path d="M6 3h8.5L19 7.5V21H6z"/><path d="M14 3v5h5M9 12h7M9 15h7M9 18h4"/>',
    "settings": '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    "clear": '<path d="M5 7h14M9.5 7V4.5h5V7M7 7l1 13h8l1-13"/>',
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
    "chevron_right": '<path d="M9.5 6l6 6-6 6"/>',
    "chevron_down": '<path d="M6 9.5l6 6 6-6"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "ok": '<circle cx="12" cy="12" r="8.5"/><path d="M8 12.5l2.8 2.8L16.2 9.8"/>',
    "warn": '<path d="M12 3.5 21.5 20h-19z"/><path d="M12 10v4.5M12 17.4v.1"/>',
    "error": '<circle cx="12" cy="12" r="8.5"/><path d="M9 9l6 6M15 9l-6 6"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="1.5"/><path d="M16 8V5.5A1.5 1.5 0 0 0 14.5 4h-9A1.5 1.5 0 0 0 4 5.5v9A1.5 1.5 0 0 0 5.5 16H8"/>',
    "export": '<path d="M12 15V3.5M7.5 8 12 3.5 16.5 8"/><path d="M4 15.5V19a1.5 1.5 0 0 0 1.5 1.5h13A1.5 1.5 0 0 0 20 19v-3.5"/>',
    "folder": '<path d="M3 7.5V18a1.5 1.5 0 0 0 1.5 1.5h15A1.5 1.5 0 0 0 21 18V9.5A1.5 1.5 0 0 0 19.5 8H12l-2-2.5H4.5A1.5 1.5 0 0 0 3 7z"/><path d="M3 11h18"/>',
    "reset": '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 4.5v4h4"/>',
    "rotate": '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v4h-4"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
    "drop": '<rect x="5" y="3" width="14" height="18" rx="1"/><path d="M5 16h14M12.5 16v5M8 7h8M8 10h5"/><path d="M12 9v0"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "info": '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.6v.1"/>',
    "select": '<rect x="3.5" y="4" width="6" height="6" rx="1"/><path d="M5 7l1.2 1.2L8.3 6"/><rect x="3.5" y="14" width="6" height="6" rx="1"/><path d="M13 7h7.5M13 17h7.5"/>',
    "area": '<path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4" /><path d="M10 4h4M10 20h4M4 10v4M20 10v4" stroke-dasharray="1.2 2.2"/><path d="M9 9h6v6H9z" fill="{c}" fill-opacity="0.25"/>',
    "overlay": '<rect x="3" y="6" width="12" height="12" rx="1"/><rect x="9" y="3" width="12" height="12" rx="1" stroke-dasharray="2 2"/>',
}


def svg(name: str, color: str) -> str:
    body = PATHS.get(name, PATHS["info"]).replace("{c}", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'{_S.format(c=color)}>{body}</svg>')


@lru_cache(maxsize=512)
def _icon(name: str, color: str) -> QIcon:
    renderer = QSvgRenderer(QByteArray(svg(name, color).encode("utf-8")))
    ic = QIcon()
    for px in (16, 20, 24, 32, 40, 48, 64):
        img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(p, QRectF(0, 0, px, px))
        p.end()
        ic.addPixmap(QPixmap.fromImage(img))
    return ic


def icon(name: str, color: str = "") -> QIcon:
    return _icon(name, color or theme.tok("text"))


def clear_cache() -> None:
    _icon.cache_clear()


# ---------------------------------------------------------------------------
# Application icon (also used to generate assets/icon.ico)
# ---------------------------------------------------------------------------
APP_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect x="2" y="2" width="60" height="60" rx="13" fill="#0E7490"/>
  <rect x="2" y="2" width="60" height="60" rx="13" fill="none" stroke="#0B5F76" stroke-width="2"/>
  <g fill="none" stroke="#FFFFFF" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
    <path d="M14 47 L14 26 A13 13 0 0 1 40 26 L40 47"/>
    <path d="M14 47 L50 47"/>
    <circle cx="27" cy="26" r="4.5"/>
  </g>
  <g fill="none" stroke="#9FE7EE" stroke-width="2.2" stroke-linecap="round">
    <path d="M14 55 L50 55"/>
    <path d="M11.5 57.5 L16.5 52.5 M47.5 57.5 L52.5 52.5"/>
    <path d="M50 16 L50 41"/>
    <path d="M47.5 43.5 L52.5 38.5 M47.5 18.5 L52.5 13.5"/>
  </g>
</svg>"""


def app_icon() -> QIcon:
    renderer = QSvgRenderer(QByteArray(APP_ICON_SVG.encode("utf-8")))
    ic = QIcon()
    for px in (16, 24, 32, 48, 64, 128, 256):
        img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(p, QRectF(0, 0, px, px))
        p.end()
        ic.addPixmap(QPixmap.fromImage(img))
    return ic


def write_check_svg(folder: str, color: str) -> str:
    """Checkbox tick for the style sheet (Qt style sheets need a file)."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"check_{color.strip('#')}.svg")
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg("check", color).replace('stroke-width="1.6"',
                                                 'stroke-width="2.6"'))
    return path.replace("\\", "/")


def icon_size(px: int = 18) -> QSize:
    return QSize(px, px)
