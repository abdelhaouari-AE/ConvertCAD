"""
samples.py — generates demonstration PDF drawings.

Used by:
  * the interface ("Open a sample drawing" on the welcome screen)
  * the test-suite (tests/conftest.py) — every feature is exercised
  * scripts/make_samples.py (writes samples/*.pdf for the repository)

The sample is a formwork plan (plan de coffrage) at 1:100 on an A3 sheet:
grid axes in CENTER linetype with axis bubbles, repeated columns (block
detection), walls, doors (blocks), a circular tank (circles), a curved wall
(arc), a free-form curve (spline), arrow dimension chains, architectural
tick dimensions, leaders, a multi-line notes paragraph (MTEXT), hatches and
a title block. A second, ROTATED page checks /Rotate handling.
"""

import math
import os

from .core.compat import pymupdf

A3_W, A3_H = 1190.55, 841.89          # A3 landscape, points
SCALE = 100                            # 1:100
M = 1000.0 / SCALE / (25.4 / 72.0)     # metres -> points (28.3465)

BLACK, GRAY, RED, BLUE = (0, 0, 0), (0.45, 0.45, 0.45), (0.85, 0.1, 0.1), \
    (0.1, 0.25, 0.8)
CENTER_DASH = "[12 3 2 3] 0"
HIDDEN_DASH = "[6 3] 0"


def _arrow(page, tip, direction, length=7.0, half_width=1.2, color=BLACK):
    """Filled arrowhead pointing along `direction` with its tip at `tip`."""
    dx, dy = direction
    n = math.hypot(dx, dy)
    dx, dy = dx / n, dy / n
    bx, by = tip[0] - dx * length, tip[1] - dy * length
    px, py = -dy * half_width, dx * half_width
    sh = page.new_shape()
    sh.draw_polyline([tip, (bx + px, by + py), (bx - px, by - py), tip])
    sh.finish(color=None, fill=color, closePath=True)
    sh.commit()


def _line(page, p, q, width=0.35, color=BLACK, dashes=None):
    sh = page.new_shape()
    sh.draw_line(p, q)
    sh.finish(color=color, width=width, dashes=dashes, closePath=False)
    sh.commit()


def _text(page, p, s, size=8.0, rotate=0, color=BLACK):
    page.insert_text(p, s, fontsize=size, fontname="helv", rotate=rotate,
                     color=color)


