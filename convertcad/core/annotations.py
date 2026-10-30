"""
annotations.py — STEP 4: rebuild TRUE dimensions and leaders (heuristics).

In a PDF a dimension is only drawing primitives:
    2 terminators (filled arrows OR oblique ticks) + a dimension line
    + 2 extension lines + a measurement text.
This module recognises those patterns and rebuilds real DXF DIMENSION
entities (and LEADERs for "arrow + polyline + note" patterns).

SAFE-FALLBACK RULE (never invent, never corrupt):
  * A dimension is rebuilt ONLY when terminators, line and text all agree.
  * The value shown is ALWAYS the original PDF text (kept as text override).
  * Measurement-looking texts that matched nothing go to layer DIM_RAW
    (red) so the user can review them. Unmatched geometry stays untouched.

Performance: every neighbourhood question goes through spatial.GridIndex,
so pages with tens of thousands of lines are processed in seconds.
"""

import math
import re
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .extractor import PageData, Point, RawFill, RawText
from .geometry import EArc, EPolyline, RebuiltPage
from .spatial import (GridIndex, angle_deg, angle_diff_mod180,
                      point_line_distance, point_segment_distance,
                      segment_intersection)

# Text that *looks like* a measurement: "3500", "3 500", "3.50", "12,5",
# "R25", "Ø60", "45°", "1200 mm", "⌒785"...
DIAMETER_SIGNS = "Ø\u00f8\u2300\u2205\u03a6\u03c6"    # Ø ø ⌀ ∅ Φ φ
ARC_SIGN = "\u2312"                                     # ⌒ (arc length)
DIM_TEXT_RE = re.compile(
    r"^[~±≈R" + DIAMETER_SIGNS + ARC_SIGN + r"]?\s?"
    r"(?:\d{1,3}(?:[   ]\d{3})+|\d{1,7})"
    r"(?:[.,]\d{1,3})?\s*(?:mm|cm|m|°)?$")
# Radius "R25", "R 12.5"; diameter "Ø60", "2xØ12", "%%c60" (AutoCAD code)
RADIUS_RE = re.compile(r"^(?:\d{1,3}\s?[xX×]\s?)?R\s?\d")
DIAMETER_RE = re.compile(r"^(?:\d{1,3}\s?[xX×]\s?)?(?:[" + DIAMETER_SIGNS
                         + r"]|%%[cC])\s?\d")
# Angle "45°", "22.5°", "30°15'", "12°30'15\""
ANGLE_RE = re.compile(
    r"^(\d{1,3}(?:[.,]\d{1,4})?)\s*°"
    r"(?:\s*(\d{1,2}(?:[.,]\d+)?)\s*['′])?"
    r"(?:\s*(\d{1,2}(?:[.,]\d+)?)\s*[\"″])?$")


class ATol:
    """Annotation tolerances, in page points."""
    ARROW_MAX_AREA = 14.0      # filled triangle area above this -> not an arrow
    ARROW_MIN_AREA = 0.15
    OPPOSITE_DEG = 25.0        # paired arrows must point in opposite directions
    COLLINEAR_OFF = 1.5        # arrow tips must lie on a common line
    TEXT_NEAR = 6.0            # text-to-dimension-line distance (x text height)
    EXT_PERP_DEG = 20.0        # extension line perpendicularity tolerance
    EXT_THROUGH = 1.2          # extension line passes this close to the tip
    EXT_OVERSHOOT = 10.0       # max stub of an extension line past the tip
    MIN_SPAN = 2.0             # shortest dimension (points)
    LEADER_NEAR = 2.0          # leader polyline endpoint near the arrow tip
    LEADER_TEXT = 12.0         # note text near the leader tail
    LEADER_JOIN = 0.6          # next leader segment starts this close
    LEADER_HOPS = 3            # ...at most this many extra pieces
    LEADER_TITLE = 3.0         # text this many times taller than the
                               # page's usual text is a title, not a note
    LEADER_REACH = 1.5         # note within this many text heights of the
                               # leader tail
    # --- tick-mark (architectural oblique) terminators ---
    TICK_MAX_LEN = 14.0
    TICK_MIN_LEN = 1.5
    TICK_OBLIQUE_LO = 25.0     # tick angle relative to the dimension line
    TICK_OBLIQUE_HI = 75.0
    TICK_PAIR_MIN = 6.0        # two ticks must be at least this far apart
    TICK_ON_LINE = 1.5         # tick midpoint distance to the dimension line
    # --- radius / diameter / angle / arc length ---
    ON_CIRCLE = 1.2            # arrow tip this close to a circle (or 3 % of r)
    RADIAL_DEG = 15.0          # radius arrow: along the radius
    TANGENT_DEG = 20.0         # angle arrow: along the dimension arc
    RADIAL_TEXT = 1.5          # value within this many text heights of the
                               # dimension line
    CURVE_TEXT = 3.0           # angle value within this many text heights
                               # of the dimension arc
    ANGLE_AGREE = 2.0          # written vs drawn angle: 2 degrees or 4 %
    ARC_AGREE = 0.03           # written vs drawn arc length: 3 %
    TRACK_TOL = 0.8            # arcs of one dimension arc: same centre/radius


# Arrows labelled with these words show a direction (stairs, ramps, slopes),
# they are not leaders.
DIRECTION_WORDS = {"UP", "DN", "DOWN", "MONTEE", "MONTÉE", "DESCENTE",
                   "MONTE", "DESC", "HAUT", "BAS", "SLOPE", "PENTE"}


@dataclass
class Arrowhead:
    tip: Point
    direction: Tuple[float, float]   # unit vector, base -> tip
    fill: RawFill
    used: bool = False
    length: float = 0.0              # base -> tip


@dataclass
class DimensionEntity:
    """Everything dxf_writer needs to emit one LINEAR (rotated) dimension.

    The dimension line is fixed by the two terminator tips exactly as drawn
    in the PDF; the definition points (measured object points) may sit at
    any depth — CAD projects them onto the dimension-line direction."""
    def_point1: Point          # measured point 1 (extension line origin)
    def_point2: Point
    line_point: Point          # a point ON the dimension line
    text: str                  # original PDF text, kept as override -> exact
    height: float              # PDF font size
    text_center: Optional[Point] = None   # where the PDF shows the value
    kind: str = "arrow"        # "arrow" | "tick"
    tip1: Optional[Point] = None          # terminator positions on the line
    tip2: Optional[Point] = None


@dataclass
class RadialDimension:
    """A RADIUS or DIAMETER dimension (page coordinates)."""
    kind: str                  # "radius" | "diameter"
    center: Point
    radius: float
    tip: Point                 # where the arrow touches the circle
    text: str                  # original PDF text, kept as override
    height: float
    text_center: Optional[Point] = None
    text_rotation: float = 0.0 # degrees, PDF text direction
    kink: Optional[Point] = None   # end of the radial line, before a
                                   # horizontal landing (if any)


