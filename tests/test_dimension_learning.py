"""
Dimension recognition that learns from the sheet: the drawing scale checks
the values, terminators of any shape (open, outline, dots, squares, X),
values split in several texts, sizes judged locally, AutoCAD SHX values, and
dimensions that cannot be rebuilt kept together with their value.

Scale used on most sheets below: 5000 written over 141.7 pt (1:100 on the
sheet, 1 pt = 35.28 mm). Two such dimensions are enough to know the scale.
"""

import math

import ezdxf
import pytest

from conftest import stroke
from convertcad.core import Options, convert
from convertcad.core.annotations import reconstruct
from convertcad.core.compat import pymupdf
from convertcad.core.constants import (LAYER_DIM, LAYER_DIM_CHECK,
                                       LAYER_DIM_RAW, LAYER_SHX_TEXT)
from convertcad.core.dimvalues import ScaleVotes, is_value, value_number
from convertcad.core.extractor import SHX_TITLE, extract_page
from convertcad.core.geometry import rebuild

MM = 72 / 25.4                       # one millimetre in PDF points
K = 141.7 / 5000                     # points per written unit (1:100)


# ---------------------------------------------------------------------------
# Drawing helpers (AutoCAD-like plot)
# ---------------------------------------------------------------------------
def _arrow(page, tip, direction, length=2.5 * MM, kind="filled"):
    """Terminator at `tip`, pointing along `direction`.
    kind: filled | blank (outline) | open (two strokes, 15° half) | dot."""
    dx, dy = direction
    n = math.hypot(dx, dy)
    dx, dy = dx / n, dy / n
    half = length / 6
    bx, by = tip[0] - dx * length, tip[1] - dy * length
    sh = page.new_shape()
    if kind in ("filled", "blank"):
        sh.draw_polyline([tip, (bx - dy * half, by + dx * half),
                          (bx + dy * half, by - dx * half), tip])
        if kind == "filled":
            sh.finish(color=None, fill=(0, 0, 0), closePath=True)
        else:
            sh.finish(color=(0, 0, 0), width=0.25, closePath=True)
    elif kind == "open":
        h2 = length * math.tan(math.radians(15))
        sh.draw_line(tip, (bx - dy * h2, by + dx * h2))
        sh.draw_line(tip, (bx + dy * h2, by - dx * h2))
        sh.finish(color=(0, 0, 0), width=0.25)
    else:                                                  # dot
        sh.draw_circle(tip, length / 4)
        sh.finish(color=None, fill=(0, 0, 0))
    sh.commit()


def _square(page, c, half=1.6):
    sh = page.new_shape()
    sh.draw_rect(pymupdf.Rect(c[0] - half, c[1] - half,
                              c[0] + half, c[1] + half))
    sh.finish(color=None, fill=(0, 0, 0))
    sh.commit()


def _line(page, p, q, width=0.25):
    stroke(page, [("line", p, q)], width=width)


def _text(page, p, s, size=9.0):
    page.insert_text(p, s, fontsize=size)


def _hdim(page, xa, xb, y, value, kind="filled", size=9.0, arrow=2.5 * MM):
    """Horizontal dimension, value centred above the line."""
    for x in (xa, xb):
        _line(page, (x, y + 20), (x, y - 2 * MM))
    _line(page, (xa, y), (xb, y))
    for tip, d in (((xa, y), (-1, 0)), ((xb, y), (1, 0))):
        if kind == "square":
            _square(page, tip)
        else:
            _arrow(page, tip, d, arrow, kind)
    if value:
        w = 0.5 * size * len(value)
        _text(page, ((xa + xb) / 2 - w / 2, y - 1.5), value, size)


def _scale_pair(page, y=80):
    """Two clear dimensions that tell the scale (5000 and 4500)."""
    _hdim(page, 50, 50 + 5000 * K, y, "5000")
    _hdim(page, 50 + 5000 * K, 50 + 9500 * K, y, "4500")


def _analyse(path):
    return reconstruct(rebuild(extract_page(pymupdf.open(path), 0)))


def _dims(doc):
    return {d.dxf.text: d for d in doc.modelspace().query("DIMENSION")}