def draw_plan(page) -> None:
    """Draw the demonstration formwork plan on an A3 landscape page."""
    x0, y0 = 150.0, 190.0                   # origin of axis A / axis 1
    ax_x = [x0 + i * 6.0 * M for i in range(5)]          # A..E every 6.00 m
    ax_y = [y0 + j * 5.0 * M for j in range(4)]          # 1..4 every 5.00 m
    letters, numbers = "ABCDE", "1234"

    # ---- sheet frame and title block -------------------------------------
    sh = page.new_shape()
    sh.draw_rect(pymupdf.Rect(20, 20, A3_W - 20, A3_H - 20))
    sh.finish(color=BLACK, width=1.2)
    tb = pymupdf.Rect(A3_W - 360, A3_H - 150, A3_W - 20, A3_H - 20)
    sh.draw_rect(tb)
    sh.draw_line((tb.x0, tb.y0 + 40), (tb.x1, tb.y0 + 40))
    sh.draw_line((tb.x0, tb.y0 + 90), (tb.x1, tb.y0 + 90))
    sh.draw_line((tb.x0 + 220, tb.y0 + 90), (tb.x0 + 220, tb.y1))
    sh.finish(color=BLACK, width=0.6)
    sh.commit()
    _text(page, (tb.x0 + 10, tb.y0 + 26), "PROJET : BATIMENT INDUSTRIEL TYPE",
          size=11)
    _text(page, (tb.x0 + 10, tb.y0 + 62), "PLAN DE COFFRAGE", size=14)
    _text(page, (tb.x0 + 10, tb.y0 + 80), "NIVEAU +3.50", size=10)
    _text(page, (tb.x0 + 10, tb.y0 + 110), "Echelle : 1/100", size=9)
    _text(page, (tb.x0 + 230, tb.y0 + 110), "Indice : A", size=9)
    _text(page, (tb.x0 + 10, tb.y0 + 124), "Date : 2026-10-24", size=9)

    # ---- grid axes (CENTER linetype) + bubbles ---------------------------
    top, bottom = y0 - 45, ax_y[-1] + 25
    left, right = x0 - 45, ax_x[-1] + 25
    for x, name in zip(ax_x, letters):
        _line(page, (x, top + 10), (x, bottom), 0.25, GRAY, CENTER_DASH)
        sh = page.new_shape()
        sh.draw_circle((x, top), 10)
        sh.finish(color=BLACK, width=0.35)
        sh.commit()
        _text(page, (x - 3.6, top + 3.6), name, size=10)
    for y, name in zip(ax_y, numbers):
        _line(page, (left + 10, y), (right, y), 0.25, GRAY, CENTER_DASH)
        sh = page.new_shape()
        sh.draw_circle((left, y), 10)
        sh.finish(color=BLACK, width=0.35)
        sh.commit()
        _text(page, (left - 3.0, y + 3.6), name, size=10)

    # ---- hidden beams between columns (DASHED) ----------------------------
    for y in ax_y:
        for xa, xb in zip(ax_x, ax_x[1:]):
            _line(page, (xa + 6, y - 4), (xb - 6, y - 4), 0.3, BLUE, HIDDEN_DASH)

    # ---- columns 40x40 at every intersection: repeated symbol -> BLOCK ----
    c = 0.20 * M
    for x in ax_x:
        for y in ax_y:
            sh = page.new_shape()
            sh.draw_rect(pymupdf.Rect(x - c, y - c, x + c, y + c))
            sh.finish(color=BLACK, fill=(0.75, 0.75, 0.75), width=0.6)
            sh.draw_line((x - c, y - c), (x + c, y + c))
            sh.draw_line((x - c, y + c), (x + c, y - c))
            sh.finish(color=BLACK, width=0.18)
            sh.commit()

    # ---- external walls (thick) ------------------------------------------
    sh = page.new_shape()
    sh.draw_polyline([(ax_x[0] - c, ax_y[0] - c), (ax_x[-1] + c, ax_y[0] - c),
                      (ax_x[-1] + c, ax_y[-1] + c), (ax_x[0] - c, ax_y[-1] + c),
                      (ax_x[0] - c, ax_y[0] - c)])
    sh.finish(color=BLACK, width=1.2, closePath=True)
    sh.commit()

    # ---- doors: leaf + 90 deg swing arc, repeated 3x -> BLOCK -------------
    leaf = 0.9 * M
    for x in (ax_x[0] + 2.0 * M, ax_x[1] + 2.0 * M, ax_x[2] + 2.0 * M):
        y = ax_y[-1] + c
        sh = page.new_shape()
        sh.draw_line((x, y), (x, y - leaf))
        sh.finish(color=BLACK, width=0.35, closePath=False)
        k = 0.5523 * leaf                       # quarter circle as a Bezier
        sh.draw_bezier((x, y - leaf), (x + k, y - leaf), (x + leaf, y - k),
                       (x + leaf, y))
        sh.finish(color=BLACK, width=0.18, closePath=False)
        sh.commit()

    # ---- circular tank: two concentric circles -> CIRCLE x2 --------------
    tc = (ax_x[3] + 3.0 * M, ax_y[1] + 2.5 * M)
    for r in (1.5 * M, 1.3 * M):
        sh = page.new_shape()
        sh.draw_circle(tc, r)
        sh.finish(color=RED, width=0.5)
        sh.commit()

    # ---- curved wall: a 90 deg arc -> ARC; free curve -> SPLINE -----------
    ac = (ax_x[0], ax_y[1])
    R = 2.0 * M
    k = 0.5523 * R
    sh = page.new_shape()
    sh.draw_bezier((ac[0] + R, ac[1]), (ac[0] + R, ac[1] + k),
                   (ac[0] + k, ac[1] + R), (ac[0], ac[1] + R))
    sh.finish(color=BLACK, width=0.5, closePath=False)
    sh.draw_bezier((ax_x[1] + 20, ax_y[2] + 30), (ax_x[1] + 80, ax_y[2] - 20),
                   (ax_x[2] - 60, ax_y[2] + 80), (ax_x[2] - 10, ax_y[2] + 40))
    sh.draw_bezier((ax_x[2] - 10, ax_y[2] + 40), (ax_x[2] + 20, ax_y[2] + 10),
                   (ax_x[2] + 60, ax_y[2] + 70), (ax_x[2] + 100, ax_y[2] + 50))
    sh.finish(color=(0.1, 0.55, 0.2), width=0.5, closePath=False)
    sh.commit()

    # ---- slab opening: light hatch ---------------------------------------
    sh = page.new_shape()
    sh.draw_rect(pymupdf.Rect(ax_x[3] + 30, ax_y[0] + 30,
                              ax_x[3] + 30 + 2.0 * M, ax_y[0] + 30 + 1.5 * M))
    sh.finish(color=None, fill=(0.82, 0.88, 1.0))
    sh.commit()

    # ---- arrow dimension chain (top): 4 x 6000 + overall 24000 -----------
    yd = top - 30
    for x in ax_x:
        _line(page, (x, top - 13), (x, yd - 5), 0.25)          # extension
    for xa, xb in zip(ax_x, ax_x[1:]):
        _line(page, (xa, yd), (xb, yd), 0.25)
        _arrow(page, (xa, yd), (-1, 0))
        _arrow(page, (xb, yd), (1, 0))
        _text(page, ((xa + xb) / 2 - 9, yd - 3), "6000", size=8)
    yo = yd - 22
    _line(page, (ax_x[0], yd - 5), (ax_x[0], yo - 5), 0.25)
    _line(page, (ax_x[-1], yd - 5), (ax_x[-1], yo - 5), 0.25)
    _line(page, (ax_x[0], yo), (ax_x[-1], yo), 0.25)
    _arrow(page, (ax_x[0], yo), (-1, 0))
    _arrow(page, (ax_x[-1], yo), (1, 0))
    _text(page, ((ax_x[0] + ax_x[-1]) / 2 - 11, yo - 3), "24000", size=8)

    # ---- tick dimension chain (right, vertical): 3 x 5000 ----------------
    xd = right + 40
    for y in ax_y:
        _line(page, (right + 12, y), (xd + 5, y), 0.25)         # extension
    _line(page, (xd, ax_y[0] - 6), (xd, ax_y[-1] + 6), 0.25)   # dim line
    for y in ax_y:                                              # 45 deg ticks
        _line(page, (xd - 3.5, y + 3.5), (xd + 3.5, y - 3.5), 0.5)
    for ya, yb in zip(ax_y, ax_y[1:]):
        _text(page, (xd - 3, (ya + yb) / 2 + 9), "5000", size=8, rotate=90)

    # ---- leaders ----------------------------------------------------------
    for tip, mid, note in (
            ((ax_x[0] + c, ax_y[2] + 60), (ax_x[0] + 60, ax_y[2] + 100),
             "Voile BA ep. 20 cm"),
            ((tc[0] - 1.5 * M * 0.7071, tc[1] - 1.5 * M * 0.7071),
             (tc[0] - 60, tc[1] - 100), "Cuve D=3.00 m")):
        land = (mid[0] + (35 if mid[0] > tip[0] else -35), mid[1])
        sh = page.new_shape()
        sh.draw_polyline([tip, mid, land])
        sh.finish(color=BLACK, width=0.25, closePath=False)
        sh.commit()
        _arrow(page, tip, (tip[0] - mid[0], tip[1] - mid[1]))
        tx = land[0] + 3 if land[0] > mid[0] else land[0] - 4.6 * len(note) - 3
        _text(page, (tx, land[1] + 3), note, size=8)

    # ---- an orphan level value -> DIM_RAW for review ----------------------
    _text(page, (ax_x[1] + 12, ax_y[1] + 22), "3.50", size=8, color=RED)

    # ---- notes paragraph -> MTEXT -----------------------------------------
    nx, ny = 40, A3_H - 140
    for k, line in enumerate(("NOTES :", "1. Beton C25/30 - classe XC1",
                              "2. Enrobage des aciers : 30 mm",
                              "3. Acier FeE500 - cotes en mm")):
        _text(page, (nx, ny + k * 12), line, size=8.5)


