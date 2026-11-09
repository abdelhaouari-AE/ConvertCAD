"""
Dimensions and leaders drawn like CAD programs plot them: recognition (large
arrows, values with labels / remarks, feet-inches) and how they are written
(value direction, measured sizes, leader landing and note place).

Each written case is compared with the same PDF converted with dimensions
and leaders OFF: that output is the PDF itself (plain lines and texts).
"""

import math

import ezdxf
import pytest

from conftest import stroke
from convertcad.core import Options, convert
from convertcad.core.annotations import (DIM_TEXT_RE, DIM_VALUE_RE,
                                         reconstruct)
from convertcad.core.compat import pymupdf
from convertcad.core.extractor import extract_page
from convertcad.core.geometry import rebuild

MM = 72 / 25.4                       # one millimetre in PDF points


# ---------------------------------------------------------------------------
# Drawing helpers (AutoCAD-like plot: closed filled arrows 1/3 as wide as
# long, values centred above the dimension line)
# ---------------------------------------------------------------------------
def _arrow(page, tip, direction, length=2.5 * MM):
    dx, dy = direction
    n = math.hypot(dx, dy)
    dx, dy = dx / n, dy / n
    half = length / 6
    bx, by = tip[0] - dx * length, tip[1] - dy * length
    sh = page.new_shape()
    sh.draw_polyline([tip, (bx - dy * half, by + dx * half),
                      (bx + dy * half, by - dx * half), tip])
    sh.finish(color=None, fill=(0, 0, 0), closePath=True)
    sh.commit()


def _line(page, p, q, width=0.25):
    stroke(page, [("line", p, q)], width=width)


def _text(page, p, s, size=9.0, rotate=0):
    page.insert_text(p, s, fontsize=size, rotate=rotate)


def _hdim(page, xa, xb, y, value, size=9.0, arrow=2.5 * MM, right_first=False):
    for x in (xa, xb):
        _line(page, (x, y + 20), (x, y - 2 * MM))
    _line(page, (xa, y), (xb, y))
    ends = [((xa, y), (-1, 0)), ((xb, y), (1, 0))]
    for tip, d in (ends[::-1] if right_first else ends):
        _arrow(page, tip, d, arrow)
    w = 0.5 * size * len(value)
    _text(page, ((xa + xb) / 2 - w / 2, y - 1.5), value, size)


def _vdim(page, x, ya, yb, value, rotate=90, bottom_first=False):
    for y in (ya, yb):
        _line(page, (x + 20, y), (x - 2 * MM, y))
    _line(page, (x, ya), (x, yb))
    ends = [((x, ya), (0, -1)), ((x, yb), (0, 1))]
    for tip, d in (ends[::-1] if bottom_first else ends):
        _arrow(page, tip, d)
    w = 4.5 * len(value)
    if rotate == 90:
        _text(page, (x - 1.5, (ya + yb) / 2 + w / 2), value, rotate=90)
    else:
        _text(page, (x - w - 3, (ya + yb) / 2 + 3), value)


def _leader(page, tip, elbow, end, lines, size=9.0, arrow=2.5 * MM):
    """Leader with a horizontal landing; the note starts 2 pt after the
    landing, its first line centred on it (AutoCAD's default)."""
    stroke(page, [("poly", [tip, elbow, end])], width=0.25)
    _arrow(page, tip, (tip[0] - elbow[0], tip[1] - elbow[1]), arrow)
    width = 0.5 * size * max(len(s) for s in lines)
    x = end[0] + 2 if end[0] >= elbow[0] else end[0] - 2 - width
    for i, s in enumerate(lines):
        _text(page, (x, end[1] + 0.35 * size + i * 1.6 * size), s, size)


def _analyse(path):
    rp = rebuild(extract_page(pymupdf.open(path), 0))
    return reconstruct(rp)


def _both(path, tmp_path):
    """(DXF with dimensions/leaders, the same PDF as plain lines/texts)."""
    on, off = tmp_path / "on.dxf", tmp_path / "off.dxf"
    convert(str(path), str(on), Options())
    convert(str(path), str(off), Options(dimensions=False,
                                         tick_dimensions=False,
                                         leaders=False))
    return ezdxf.readfile(str(on)), ezdxf.readfile(str(off))


