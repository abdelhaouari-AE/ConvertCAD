"""
annotations.py — STEP 4: rebuild TRUE dimensions and leaders (heuristics).

In a PDF a dimension is only drawing primitives:
    2 terminators (arrows, ticks, dots...) + a dimension line
    + 2 extension lines + a value text.
This module recognises those patterns and rebuilds real DXF DIMENSION
entities (and LEADERs for "arrow + polyline + note" patterns).

How linear dimensions are found (whole sheet at once):
  1. terminators: filled, outline and open arrows, dots, oblique ticks
     (terminators.py) — sizes judged from the values NEAR them;
  2. frames: two terminators facing each other on one line;
  3. every frame x every nearby value gets a cost (distance to the line,
     centring, agreement with the scale of the sheet — dimvalues.py);
     the scale is voted by the clear pairs first;
  4. the pairs are taken from the cheapest, each value and terminator once;
  5. values still free: starting from the value, its line and the shapes
     at both line ends — a shape repeated at line ends on the sheet is a
     terminator whatever its form ("learned");
  6. values with a line under them that still match nothing: line, ends
     and value are GROUPED (they move as one object) on layer DIM_RAW.

SAFE-FALLBACK RULE (never invent, never corrupt):
  * A dimension is rebuilt ONLY when terminators, line and text all agree.
  * The value shown is ALWAYS the original PDF text (kept as text override).
  * A value with a label / remark ("L=3500", "3500 (TYP.)") must agree with
    the scale; when nothing tells the scale, or a plain value disagrees
    with it, the dimension goes to layer DIM_CHECK (to review).
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

from .constants import LAYER_SHX_STROKES
from .dimvalues import (ANGLE_RE, ARC_SIGN, DIAMETER_RE,  # noqa: F401
                        DIAMETER_SIGNS, DIM_TEXT_RE, DIM_VALUE_RE, RADIUS_RE,
                        CompositeText, ScaleVotes, combine_split_values,
                        is_plain, text_ids, value_number)
from .extractor import PageData, Point, RawFill, RawText
from .geometry import EArc, EPolyline, RebuiltPage
from .spatial import (GridIndex, angle_deg, angle_diff_mod180,
                      point_line_distance, point_segment_distance,
                      segment_intersection)
from .terminators import (Arrowhead, TTol, best_similarity,  # noqa: F401
                          end_shape, find_arrowheads, find_dots,
                          find_stroke_arrows, merge_outlined_fills,
                          size_lookup)


class ATol:
    """Annotation tolerances, in page points.

    Sizes are given for values written about REF_SIZE points high (2.5 mm
    letters); where the values are larger (a detail drawn larger, a sheet
    printed larger), the size limits of arrows, ticks and notes grow in
    proportion there, never shrink."""
    REF_SIZE = 10.0            # usual font size of dimension values
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
    # --- values ---
    CLEAR_COST = 1.5           # a pair this good (and mutual) votes the scale
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
    # --- shapes learned at line ends, unrecognised dimensions ---
    LINE_UNDER = 2.5           # value within this many heights of its line
    END_RADIUS = 1.2           # end shape: within this many text heights
    SAME_SHAPE = 0.7           # signature similarity of two ends
    LEARNED_MIN = 3            # a shape seen at fewer ends is not learned
    LEARNED_SURE = 4           # ends with one shape on the sheet: sure


# Arrows labelled with these words show a direction (stairs, ramps, slopes),
# they are not leaders.
DIRECTION_WORDS = {"UP", "DN", "DOWN", "MONTEE", "MONTÉE", "DESCENTE",
                   "MONTE", "DESC", "HAUT", "BAS", "SLOPE", "PENTE"}


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
    kind: str = "arrow"        # "arrow" | "tick" | "dot" | "learned"
    tip1: Optional[Point] = None          # terminator positions on the line
    tip2: Optional[Point] = None
    # --- measured in the PDF, so the CAD dimension looks the same ---
    text_rotation: Optional[float] = None  # degrees, direction of the value
    value: Optional[RawText] = None        # the PDF text (font, letter size)
    terminator: float = 0.0    # arrow length / tick length / dot diameter
    ext1: bool = False         # extension line found at def_point1 / 2
    ext2: bool = False         # (otherwise the CAD one is not drawn)
    ext_beyond: Optional[float] = None    # extension lines pass the
                                          # dimension line by (points)
    line_beyond: float = 0.0   # dimension line passes the ticks by (points)
    arrow: str = ""            # CAD arrow block ("" closed filled, "DOT"...)
    mtext: str = ""            # value with MTEXT stacking codes (3\S50^ ;)
    review: bool = False       # doubtful: written on layer DIM_CHECK
    # terminators of an unknown shape, drawn as in the PDF (page coords)
    extra_lines: List[List[Point]] = field(default_factory=list)
    extra_fills: List[List[Point]] = field(default_factory=list)


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
    arrow: float = 0.0         # arrowhead length (points)
    arrow_kind: str = ""       # CAD arrow block ("" closed filled, "DOT"...)


@dataclass
class DimGroup:
    """A dimension that could not be rebuilt: its value, line and ends,
    written as they are on layer DIM_RAW and grouped (one object)."""
    texts: List[RawText] = field(default_factory=list)
    lines: List[List[Point]] = field(default_factory=list)
    fills: List[RawFill] = field(default_factory=list)
    styles: list = field(default_factory=list)       # Style of each line


@dataclass
class AnnotationResult:
    dimensions: List[DimensionEntity] = field(default_factory=list)
    radial: List[RadialDimension] = field(default_factory=list)
    angular: List[AngularDimension] = field(default_factory=list)
    leaders: List[LeaderEntity] = field(default_factory=list)
    groups: List[DimGroup] = field(default_factory=list)
    dim_raw_texts: List[RawText] = field(default_factory=list)
    consumed_fills: set = field(default_factory=set)     # id() of RawFill
    consumed_texts: set = field(default_factory=set)     # id() of RawText

    @property
    def to_review(self) -> int:
        return sum(1 for d in self.dimensions if d.review)


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
        # current pieces of the polylines stroked terminators were cut from
        self._pieces: Dict[int, List[EPolyline]] = {}
        # PDF texts AND the AutoCAD SHX texts read from the PDF comments
        texts = list(rp.page.texts) + list(rp.page.shx_texts)
        self.texts = texts
        # values split by the PDF ("3" + small raised "50"...): the
        # composite stands for its parts
        self.composites = combine_split_values(texts)
        parts = {id(p) for c in self.composites for p in c.parts}
        pool = [t for t in texts if id(t) not in parts] + self.composites
        # possible dimension values (plain measurements AND values with a
        # label / count / remark: "L=3500", "2x1500", "3500 (TYP.)"...)
        self.dim_texts = [t for t in pool
                          if DIM_VALUE_RE.match(t.text.strip())]
        heights = [t.height for t in self.dim_texts] or [2.5]
        self.text_margin = ATol.TEXT_NEAR * max(statistics.median(heights),
                                                1.0) * 2
        # usual size of the values (PDF font size), for the whole sheet and
        # near each point: arrows, ticks and gaps grow with it
        sized = self.dim_texts if len(self.dim_texts) >= 3 else texts
        self.size = statistics.median([t.height for t in sized]) \
            if sized else 0.0
        self.k = max(1.0, self.size / ATol.REF_SIZE)
        self.dim_text_index: GridIndex[RawText] = GridIndex(24.0)
        for t in self.dim_texts:
            c = t.center()
            self.dim_text_index.insert(t, (c[0], c[1], c[0], c[1]))
        self.size_at = size_lookup({}, 40.0, self._local_size)
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

    # ---- sizes ----------------------------------------------------------
    def _local_size(self, p: Point) -> float:
        """Font size of the values near p: the largest of the three nearest
        (the whole sheet's when none is near)."""
        near = sorted((math.dist(t.center(), p), t.height)
                      for t in self.dim_text_index.near(p[0], p[1], 400.0))
        near = [h for d, h in near if d <= 400.0][:3]
        # the largest of them: a large detail next to small dimensions
        # keeps its large arrows (the limits are upper bounds only)
        return max(near) if near else self.size

    def k_at(self, p: Point) -> float:
        return max(1.0, self.size_at(p) / ATol.REF_SIZE)

    def open_ends(self) -> GridIndex:
        """Ends of the short open polylines (leader pieces), built once."""
        if self._open_ends is None:
            self._open_ends = _end_index(self.rp)
        return self._open_ends

    # ---- cutting stroked terminators out of their polylines --------------
    def detach(self, strokes: List[Tuple[EPolyline, Point, Point]]) -> None:
        """Remove the segments a-b of a used terminator from the polylines
        they belong to; what is left becomes new polylines (and lines)."""
        for orig, a, b in strokes:
            pieces = self._pieces.get(id(orig), [orig])
            for piece in pieces:
                if piece.consumed:
                    continue
                i = _segment_at(piece, a, b)
                if i is None:
                    continue
                piece.consumed = True
                runs = _runs_without(piece, i)
                new = [EPolyline(points=r, closed=False, style=piece.style)
                       for r in runs]
                self._pieces[id(orig)] = [p for p in pieces
                                          if p is not piece] + new
                for p in new:
                    self.add_polyline(p)
                break

    def split_out(self, strokes: List[Tuple[EPolyline, Point, Point]]
                  ) -> None:
        """Like detach, but the strokes stay drawn as pieces of their own
        (a terminator not used yet: a leader may start from it)."""
        for orig, a, b in strokes:
            pieces = self._pieces.get(id(orig), [orig])
            for piece in pieces:
                if piece.consumed or len(piece.points) == 2 and \
                        not piece.closed:
                    continue
                i = _segment_at(piece, a, b)
                if i is None:
                    continue
                piece.consumed = True
                new = [EPolyline(points=r, closed=False, style=piece.style)
                       for r in _runs_without(piece, i)]
                new.append(EPolyline(points=[a, b], closed=False,
                                     style=piece.style))
                self._pieces[id(orig)] = [p for p in pieces
                                          if p is not piece] + new
                for p in new:
                    self.add_polyline(p)
                break

    def add_polyline(self, pl: EPolyline) -> None:
        self.rp.polylines.append(pl)
        if pl.is_single_line:
            self.lines.append(pl)
            self.line_index.insert_segment(pl, pl.points[0], pl.points[1])
        self._open_ends = None


def _segment_at(pl: EPolyline, a: Point, b: Point) -> Optional[int]:
    """Index of the segment a-b (either way) of a polyline."""
    pts = pl.points
    n = len(pts)
    pairs = [(i, pts[i], pts[i + 1]) for i in range(n - 1)]
    if pl.closed and n > 2:
        pairs.append((n - 1, pts[-1], pts[0]))
    for i, p, q in pairs:
        if (p == a and q == b) or (p == b and q == a):
            return i
    return None


def _runs_without(pl: EPolyline, i: int) -> List[List[Point]]:
    """The parts of a polyline left when its segment i is removed."""
    pts = list(pl.points)
    if pl.closed and len(pts) > 2:
        ring = pts[i + 1:] + pts[:i + 1]
        return [ring] if len(ring) >= 2 else []
    runs = [pts[:i + 1], pts[i + 1:]]
    return [r for r in runs if len(r) >= 2]


def _use_terminator(ctx: _Context, res: AnnotationResult,
                    ar: Arrowhead) -> None:
    """Mark a terminator as used: its fill and strokes are not written."""
    ar.used = True
    if ar.fill is not None:
        res.consumed_fills.add(id(ar.fill))
    for f in ar.extra_fills:
        res.consumed_fills.add(id(f))
    if ar.strokes:
        ctx.detach(ar.strokes)


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


def _find_extension(ctx: _Context, tip: Point, axis: Tuple[float, float]
                    ) -> Optional[Tuple[Point, EPolyline, float]]:
    """Extension line crossing the dimension line at `tip`: a line roughly
    perpendicular to the axis that passes through (or ends at) the tip.

    The measured point is the far end on the OBJECT side. It is only trusted
    when unambiguous: the line must overshoot the dimension line by a short
    stub (<= EXT_OVERSHOOT) on one side and run clearly longer on the other.
    Extension lines shared by stacked dimensions (chain + overall) are
    ambiguous -> None, and the dimension keeps its tips as definition points
    (the measured distance is identical; the drawn line stays as geometry).

    Returns (measured point, line, how far it passes the dimension line)."""
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
            return (a if da >= db else b), pl, short
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


def _consume_chain_lines(ctx: _Context, res: AnnotationResult) -> None:
    """A dimension line drawn once for a whole chain (or joined to its
    neighbours when the geometry was rebuilt), or running past arrows drawn
    outside, lies inside no single dimension: it is consumed when the arrow
    dimensions on its line cover it (otherwise it would stay as a duplicate
    line under the dimensions)."""
    dims = [d for d in res.dimensions
            if d.kind in ("arrow", "learned") and d.tip1 is not None
            and d.tip2 is not None]
    if not dims:
        return
    index: GridIndex[DimensionEntity] = GridIndex(24.0)
    for d in dims:
        index.insert(d, (min(d.tip1[0], d.tip2[0]), min(d.tip1[1], d.tip2[1]),
                         max(d.tip1[0], d.tip2[0]), max(d.tip1[1], d.tip2[1])))
    for pl in list(ctx.lines):
        if pl.consumed:
            continue
        a, b = pl.points
        L = math.dist(a, b)
        if L < ATol.MIN_SPAN:
            continue
        u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        spans = []
        for d in index.query(min(a[0], b[0]) - 1, min(a[1], b[1]) - 1,
                             max(a[0], b[0]) + 1, max(a[1], b[1]) + 1):
            if (point_line_distance(d.tip1, a, b) > ATol.COLLINEAR_OFF
                    or point_line_distance(d.tip2, a, b) > ATol.COLLINEAR_OFF):
                continue
            s1 = (d.tip1[0] - a[0]) * u[0] + (d.tip1[1] - a[1]) * u[1]
            s2 = (d.tip2[0] - a[0]) * u[0] + (d.tip2[1] - a[1]) * u[1]
            spans.append((min(s1, s2), max(s1, s2), 2.5 * d.terminator + 1.0))
        if not spans:
            continue
        spans.sort()
        lo, hi, end_lo = spans[0][0], spans[0][1], spans[0][2]
        end_hi = spans[0][2]
        for s0, s1, e in spans[1:]:
            if s0 > hi + 1.0:                 # a gap: not one chain
                break
            if s1 > hi:
                hi, end_hi = s1, e
        if lo - end_lo <= 0.0 and hi + end_hi >= L:
            pl.consumed = True


def _make_dimension(ctx: _Context, res: AnnotationResult, t1: Point,
                    t2: Point, text: RawText, kind: str,
                    consume_ext: bool = True, terminator: float = 0.0,
                    line_beyond: float = 0.0) -> DimensionEntity:
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
    beyond = [e[2] for e in (e1, e2) if e]
    res.consumed_texts.update(text_ids(text))
    _consume_dim_line(ctx, t1, t2)
    return DimensionEntity(def_point1=p1, def_point2=p2,
                           line_point=((t1[0] + t2[0]) / 2,
                                       (t1[1] + t2[1]) / 2),
                           text=text.text, height=text.height,
                           text_center=text.center(), kind=kind,
                           tip1=t1, tip2=t2, text_rotation=text.rotation,
                           value=text, terminator=terminator,
                           ext1=bool(e1) and consume_ext,
                           ext2=bool(e2) and consume_ext,
                           ext_beyond=(sum(beyond) / len(beyond)
                                       if beyond else None),
                           line_beyond=line_beyond,
                           mtext=getattr(text, "mtext", "") or "")


# ---------------------------------------------------------------------------
# Linear dimensions: frames x values, matched over the whole sheet
# ---------------------------------------------------------------------------
@dataclass
class _Frame:
    """Two terminators facing each other on one line."""
    t1: Point
    t2: Point
    kind: str                  # "arrow" | "tick" | "dot"
    terms: tuple = ()          # Arrowheads; ticks: indexes in ticks list
    size: float = 0.0          # terminator size (points)
    line: Optional[EPolyline] = None     # tick / dot frames: the line
    cad: str = ""              # CAD arrow block
    mixed: bool = False        # two different kinds of arrows
    penalty: float = 0.0       # arrows pointing at each other, other
                               # terminators between the two ends

    @property
    def span(self) -> float:
        return math.dist(self.t1, self.t2)


def _axis_key(tip: Point, d: Tuple[float, float]) -> Tuple[int, int]:
    """Bucket key of the infinite line through `tip` along `d`.
    Sign-agnostic (abs offset, angle mod 180) so that two opposite arrows on
    the same line always land in the same or neighbouring buckets."""
    theta = math.degrees(math.atan2(d[1], d[0])) % 180.0
    tr = math.radians(theta)
    offset = abs(-math.sin(tr) * tip[0] + math.cos(tr) * tip[1])
    return (int(round(theta / 4.0)) % 45, int(round(offset / 3.0)))


def _arrow_frames(arrows: List[Arrowhead]) -> List[_Frame]:
    """Pairs of arrows pointing in opposite directions on one line
    (outwards; inwards for small dimensions with the arrows outside). Each
    arrow keeps its three nearest partners."""
    arrows = [a for a in arrows if a.has_direction and not a.used]
    buckets: Dict[Tuple[int, int], List[int]] = {}
    for i, a in enumerate(arrows):
        buckets.setdefault(_axis_key(a.tip, a.direction), []).append(i)
    cos_opp = math.cos(math.radians(180.0 - ATol.OPPOSITE_DEG))
    frames: List[_Frame] = []
    seen: set = set()
    for i, a1 in enumerate(arrows):
        kt, ko = _axis_key(a1.tip, a1.direction)
        cands = []
        for dt in (-1, 0, 1):
            for do in (-1, 0, 1):
                for j in buckets.get(((kt + dt) % 45, ko + do), ()):
                    if j == i:
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
        for _, inward, j in sorted(cands)[:3]:
            key = (min(i, j), max(i, j))
            if key in seen:
                continue
            seen.add(key)
            a2 = arrows[j]
            cad = a1.cad_arrow() if a1.kind != "filled" else a2.cad_arrow()
            # arrows pointing at each other are rarer than pointing away
            # (and two neighbours of a chain look like that); a frame with
            # other arrows between its ends is two dimensions, not one
            inner = _arrows_between(arrows, buckets, a1, a2)
            frames.append(_Frame(a1.tip, a2.tip, "arrow", (a1, a2),
                                 size=(a1.length + a2.length) / 2.0,
                                 cad=cad, mixed=a1.kind != a2.kind,
                                 penalty=0.5 * inward + 0.6 * inner))
    return frames


def _arrows_between(arrows: List[Arrowhead], buckets, a1: Arrowhead,
                    a2: Arrowhead) -> int:
    """Arrows lying on the line a1-a2, strictly between the two tips."""
    kt, ko = _axis_key(a1.tip, a1.direction)
    span = math.dist(a1.tip, a2.tip)
    u = ((a2.tip[0] - a1.tip[0]) / span, (a2.tip[1] - a1.tip[1]) / span)
    n = 0
    seen: set = set()
    for dt in (-1, 0, 1):
        for do in (-1, 0, 1):
            for j in buckets.get(((kt + dt) % 45, ko + do), ()):
                a = arrows[j]
                if a is a1 or a is a2 or id(a) in seen:
                    continue
                seen.add(id(a))
                if point_line_distance(a.tip, a1.tip, a2.tip) \
                        > ATol.COLLINEAR_OFF:
                    continue
                t = (a.tip[0] - a1.tip[0]) * u[0] + (a.tip[1] - a1.tip[1]) * u[1]
                if 1.0 < t < span - 1.0:
                    n += 1
    return min(n, 4)


def _tick_list(ctx: _Context) -> list:
    """Short lines that may be oblique ticks: (mid, angle, line, length)."""
    ticks = []
    for pl in ctx.lines:
        if pl.consumed or pl.style.pdf_layer == LAYER_SHX_STROKES:
            continue
        a, b = pl.points
        L = math.dist(a, b)
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        if ATol.TICK_MIN_LEN <= L <= ATol.TICK_MAX_LEN * ctx.k_at(mid):
            ang = angle_deg((b[0] - a[0], b[1] - a[1])) % 180.0
            ticks.append((mid, ang, pl, L))
    return ticks


def _stations(ctx: _Context, line: EPolyline, items, max_reach: float,
              accept) -> list:
    """Things lying on a line, sorted along it: [(t, item)]; `accept(item,
    line angle)` filters them."""
    a, b = line.points
    L = math.dist(a, b)
    u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
    line_ang = angle_deg(u)
    out = []
    for item, p in items:
        if point_line_distance(p, a, b) > ATol.TICK_ON_LINE:
            continue
        t = (p[0] - a[0]) * u[0] + (p[1] - a[1]) * u[1]
        if not -max_reach <= t <= L + max_reach:
            continue
        if accept(item, line_ang):
            out.append((t, item))
    out.sort(key=lambda x: x[0])
    return out


def _tick_frames(ctx: _Context, ticks: list) -> List[_Frame]:
    """Consecutive oblique ticks along a line."""
    if len(ticks) < 2:
        return []
    index: GridIndex[int] = GridIndex(12.0)
    for k, (mid, _, _, _) in enumerate(ticks):
        index.insert(k, (mid[0], mid[1], mid[0], mid[1]))
    frames: List[_Frame] = []
    for line in sorted(ctx.lines, key=lambda p: -math.dist(*p.points)):
        if line.consumed:
            continue
        a, b = line.points
        if math.dist(a, b) < ATol.TICK_PAIR_MIN:
            continue
        m = ATol.TICK_ON_LINE + ATol.TICK_MAX_LEN * ctx.k
        cand = [(k, ticks[k][0]) for k in index.query(
            min(a[0], b[0]) - m, min(a[1], b[1]) - m,
            max(a[0], b[0]) + m, max(a[1], b[1]) + m)
            if ticks[k][2] is not line and not ticks[k][2].consumed]

        def oblique(k, line_ang):
            rel = angle_diff_mod180(ticks[k][1], line_ang)
            return ATol.TICK_OBLIQUE_LO <= rel <= ATol.TICK_OBLIQUE_HI
        on_line = _stations(ctx, line, cand, m, oblique)
        for (t_a, ka), (t_b, kb) in zip(on_line, on_line[1:]):
            if t_b - t_a < ATol.TICK_PAIR_MIN:
                continue
            frames.append(_Frame(ticks[ka][0], ticks[kb][0], "tick",
                                 (ka, kb), size=(ticks[ka][3]
                                                 + ticks[kb][3]) / 2.0,
                                 line=line))
    return frames


def _dot_frames(ctx: _Context, dots: List[Arrowhead]) -> List[_Frame]:
    """Consecutive dots along a line (two dots at one place, the ends of
    two dimensions of a chain, count once)."""
    if len(dots) < 2:
        return []
    index: GridIndex[Arrowhead] = GridIndex(12.0)
    for d in dots:
        index.insert(d, (d.tip[0], d.tip[1], d.tip[0], d.tip[1]))
    frames: List[_Frame] = []
    for line in ctx.lines:
        if line.consumed:
            continue
        a, b = line.points
        if math.dist(a, b) < ATol.MIN_SPAN:
            continue
        m = 4.0
        cand = [(d, d.tip) for d in index.query(
            min(a[0], b[0]) - m, min(a[1], b[1]) - m,
            max(a[0], b[0]) + m, max(a[1], b[1]) + m) if not d.used]
        on_line = _stations(ctx, line, cand, m, lambda d, ang: True)
        groups: List[Tuple[float, List[Arrowhead]]] = []
        for t, d in on_line:
            if groups and t - groups[-1][0] <= 0.6:
                groups[-1][1].append(d)
            else:
                groups.append((t, [d]))
        for (t_a, ga), (t_b, gb) in zip(groups, groups[1:]):
            if t_b - t_a < ATol.MIN_SPAN:
                continue
            frames.append(_Frame(ga[0].tip, gb[0].tip, "dot",
                                 (tuple(ga), tuple(gb)),
                                 size=(ga[0].length + gb[0].length) / 2.0,
                                 line=line, cad="DOT"))
    return frames


def _frame_texts(ctx: _Context, res: AnnotationResult,
                 f: _Frame) -> List[Tuple[float, RawText]]:
    """Values that may belong to a frame, with their cost on geometry
    alone: distance to the line (text heights), outside the span, and
    off-centre."""
    tip1, tip2 = f.t1, f.t2
    m = ctx.text_margin
    x0, x1 = min(tip1[0], tip2[0]) - m, max(tip1[0], tip2[0]) + m
    y0, y1 = min(tip1[1], tip2[1]) - m, max(tip1[1], tip2[1]) + m
    mid = ((tip1[0] + tip2[0]) / 2, (tip1[1] + tip2[1]) / 2)
    span = f.span
    u = ((tip2[0] - tip1[0]) / span, (tip2[1] - tip1[1]) / span)
    line_ang = angle_deg((tip2[0] - tip1[0], -(tip2[1] - tip1[1])))
    out = []
    for t in ctx.dim_text_index.query(x0, y0, x1, y1):
        if text_ids(t) & res.consumed_texts:
            continue
        c = t.center()
        h = max(t.height, 1.0)
        d = point_line_distance(c, tip1, tip2)
        if d > ATol.TEXT_NEAR * h:
            continue
        s = (c[0] - mid[0]) * u[0] + (c[1] - mid[1]) * u[1]
        outside = max(0.0, abs(s) - span / 2.0)
        if outside > 4 * h + ATol.TEXT_NEAR * h:
            continue
        # The value is written along the dimension line (aligned style) or
        # horizontally (unidirectional style); any other angle is a mismatch.
        if (angle_diff_mod180(line_ang, t.rotation) > 30.0
                and angle_diff_mod180(t.rotation, 0.0) > 5.0):
            continue
        geo = d / h + 0.5 * outside / h \
            + 0.15 * min(abs(s) / max(span / 2.0, 1e-9), 1.0)
        out.append((geo, t))
    return out


def _value_cost(geo: float, t: RawText, span: float, votes: ScaleVotes,
                mixed: bool = False, penalty: float = 0.0
                ) -> Tuple[Optional[float], bool]:
    """Cost of a value for a frame, and whether the dimension should be
    reviewed. A doubtful value (label, remark...) that disagrees with a
    known scale is refused (None)."""
    nv = value_number(t.text)
    agree = votes.check(nv[0], nv[1], span) if nv else None
    cost, review = geo, False
    if is_plain(t.text):
        if agree is True:
            cost -= 0.8
        elif agree is False:          # not to scale, or not its value
            cost += 1.2
            review = True
    elif nv is None:                  # "EQ"
        cost += 0.6
    elif agree is True:
        cost -= 0.4
    elif agree is False:
        return None, False
    else:                             # nothing tells the scale
        cost += 0.8
        review = True
    if isinstance(t, CompositeText):
        cost -= 0.2
    if mixed:
        cost += 0.3
    return cost + penalty, review


def _linear_dimensions(ctx: _Context, arrows: List[Arrowhead],
                       dots: List[Arrowhead], res: AnnotationResult,
                       ticks_on: bool, votes: ScaleVotes) -> None:
    ticks = _tick_list(ctx) if ticks_on else []
    frames = _arrow_frames(arrows) + _dot_frames(ctx, dots) \
        + _tick_frames(ctx, ticks)
    pairs = []
    for fi, f in enumerate(frames):
        for geo, t in _frame_texts(ctx, res, f):
            pairs.append((geo, fi, t))
    if not pairs:
        return
    # 1. the clear pairs (each other's best, plain value) vote the scale
    best_f: Dict[int, Tuple[float, RawText]] = {}
    best_t: Dict[int, Tuple[float, int]] = {}
    for geo, fi, t in pairs:
        geo += frames[fi].penalty
        if fi not in best_f or geo < best_f[fi][0]:
            best_f[fi] = (geo, t)
        if id(t) not in best_t or geo < best_t[id(t)][0]:
            best_t[id(t)] = (geo, fi)
    for fi, (geo, t) in best_f.items():
        if best_t[id(t)][1] == fi and geo <= ATol.CLEAR_COST \
                and frames[fi].penalty == 0.0 and is_plain(t.text):
            nv = value_number(t.text)
            if nv:
                votes.add(nv[0], nv[1], frames[fi].span)
    votes.finish()
    # 2. every pair with its full cost, the cheapest first
    scored = []
    for geo, fi, t in pairs:
        cost, review = _value_cost(geo, t, frames[fi].span, votes,
                                   frames[fi].mixed, frames[fi].penalty)
        if cost is not None:
            scored.append((cost, fi, t, review))
    scored.sort(key=lambda x: x[0])
    taken_texts: set = set()
    taken_arrows: set = set()
    tick_use: Dict[int, int] = {}
    done: set = set()
    chosen = []
    for _cost, fi, t, review in scored:
        f = frames[fi]
        ids = text_ids(t)
        if fi in done or ids & taken_texts or ids & res.consumed_texts:
            continue
        if f.kind == "arrow":
            if any(id(a) in taken_arrows for a in f.terms):
                continue
            taken_arrows.update(id(a) for a in f.terms)
        elif f.kind == "dot":
            ends = [id(g[0]) for g in f.terms]
            if any(tick_use.get(e, 0) >= 2 for e in ends):
                continue
            for e in ends:
                tick_use[e] = tick_use.get(e, 0) + 1
        else:
            if any(tick_use.get(-1 - k, 0) >= 2 for k in f.terms):
                continue
            for k in f.terms:
                tick_use[-1 - k] = tick_use.get(-1 - k, 0) + 1
        taken_texts |= ids
        done.add(fi)
        chosen.append((f, t, review))
    # 3. terminators first (a steep tick must not pass for an extension
    #    line), then the dimensions
    for f, _t, _review in chosen:
        if f.kind == "arrow":
            for a in f.terms:
                _use_terminator(ctx, res, a)
        elif f.kind == "dot":
            for g in f.terms:
                for d in g:
                    _use_terminator(ctx, res, d)
        else:
            for k in f.terms:
                ticks[k][2].consumed = True
    by_line: Dict[int, list] = {}
    for f, t, review in chosen:
        dim = _make_dimension(ctx, res, f.t1, f.t2, t, f.kind,
                              terminator=f.size)
        dim.arrow = f.cad
        dim.review = review
        _consume_value_marks(ctx, t)
        res.dimensions.append(dim)
        if f.line is not None:
            by_line.setdefault(id(f.line), []).append((f, dim))
    # 4. a tick / dot line whose every interval is a dimension is theirs
    intervals: Dict[int, int] = {}
    lines: Dict[int, EPolyline] = {}
    for f in frames:
        if f.line is not None:
            intervals[id(f.line)] = intervals.get(id(f.line), 0) + 1
            lines[id(f.line)] = f.line
    for lid, made in by_line.items():
        if len(made) != intervals.get(lid, 0):
            continue
        line = lines[lid]
        line.consumed = True
        if made[0][0].kind != "tick":
            continue
        # the line passes the end ticks (CAD "dimension line extension"):
        # the CAD dimensions draw it, never longer than in the PDF
        a, b = line.points
        L = math.dist(a, b)
        u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        ts = [(p[0] - a[0]) * u[0] + (p[1] - a[1]) * u[1]
              for f, _ in made for p in (f.t1, f.t2)]
        ends = (min(ts), L - max(ts))
        if min(ends) > 0.5:
            for _, dim in made:
                dim.line_beyond = min(ends)


def _consume_value_marks(ctx: _Context, t: RawText) -> None:
    """The bar of a stacked fraction drawn as a line: part of the value."""
    if not isinstance(t, CompositeText) or "/" not in t.text:
        return
    d = t.direction()
    w = t.width or 0.55 * t.height * len(t.text)
    c = t.center()
    for pl in ctx.line_index.near(c[0], c[1], w):
        if pl.consumed:
            continue
        a, b = pl.points
        L = math.dist(a, b)
        if L > 0.8 * w or L < 0.5:
            continue
        if abs((b[0] - a[0]) * d[0] + (b[1] - a[1]) * d[1]) < 0.9 * L:
            continue
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        if point_line_distance(mid, t.origin,
                               (t.origin[0] + d[0], t.origin[1] + d[1])) \
                < t.height and math.dist(mid, c) < w:
            pl.consumed = True


# ---------------------------------------------------------------------------
# From the value: its line, and the shapes at both ends of the line
# ---------------------------------------------------------------------------
def _line_under(ctx: _Context, t: RawText) -> Optional[EPolyline]:
    """The line a value is written along (above, under or on it), the value
    lying between its ends."""
    c = t.center()
    h = max(t.height, 1.0)
    best, bd = None, 1e18
    for pl in ctx.line_index.near(c[0], c[1], ATol.LINE_UNDER * h):
        if pl.consumed:
            continue
        a, b = pl.points
        L = math.dist(a, b)
        if L < 2.0 * h:
            continue
        ang = angle_deg((b[0] - a[0], -(b[1] - a[1])))
        if angle_diff_mod180(ang, t.rotation) > 5.0:
            continue
        d = point_line_distance(c, a, b)
        if d > ATol.LINE_UNDER * h:
            continue
        s = ((c[0] - a[0]) * (b[0] - a[0]) + (c[1] - a[1]) * (b[1] - a[1])) / L
        if not 0.0 < s < L:
            continue
        if d < bd:
            best, bd = pl, d
    return best


class _Ends:
    """Small pieces of geometry, for the shapes at line ends."""

    def __init__(self, ctx: _Context, res: AnnotationResult):
        self.ctx = ctx
        self.res = res
        self.segs: GridIndex = GridIndex(8.0)
        for pl in ctx.rp.polylines:
            if pl.consumed or pl.style.pdf_layer == LAYER_SHX_STROKES:
                continue
            pts = pl.points
            pairs = list(zip(pts, pts[1:]))
            if pl.closed and len(pts) > 2:
                pairs.append((pts[-1], pts[0]))
            for a, b in pairs:
                if math.dist(a, b) <= 30.0:
                    self.segs.insert((pl, a, b), (min(a[0], b[0]),
                                                  min(a[1], b[1]),
                                                  max(a[0], b[0]),
                                                  max(a[1], b[1])))
        self.fills: GridIndex[RawFill] = GridIndex(8.0)
        for f in ctx.rp.page.fills:
            if f.background or id(f) in res.consumed_fills:
                continue
            xs = [p[0] for p in f.points]
            ys = [p[1] for p in f.points]
            self.fills.insert(f, (min(xs), min(ys), max(xs), max(ys)))

    def stations(self, line: EPolyline, r: float) -> list:
        """Small shapes touching a line (crossing it, ending on it, centred
        on it), grouped by their place along it:
        [(s, items, strokes, fills)], s from the first end."""
        a, b = line.points
        L = math.dist(a, b)
        u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        x0, x1 = min(a[0], b[0]) - r, max(a[0], b[0]) + r
        y0, y1 = min(a[1], b[1]) - r, max(a[1], b[1]) + r
        found = []
        for pl, p, q in self.segs.query(x0, y0, x1, y1):
            if pl is line or pl.consumed or math.dist(p, q) > 2.0 * r:
                continue
            hit = segment_intersection(p, q, a, b, eps=0.0)
            if hit is None:
                dp = point_segment_distance(p, a, b)
                dq = point_segment_distance(q, a, b)
                if min(dp, dq) > 0.6:
                    continue
                hit = p if dp <= dq else q
            if math.dist(p, hit) > r or math.dist(q, hit) > r:
                continue                  # not small around the line
            sp = (hit[0] - a[0]) * u[0] + (hit[1] - a[1]) * u[1]
            found.append((sp, ("seg", (p, q)), (pl, p, q), None))
        for f in self.fills.query(x0, y0, x1, y1):
            if id(f) in self.res.consumed_fills:
                continue
            xs, ys = [p[0] for p in f.points], [p[1] for p in f.points]
            cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
            if any(math.dist(p, (cx, cy)) > r for p in f.points):
                continue
            if point_segment_distance((cx, cy), a, b) > 0.6 and \
                    min(point_segment_distance(p, a, b) for p in f.points) > 0.6:
                continue
            sp = (cx - a[0]) * u[0] + (cy - a[1]) * u[1]
            found.append((sp, ("fill", f), None, f))
        found.sort(key=lambda x: x[0])
        out = []
        for sp, item, stroke, fill in found:
            if out and sp - out[-1][4] <= 0.4 * r:
                st = out[-1]
            else:
                st = [sp, [], [], [], sp]
                out.append(st)
            st[1].append(item)
            if stroke is not None:
                st[2].append(stroke)
            if fill is not None:
                st[3].append(fill)
            st[4] = sp
        res = []
        for sp0, items, strokes, fills, sp1 in out:
            res.append(((sp0 + sp1) / 2.0, items, strokes, fills))
        return res

    def at(self, end: Point, r: float, line: EPolyline):
        """Pieces lying within r of a line end and touching it:
        ([("seg", (a, b)) | ("fill", fill)], strokes, fills)."""
        items, strokes, fills = [], [], []
        touch = max(0.25 * r, 1.0)
        near = 1e18
        for pl, a, b in self.segs.near(end[0], end[1], r):
            if pl is line or pl.consumed:
                continue
            if math.dist(a, end) > r + 0.3 or math.dist(b, end) > r + 0.3:
                continue
            items.append(("seg", (a, b)))
            strokes.append((pl, a, b))
            near = min(near, point_segment_distance(end, a, b))
        for f in self.fills.near(end[0], end[1], r):
            if id(f) in self.res.consumed_fills:
                continue
            if any(math.dist(p, end) > r + 0.3 for p in f.points):
                continue
            items.append(("fill", f))
            fills.append(f)
            near = min(near, min(math.dist(p, end) for p in f.points))
        if near > touch:
            return [], [], []
        return items, strokes, fills


def _learned_dimensions(ctx: _Context, res: AnnotationResult,
                        votes: ScaleVotes, ticks_on: bool = True) -> None:
    """Values still free: the line they are written along, and the small
    shapes on that line on both sides of the value (at its ends, or in the
    middle of a chain). The same shape on both sides — and repeated on
    other dimension lines of the sheet — is a terminator, whatever its
    form."""
    free = [t for t in ctx.dim_texts
            if not (text_ids(t) & res.consumed_texts) and not _is_label(ctx, t)]
    if not free:
        return
    ends = _Ends(ctx, res)
    cands = []
    for t in free:
        line = _line_under(ctx, t)
        if line is None:
            continue
        a, b = line.points
        L = math.dist(a, b)
        u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        r = max(ATol.END_RADIUS * t.height, 4.0)
        c = t.center()
        st = (c[0] - a[0]) * u[0] + (c[1] - a[1]) * u[1]
        stations = ends.stations(line, r)
        left = [x for x in stations if x[0] < st]
        right = [x for x in stations if x[0] > st]
        if not left or not right:
            continue
        sa, sb = left[-1], right[0]
        if sb[0] - sa[0] < 2.0 * r:
            continue
        pa = (a[0] + u[0] * sa[0], a[1] + u[1] * sa[0])
        pb = (a[0] + u[0] * sb[0], a[1] + u[1] * sb[0])
        if not ticks_on and (_tick_like(sa[1], u) or _tick_like(sb[1], u)):
            continue                      # tick dimensions are switched off
        sig_a = end_shape(sa[1], pa, u, r)
        sig_b = end_shape(sb[1], pb, (-u[0], -u[1]), r)
        if len(sig_a) < 2 or len(sig_b) < 2 or \
                best_similarity(sig_a, sig_b) < ATol.SAME_SHAPE:
            continue
        cands.append((t, line, pa, pb, sa, sb, sig_a, sig_b))
    if not cands:
        return
    shapes = [x for c in cands for x in (c[6], c[7])]
    support = [sum(1 for o in shapes if best_similarity(x, o)
                   >= ATol.SAME_SHAPE) for x in shapes]
    order = sorted(range(len(cands)), key=lambda i: -min(support[2 * i],
                                                         support[2 * i + 1]))
    shared: set = set()                   # ends of the dimensions made here
    made: Dict[int, list] = {}
    for i in order:
        t, line, pa, pb, sa, sb, sig_a, sig_b = cands[i]
        if text_ids(t) & res.consumed_texts:
            continue
        items = sa[2] + sb[2]
        fills = sa[3] + sb[3]
        if any(pl.consumed and (id(pl), p, q) not in shared
               for pl, p, q in items) or \
                any(id(f) in res.consumed_fills and id(f) not in shared
                    for f in fills):
            continue
        seen = min(support[2 * i], support[2 * i + 1])
        if seen < ATol.LEARNED_MIN:
            continue                      # one shape at two ends: not enough
        nv = value_number(t.text)
        agree = votes.check(nv[0], nv[1], math.dist(pa, pb)) if nv else None
        if agree is False:
            continue                      # unknown ends AND not to scale
        sure = seen >= ATol.LEARNED_SURE
        dim = _make_dimension(ctx, res, pa, pb, t, "learned")
        dim.arrow = "NONE"
        dim.extra_lines = [[p, q] for pl, p, q in items
                           if (id(pl), p, q) not in shared]
        dim.extra_fills = [list(f.points) for f in fills
                           if id(f) not in shared]
        dim.terminator = max((math.dist(p, e) for e, st in ((pa, sa),
                                                           (pb, sb))
                              for pl, p0, q0 in st[2] for p in (p0, q0)),
                             default=0.0)
        dim.review = not (sure and agree is True)
        ctx.detach(items)
        for f in fills:
            res.consumed_fills.add(id(f))
            shared.add(id(f))
        shared.update((id(pl), p, q) for pl, p, q in items)
        _consume_value_marks(ctx, t)
        res.dimensions.append(dim)
        made.setdefault(id(line), []).append((line, dim))
    # the line under a chain of such dimensions is theirs when they cover it
    for dims in made.values():
        line = dims[0][0]
        a, b = line.points
        L = math.dist(a, b)
        u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        ts = sorted(((d.tip1[0] - a[0]) * u[0] + (d.tip1[1] - a[1]) * u[1],
                     (d.tip2[0] - a[0]) * u[0] + (d.tip2[1] - a[1]) * u[1])
                    for _, d in dims)
        ts = [tuple(sorted(x)) for x in ts]
        ts.sort()
        lo, hi = ts[0]
        whole = True
        for s0, s1 in ts[1:]:
            if s0 > hi + 1.0:
                whole = False
                break
            hi = max(hi, s1)
        if whole and lo <= 1.0 and hi >= L - 1.0:
            line.consumed = True


def _tick_like(items, u: Tuple[float, float]) -> bool:
    """One oblique stroke across the line: an architectural tick."""
    if len(items) != 1 or items[0][0] != "seg":
        return False
    a, b = items[0][1]
    rel = angle_diff_mod180(angle_deg((b[0] - a[0], b[1] - a[1])),
                            angle_deg(u))
    return ATol.TICK_OBLIQUE_LO <= rel <= ATol.TICK_OBLIQUE_HI


def _fallback_groups(ctx: _Context, res: AnnotationResult) -> None:
    """Plain values still free, written along a line with something at its
    ends (arrow, tick, extension line): the dimension could not be rebuilt
    — its value, line and ends are grouped on layer DIM_RAW, so they move
    as one object."""
    free = [t for t in ctx.dim_texts
            if not (text_ids(t) & res.consumed_texts) and is_plain(t.text)
            and not _is_label(ctx, t)]
    if not free:
        return
    ends = _Ends(ctx, res)
    for t in free:
        line = _line_under(ctx, t)
        if line is None:
            continue
        a, b = line.points
        r = max(ATol.END_RADIUS * t.height, 4.0)
        L = math.dist(a, b)
        axis = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        pieces = [ends.at(p, r, line) for p in (a, b)]
        exts = [e for e in (_find_extension(ctx, p, axis) for p in (a, b))
                if e is not None and not e[1].consumed]
        if not any(p[0] for p in pieces) and not exts:
            continue
        group = DimGroup()
        group.texts = list(t.parts) if isinstance(t, CompositeText) else [t]
        group.lines.append(list(line.points))
        group.styles.append(line.style)
        line.consumed = True
        for e in exts:
            group.lines.append(list(e[1].points))
            group.styles.append(e[1].style)
            e[1].consumed = True
        for _items, strokes, fills in pieces:
            for pl, p, q in strokes:
                if not pl.consumed:
                    group.lines.append([p, q])
                    group.styles.append(pl.style)
            ctx.detach(strokes)
            for f in fills:
                if id(f) not in res.consumed_fills:
                    group.fills.append(f)
                    res.consumed_fills.add(id(f))
        res.consumed_texts.update(text_ids(t))
        res.groups.append(group)


def _restore_twins(ctx: _Context, arrows: List[Arrowhead]) -> None:
    """Two open arrows tip to tip drawn as two crossing strokes (an X): when
    only one of them was used, the other one's half strokes are drawn
    again (cutting the X removed them)."""
    for ar in arrows:
        twin = ar.twin
        if ar.used and twin is not None and not twin.used \
                and not twin.restored:
            twin.restored = True
            style = ar.strokes[0][0].style if ar.strokes else None
            if style is None or not twin.v_ends:
                continue
            ctx.add_polyline(EPolyline(points=[twin.v_ends[0], twin.tip,
                                               twin.v_ends[1]],
                                       closed=False, style=style))


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
        _use_terminator(ctx, res, ar)
        res.consumed_texts.add(id(text))
        other = (_opposite_arrow(arrows, ar, center, u, r)
                 if kind == "diameter" else None)
        if other is not None:
            _use_terminator(ctx, res, other)
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
            _use_terminator(ctx, res, x[0])
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
    near = ATol.LEADER_TEXT * ctx.k_at(tail)  # larger where values are
    reach = near + ctx.max_text_len
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
        if d <= min(near, ATol.LEADER_REACH * max(t.height, 1.0)) \
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
    BACK along the arrow axis and never passes beyond the tip. A dot: the
    piece starts at its centre or on its edge."""
    if not ar.has_direction:
        r = ar.length / 2.0
        best, bd = None, 1e18
        for pl, end in index.near(ar.tip[0], ar.tip[1], r + ATol.LEADER_NEAR):
            if pl.consumed:
                continue
            first = pl.points[0] if end == 0 else pl.points[-1]
            second = pl.points[1] if end == 0 else pl.points[-2]
            d = math.dist(first, ar.tip)
            if d > r + ATol.LEADER_NEAR or \
                    math.dist(second, ar.tip) <= d + 0.5:
                continue                          # must leave the dot
            if d < bd:
                best, bd = (pl, end), d
        return best
    base = ar.base()
    best, bd = None, 1e18
    radius = ATol.LEADER_NEAR + ar.length
    own = {frozenset((a, b)) for _, a, b in ar.strokes}
    for pl, end in index.near(ar.tip[0], ar.tip[1], radius):
        if pl.consumed or (len(pl.points) == 2
                           and frozenset(pl.points) in own):
            continue                          # the arrow's own stroke
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


def _ends_at_arrow(ar: Arrowhead, p: Point, tips: "GridIndex",
                   longest: float) -> bool:
    """Does the far end of a leader path touch ANOTHER terminator (its tip
    or its base)? A line with a terminator at each end is a dimension line
    whose value was not recognised, not a leader."""
    for other in tips.near(p[0], p[1], ATol.LEADER_NEAR + longest):
        if other is ar:
            continue
        base = other.base() if other.has_direction else other.tip
        reach = ATol.LEADER_NEAR + (0.0 if other.has_direction
                                    else other.length / 2.0)
        if min(math.dist(p, other.tip), math.dist(p, base)) <= reach:
            return True
    return False


def _leaders(ctx: _Context, arrows: List[Arrowhead],
             res: AnnotationResult) -> None:
    # an open / outline arrow is often joined to its shaft in one polyline
    # (stroke, shaft, landing): its strokes become pieces of their own, so
    # the shaft starts at the tip
    for ar in arrows:
        if not ar.used and ar.strokes:
            ctx.split_out(ar.strokes)
    open_polys = [pl for pl in ctx.rp.polylines
                  if not pl.consumed and not pl.closed and len(pl.points) <= 6]
    end_index: GridIndex[Tuple[EPolyline, int]] = GridIndex(8.0)
    for pl in open_polys:
        for end in (0, -1):
            p = pl.points[end]
            end_index.insert((pl, end), (p[0], p[1], p[0], p[1]))
    heights = [t.height for t in ctx.rp.page.texts] or [2.5]
    usual = statistics.median(heights)
    tips: GridIndex[Arrowhead] = GridIndex(8.0)
    for a in arrows:
        tips.insert(a, (a.tip[0], a.tip[1], a.tip[0], a.tip[1]))
    longest = max((a.length for a in arrows), default=0.0)
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
        if _ends_at_arrow(ar, pts[-1], tips, longest):
            continue                  # arrows at both ends: a dimension line
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
        if not ar.has_direction and length < 4.0 * ar.length:
            continue                                  # a dot on a short line
        for piece in pieces:
            piece.consumed = True
        _use_terminator(ctx, res, ar)
        for t in lines:
            res.consumed_texts.add(id(t))
        res.leaders.append(LeaderEntity(vertices=pts, text=txt, lines=lines,
                                        arrow=ar.length,
                                        arrow_kind=ar.cad_arrow()))


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def reconstruct(rp: RebuiltPage, enable_dims: bool = True,
                enable_leaders: bool = True,
                enable_ticks: bool = True,
                units_per_pt: Optional[float] = None,
                units: str = "mm",
                scale_known: bool = False) -> AnnotationResult:
    """Detect dimensions (radius / diameter, angle / arc length, then linear
    with arrows, dots or ticks, then from the values left) then leaders on
    a page.

    units_per_pt (drawing units per page point) lets an arc length written
    without its "⌒" sign be checked against the drawn arc; with
    scale_known (the scale was read on the sheet or calibrated) it also
    checks the values of linear dimensions."""
    res = AnnotationResult()
    page: PageData = rp.page
    ctx = _Context(rp)
    filled = find_arrowheads(page.fills, ctx.size_at)
    stroked = merge_outlined_fills(filled, find_stroke_arrows(rp.polylines,
                                                              ctx.size_at))
    dots = find_dots(page.fills, ctx.size_at)
    arrows = filled + stroked               # terminators with a direction
    votes = ScaleVotes(units_per_pt, units, scale_known)
    if enable_dims:
        # curved dimensions first: their arrows could otherwise pass for a
        # linear dimension (two nearly opposite arrows on a flat arc)
        _radial_dimensions(ctx, arrows, res)
        _angular_dimensions(ctx, arrows, res, units_per_pt)
        _linear_dimensions(ctx, arrows, dots, res, enable_ticks, votes)
        _consume_chain_lines(ctx, res)
        _learned_dimensions(ctx, res, votes, enable_ticks)
    if enable_leaders:
        _leaders(ctx, arrows + dots, res)
    if enable_dims:
        _fallback_groups(ctx, res)
    _restore_twins(ctx, stroked)
    for t in ctx.dim_texts:
        # unmatched plain measurements only ("L=3500", "2x1500"... are
        # often notes: they stay ordinary texts)
        if text_ids(t) & res.consumed_texts or _is_label(ctx, t) \
                or not DIM_TEXT_RE.match(t.text.strip()):
            continue
        res.dim_raw_texts.extend(t.parts if isinstance(t, CompositeText)
                                 else [t])
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
