"""Step 4 — dimensions (arrows and ticks) and leaders."""

import math

import ezdxf
import pytest

from conftest import arc, arrow, stroke
from convertcad.core import Options, convert
from convertcad.core.annotations import (ANGLE_RE, DIAMETER_RE, DIM_TEXT_RE,
                                         RADIUS_RE, angle_value,
                                         length_values, reconstruct)
from convertcad.core.compat import pymupdf
from convertcad.core.extractor import extract_page
from convertcad.core.geometry import rebuild


def _analyse(path, **kw):
    pd = extract_page(pymupdf.open(path), 0)
    rp = rebuild(pd)
    return rp, reconstruct(rp, **kw)


def test_dimension_text_regex():
    for ok in ("3500", "3 500", "3.50", "12,5", "R25", "Ø60", "45°",
               "1200 mm", "24000"):
        assert DIM_TEXT_RE.match(ok), ok
    for bad in ("+3.50", "C25/30", "Voile", "2026-10-24", "1/100"):
        assert not DIM_TEXT_RE.match(bad), bad


def _chain(page, xs, y, text_size=8):
    for x in xs:
        stroke(page, [("line", (x, y + 20), (x, y - 5))], width=0.25)
    for xa, xb in zip(xs, xs[1:]):
        stroke(page, [("line", (xa, y), (xb, y))], width=0.25)
        arrow(page, (xa, y), (-1, 0))
        arrow(page, (xb, y), (1, 0))
        page.insert_text(((xa + xb) / 2 - 9, y - 3), str(int(xb - xa) * 10),
                         fontsize=text_size)


def test_arrow_dimension_chain(pdf_factory):
    xs = [50, 150, 300, 420]
    _, ann = _analyse(pdf_factory(lambda p: _chain(p, xs, 100)))
    assert len(ann.dimensions) == 3
    assert sorted(d.text for d in ann.dimensions) == ["1000", "1200", "1500"]
    for d in ann.dimensions:          # each spans exactly one interval
        assert abs(abs(d.tip2[0] - d.tip1[0]) - int(d.text) / 10) < 0.5
    assert not ann.dim_raw_texts


def test_tick_dimension_chain_vertical(pdf_factory):
    ys = [60, 200, 340]

    def draw(page):
        x = 300
        stroke(page, [("line", (x, ys[0] - 6), (x, ys[-1] + 6))], width=0.25)
        for y in ys:
            stroke(page, [("line", (x - 30, y), (x + 5, y))], width=0.25)
            stroke(page, [("line", (x - 3.5, y + 3.5), (x + 3.5, y - 3.5))],
                   width=0.5)
        for ya, yb in zip(ys, ys[1:]):
            page.insert_text((x - 3, (ya + yb) / 2 + 9), "5000", fontsize=8,
                             rotate=90)
    _, ann = _analyse(pdf_factory(draw, width=400, height=420))
    assert len(ann.dimensions) == 2
    assert all(d.kind == "tick" and d.text == "5000" for d in ann.dimensions)


def test_ticks_can_be_disabled(pdf_factory):
    ys = [60, 200]

    def draw(page):
        stroke(page, [("line", (300, 54), (300, 206))], width=0.25)
        for y in ys:
            stroke(page, [("line", (296.5, y + 3.5), (303.5, y - 3.5))],
                   width=0.5)
        page.insert_text((297, 140), "5000", fontsize=8, rotate=90)
    _, ann = _analyse(pdf_factory(draw, width=400, height=300),
                      enable_ticks=False)
    assert not ann.dimensions and len(ann.dim_raw_texts) == 1


def test_leader_with_text_on_the_left(pdf_factory):
    def draw(page):
        tip, mid, land = (300, 200), (260, 150), (225, 150)
        stroke(page, [("poly", [tip, mid, land])], width=0.25)
        arrow(page, tip, (tip[0] - mid[0], tip[1] - mid[1]))
        page.insert_text((176, 153), "Cuve D=3.00", fontsize=8)  # ends 4pt before
    _, ann = _analyse(pdf_factory(draw))
    assert len(ann.leaders) == 1 and ann.leaders[0].text.text == "Cuve D=3.00"


def test_grid_bubble_numbers_are_not_dim_raw(pdf_factory):
    def draw(page):
        stroke(page, [("circle", (100, 100), 10)], width=0.35)
        page.insert_text((96.5, 103.5), "2", fontsize=10)
        page.insert_text((200, 200), "3.50", fontsize=8)
    _, ann = _analyse(pdf_factory(draw))
    assert [t.text for t in ann.dim_raw_texts] == ["3.50"]