def _segments(doc):
    """Every straight piece drawn in the reference (blocks exploded)."""
    ents = list(doc.modelspace())
    for ins in doc.modelspace().query("INSERT"):
        ents += list(ins.virtual_entities())
    out = []
    for e in ents:
        if e.dxftype() == "LINE":
            out.append((e.dxf.start.vec2, e.dxf.end.vec2))
        elif e.dxftype() == "LWPOLYLINE":
            pts = [ezdxf.math.Vec2(p) for p in e.get_points("xy")]
            out += list(zip(pts, pts[1:]))
    return out


def _off_by(lines, segments) -> float:
    """How far the given lines stray from the reference pieces."""
    worst = 0.0
    for a, b in lines:
        for k in range(6):
            p = a.lerp(b, k / 5)
            worst = max(worst, min(_seg_dist(p, s, e) for s, e in segments))
    return worst


def _seg_dist(p, a, b) -> float:
    ab = b - a
    if ab.magnitude < 1e-12:
        return p.distance(a)
    t = max(0.0, min(1.0, (p - a).dot(ab) / ab.dot(ab)))
    return p.distance(a + ab * t)


def _texts(doc):
    """Plain texts of the reference: value -> TEXT entity."""
    return {e.dxf.text.strip(): e for e in doc.modelspace().query("TEXT")}


def _dim_text(doc, dim):
    return next(e for e in doc.blocks.get(dim.dxf.geometry)
                if e.dxftype() == "MTEXT")


# ---------------------------------------------------------------------------
# Recognition
# ---------------------------------------------------------------------------
def test_value_patterns():
    for ok in ("12'-6\"", "4'-3 1/2\"", "10'", "6\"", "3/4\"", "4'-3½\"",
               "3⁵⁰", "2,40 m", "3500 MM"):
        assert DIM_TEXT_RE.match(ok), ok
    for ok in ("L=3500", "3500 (TYP.)", "2x1500", "(3500)", "3500*",
               "3500 ±5", "25 +0.1/-0.2", "Ø20 H7", "EQ", "H = 2.50",
               "1500 c/c"):
        assert DIM_VALUE_RE.match(ok) and not DIM_TEXT_RE.match(ok), ok
    for bad in ("+3.50", "C25/30", "Voile", "2026-10-24", "1/100", "1:100",
                "40x40 cm", "HA 8T16", "POTEAU P1", "Cuve D=3.00"):
        assert not DIM_VALUE_RE.match(bad), bad


@pytest.mark.parametrize("arrow, size", [(3.5 * MM, 12.0),   # 3.5 mm arrows
                                         (5.0 * MM, 18.0)])  # printed 2x
def test_large_arrows_are_found(pdf_factory, arrow, size):
    def draw(page):
        _hdim(page, 50, 250, 100, "6000", size=size, arrow=arrow)
        _hdim(page, 250, 450, 100, "6000", size=size, arrow=arrow)
        _leader(page, (120, 250), (160, 320), (200, 320), ["NOTE"],
                size=size, arrow=arrow)
    ann = _analyse(pdf_factory(draw))
    assert [d.text for d in ann.dimensions] == ["6000", "6000"]
    assert [ld.text.text for ld in ann.leaders] == ["NOTE"]