@dataclass
class AngularDimension:
    """An ANGLE or ARC LENGTH dimension (page coordinates).

    The dimension arc runs from start_angle to end_angle (degrees, page
    convention like EArc: y down, increasing angle from start to end)."""
    kind: str                  # "angle" | "arc"
    center: Point
    radius: float              # radius of the dimension arc
    start_angle: float
    end_angle: float
    text: str
    height: float
    text_center: Optional[Point] = None
    text_rotation: float = 0.0
    arc_radius: float = 0.0    # arc length: radius of the measured arc

    @property
    def sweep(self) -> float:
        return (self.end_angle - self.start_angle) % 360.0


@dataclass
class LeaderEntity:
    vertices: List[Point]      # from the arrow tip towards the text
    text: RawText              # the line closest to the landing
    lines: List[RawText] = field(default_factory=list)   # all lines, top
                                                         # to bottom


@dataclass
class AnnotationResult:
    dimensions: List[DimensionEntity] = field(default_factory=list)
    radial: List[RadialDimension] = field(default_factory=list)
    angular: List[AngularDimension] = field(default_factory=list)
    leaders: List[LeaderEntity] = field(default_factory=list)
    dim_raw_texts: List[RawText] = field(default_factory=list)
    consumed_fills: set = field(default_factory=set)     # id() of RawFill
    consumed_texts: set = field(default_factory=set)     # id() of RawText


# ---------------------------------------------------------------------------
# Arrowhead detection
# ---------------------------------------------------------------------------
def _polygon_area(pts: List[Point]) -> float:
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def _dedupe(pts: List[Point], tol: float = 0.05) -> List[Point]:
    out: List[Point] = []
    for p in pts:
        if all(math.dist(p, q) > tol for q in out):
            out.append(p)
    return out


def find_arrowheads(fills: List[RawFill]) -> List[Arrowhead]:
    """Small filled triangles are arrowheads; tip = the sharpest vertex."""
    arrows: List[Arrowhead] = []
    for f in fills:
        if len(f.points) > 12:
            continue
        pts = _dedupe(f.points)
        if not 3 <= len(pts) <= 4:
            continue
        area = _polygon_area(pts)
        if not ATol.ARROW_MIN_AREA <= area <= ATol.ARROW_MAX_AREA:
            continue
        best_tip, best_d, best_base = None, -1.0, (0.0, 0.0)
        for i, p in enumerate(pts):
            others = [q for j, q in enumerate(pts) if j != i]
            bx = sum(q[0] for q in others) / len(others)
            by = sum(q[1] for q in others) / len(others)
            d = math.dist(p, (bx, by))
            if d > best_d:
                best_tip, best_d, best_base = p, d, (bx, by)
        if best_d < 1e-6:
            continue
        # A real arrowhead is clearly longer than wide.
        base_w = 2.0 * area / best_d
        if best_d < 1.2 * base_w:
            continue
        arrows.append(Arrowhead(
            tip=best_tip,
            direction=((best_tip[0] - best_base[0]) / best_d,
                       (best_tip[1] - best_base[1]) / best_d),
            fill=f, length=best_d))
    return arrows


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
class _Context:
    """Spatial indexes built once per page."""

    def __init__(self, rp: RebuiltPage):
        self.rp = rp
        self.lines = [pl for pl in rp.polylines
                      if pl.is_single_line and not pl.consumed]
        # ids of lines consumed as extension lines: still usable by the
        # NEXT dimension of a chain (one extension line bounds two dims)
        self.ext_ids: set = set()
        self.line_index: GridIndex[EPolyline] = GridIndex(12.0)
        for pl in self.lines:
            self.line_index.insert_segment(pl, pl.points[0], pl.points[1])
        texts = rp.page.texts
        self.dim_texts = [t for t in texts if DIM_TEXT_RE.match(t.text)]
        heights = [t.height for t in self.dim_texts] or [2.5]
        self.text_margin = ATol.TEXT_NEAR * max(statistics.median(heights),
                                                1.0) * 2
        self.dim_text_index: GridIndex[RawText] = GridIndex(24.0)
        for t in self.dim_texts:
            c = t.center()
            self.dim_text_index.insert(t, (c[0], c[1], c[0], c[1]))
        self.text_index: GridIndex[RawText] = GridIndex(24.0)
        for t in texts:
            self.text_index.insert(t, (t.origin[0], t.origin[1],
                                       t.origin[0], t.origin[1]))
        self.max_text_len = max(
            [t.width or 0.55 * t.height * len(t.text) for t in texts] or [0.0])
        self.circle_index: GridIndex = GridIndex(24.0)
        for c in rp.circles:
            self.circle_index.insert(c, (c.center[0] - c.radius,
                                         c.center[1] - c.radius,
                                         c.center[0] + c.radius,
                                         c.center[1] + c.radius))
        # circles AND arcs, indexed along their outline (radius / diameter /
        # angle dimensions look for the curve under an arrow tip) and by
        # their centre (concentric arcs)
        self.curve_index: GridIndex = GridIndex(24.0)
        self.arc_centers: GridIndex[EArc] = GridIndex(8.0)
        for c in list(rp.circles) + list(rp.arcs):
            if c.consumed or c.radius <= 0:
                continue
            self.curve_index.insert_path(c, _outline(c, 6.0))
            if isinstance(c, EArc):
                self.arc_centers.insert(c, (c.center[0], c.center[1],
                                            c.center[0], c.center[1]))
        self._open_ends: Optional[GridIndex] = None
        # values of radius / diameter dimensions, and of angle / arc length
        # dimensions (angles with minutes are not in dim_texts)
        self.radial_texts: GridIndex[RawText] = GridIndex(24.0)
        self.curve_texts: GridIndex[RawText] = GridIndex(24.0)
        for t in texts:
            s = t.text.strip()
            c = t.center()
            box = (c[0], c[1], c[0], c[1])
            if RADIUS_RE.match(s) or DIAMETER_RE.match(s):
                self.radial_texts.insert(t, box)
            elif ANGLE_RE.match(s) or DIM_TEXT_RE.match(s):
                self.curve_texts.insert(t, box)

    def open_ends(self) -> GridIndex:
        """Ends of the short open polylines (leader pieces), built once."""
        if self._open_ends is None:
            self._open_ends = _end_index(self.rp)
        return self._open_ends


def _end_index(rp: RebuiltPage) -> GridIndex:
    """Both ends of every short open polyline: where leaders are walked."""
    index: GridIndex[Tuple[EPolyline, int]] = GridIndex(8.0)
    for pl in rp.polylines:
        if pl.consumed or pl.closed or len(pl.points) > 6:
            continue
        for end in (0, -1):
            p = pl.points[end]
            index.insert((pl, end), (p[0], p[1], p[0], p[1]))
    return index


