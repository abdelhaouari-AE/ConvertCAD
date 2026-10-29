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
from .geometry import EPolyline, RebuiltPage
from .spatial import (GridIndex, angle_deg, angle_diff_mod180,
                      point_line_distance, point_segment_distance)

# Text that *looks like* a measurement: "3500", "3 500", "3.50", "12,5",
# "R25", "Ø60", "45°", "1200 mm"...
DIM_TEXT_RE = re.compile(
    r"^[~±≈ØøR⌀]?\s?"
    r"(?:\d{1,3}(?:[   ]\d{3})+|\d{1,7})"
    r"(?:[.,]\d{1,3})?\s*(?:mm|cm|m|°)?$")


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
class LeaderEntity:
    vertices: List[Point]      # from the arrow tip towards the text
    text: RawText              # the line closest to the landing
    lines: List[RawText] = field(default_factory=list)   # all lines, top
                                                         # to bottom


@dataclass
class AnnotationResult:
    dimensions: List[DimensionEntity] = field(default_factory=list)
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
                enable_ticks: bool = True) -> AnnotationResult:
    """Detect dimensions (arrow + tick styles) then leaders on a page."""
    res = AnnotationResult()
    page: PageData = rp.page
    ctx = _Context(rp)
    arrows = find_arrowheads(page.fills)
    if enable_dims:
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