# ---------------------------------------------------------------------------
# Values: what counts as one, the number it gives, the scale check
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("note", ["5 HA12", "4T16", "12 T10", "20 A1",
                                  "2 P1", "HA 8T16", "4 HA 10"])
def test_rebar_notes_and_counts_are_not_values(note):
    assert not is_value(note)


@pytest.mark.parametrize("value", ["5000", "L=3500", "2x1500", "(3500)",
                                   "3500*", "3500 (TYP.)", "12'-6\"",
                                   "25 +0.1/-0.2", "Ø12 H7"])
def test_values_are_still_values(value):
    assert is_value(value)


def test_value_numbers():
    assert value_number("L=3500") == (3500.0, "metric")
    assert value_number("12'-6\"") == (150.0, "imperial")
    assert value_number("3⁵⁰") == (3.5, "metric")
    assert value_number("EQ") is None


def test_scale_votes_compare_modulo_powers_of_ten():
    votes = ScaleVotes()
    votes.add(5000, "metric", 5000 * K)
    votes.add(4500, "metric", 4500 * K)
    votes.finish()
    assert votes.known
    assert votes.check(3500, "metric", 3500 * K) is True
    assert votes.check(3.5, "metric", 3500 * K) is True   # same, in metres
    assert votes.check(15, "metric", 100) is False
    assert votes.check(120, "imperial", 100) is None      # no imperial vote


def test_rebar_note_beside_a_value_stays_a_note(pdf_factory):
    def draw(p):
        _hdim(p, 100, 100 + 4500 * K, 150, "4500")
        _text(p, (150, 140), "5 HA12")
    ann = _analyse(pdf_factory(draw))
    assert [d.text for d in ann.dimensions] == ["4500"]
    assert not [t for t in ann.dim_raw_texts if "HA" in t.text]


def test_doubtful_values_are_checked_against_the_scale(pdf_factory):
    def draw(p):
        _scale_pair(p)
        _hdim(p, 50, 50 + 3500 * K, 200, "L=3500")   # agrees with the scale
        _hdim(p, 300, 400, 200, "e=15")              # 15 over 100 pt: no
    ann = _analyse(pdf_factory(draw, width=700))
    assert sorted(d.text for d in ann.dimensions) == ["4500", "5000",
                                                      "L=3500"]
    assert not ann.to_review


def test_value_against_the_scale_goes_to_review(pdf_factory, tmp_path):
    def draw(p):
        _scale_pair(p)
        _hdim(p, 50, 150, 200, "9000")               # 9000 over 100 pt
    pdf = pdf_factory(draw, width=700)
    ann = _analyse(pdf)
    review = [d.text for d in ann.dimensions if d.review]
    assert review == ["9000"] and ann.to_review == 1
    out = tmp_path / "r.dxf"
    rep = convert(pdf, str(out), Options())
    dims = _dims(ezdxf.readfile(str(out)))
    assert dims["9000"].dxf.layer == LAYER_DIM_CHECK
    assert dims["5000"].dxf.layer == LAYER_DIM
    assert rep.stats.dims_to_check == 1
    assert any("DIM_CHECK" in n for n in rep.page_notes)


# ---------------------------------------------------------------------------
# Terminators: open, outline, dots, squares learned from the sheet, X
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind, block", [("open", "OPEN30"),
                                         ("blank", "CLOSEDBLANK"),
                                         ("dot", "DOT")])
def test_terminator_kinds_are_found_and_kept(pdf_factory, tmp_path, kind,
                                             block):
    def draw(p):
        _hdim(p, 50, 200, 100, "5000", kind=kind)
        _hdim(p, 200, 330, 100, "4500", kind=kind)
        if kind != "blank":                          # leader with that end
            tip, elbow, end = (120, 250), (160, 300), (200, 300)
            stroke(p, [("poly", [tip, elbow, end])], width=0.25)
            _arrow(p, tip, (tip[0] - elbow[0], tip[1] - elbow[1]), kind=kind)
            _text(p, (202, 303), "NOTE")
    pdf = pdf_factory(draw)
    ann = _analyse(pdf)
    assert sorted(d.text for d in ann.dimensions) == ["4500", "5000"]
    assert len(ann.leaders) == (0 if kind == "blank" else 1)
    out = tmp_path / "t.dxf"
    convert(pdf, str(out), Options())
    for dim in _dims(ezdxf.readfile(str(out))).values():
        assert dim.override().get("dimblk") == block