def _outline(c, step: float) -> List[Point]:
    """Points along a circle or an arc, about `step` apart."""
    a0, sweep = _span(c)
    n = max(4, int(math.radians(sweep) * c.radius / step) + 1)
    out = []
    for k in range(n + 1):
        a = math.radians(a0 + sweep * k / n)
        out.append((c.center[0] + c.radius * math.cos(a),
                    c.center[1] + c.radius * math.sin(a)))
    return out


def _span(c) -> Tuple[float, float]:
    """(start angle, sweep) of an arc; a circle is (0, 360)."""
    if isinstance(c, EArc):
        return c.start_angle % 360.0, (c.sweep or 360.0)
    return 0.0, 360.0


def _nearest_dim_text(ctx: _Context, res: AnnotationResult,
                      tip1: Point, tip2: Point) -> Optional[RawText]:
    """Measurement text sitting along the segment tip1-tip2."""
    m = ctx.text_margin
    x0, x1 = min(tip1[0], tip2[0]) - m, max(tip1[0], tip2[0]) + m
    y0, y1 = min(tip1[1], tip2[1]) - m, max(tip1[1], tip2[1]) + m
    mid = ((tip1[0] + tip2[0]) / 2, (tip1[1] + tip2[1]) / 2)
    span = math.dist(tip1, tip2)
    best, bd = None, 1e18
    for t in ctx.dim_text_index.query(x0, y0, x1, y1):
        if id(t) in res.consumed_texts:
            continue
        c = t.center()
        h = max(t.height, 1.0)
        d = point_line_distance(c, tip1, tip2)
        if d > ATol.TEXT_NEAR * h:
            continue
        if math.dist(c, mid) > span / 2 + 4 * h + ATol.TEXT_NEAR * h:
            continue
        # The value is written along the dimension line (aligned style) or
        # horizontally (unidirectional style); any other angle is a mismatch.
        line_ang = angle_deg((tip2[0] - tip1[0], -(tip2[1] - tip1[1])))
        if (angle_diff_mod180(line_ang, t.rotation) > 30.0
                and angle_diff_mod180(t.rotation, 0.0) > 5.0):
            continue
        if d < bd:
            best, bd = t, d
    return best


def _find_extension(ctx: _Context, tip: Point, axis: Tuple[float, float]
                    ) -> Optional[Tuple[Point, EPolyline]]:
    """Extension line crossing the dimension line at `tip`: a line roughly
    perpendicular to the axis that passes through (or ends at) the tip.

    The measured point is the far end on the OBJECT side. It is only trusted
    when unambiguous: the line must overshoot the dimension line by a short
    stub (<= EXT_OVERSHOOT) on one side and run clearly longer on the other.
    Extension lines shared by stacked dimensions (chain + overall) are
    ambiguous -> None, and the dimension keeps its tips as definition points
    (the measured distance is identical; the drawn line stays as geometry)."""
    axis_ang = angle_deg(axis)
    p2 = (tip[0] + axis[0], tip[1] + axis[1])
    for pl in ctx.line_index.near(tip[0], tip[1], ATol.EXT_THROUGH + 0.5):
        if pl.consumed and id(pl) not in ctx.ext_ids:
            continue
        a, b = pl.points
        seg_ang = angle_deg((b[0] - a[0], b[1] - a[1]))
        if abs(angle_diff_mod180(seg_ang, axis_ang) - 90.0) > ATol.EXT_PERP_DEG:
            continue
        if point_segment_distance(tip, a, b) > ATol.EXT_THROUGH:
            continue
        da = point_line_distance(a, tip, p2)
        db = point_line_distance(b, tip, p2)
        short, long_ = min(da, db), max(da, db)
        if short <= ATol.EXT_OVERSHOOT and long_ >= 2.0 * max(short, 1.0):
            return (a if da >= db else b), pl
        return None                                     # ambiguous: keep tip
    return None


def _consume_dim_line(ctx: _Context, tip1: Point, tip2: Point) -> None:
    """Mark the drawn line(s) lying along tip1-tip2 as consumed."""
    x0, x1 = min(tip1[0], tip2[0]) - 1, max(tip1[0], tip2[0]) + 1
    y0, y1 = min(tip1[1], tip2[1]) - 1, max(tip1[1], tip2[1]) + 1
    for pl in ctx.line_index.query(x0, y0, x1, y1):
        if pl.consumed:
            continue
        a, b = pl.points
        if (point_line_distance(a, tip1, tip2) < ATol.COLLINEAR_OFF
                and point_line_distance(b, tip1, tip2) < ATol.COLLINEAR_OFF
                and all(x0 <= p[0] <= x1 and y0 <= p[1] <= y1
                        for p in (a, b))):
            pl.consumed = True


def _make_dimension(ctx: _Context, res: AnnotationResult, t1: Point,
                    t2: Point, text: RawText, kind: str,
                    consume_ext: bool = True) -> DimensionEntity:
    span = math.dist(t1, t2)
    axis = ((t2[0] - t1[0]) / span, (t2[1] - t1[1]) / span)
    e1 = _find_extension(ctx, t1, axis)
    e2 = _find_extension(ctx, t2, axis)
    p1 = e1[0] if e1 else t1
    p2 = e2[0] if e2 else t2
    if consume_ext:
        for e in (e1, e2):
            if e:
                e[1].consumed = True
                ctx.ext_ids.add(id(e[1]))
    res.consumed_texts.add(id(text))
    _consume_dim_line(ctx, t1, t2)
    return DimensionEntity(def_point1=p1, def_point2=p2,
                           line_point=((t1[0] + t2[0]) / 2,
                                       (t1[1] + t2[1]) / 2),
                           text=text.text, height=text.height,
                           text_center=text.center(), kind=kind,
                           tip1=t1, tip2=t2)


# ---------------------------------------------------------------------------
# Arrow dimensions (pairs found along common axes -> handles chains)
# ---------------------------------------------------------------------------
def _axis_key(tip: Point, d: Tuple[float, float]) -> Tuple[int, int]:
    """Bucket key of the infinite line through `tip` along `d`.
    Sign-agnostic (abs offset, angle mod 180) so that two opposite arrows on
    the same line always land in the same or neighbouring buckets."""
    theta = math.degrees(math.atan2(d[1], d[0])) % 180.0
    tr = math.radians(theta)
    offset = abs(-math.sin(tr) * tip[0] + math.cos(tr) * tip[1])
    return (int(round(theta / 4.0)) % 45, int(round(offset / 3.0)))