def test_sample_plan_annotations(sample_plan):
    pd = extract_page(pymupdf.open(sample_plan), 0)
    rp = rebuild(pd)
    ann = reconstruct(rp)
    texts = sorted(d.text for d in ann.dimensions)
    assert texts == ["24000", "5000", "5000", "5000", "6000", "6000",
                     "6000", "6000"]
    assert len(ann.leaders) == 2
    assert [t.text for t in ann.dim_raw_texts] == ["3.50"]


# ---------------------------------------------------------------------------
# Radius, diameter, angle and arc length dimensions
# ---------------------------------------------------------------------------
PT_MM = 25.4 / 72.0            # one PDF point in mm (sheet at 1:1, in mm)


def _on(c, r, a):
    """Point at page angle a (degrees, y down) on the circle (c, r)."""
    return (c[0] + r * math.cos(math.radians(a)),
            c[1] + r * math.sin(math.radians(a)))


def _along(a, sense):
    """Unit vector along a circle at angle a, towards increasing (+1) or
    decreasing (-1) angles."""
    t = math.radians(a)
    return (-math.sin(t) * sense, math.cos(t) * sense)


def _curved_dims(page, angle_text="40°", arc_text="18.47"):
    # radius, value inside on the line from the centre
    stroke(page, [("circle", (150, 150), 40)])
    stroke(page, [("line", (150, 150), (190, 150))], width=0.25)
    arrow(page, (190, 150), (1, 0))
    page.insert_text((158, 147), "R40", fontsize=8)
    # diameter, value at the centre, two arrows
    stroke(page, [("circle", (350, 150), 30)])
    stroke(page, [("line", (320, 150), (380, 150))], width=0.25)
    arrow(page, (320, 150), (-1, 0))
    arrow(page, (380, 150), (1, 0))
    page.insert_text((340, 147), "Ø60", fontsize=8)
    # radius, value outside after a horizontal landing
    c = (150, 300)
    stroke(page, [("circle", c, 25)])
    tip, out = _on(c, 25, -45), _on(c, 45, -45)
    stroke(page, [("poly", [tip, out, (out[0] + 15, out[1])])], width=0.25)
    arrow(page, tip, (-math.cos(math.radians(-45)),
                      -math.sin(math.radians(-45))))
    page.insert_text((out[0] + 2, out[1] - 2), "R25", fontsize=8)
    # angle between two lines (page angles -40..0)
    v = (450, 330)
    stroke(page, [("line", v, _on(v, 90, 0)), ("line", v, _on(v, 90, -40))])
    arc(page, v, 60, -40, 0)
    arrow(page, _on(v, 60, -40), _along(-40, -1), length=5, half=1.0)
    arrow(page, _on(v, 60, 0), _along(0, 1), length=5, half=1.0)
    t = _on(v, 64, -20)
    page.insert_text((t[0] + 1, t[1]), angle_text, fontsize=8)
    # arc length of the arc r=50 (page angles -120..-60): 52.36 pt, i.e.
    # 18.47 mm at 1:1; dimension arc at r=62, extension lines
    c = (450, 200)
    arc(page, c, 50, -120, -60, width=0.5)
    for a in (-120, -60):
        stroke(page, [("line", _on(c, 52, a), _on(c, 65, a))], width=0.25)
    arc(page, c, 62, -120, -60)
    arrow(page, _on(c, 62, -120), _along(-120, -1), length=5, half=1.0)
    arrow(page, _on(c, 62, -60), _along(-60, 1), length=5, half=1.0)
    t = _on(c, 66, -90)
    if arc_text.isascii():
        page.insert_text((t[0] - 10, t[1]), arc_text, fontsize=8)
    else:                         # "⌒" is not in Helvetica: built-in CJK font
        tw = pymupdf.TextWriter(page.rect)
        tw.append((t[0] - 10, t[1]), arc_text, font=pymupdf.Font("cjk"),
                  fontsize=8)
        tw.write_text(page)


def test_curved_dimension_text_regexes():
    for ok in ("R25", "R 12.5", "2xR5"):
        assert RADIUS_RE.match(ok), ok
    for ok in ("Ø60", "ø 8", "⌀12", "∅12", "4xØ12", "%%c60"):
        assert DIAMETER_RE.match(ok), ok
    for bad in ("R+1", "RDC", "Ø", "PLAN"):
        assert not RADIUS_RE.match(bad) and not DIAMETER_RE.match(bad), bad
    assert ANGLE_RE.match("45°") and ANGLE_RE.match("30°15'")
    assert angle_value("22,5°") == 22.5 and angle_value("30°15'") == 30.25
    assert angle_value("45") is None
    assert length_values("3 500") == [3500.0]
    assert length_values("1,250") == [1.25, 1250.0]
    assert DIM_TEXT_RE.match("⌒785") and DIM_TEXT_RE.match("∅60")