def test_terminators_learned_from_the_sheet(pdf_factory, tmp_path):
    """Squares are no known terminator: repeated at line ends next to
    values, the sheet teaches them."""
    def draw(p):
        _scale_pair(p)
        _hdim(p, 50, 50 + 4000 * K, 200, "4000", kind="square")
        _hdim(p, 50 + 4000 * K, 50 + 7000 * K, 200, "3000", kind="square")
    pdf = pdf_factory(draw, width=700)
    ann = _analyse(pdf)
    assert sorted(d.text for d in ann.dimensions) == ["3000", "4000",
                                                      "4500", "5000"]
    out = tmp_path / "s.dxf"
    convert(pdf, str(out), Options())
    dim = _dims(ezdxf.readfile(str(out)))["4000"]
    assert dim.override().get("dimblk") == "NONE"
    # the squares are drawn inside the dimension, not left loose
    block = dim.get_geometry_block()
    assert len([e for e in block if e.dxftype() in ("HATCH", "SOLID")]) >= 2


def test_x_between_two_open_arrows(pdf_factory):
    """A chain with open arrows: at the shared station the two arrows
    form an X. Both dimensions use it."""
    def draw(p):
        y, xs = 100, (50, 200, 330)
        for x in xs:
            _line(p, (x, y + 20), (x, y - 2 * MM))
        _line(p, (xs[0], y), (xs[-1], y))
        _arrow(p, (xs[0], y), (-1, 0), kind="open")
        _arrow(p, (xs[-1], y), (1, 0), kind="open")
        h = 2.5 * MM
        k = h * math.tan(math.radians(15))
        _line(p, (xs[1] - h, y - k), (xs[1] + h, y + k))     # the X
        _line(p, (xs[1] - h, y + k), (xs[1] + h, y - k))
        for xa, xb, v in ((50, 200, "5000"), (200, 330, "4500")):
            _text(p, ((xa + xb) / 2 - 9, y - 1.5), v)
    ann = _analyse(pdf_factory(draw))
    assert sorted(d.text for d in ann.dimensions) == ["4500", "5000"]


# ---------------------------------------------------------------------------
# Values split in several texts
# ---------------------------------------------------------------------------
def _bare_dim(p, xa, xb, y):
    for x in (xa, xb):
        _line(p, (x, y + 20), (x, y - 2 * MM))
    _line(p, (xa, y), (xb, y))
    _arrow(p, (xa, y), (-1, 0))
    _arrow(p, (xb, y), (1, 0))


def test_metres_with_raised_centimetres(pdf_factory, tmp_path):
    def draw(p):
        _scale_pair(p)
        xa, xb, y = 60, 60 + 3500 * K, 200
        _bare_dim(p, xa, xb, y)
        _text(p, ((xa + xb) / 2 - 5, y - 1.5), "3,", 9)
        _text(p, ((xa + xb) / 2 + 2.5, y - 5.0), "50", 6)
    pdf = pdf_factory(draw, width=700)
    ann = _analyse(pdf)
    split = [d for d in ann.dimensions if d.mtext]
    assert len(split) == 1 and split[0].mtext == "3\\S50^ ;"
    assert not ann.dim_raw_texts
    out = tmp_path / "m.dxf"
    convert(pdf, str(out), Options())
    texts = sorted(d.dxf.text for d in
                   ezdxf.readfile(str(out)).modelspace().query("DIMENSION"))
    assert "3\\S50^ ;" in texts


def test_value_with_stacked_tolerance(pdf_factory):
    def draw(p):
        xa, xb, y = 100, 300, 150
        _bare_dim(p, xa, xb, y)
        _text(p, (190, y - 1.5), "25", 9)
        _text(p, (200.5, y - 5.5), "+0.1", 5.5)
        _text(p, (200.5, y - 0.5), "-0.2", 5.5)
    ann = _analyse(pdf_factory(draw))
    assert [d.mtext for d in ann.dimensions] == ["25\\S+0.1^ -0.2;"]