def _arrow_dimensions(ctx: _Context, arrows: List[Arrowhead],
                      res: AnnotationResult) -> None:
    buckets: Dict[Tuple[int, int], List[int]] = {}
    for i, a in enumerate(arrows):
        buckets.setdefault(_axis_key(a.tip, a.direction), []).append(i)
    cos_opp = math.cos(math.radians(180.0 - ATol.OPPOSITE_DEG))
    for i, a1 in enumerate(arrows):
        if a1.used:
            continue
        kt, ko = _axis_key(a1.tip, a1.direction)
        cands = []
        for dt in (-1, 0, 1):
            for do in (-1, 0, 1):
                for j in buckets.get(((kt + dt) % 45, ko + do), ()):
                    if j == i or arrows[j].used:
                        continue
                    a2 = arrows[j]
                    dot = (a1.direction[0] * a2.direction[0]
                           + a1.direction[1] * a2.direction[1])
                    if dot > cos_opp:                 # not opposite enough
                        continue
                    span = math.dist(a1.tip, a2.tip)
                    if span < ATol.MIN_SPAN:
                        continue
                    far = (a1.tip[0] + a1.direction[0],
                           a1.tip[1] + a1.direction[1])
                    if point_line_distance(a2.tip, a1.tip, far) \
                            > ATol.COLLINEAR_OFF:
                        continue
                    v = (a2.tip[0] - a1.tip[0], a2.tip[1] - a1.tip[1])
                    s1 = a1.direction[0] * v[0] + a1.direction[1] * v[1]
                    s2 = a2.direction[0] * v[0] + a2.direction[1] * v[1]
                    outward = s1 < 0 < s2      # standard: arrows point outward
                    inward = s2 < 0 < s1       # small dims: arrows outside
                    if outward or inward:
                        cands.append((span, 0 if outward else 1, j))
        for _, _, j in sorted(cands):
            a2 = arrows[j]
            text = _nearest_dim_text(ctx, res, a1.tip, a2.tip)
            if text is None:
                continue
            a1.used = a2.used = True
            res.consumed_fills.update({id(a1.fill), id(a2.fill)})
            res.dimensions.append(
                _make_dimension(ctx, res, a1.tip, a2.tip, text, "arrow"))
            break


# ---------------------------------------------------------------------------
# Tick-mark dimensions (architectural style)
# ---------------------------------------------------------------------------
def _tick_dimensions(ctx: _Context, res: AnnotationResult) -> None:
    ticks = []
    tick_index: GridIndex[int] = GridIndex(12.0)
    for pl in ctx.lines:
        if pl.consumed:
            continue
        a, b = pl.points
        L = math.dist(a, b)
        if ATol.TICK_MIN_LEN <= L <= ATol.TICK_MAX_LEN:
            mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
            ang = angle_deg((b[0] - a[0], b[1] - a[1])) % 180.0
            k = len(ticks)
            ticks.append((mid, ang, pl))
            tick_index.insert(k, (mid[0], mid[1], mid[0], mid[1]))
    if len(ticks) < 2:
        return
    used = [False] * len(ticks)
    for line in sorted(ctx.lines, key=lambda p: -math.dist(*p.points)):
        if line.consumed:
            continue
        a, b = line.points
        L = math.dist(a, b)
        if L < ATol.TICK_PAIR_MIN:
            continue
        u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        line_ang = angle_deg(u)
        m = ATol.TICK_ON_LINE + ATol.TICK_MAX_LEN
        on_line = []
        for k in tick_index.query(min(a[0], b[0]) - m, min(a[1], b[1]) - m,
                                  max(a[0], b[0]) + m, max(a[1], b[1]) + m):
            mid, ang, tpl = ticks[k]
            if used[k] or tpl is line or tpl.consumed:
                continue
            if point_line_distance(mid, a, b) > ATol.TICK_ON_LINE:
                continue
            t = (mid[0] - a[0]) * u[0] + (mid[1] - a[1]) * u[1]
            if not -ATol.TICK_MAX_LEN <= t <= L + ATol.TICK_MAX_LEN:
                continue
            rel = angle_diff_mod180(ang, line_ang)
            if ATol.TICK_OBLIQUE_LO <= rel <= ATol.TICK_OBLIQUE_HI:
                on_line.append((t, k))
        if len(on_line) < 2:
            continue
        on_line.sort()
        made, intervals = 0, 0
        for (t_a, ka), (t_b, kb) in zip(on_line, on_line[1:]):
            if t_b - t_a < ATol.TICK_PAIR_MIN:
                continue
            intervals += 1
            p1, p2 = ticks[ka][0], ticks[kb][0]
            text = _nearest_dim_text(ctx, res, p1, p2)
            if text is None:
                continue
            for k in (ka, kb):            # consume ticks BEFORE looking for
                used[k] = True            # extension lines (a steep tick must
                ticks[k][2].consumed = True   # not pass for one)
            dim = _make_dimension(ctx, res, p1, p2, text, "tick")
            res.dimensions.append(dim)
            made += 1
        if made and made == intervals:
            line.consumed = True


# ---------------------------------------------------------------------------
# Shared helpers for curved dimensions (radius, diameter, angle, arc length)
# ---------------------------------------------------------------------------
def _angle_at(center: Point, p: Point) -> float:
    """Angle of p seen from `center`: degrees 0..360, page convention
    (y down), the same as EArc."""
    return math.degrees(math.atan2(p[1] - center[1],
                                   p[0] - center[0])) % 360.0


def _in_span(a: float, start: float, sweep: float,
             margin: float = 0.0) -> bool:
    """Is the angle `a` on the arc start..start+sweep (+/- margin)?"""
    if sweep + 2.0 * margin >= 360.0:
        return True
    return (a - start + margin) % 360.0 <= sweep + 2.0 * margin


def _on_curve_tol(r: float) -> float:
    """How far from a circle an arrow tip may be and still touch it."""
    return max(ATol.ON_CIRCLE, min(0.02 * r, 3.0))


def _text_box(t: RawText) -> List[Point]:
    """Corners of a text's footprint: baseline left, baseline right, top
    right, top left (page coordinates)."""
    d = t.direction()
    w = t.width or 0.55 * t.height * len(t.text)
    a = math.radians(t.rotation)
    up = (-math.sin(a) * 0.7 * t.height, -math.cos(a) * 0.7 * t.height)
    p0 = t.origin
    p1 = (p0[0] + d[0] * w, p0[1] + d[1] * w)
    return [p0, p1, (p1[0] + up[0], p1[1] + up[1]),
            (p0[0] + up[0], p0[1] + up[1])]


def _inside_polygon(p: Point, poly: List[Point]) -> bool:
    """Ray casting: is p inside the polygon?"""
    inside = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > p[1]) != (y2 > p[1]):
            x = x1 + (p[1] - y1) * (x2 - x1) / (y2 - y1)
            if x > p[0]:
                inside = not inside
    return inside


def _box_segment_distance(box: List[Point], a: Point, b: Point) -> float:
    """Shortest distance between a text footprint and the segment a-b."""
    edges = list(zip(box, box[1:] + box[:1]))
    if _inside_polygon(a, box) or any(
            segment_intersection(p, q, a, b, eps=0.0) is not None
            for p, q in edges):
        return 0.0
    d = min(point_segment_distance(p, a, b) for p in box)
    for p, q in edges:
        d = min(d, point_segment_distance(a, p, q),
                point_segment_distance(b, p, q))
    return d


