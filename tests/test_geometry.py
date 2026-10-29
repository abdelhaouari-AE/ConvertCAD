"""Step 2 — geometry rebuild: arcs, circles, splines, polylines."""

import math

from convertcad.core.extractor import PageData, RawBezier, RawSegment, Style
from convertcad.core.geometry import (EArc, bezier_to_arc, chain_beziers,
                                      chain_segments, dedupe_segments,
                                      merge_arcs, rebuild)

S = Style()
K = 0.5522847498


def quarter(c, r, q):
    """Bezier of the q-th quarter of a circle (y-down page coords)."""
    cx, cy = c
    pts = [(cx + r, cy), (cx, cy + r), (cx - r, cy), (cx, cy - r), (cx + r, cy)]
    a, b = pts[q], pts[q + 1]
    ta = (a[0] - cx, a[1] - cy)
    tb = (b[0] - cx, b[1] - cy)
    c1 = (a[0] - ta[1] * K, a[1] + ta[0] * K)
    c2 = (b[0] + tb[1] * K, b[1] - tb[0] * K)
    return RawBezier(a, c1, c2, b, S)


def test_bezier_to_arc_exact():
    arc = bezier_to_arc(quarter((100, 100), 50, 0))
    assert arc is not None
    assert math.dist(arc.center, (100, 100)) < 0.05
    assert abs(arc.radius - 50) < 0.05
    assert abs(arc.sweep - 90) < 0.5


def test_non_circular_curve_stays_spline():
    b = RawBezier((0, 0), (30, 80), (60, -80), (90, 0), S)
    assert bezier_to_arc(b) is None


def test_four_quarters_make_a_circle():
    arcs = [bezier_to_arc(quarter((10, 10), 5, q)) for q in range(4)]
    rest, circles = merge_arcs(arcs)
    assert len(circles) == 1 and not rest
    assert abs(circles[0].radius - 5) < 0.05


def test_contiguous_arcs_merge_into_one_arc():
    arcs = [bezier_to_arc(quarter((0, 0), 20, q)) for q in range(2)]
    rest, circles = merge_arcs(arcs)
    assert not circles and len(rest) == 1
    assert abs(rest[0].sweep - 180) < 1.0


def test_duplicate_arcs_do_not_fake_a_circle():
    """Two copies of the same 180 deg arc must NOT become a circle."""
    a = EArc((0, 0), 10, 0, 180, S)
    b = EArc((0, 0), 10, 0, 180, S)
    rest, circles = merge_arcs([a, b])
    assert not circles and len(rest) == 1


def test_bezier_chain_becomes_one_spline():
    b1 = RawBezier((0, 0), (10, 30), (20, -30), (30, 0), S)
    b2 = RawBezier((30, 0), (40, 30), (50, -30), (60, 0), S)
    b3 = RawBezier((90, 0), (80, 20), (70, -20), (60, 0), S)   # reversed
    splines = chain_beziers([b2, b1, b3])
    assert len(splines) == 1
    sp = splines[0]
    assert len(sp.control_points) == 10 and sp.segment_count == 3
    ends = {sp.control_points[0], sp.control_points[-1]}
    assert ends == {(0, 0), (90, 0)}


def test_segments_chain_and_collinear_merge():
    segs = [RawSegment((0, 0), (10, 0), S), RawSegment((10, 0), (20, 0), S),
            RawSegment((20, 0), (20, 10), S)]
    pls = chain_segments(segs)
    assert len(pls) == 1
    assert pls[0].points in ([(0, 0), (20, 0), (20, 10)],
                             [(20, 10), (20, 0), (0, 0)])


def test_closed_rectangle():
    pts = [(0, 0), (10, 0), (10, 5), (0, 5)]
    segs = [RawSegment(pts[i], pts[(i + 1) % 4], S) for i in range(4)]
    pls = chain_segments(segs)
    assert len(pls) == 1 and pls[0].closed and len(pls[0].points) == 4


def test_collinear_wraparound_at_180_degrees():
    """Lines heading in -x direction (angle +/-180) must still merge."""
    segs = [RawSegment((10, 0.0), (5, 1e-9), S),
            RawSegment((5, 1e-9), (0, -1e-9), S)]
    pls = chain_segments(segs)
    assert len(pls) == 1 and len(pls[0].points) == 2


def test_dedupe_removes_double_strokes():
    segs = [RawSegment((0, 0), (10, 0), S), RawSegment((10, 0), (0, 0), S),
            RawSegment((0, 0), (0, 0), S)]
    out, removed = dedupe_segments(segs)
    assert len(out) == 1 and removed == 2


def test_rebuild_precision_option():
    # a slightly irregular quarter: accepted as ARC with loose precision
    b = quarter((0, 0), 100, 0)
    wobbly = RawBezier(b.p0, (b.p1[0] + 3.0, b.p1[1]), b.p2, b.p3, S)
    page = PageData(1, 500, 500, beziers=[wobbly])      # deviation ~0.45 pt
    assert rebuild(page, precision=0.5).splines        # fine: stays spline
    assert rebuild(page, precision=1.0).splines        # normal: stays spline
    assert rebuild(page, precision=2.0).arcs            # loose: becomes arc