def test_radius_and_diameter_dimensions(pdf_factory):
    rp, ann = _analyse(pdf_factory(_curved_dims, width=600, height=420),
                       units_per_pt=PT_MM)
    got = sorted((d.kind, d.text) for d in ann.radial)
    assert got == [("diameter", "Ø60"), ("radius", "R25"), ("radius", "R40")]
    by_text = {d.text: d for d in ann.radial}
    assert abs(by_text["R40"].radius - 40) < 0.5
    assert by_text["R40"].tip == pytest.approx((190, 150), abs=0.5)
    assert by_text["R25"].kink is not None            # landing kept
    assert not ann.leaders and not ann.dimensions
    # the lines of the dimensions are used; the circles stay
    left = [p for p in rp.polylines if not p.consumed]
    assert len(left) == 3          # the angle legs (one polyline) + the arc
    #                                length extension lines
    assert len(rp.circles) == 3 and not any(c.consumed for c in rp.circles)


def test_angle_and_arc_length_dimensions(pdf_factory):
    rp, ann = _analyse(pdf_factory(_curved_dims, width=600, height=420),
                       units_per_pt=PT_MM)
    kinds = {d.kind: d for d in ann.angular}
    assert set(kinds) == {"angle", "arc"}
    ang = kinds["angle"]
    assert ang.text == "40°" and abs(ang.sweep - 40) < 0.5
    assert abs(ang.start_angle - 320) < 0.5 and abs(ang.radius - 60) < 0.5
    ln = kinds["arc"]
    assert ln.text == "18.47" and abs(ln.arc_radius - 50) < 0.5
    assert abs(ln.sweep - 60) < 0.5
    # the dimension arcs are used, the measured arc stays
    assert [round(a.radius) for a in rp.arcs if not a.consumed] == [50]
    assert not ann.dim_raw_texts


def test_curved_dimensions_must_agree_with_the_drawing(pdf_factory):
    # a wrong angle, and an arc length checked without a scale: nothing is
    # invented, the values stay for review on DIM_RAW
    _, ann = _analyse(pdf_factory(lambda p: _curved_dims(p, angle_text="35°"),
                                  width=600, height=420))
    assert not ann.angular
    assert sorted(t.text for t in ann.dim_raw_texts) == ["18.47", "35°"]
    # with the arc length sign, no scale is needed
    _, ann = _analyse(pdf_factory(lambda p: _curved_dims(
        p, arc_text="\u231218.47"), width=600, height=420))
    assert sorted(d.kind for d in ann.angular) == ["angle", "arc"]


@pytest.mark.parametrize("version,fmt", [("R2018", "dxf"), ("R12", "dxf"),
                                         ("R2000", "dwg")])
def test_curved_dimensions_written(pdf_factory, tmp_path, version, fmt):
    from convertcad.core import dwg
    if fmt == "dwg" and not dwg.find_tools().dxf2dwg:
        pytest.skip("LibreDWG not available")
    pdf = pdf_factory(_curved_dims, width=600, height=420)
    out = tmp_path / f"curved.{fmt}"
    opt = Options(scale_denominator=1, units="mm", dxf_version=version,
                  output_format=fmt, auto_scale=False, write_log=False,
                  block_detection=False)
    rep = convert(pdf, str(out), opt)
    assert rep.success and rep.stats.dimensions == 5, rep.warnings
    if fmt == "dwg":
        return                      # complete: dxf_to_dwg reads it back
    doc = ezdxf.readfile(str(out))
    dims = {}
    for e in doc.modelspace().query("DIMENSION"):
        dims.setdefault(e.dimtype, []).append(e)
    radii = sorted(round(e.get_measurement(), 1) for e in dims[4])
    assert radii == [round(25 * PT_MM, 1), round(40 * PT_MM, 1)]
    assert round(dims[3][0].get_measurement(), 1) == round(60 * PT_MM, 1)
    assert abs(dims[5][0].get_measurement() - 40.0) < 0.5
    arc_dims = doc.modelspace().query("ARC_DIMENSION")
    # ARC_DIMENSION from AutoCAD 2007; before, its drawing on layer DIM
    assert len(arc_dims) == (1 if version == "R2018" else 0)