def _path_distance(box: List[Point], pts: List[Point]) -> float:
    """Shortest distance between a text footprint and a polyline."""
    return min(_box_segment_distance(box, p, q) for p, q in zip(pts, pts[1:]))


# ---------------------------------------------------------------------------
# Radius and diameter dimensions
# ---------------------------------------------------------------------------
def _curve_under_tip(ctx: _Context, ar: Arrowhead):
    """The circle or arc an arrow points at ALONG ITS RADIUS (inwards or
    outwards): the tip lies on it. Returns (curve, unit vector centre ->
    tip) or None."""
    best, bd = None, 1e18
    cos_max = math.cos(math.radians(ATol.RADIAL_DEG))
    for c in ctx.curve_index.near(ar.tip[0], ar.tip[1], 3.5):
        if c.consumed:
            continue
        r = c.radius
        d = math.dist(ar.tip, c.center)
        off = abs(d - r)
        if r < 0.5 or d < 1e-9 or off > _on_curve_tol(r):
            continue
        u = ((ar.tip[0] - c.center[0]) / d, (ar.tip[1] - c.center[1]) / d)
        if abs(ar.direction[0] * u[0] + ar.direction[1] * u[1]) < cos_max:
            continue
        start, sweep = _span(c)
        margin = math.degrees((ar.length + 1.0) / r)
        if not _in_span(_angle_at(c.center, ar.tip), start, sweep, margin):
            continue
        if off < bd:
            best, bd = (c, u), off
    return best


def _radial_text(ctx: _Context, res: AnnotationResult, ar: Arrowhead,
                 curve, u: Tuple[float, float]):
    """The R / Ø value of a radius or diameter dimension whose arrow is
    `ar`: written along the radius (or diameter) line, or at the end of the
    line drawn from the arrow, possibly after a landing.
    Returns (text, drawn path or None, pieces of the path) or None."""
    center, r = curve.center, curve.radius
    path: Optional[List[Point]] = None
    pieces: List[EPolyline] = []
    start = _leader_start(ar, ctx.open_ends())
    if start is not None:
        pts, pieces = _walk_leader(ctx, start[0], start[1], ctx.open_ends())
        pts[0] = ar.tip
        if len(pts) >= 2:
            path = pts
    length = (sum(math.dist(p, q) for p, q in zip(path, path[1:]))
              if path else 0.0)
    reach = max(2.0 * r, length) + ctx.text_margin + ctx.max_text_len
    best = None
    for t in ctx.radial_texts.near(ar.tip[0], ar.tip[1], reach):
        if id(t) in res.consumed_texts:
            continue
        h = max(t.height, 1.0)
        box = _text_box(t)
        # along the radius (R) or the whole diameter (Ø), up to a little
        # outside the circle
        diameter = not RADIUS_RE.match(t.text.strip())
        k = -1.0 if diameter else 0.0
        a = (center[0] + u[0] * k * r, center[1] + u[1] * k * r)
        b = (ar.tip[0] + u[0] * 4.0 * h, ar.tip[1] + u[1] * 4.0 * h)
        d_axis = _box_segment_distance(box, a, b)
        d_path = _path_distance(box, path) if path else 1e18
        d = min(d_axis, d_path)
        if d > ATol.RADIAL_TEXT * h:
            continue
        if best is None or d < best[0]:
            best = (d, t, d_path <= ATol.RADIAL_TEXT * h)
    if best is None:
        return None
    _, t, via_path = best          # the drawn line leads to the value
    return t, (path if via_path else None), (pieces if via_path else [])


def _opposite_arrow(arrows: List[Arrowhead], ar: Arrowhead, center: Point,
                    u: Tuple[float, float], r: float) -> Optional[Arrowhead]:
    """Second arrow of a diameter dimension, on the other side."""
    target = (center[0] - u[0] * r, center[1] - u[1] * r)
    cos_opp = math.cos(math.radians(180.0 - ATol.OPPOSITE_DEG))
    for other in arrows:
        if other is ar or other.used:
            continue
        if math.dist(other.tip, target) > 2.0 * _on_curve_tol(r):
            continue
        if (ar.direction[0] * other.direction[0]
                + ar.direction[1] * other.direction[1]) <= cos_opp:
            return other
    return None


def _consume_axis_lines(ctx: _Context, center: Point, u: Tuple[float, float],
                        s_lo: float, s_hi: float) -> None:
    """Mark as consumed the plain lines drawn along the radius / diameter
    between distances s_lo and s_hi from the centre. Centre lines (dash-dot)
    are never taken."""
    if s_hi - s_lo < 1e-6:
        return
    a = (center[0] + u[0] * s_lo, center[1] + u[1] * s_lo)
    b = (center[0] + u[0] * s_hi, center[1] + u[1] * s_hi)
    x0, x1 = min(a[0], b[0]) - 1, max(a[0], b[0]) + 1
    y0, y1 = min(a[1], b[1]) - 1, max(a[1], b[1]) + 1
    for pl in ctx.line_index.query(x0, y0, x1, y1):
        if pl.consumed or pl.style.dashed or \
                pl.style.linetype not in ("", "CONTINUOUS"):
            continue
        p, q = pl.points
        if all(point_line_distance(z, a, b) < ATol.COLLINEAR_OFF
               and x0 <= z[0] <= x1 and y0 <= z[1] <= y1 for z in (p, q)):
            pl.consumed = True


def _radial_dimensions(ctx: _Context, arrows: List[Arrowhead],
                       res: AnnotationResult) -> None:
    """RADIUS and DIAMETER dimensions: an arrow touching a circle or an arc
    along its radius + an "R..." / "Ø..." value next to its line."""
    if not len(ctx.radial_texts) or not len(ctx.curve_index):
        return
    for ar in arrows:
        if ar.used:
            continue
        hit = _curve_under_tip(ctx, ar)
        if hit is None:
            continue
        curve, u = hit
        found = _radial_text(ctx, res, ar, curve, u)
        if found is None:
            continue
        text, path, pieces = found
        kind = "radius" if RADIUS_RE.match(text.text.strip()) else "diameter"
        center, r = curve.center, curve.radius
        ar.used = True
        res.consumed_fills.add(id(ar.fill))
        res.consumed_texts.add(id(text))
        other = (_opposite_arrow(arrows, ar, center, u, r)
                 if kind == "diameter" else None)
        if other is not None:
            other.used = True
            res.consumed_fills.add(id(other.fill))
        for piece in pieces:
            piece.consumed = True
        # the dimension line drawn along the radius / diameter: from the
        # centre (radius) or the other side (diameter) when the value is
        # inside the circle, out to the value when it is outside
        c = text.center()
        s_text = (c[0] - center[0]) * u[0] + (c[1] - center[1]) * u[1]
        marks = [r]
        if abs(s_text) < r:
            marks += [-r] if kind == "diameter" else [0.0]
        else:
            marks.append(s_text)
        if other is not None:
            marks.append(-r)
        _consume_axis_lines(ctx, center, u, min(marks), max(marks))
        res.radial.append(RadialDimension(
            kind=kind, center=center, radius=r, tip=ar.tip, text=text.text,
            height=text.height, text_center=c, text_rotation=text.rotation,
            kink=path[1] if path and len(path) >= 3 else None))