def draw_rotated_page(page) -> None:
    """A simple drawing on a page carrying /Rotate 90 (tests rotation)."""
    sh = page.new_shape()
    sh.draw_rect(pymupdf.Rect(60, 60, 300, 200))
    sh.finish(color=BLACK, width=0.8)
    sh.draw_circle((180, 130), 40)
    sh.finish(color=RED, width=0.5)
    sh.commit()
    _text(page, (70, 230), "PAGE TOURNEE 90", size=12)
    page.set_rotation(90)


def make_sample_plan(path: str, with_rotated_page: bool = True) -> str:
    """Write the vector demonstration PDF; returns its path."""
    doc = pymupdf.open()
    draw_plan(doc.new_page(width=A3_W, height=A3_H))
    if with_rotated_page:
        draw_rotated_page(doc.new_page(width=420, height=297))
    doc.set_metadata({"title": "ConvertCAD sample - plan de coffrage",
                      "creator": "ConvertCAD samples", "producer": "PyMuPDF"})
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


def make_sample_scan(path: str, dpi: int = 150) -> str:
    """Write an image-only ('scanned') version of the sample plan."""
    src = pymupdf.open()
    draw_plan(src.new_page(width=A3_W, height=A3_H))
    pix = src[0].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    out = pymupdf.open()
    page = out.new_page(width=A3_W, height=A3_H)
    page.insert_image(page.rect, pixmap=pix)
    out.set_metadata({"title": "ConvertCAD sample - scanned plan",
                      "creator": "ConvertCAD samples (scan simulation)"})
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    out.save(path, garbage=3, deflate=True)
    out.close()
    src.close()
    return path
