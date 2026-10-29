"""
Exploded linetypes and hatch patterns (core/patterns.py): what CAD plotters
cut into pieces is rebuilt — and only when it is regular.
"""

import math

import ezdxf
from conftest import stroke

from convertcad.core.compat import pymupdf
from convertcad.core.extractor import RawSegment, Style
from convertcad.core.patterns import (add_mask_holes, detect_hatch_patterns,
                                      merge_dashed_lines, parse_dash_pattern)
from convertcad.core.pipeline import Options, convert

BLACK = Style(color=(0, 0, 0), width=0.0)


def _dashes(y, x0, x1, on, off, style=BLACK):
    """A horizontal dashed line drawn as separate pieces (like AutoCAD)."""
    segs, x = [], x0
    while x + on <= x1:
        segs.append(RawSegment((x, y), (x + on, y), style))
        x += on + off
    return segs


def test_simple_dashes_become_one_dashed_line():
    segs = _dashes(100, 0, 200, 6.0, 3.0)
    out, made, used = merge_dashed_lines(segs)
    assert made == 1 and used == len(segs) and len(out) == 1
    line = out[0]
    assert line.style.linetype == "DASHED"
    assert parse_dash_pattern(line.style.dash_pattern) == (6.0, -3.0)
    assert math.isclose(line.p1[0], 0.0) and line.p2[0] > 190


def test_center_line_pattern_is_measured():
    segs, x = [], 0.0
    while x < 300:                                 # long, gap, short, gap
        segs.append(RawSegment((x, 50), (x + 12, 50), BLACK))
        segs.append(RawSegment((x + 14, 50), (x + 16, 50), BLACK))
        x += 18
    out, made, _ = merge_dashed_lines(segs)
    assert made == 1 and out[0].style.linetype == "CENTER"
    assert parse_dash_pattern(out[0].style.dash_pattern) == \
        (12.0, -2.0, 2.0, -2.0)


def test_dotted_line_from_dots_only():
    dots = [RawSegment((10 + 4 * k, 20), (10 + 4 * k, 20), BLACK)
            for k in range(20)]
    out, made, used = merge_dashed_lines(dots)
    assert made == 1 and used == 20
    assert out[0].style.linetype == "DOT"


def test_irregular_collinear_segments_are_left_alone():
    # three walls with door openings of different widths: NOT a linetype
    segs = [RawSegment((0, 0), (30, 0), BLACK),
            RawSegment((38, 0), (90, 0), BLACK),
            RawSegment((112, 0), (130, 0), BLACK)]
    out, made, _ = merge_dashed_lines(segs)
    assert made == 0 and len(out) == 3


def _hatch_lines(angle_deg, spacing, box, style=BLACK):
    """Parallel lines clipped to a rectangle (like a plotted hatch)."""
    from convertcad.core.clip import clip_segment
    a = math.radians(angle_deg)
    u = (math.cos(a), math.sin(a))
    n = (-u[1], u[0])
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    big = 2 * max(box[2] - box[0], box[3] - box[1])
    segs = []
    k = -int(big / spacing)
    while k <= int(big / spacing):
        c = (cx + n[0] * k * spacing, cy + n[1] * k * spacing)
        p = (c[0] - u[0] * big, c[1] - u[1] * big)
        q = (c[0] + u[0] * big, c[1] + u[1] * big)
        cut = clip_segment(p, q, box)
        if cut:
            segs.append(RawSegment(cut[0], cut[1], style))
        k += 1
    return segs


def test_diagonal_hatch_becomes_one_pattern():
    segs = _hatch_lines(45, 6.0, (100, 100, 300, 220))
    res = detect_hatch_patterns(segs)
    assert len(res.hatches) == 1 and not res.segments
    h = res.hatches[0]
    assert math.isclose(h.spacing, 6.0, rel_tol=0.02)
    assert round(h.angle) in (45, 135)
    assert h.line_count == len(segs)


def test_few_horizontal_rows_stay_lines():
    # 8 stair treads: regular, but axis-aligned and too few for a hatch
    segs = [RawSegment((0, 10 + 5 * k), (40, 10 + 5 * k), BLACK)
            for k in range(8)]
    res = detect_hatch_patterns(segs)
    assert not res.hatches and len(res.segments) == 8


def test_grid_rows_in_both_directions_make_a_grating():
    box = (0, 0, 40, 40)
    segs = _hatch_lines(0, 5.0, box) + _hatch_lines(90, 5.0, box)
    res = detect_hatch_patterns(segs)
    assert len(res.hatches) == 2


def test_white_mask_cuts_a_hole_in_the_hatch():
    segs = _hatch_lines(45, 6.0, (100, 100, 300, 220))
    h = detect_hatch_patterns(segs).hatches[0]
    mask = [(150, 140), (250, 140), (250, 180), (150, 180)]
    outside = [(10, 10), (20, 10), (20, 20), (10, 20)]
    assert add_mask_holes([h], [mask, outside]) == 1
    assert mask in h.holes


def test_pipeline_writes_pattern_hatch_and_linetype(pdf_factory, tmp_path):
    def draw(page):
        for s in _hatch_lines(45, 6.0, (60, 60, 260, 200)):
            stroke(page, [("line", s.p1, s.p2)], width=0.2)
        stroke(page, [("rect", 60, 60, 260, 200)], width=0.8)
        for s in _dashes(300, 40, 520, 8.0, 3.0):
            stroke(page, [("line", s.p1, s.p2)], width=0.3)
    pdf = pdf_factory(draw, width=600, height=400)
    out = tmp_path / "p.dxf"
    rep = convert(pdf, str(out), Options(scale_denominator=100))
    assert rep.success
    assert rep.stats.pattern_hatches == 1 and rep.stats.dashed_lines == 1
    doc = ezdxf.readfile(str(out))
    hatches = [h for h in doc.modelspace().query("HATCH")
               if h.dxf.solid_fill == 0]
    assert len(hatches) == 1 and hatches[0].dxf.pattern_name == "_USER"
    # pattern spacing in drawing units: 6 pt at 1:100 = 211.7 mm
    assert math.isclose(hatches[0].dxf.pattern_scale,
                        6 * 25.4 / 72 * 100, rel_tol=0.03)
    dashed = [e for e in doc.modelspace().query("LINE")
              if e.dxf.linetype.startswith("CC_DASHED")]
    assert len(dashed) == 1
    lt = doc.linetypes.get(dashed[0].dxf.linetype)
    assert lt is not None
    # the measured pattern reproduces 8 pt dash / 3 pt gap at the drawing
    # linetype scale
    pattern = lt.pattern_tags.tags
    lengths = [t.value for t in pattern if t.code == 49]
    ltscale = doc.header["$LTSCALE"]
    assert math.isclose(lengths[0] * ltscale, 8 * 25.4 / 72 * 100,
                        rel_tol=0.01)


def test_options_can_switch_rebuilding_off(pdf_factory, tmp_path):
    def draw(page):
        for s in _dashes(100, 40, 400, 6.0, 3.0):
            stroke(page, [("line", s.p1, s.p2)], width=0.3)
    pdf = pdf_factory(draw)
    rep = convert(pdf, str(tmp_path / "x.dxf"),
                  Options(merge_dashes=False, hatch_patterns=False))
    assert rep.success and rep.stats.dashed_lines == 0
    assert rep.stats.lines > 30


def test_pymupdf_present():
    assert pymupdf.Matrix(1, 1).a == 1