# ---------------------------------------------------------------------------
# Angle and arc length dimensions
# ---------------------------------------------------------------------------
def angle_value(text: str) -> Optional[float]:
    """Degrees written in an angle text ("45°", "22,5°", "30°15'"), or
    None when the text is not an angle."""
    m = ANGLE_RE.match(text.strip())
    if not m:
        return None
    deg = float(m.group(1).replace(",", "."))
    if m.group(2):
        deg += float(m.group(2).replace(",", ".")) / 60.0
    if m.group(3):
        deg += float(m.group(3).replace(",", ".")) / 3600.0
    return deg


def length_values(text: str) -> List[float]:
    """Possible values of a length text: "3 500" -> [3500], "12,5" ->
    [12.5], "1,250" -> [1.25, 1250] (decimal or thousands separator)."""
    s = text.strip().lstrip("~±≈" + ARC_SIGN).strip()
    s = re.sub(r"\s*(?:mm|cm|m)$", "", s)
    s = re.sub(r"[\s  ]", "", s)
    try:
        out = [float(s.replace(",", "."))]
    except ValueError:
        return []
    m = re.fullmatch(r"(\d{1,3})[.,](\d{3})", s)
    if m:
        out.append(float(m.group(1) + m.group(2)))
    return out


# a length may be written in mm, cm or m whatever the drawing units
_UNIT_FACTORS = (1.0, 10.0, 0.1, 1000.0, 0.001)


def _matches_length(values: List[float], length: float) -> bool:
    if length <= 0:
        return False
    return any(abs(v * f - length) <= ATol.ARC_AGREE * length
               for v in values for f in _UNIT_FACTORS)


def _arc_attachments(ctx: _Context, arrows: List[Arrowhead]) -> list:
    """Arrows lying on an arc and pointing ALONG it: (arrow, arc, angle of
    the tip, +1 when the arrow points towards increasing angles else -1)."""
    out = []
    cos_max = math.cos(math.radians(ATol.TANGENT_DEG))
    for ar in arrows:
        if ar.used:
            continue
        for arc in ctx.curve_index.near(ar.tip[0], ar.tip[1], 3.5):
            if not isinstance(arc, EArc) or arc.consumed:
                continue
            R = arc.radius
            if R < 2.0 * ar.length or \
                    abs(math.dist(ar.tip, arc.center) - R) > _on_curve_tol(R):
                continue
            th = _angle_at(arc.center, ar.tip)
            a = math.radians(th)
            dot = -math.sin(a) * ar.direction[0] + math.cos(a) * ar.direction[1]
            if abs(dot) < cos_max:
                continue
            margin = math.degrees((ar.length + 1.0) / R) + 1.0
            if not _in_span(th, arc.start_angle % 360.0, arc.sweep, margin):
                continue
            out.append((ar, arc, th, 1 if dot > 0 else -1))
    return out


def _track_arcs(ctx: _Context, center: Point, R: float) -> List[EArc]:
    """Every arc of one dimension arc (same centre and radius)."""
    return [a for a in ctx.arc_centers.near(center[0], center[1],
                                            ATol.TRACK_TOL)
            if not a.consumed
            and math.dist(a.center, center) <= ATol.TRACK_TOL
            and abs(a.radius - R) <= ATol.TRACK_TOL]


def _covered(arcs: List[EArc], a: float, margin: float = 0.0) -> bool:
    return any(_in_span(a, x.start_angle % 360.0, x.sweep, margin)
               for x in arcs)


def _coverage(arcs: List[EArc], start: float, sweep: float) -> float:
    """Share of the arc start..start+sweep drawn by `arcs`."""
    n = max(12, min(180, int(sweep)))
    return sum(1 for k in range(n)
               if _covered(arcs, start + sweep * (k + 0.5) / n)) / n


def _measured_arc(ctx: _Context, center: Point, R: float, start: float,
                  sweep: float) -> float:
    """Radius of the arc an arc length dimension measures: a concentric arc
    (another radius) along the whole dimension. 0 when none is drawn."""
    best, bd = 0.0, 1e18
    for arc in ctx.arc_centers.near(center[0], center[1], ATol.TRACK_TOL):
        if arc.consumed or math.dist(arc.center, center) > ATol.TRACK_TOL \
                or abs(arc.radius - R) <= ATol.TRACK_TOL:
            continue
        if _coverage([arc], start, sweep) < 0.9:
            continue
        if abs(arc.radius - R) < bd:
            best, bd = arc.radius, abs(arc.radius - R)
    return best


def _curve_texts_near(ctx: _Context, res: AnnotationResult, center: Point,
                      R: float, start: float, sweep: float) -> list:
    """Values written next to the dimension arc start..start+sweep, the
    nearest first: [(distance in text heights, text)]."""
    pts = [(center[0] + R * math.cos(math.radians(start + sweep * k / 8)),
            center[1] + R * math.sin(math.radians(start + sweep * k / 8)))
           for k in range(9)]
    m = ctx.text_margin + ctx.max_text_len / 2.0
    out = []
    for t in ctx.curve_texts.query(min(p[0] for p in pts) - m,
                                   min(p[1] for p in pts) - m,
                                   max(p[0] for p in pts) + m,
                                   max(p[1] for p in pts) + m):
        if id(t) in res.consumed_texts:
            continue
        c = t.center()
        h = max(t.height, 1.0)
        w = t.width or 0.55 * t.height * len(t.text)
        off = abs(math.dist(c, center) - R)
        if off > ATol.CURVE_TEXT * h + w / 2.0:
            continue
        margin = math.degrees((w / 2.0 + 2.0 * h) / max(R, 1e-6))
        if not _in_span(_angle_at(center, c), start, sweep, margin):
            continue
        out.append((off / h, t))
    out.sort(key=lambda x: x[0])
    return out


def _curve_value(ctx: _Context, t: RawText, center: Point, R: float,
                 start: float, sweep: float,
                 units_per_pt: Optional[float]) -> Optional[Tuple[str, float]]:
    """Does the text give this arc's angle or length? Returns ("angle", 0)
    or ("arc", radius of the measured arc), or None when it does not agree
    with the drawing (never invent a dimension)."""
    s = t.text.strip()
    ang = angle_value(s)
    if ang is not None:
        if abs(ang - sweep) <= max(ATol.ANGLE_AGREE, 0.04 * ang):
            return "angle", 0.0
        return None
    if RADIUS_RE.match(s) or DIAMETER_RE.match(s) or not DIM_TEXT_RE.match(s):
        return None
    r_arc = _measured_arc(ctx, center, R, start, sweep) or R
    if s.startswith(ARC_SIGN):
        return "arc", r_arc
    if units_per_pt and _matches_length(
            length_values(s), r_arc * math.radians(sweep) * units_per_pt):
        return "arc", r_arc
    return None