def test_values_with_labels_remarks_and_feet_inches(pdf_factory):
    values = ["L=3500", "3500 (TYP.)", "2x1500", "(3500)", "3500*",
              "12'-6\"", "4'-3 1/2\""]

    def draw(page):
        for i, v in enumerate(values):
            x = 40 + (i % 4) * 170
            _hdim(page, x, x + 150, 100 + 120 * (i // 4), v)
    ann = _analyse(pdf_factory(draw, width=760))
    assert sorted(d.text for d in ann.dimensions) == sorted(values)
    assert not ann.leaders and not ann.dim_raw_texts


def test_unmatched_labelled_value_stays_a_text(pdf_factory):
    def draw(page):
        _text(page, (100, 100), "L=3500")         # a note, no dimension
        _text(page, (100, 200), "3.50")
    ann = _analyse(pdf_factory(draw))
    assert [t.text for t in ann.dim_raw_texts] == ["3.50"]


def test_dimension_line_is_never_a_leader(pdf_factory):
    """Arrows at both ends, value not recognised: not a leader to the
    nearest note."""
    def draw(page):
        _line(page, (100, 200), (300, 200))
        _arrow(page, (100, 200), (-1, 0))
        _arrow(page, (300, 200), (1, 0))
        _text(page, (302, 203), "NOTE")
    ann = _analyse(pdf_factory(draw))
    assert not ann.leaders and not ann.dimensions


# ---------------------------------------------------------------------------
# Writing: dimensions
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("case", ["right_first", "bottom_first", "ticks_rtl"])
def test_dimension_value_reads_like_the_pdf(pdf_factory, tmp_path, case):
    """The CAD value follows the dimension direction: whatever the order of
    the PDF drawing, it is never upside down, and the arrows stay inside."""
    def draw(page):
        if case == "right_first":
            _hdim(page, 100, 300, 100, "5000", right_first=True)
        elif case == "bottom_first":
            _vdim(page, 300, 60, 260, "7000", bottom_first=True)
        else:                                  # ticks, line drawn right->left
            _line(page, (306, 100), (94, 100))
            for x in (300, 100):
                _line(page, (x, 120), (x, 94))
                _line(page, (x - 3.5, 103.5), (x + 3.5, 96.5), width=0.5)
            _text(page, (190, 98.5), "5000")
    on, off = _both(pdf_factory(draw), tmp_path)
    (dim,) = on.modelspace().query("DIMENSION")
    ref = _texts(off)[dim.dxf.text]
    assert abs(_dim_text(on, dim).get_rotation() - ref.dxf.rotation) < 0.5
    # the CAD dimension draws the PDF lines (no arrow flipped outside)
    lines = [(e.dxf.start.vec2, e.dxf.end.vec2)
             for e in on.blocks.get(dim.dxf.geometry) if e.dxftype() == "LINE"]
    assert _off_by(lines, _segments(off)) < 0.05 * ref.dxf.height


def test_horizontal_value_on_a_vertical_dimension(pdf_factory, tmp_path):
    on, off = _both(pdf_factory(lambda p: _vdim(p, 300, 60, 260, "7000",
                                                rotate=0)), tmp_path)
    (dim,) = on.modelspace().query("DIMENSION")
    assert abs(_dim_text(on, dim).get_rotation()) < 0.5
    assert dim.override().get("dimtih") == 1


def test_dimension_sizes_are_measured(pdf_factory, tmp_path):
    def draw(page):
        _hdim(page, 100, 300, 100, "5000", arrow=3.5 * MM)       # arrows
        y = 250                                                  # ticks
        _line(page, (92, y), (338, y))
        for x in (100, 220, 330):
            _line(page, (x, y + 25), (x, y - 5))
            _line(page, (x - 4, y + 4), (x + 4, y - 4), width=0.5)
        _text(page, (151, y - 2), "3000")
        _text(page, (266, y - 2), "2750")
    on, off = _both(pdf_factory(draw), tmp_path)
    dims = {d.dxf.text: d for d in on.modelspace().query("DIMENSION")}
    assert set(dims) == {"5000", "3000", "2750"}
    # sizes in drawing units: compare with the PDF lengths through the
    # dimension's own measurement (5000 drawn over 200 pt)
    per_pt = dims["5000"].get_measurement() / 200.0
    arrows = dims["5000"].override()
    assert abs(arrows.get("dimasz") - 3.5 * MM * per_pt) < 0.01 * per_pt
    assert arrows.get("dimexo") == 0.0
    assert abs(arrows.get("dimexe") - 2 * MM * per_pt) < 0.05 * per_pt
    ticks = dims["3000"].override()
    tick = 8 * math.sqrt(2.0) * per_pt                   # PDF tick length
    assert abs(ticks.get("dimtsz") * 2 * math.sqrt(2.0) - tick) < 0.05 * per_pt
    assert abs(ticks.get("dimdle") - 8 * per_pt) < 0.05 * per_pt
    for d in dims.values():                 # every CAD line is a PDF line
        h = d.override().get("dimtxt")
        lines = [(e.dxf.start.vec2, e.dxf.end.vec2)
                 for e in on.blocks.get(d.dxf.geometry)
                 if e.dxftype() == "LINE"]
        assert _off_by(lines, _segments(off)) < 0.05 * h


def test_no_extension_line_when_the_pdf_has_none(pdf_factory, tmp_path):
    def draw(page):
        _line(page, (100, 200), (300, 200))
        _arrow(page, (100, 200), (-1, 0))
        _arrow(page, (300, 200), (1, 0))
        _text(page, (190, 198.5), "5000")
    on, _ = _both(pdf_factory(draw), tmp_path)
    (dim,) = on.modelspace().query("DIMENSION")
    ov = dim.override()
    assert ov.get("dimse1") == 1 and ov.get("dimse2") == 1


# ---------------------------------------------------------------------------
# Writing: leaders
# ---------------------------------------------------------------------------
def _mleader(doc):
    (m,) = doc.modelspace().query("MULTILEADER")
    parts = list(m.virtual_entities())
    text = next(e for e in parts if e.dxftype() == "MTEXT")
    lines = [(e.dxf.start.vec2, e.dxf.end.vec2) for e in parts
             if e.dxftype() == "LINE"]
    return m, text, lines


def _top_left(ref):
    """Top-left corner of a reference TEXT (insert + its height 'up')."""
    a = math.radians(ref.dxf.rotation)
    up = ezdxf.math.Vec2(-math.sin(a), math.cos(a))
    return ref.dxf.insert.vec2 + up * ref.dxf.height


@pytest.mark.parametrize("case", ["middle", "left", "underline", "straight",
                                  "rotated"])
def test_leader_is_drawn_like_the_pdf(pdf_factory, tmp_path, case):
    """The MULTILEADER draws the PDF leader (shaft, landing) and keeps the
    note at its PDF place, in its PDF direction."""
    def draw(page):
        if case == "middle":          # landing at mid-height of the line
            _leader(page, (120, 250), (160, 300), (200, 300),
                    ["DALLE EP. 20 cm"])
        elif case == "left":          # note on the left of the leader
            _leader(page, (300, 250), (260, 200), (230, 200), ["Cuve D=3.00"])
        elif case == "underline":     # note written ON the landing
            stroke(page, [("poly", [(150, 250), (200, 200), (244, 200)])],
                   width=0.25)
            _arrow(page, (150, 250), (-50, 50))
            _text(page, (204, 198), "TAG-101")
        elif case == "straight":      # no landing
            stroke(page, [("poly", [(150, 250), (198, 203)])], width=0.25)
            _arrow(page, (150, 250), (-48, 47))
            _text(page, (200, 206), "NOTE")
        else:                         # note turned 90 degrees
            stroke(page, [("poly", [(150, 300), (200, 250), (200, 210)])],
                   width=0.25)
            _arrow(page, (150, 300), (-50, 50))
            _text(page, (203, 206), "NOTE", rotate=90)
    on, off = _both(pdf_factory(draw), tmp_path)
    m, text, lines = _mleader(on)
    first = text.plain_text().split("\n")[0].strip()
    ref = _texts(off)[first]
    h = ref.dxf.height
    assert abs(text.get_rotation() - ref.dxf.rotation) < 0.5
    assert _off_by(lines, _segments(off)) < 0.15 * h
    corner = text.dxf.insert.vec2
    if text.dxf.attachment_point == 1:                  # top-left
        assert corner.distance(_top_left(ref)) < 0.1 * h
    else:                                               # top-right
        assert case == "left" and text.dxf.attachment_point == 3
        assert abs(corner.y - _top_left(ref).y) < 0.1 * h
    if case == "middle":
        assert m.context.left_attachment == 1           # middle of top line
    if case == "underline":
        assert m.context.left_attachment == 6           # underlined