def test_value_in_two_texts(pdf_factory):
    def draw(p):
        _bare_dim(p, 100, 300, 100)
        _text(p, (186, 98.5), "3")
        _text(p, (193, 98.5), "500")
    ann = _analyse(pdf_factory(draw))
    assert [d.text.replace(" ", "") for d in ann.dimensions] == ["3500"]


# ---------------------------------------------------------------------------
# Sizes judged locally; SHX values; dimensions that cannot be rebuilt
# ---------------------------------------------------------------------------
def test_large_detail_next_to_small_dimensions(pdf_factory):
    def draw(p):
        for i in range(5):
            x = 40 + i * 60
            _hdim(p, x, x + 60, 60, "1700", size=7, arrow=2.0 * MM)
        _hdim(p, 100, 400, 330, "8500", size=18, arrow=5.0 * MM)
        _hdim(p, 400, 700, 330, "8500", size=18, arrow=5.0 * MM)
    ann = _analyse(pdf_factory(draw, width=800, height=500))
    assert sorted(d.text for d in ann.dimensions) == ["1700"] * 5 + \
        ["8500"] * 2


def _shx_value(page, x, y, content):
    """An AutoCAD SHX value: letters as strokes + AutoCAD's hidden
    comment holding the real string."""
    for k in range(len(content)):
        x0 = x + 6 * k
        stroke(page, [("line", (x0, y), (x0, y - 7)),
                      ("line", (x0, y - 7), (x0 + 4, y - 7))], width=0.25)
    annot = page.add_rect_annot(pymupdf.Rect(x - 2, y - 9,
                                             x + 6 * len(content), y + 2))
    annot.set_info(title=SHX_TITLE, content=content)
    annot.set_flags(pymupdf.PDF_ANNOT_IS_READ_ONLY)
    annot.update()
    doc = page.parent
    for key in ("AP", "C", "BS"):
        doc.xref_set_key(annot.xref, key, "null")
    doc.xref_set_key(annot.xref, "Border", "[0 0 0]")


def test_shx_value_becomes_the_dimension_text(pdf_factory, tmp_path):
    def draw(p):
        _bare_dim(p, 100, 300, 100)
        _shx_value(p, 188, 98.5, "5000")
    pdf = pdf_factory(draw)
    out = tmp_path / "x.dxf"
    assert convert(pdf, str(out), Options()).success
    doc = ezdxf.readfile(str(out))
    assert list(_dims(doc)) == ["5000"]
    assert not [e for e in doc.modelspace().query("TEXT MTEXT")
                if e.dxf.layer == LAYER_SHX_TEXT]


def test_dimension_that_cannot_be_rebuilt_is_grouped(pdf_factory, tmp_path):
    """One arrow only: no DIMENSION, but its value, line and arrow move
    as one (a GROUP on layer DIM_RAW)."""
    def draw(p):
        xa, xb, y = 100, 300, 150
        for x in (xa, xb):
            _line(p, (x, y + 20), (x, y - 2 * MM))
        _line(p, (xa, y), (xb, y))
        _arrow(p, (xb, y), (1, 0))
        _text(p, (190, y - 1.5), "5000")
    pdf = pdf_factory(draw)
    ann = _analyse(pdf)
    assert not ann.dimensions and len(ann.groups) == 1
    assert [t.text for t in ann.groups[0].texts] == ["5000"]
    out = tmp_path / "g.dxf"
    rep = convert(pdf, str(out), Options())
    doc = ezdxf.readfile(str(out))
    groups = [g for _, g in doc.groups]
    assert len(groups) == 1
    members = list(groups[0])
    assert {e.dxf.layer for e in members} == {LAYER_DIM_RAW}
    assert {"TEXT", "LINE", "HATCH"} <= {e.dxftype() for e in members}
    assert rep.stats.dim_groups == 1
    assert any("DIM_RAW" in n and "grouped" in n for n in rep.page_notes)