def _angular_dimensions(ctx: _Context, arrows: List[Arrowhead],
                        res: AnnotationResult,
                        units_per_pt: Optional[float]) -> None:
    """ANGLE and ARC LENGTH dimensions: two arrows on one dimension arc,
    pointing along it in opposite senses, + a value that agrees with the
    drawn arc ("45°" with its angle; a length with its length)."""
    att = _arc_attachments(ctx, arrows)
    if len(att) < 2:
        return
    tracks: list = []                  # [centre, radius, attachments]
    for a in att:
        arc = a[1]
        for tk in tracks:
            if math.dist(tk[0], arc.center) <= ATol.TRACK_TOL and \
                    abs(tk[1] - arc.radius) <= ATol.TRACK_TOL:
                tk[2].append(a)
                break
        else:
            tracks.append([arc.center, arc.radius, [a]])
    found = []
    for center, R, A in tracks:
        if len(A) < 2:
            continue
        arcs = _track_arcs(ctx, center, R)
        for i in range(len(A)):
            for j in range(i + 1, len(A)):
                a1, a2 = A[i], A[j]
                if a1[0] is a2[0] or a1[3] == a2[3]:
                    continue
                neg, pos = (a1, a2) if a1[3] < 0 else (a2, a1)
                # the dimension arc runs under both arrowheads
                if not all(_covered(arcs, x[2] - x[3] * math.degrees(
                        x[0].length / 2.0 / R), 1.0) for x in (neg, pos)):
                    continue
                # arrows pointing outwards (start = the arrow pointing back)
                # or inwards (small angles: arrows outside the arc)
                for start, end in ((neg[2], pos[2]), (pos[2], neg[2])):
                    sweep = (end - start) % 360.0
                    if sweep < 0.5:
                        continue
                    cov = _coverage(arcs, start, sweep)
                    for off, t in _curve_texts_near(ctx, res, center, R,
                                                    start, sweep):
                        val = _curve_value(ctx, t, center, R, start, sweep,
                                           units_per_pt)
                        if val is not None:
                            found.append((off - 2.0 * cov, center, R, neg,
                                          pos, start, end, t, val))
                            break
    found.sort(key=lambda f: f[0])
    for _, center, R, neg, pos, start, end, t, (kind, r_arc) in found:
        if neg[0].used or pos[0].used or id(t) in res.consumed_texts:
            continue
        for x in (neg, pos):
            x[0].used = True
            res.consumed_fills.add(id(x[0].fill))
        res.consumed_texts.add(id(t))
        # the drawn dimension arc (and its tails outside the arrows)
        sweep = (end - start) % 360.0
        m = math.degrees(3.0 * max(neg[0].length, pos[0].length) / R) + 2.0
        for arc in _track_arcs(ctx, center, R):
            if _arc_share_inside(arc, start - m, sweep + 2.0 * m) >= 0.7:
                arc.consumed = True
        res.angular.append(AngularDimension(
            kind=kind, center=center, radius=R, start_angle=start,
            end_angle=end, text=t.text, height=t.height,
            text_center=t.center(), text_rotation=t.rotation,
            arc_radius=r_arc))


def _arc_share_inside(arc: EArc, start: float, sweep: float) -> float:
    """Share of `arc` lying on start..start+sweep."""
    n = 24
    a0, sw = arc.start_angle % 360.0, arc.sweep
    return sum(1 for k in range(n)
               if _in_span(a0 + sw * (k + 0.5) / n, start % 360.0, sweep)) / n


# ---------------------------------------------------------------------------
# Leaders
# ---------------------------------------------------------------------------
def _text_distance(t: RawText, p: Point) -> float:
    """Distance from p to the text's footprint (baseline and mid-height
    line), so a note written on either side of a leader landing matches."""
    d = t.direction()
    w = t.width or 0.55 * t.height * len(t.text)
    a = math.radians(t.rotation)
    up = (-math.sin(a), -math.cos(a))
    cap = 0.35 * t.height
    s0 = t.origin
    s1 = (s0[0] + d[0] * w, s0[1] + d[1] * w)
    m0 = (s0[0] + up[0] * cap, s0[1] + up[1] * cap)
    m1 = (s1[0] + up[0] * cap, s1[1] + up[1] * cap)
    return min(point_segment_distance(p, s0, s1),
               point_segment_distance(p, m0, m1))
def _walk_leader(ctx: _Context, first: EPolyline, end: int,
                 index: "GridIndex") -> Tuple[List[Point], List[EPolyline]]:
    """Follow a leader from its first piece through the pieces joined to
    its tail (a CAD leader is often plotted as 2-3 separate lines: shaft,
    elbow, landing). Returns the vertices and the pieces used."""
    pts = list(first.points if end == 0 else reversed(first.points))
    used = [first]
    for _ in range(ATol.LEADER_HOPS):
        tail = pts[-1]
        nxt = None
        for pl, e in index.near(tail[0], tail[1], ATol.LEADER_JOIN):
            if pl in used or pl.consumed or len(pl.points) != 2:
                continue                  # leader pieces are single lines
            if math.dist(*pl.points) < 1.0:
                continue                  # crumbs (arrow outlines, glyphs)
            p = pl.points[e]
            if math.dist(p, tail) <= ATol.LEADER_JOIN:
                nxt = (pl, e)
                break
        if nxt is None:
            break
        pl, e = nxt
        more = list(pl.points if e == 0 else reversed(pl.points))
        pts += more[1:]
        used.append(pl)
    return pts, used


def _landing_texts(ctx: _Context, res: AnnotationResult,
                   pts: List[Point]) -> List[RawText]:
    """Note lines of a leader, top to bottom.

    1. Landing: when the last segment is parallel to text, the note is the
       line written ON it plus the line written UNDER it (tag above the
       landing, "(HOLD 18)" below), never the neighbouring notes.
    2. Otherwise the text nearest the tail, within LEADER_REACH heights."""
    a, b = pts[-2], pts[-1]
    tail = b
    reach = ATol.LEADER_TEXT + ctx.max_text_len
    seg = angle_deg((b[0] - a[0], -(b[1] - a[1])))
    above = below = None
    if math.dist(a, b) > 1e-6:
        for t in ctx.text_index.near(tail[0], tail[1], reach):
            if id(t) in res.consumed_texts or \
                    angle_diff_mod180(seg, t.rotation) > 10.0:
                continue
            h = max(t.height, 0.5)
            r = math.radians(t.rotation)
            down = (math.sin(r), math.cos(r))          # page 'down' of text
            along = (math.cos(r), -math.sin(r))
            off = (t.origin[0] - a[0]) * down[0] + (t.origin[1] - a[1]) * down[1]
            sa = a[0] * along[0] + a[1] * along[1]
            sb = b[0] * along[0] + b[1] * along[1]
            s0 = t.origin[0] * along[0] + t.origin[1] * along[1]
            s1 = s0 + (t.width or 0.55 * t.height * len(t.text))
            if s1 < min(sa, sb) - h or s0 > max(sa, sb) + h:
                continue
            if -0.9 * h <= off <= 0.35 * h:            # written ON it
                if above is None or abs(off) < abs(above[0]):
                    above = (off, t)
            elif 0.35 * h < off <= 1.9 * h:            # written UNDER it
                if below is None or off < below[0]:
                    below = (off, t)
    if above is not None or below is not None:
        lines = [x[1] for x in (above, below) if x is not None]
        if len(lines) == 2 and (abs(lines[0].height - lines[1].height)
                                > 0.35 * max(lines[0].height, 0.5)):
            lines = [min(lines, key=lambda t: abs(
                (above or below)[0]))]
        return lines
    best, bd = None, 1e18
    for t in ctx.text_index.near(tail[0], tail[1], reach):
        if id(t) in res.consumed_texts:
            continue
        d = _text_distance(t, tail)
        if d <= min(ATol.LEADER_TEXT, ATol.LEADER_REACH * max(t.height, 1.0)) \
                and d < bd:
            best, bd = t, d
    return [best] if best is not None else []


def _in_line_label(pts: List[Point], t: RawText) -> bool:
    """Text written ALONG the leader's last segment, centred on its axis
    (flow arrow): a direction label, not a note."""
    a, b = pts[-2], pts[-1]
    seg = angle_deg((b[0] - a[0], -(b[1] - a[1])))
    if angle_diff_mod180(seg, t.rotation) > 10.0:
        return False
    c = t.center()
    L = math.dist(a, b)
    if L < 1e-9:
        return False
    s = ((c[0] - a[0]) * (b[0] - a[0]) + (c[1] - a[1]) * (b[1] - a[1])) / L
    if not 0.0 <= s <= L:                 # beside the END: a normal note
        return False
    return point_line_distance(c, a, b) < 0.2 * max(t.height, 0.5)


def _leader_start(ar: Arrowhead, index: "GridIndex"):
    """The piece a leader starts with: it touches the arrow (at its tip or
    its base, plotters stop the line where the arrowhead begins), runs
    BACK along the arrow axis and never passes beyond the tip."""
    base = (ar.tip[0] - ar.direction[0] * ar.length,
            ar.tip[1] - ar.direction[1] * ar.length)
    best, bd = None, 1e18
    radius = ATol.LEADER_NEAR + ar.length
    for pl, end in index.near(ar.tip[0], ar.tip[1], radius):
        if pl.consumed:
            continue
        first = pl.points[0] if end == 0 else pl.points[-1]
        second = pl.points[1] if end == 0 else pl.points[-2]
        d = min(math.dist(first, ar.tip), math.dist(first, base))
        if d > ATol.LEADER_NEAR:
            continue
        ahead = (first[0] - ar.tip[0]) * ar.direction[0] + \
            (first[1] - ar.tip[1]) * ar.direction[1]
        if ahead > 0.3:
            continue                          # passes beyond the tip
        L = math.dist(first, second)
        if L < 1e-6:
            continue
        back = -((second[0] - first[0]) * ar.direction[0]
                 + (second[1] - first[1]) * ar.direction[1]) / L
        if back < 0.85:
            continue                          # not along the arrow axis
        if d < bd:
            best, bd = (pl, end), d
    return best


def _leaders(ctx: _Context, arrows: List[Arrowhead],
             res: AnnotationResult) -> None:
    open_polys = [pl for pl in ctx.rp.polylines
                  if not pl.consumed and not pl.closed and len(pl.points) <= 6]
    end_index: GridIndex[Tuple[EPolyline, int]] = GridIndex(8.0)
    for pl in open_polys:
        for end in (0, -1):
            p = pl.points[end]
            end_index.insert((pl, end), (p[0], p[1], p[0], p[1]))
    heights = [t.height for t in ctx.rp.page.texts] or [2.5]
    usual = statistics.median(heights)
    for ar in arrows:
        if ar.used:
            continue
        start = _leader_start(ar, end_index)
        if start is None:
            continue
        pl, end = start
        pts, pieces = _walk_leader(ctx, pl, end, end_index)
        pts[0] = ar.tip
        if len(pts) < 2:
            continue
        length = sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))
        lines = _landing_texts(ctx, res, pts)
        if not lines:
            continue
        txt = min(lines, key=lambda t: _text_distance(t, pts[-1]))
        if txt.height > ATol.LEADER_TITLE * usual and \
                length < 2.0 * txt.height:
            continue                                  # a title, not a note
        if length < 1.5 * max(ar.length, 1.0):
            continue                                  # arrow without leader
        if _in_line_label(pts, txt):
            continue                                  # flow arrow label
        if any(t.text.strip().upper() in DIRECTION_WORDS for t in lines):
            continue                                  # "UP" on a stair
        for piece in pieces:
            piece.consumed = True
        ar.used = True
        res.consumed_fills.add(id(ar.fill))
        for t in lines:
            res.consumed_texts.add(id(t))
        res.leaders.append(LeaderEntity(vertices=pts, text=txt, lines=lines))


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def reconstruct(rp: RebuiltPage, enable_dims: bool = True,
                enable_leaders: bool = True,
                enable_ticks: bool = True,
                units_per_pt: Optional[float] = None) -> AnnotationResult:
    """Detect dimensions (radius / diameter, angle / arc length, then linear
    with arrows or ticks) then leaders on a page.

    units_per_pt (drawing units per page point) lets an arc length written
    without its "⌒" sign be checked against the drawn arc."""
    res = AnnotationResult()
    page: PageData = rp.page
    ctx = _Context(rp)
    arrows = find_arrowheads(page.fills)
    if enable_dims:
        # curved dimensions first: their arrows could otherwise pass for a
        # linear dimension (two nearly opposite arrows on a flat arc)
        _radial_dimensions(ctx, arrows, res)
        _angular_dimensions(ctx, arrows, res, units_per_pt)
        _arrow_dimensions(ctx, arrows, res)
        if enable_ticks:
            _tick_dimensions(ctx, res)
    if enable_leaders:
        _leaders(ctx, arrows, res)
    for t in ctx.dim_texts:
        if id(t) not in res.consumed_texts and not _is_label(ctx, t):
            res.dim_raw_texts.append(t)
    return res


def _is_label(ctx: _Context, t: RawText) -> bool:
    """Grid-axis numbers, item marks... are not dimension values:
    a single character, or a short text sitting inside a small circle."""
    if len(t.text.strip()) <= 1:
        return True
    c = t.center()
    for circ in ctx.circle_index.near(c[0], c[1], 0.0):
        if circ.radius < 4 * t.height and \
                math.dist(circ.center, c) < circ.radius:
            return True
    return False
