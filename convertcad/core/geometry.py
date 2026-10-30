"""
geometry.py — STEP 2: rebuild REAL CAD geometry from raw primitives.

The quality heart of ConvertCAD:
  * cubic Beziers that fit a circle      -> true ARC entities
  * arcs sharing centre + radius         -> merged into one ARC, or a CIRCLE
                                            when they close the full 360 deg
  * remaining Beziers chained end to end -> ONE exact SPLINE per curve
  * touching segments of the same style  -> ONE LWPOLYLINE (not spaghetti)
  * duplicated segments (stroked twice)  -> removed

All maths happen in page coordinates (points, y down); the Y flip to DXF is
done once, in dxf_writer.py. Tolerances live in `Tol` (scaled by the
"curve precision" option: fine 0.5x / normal 1x / loose 2x).
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .extractor import PageData, Point, RawBezier, RawSegment, Style
from .patterns import HatchPattern, detect_hatch_patterns, merge_dashed_lines
from .textures import TextureHatch, detect_textures, snap_boundaries


class Tol:
    """Central tolerances (page points; 1 pt = 0.353 mm on paper)."""
    ARC_FIT_DEV = 0.08       # max deviation Bezier vs fitted arc to accept ARC
    ARC_FIT_REL = 0.004      # ...relaxed proportionally for large radii
    JOIN_DIST = 0.05         # endpoint distance to consider segments connected
    CIRCLE_CENTER = 0.30     # arcs whose centres are this close are merged
    CIRCLE_RADIUS = 0.30     # ...and whose radii differ less than this
    ARC_GAP_DEG = 0.75       # angular gap still considered continuous
    FULL_CIRCLE_DEG = 358.5  # merged sweep >= this becomes a CIRCLE
    COLLINEAR_DEG = 0.5      # angle below which a vertex is redundant
    MAX_ARC_RADIUS = 5000.0  # flatter curves stay splines


# ---------------------------------------------------------------------------
# Rebuilt entity dataclasses (consumed by annotations / blocks / dxf_writer)
# ---------------------------------------------------------------------------
@dataclass
class EArc:
    center: Point
    radius: float
    start_angle: float       # degrees, page convention (y down), CCW a1 -> a2
    end_angle: float
    style: Style
    consumed: bool = False   # True when absorbed by a dimension/leader/block

    @property
    def sweep(self) -> float:
        return (self.end_angle - self.start_angle) % 360.0


@dataclass
class ECircle:
    center: Point
    radius: float
    style: Style
    consumed: bool = False


@dataclass
class EPolyline:
    points: List[Point]
    closed: bool
    style: Style
    consumed: bool = False

    @property
    def is_single_line(self) -> bool:
        return len(self.points) == 2 and not self.closed


@dataclass
class ESpline:
    """A chain of cubic Beziers: 3n+1 control points for n segments."""
    control_points: List[Point]
    style: Style
    consumed: bool = False

    @property
    def segment_count(self) -> int:
        return max(1, (len(self.control_points) - 1) // 3)


@dataclass
class RebuiltPage:
    """Output of this module: clean entities ready for classification."""
    page: PageData
    polylines: List[EPolyline] = field(default_factory=list)
    arcs: List[EArc] = field(default_factory=list)
    circles: List[ECircle] = field(default_factory=list)
    splines: List[ESpline] = field(default_factory=list)
    hatch_patterns: List[HatchPattern] = field(default_factory=list)
    texture_hatches: List[TextureHatch] = field(default_factory=list)
    texture_pieces: int = 0          # dashes and dots they replace
    duplicates_removed: int = 0
    dashed_lines: int = 0            # dashed lines rebuilt from pieces
    dash_pieces: int = 0             # ...pieces they replace
    hatch_segments: int = 0          # segments replaced by pattern hatches

    def all_styles(self) -> List[Style]:
        return ([p.style for p in self.polylines] + [a.style for a in self.arcs]
                + [c.style for c in self.circles]
                + [s.style for s in self.splines]
                + [h.style for h in self.hatch_patterns]
                + [h.style for h in self.texture_hatches])


def style_key(s: Style) -> tuple:
    """Entities only merge when they share this full visual signature."""
    return (s.color, round(s.width, 2), s.linetype, s.dash_pattern,
            s.pdf_layer)


# ---------------------------------------------------------------------------
# Bezier -> Arc fitting
# ---------------------------------------------------------------------------
def _bezier_points(b: RawBezier, n: int = 13) -> np.ndarray:
    t = np.linspace(0.0, 1.0, n)[:, None]
    p0, p1 = np.array(b.p0), np.array(b.p1)
    p2, p3 = np.array(b.p2), np.array(b.p3)
    mt = 1 - t
    return mt**3 * p0 + 3 * mt**2 * t * p1 + 3 * mt * t**2 * p2 + t**3 * p3


def fit_circle(pts: np.ndarray) -> Optional[Tuple[Point, float, float]]:
    """Kasa algebraic circle fit -> (centre, radius, max deviation) or None."""
    x, y = pts[:, 0], pts[:, 1]
    A = np.column_stack([x, y, np.ones(len(x))])
    rhs = x**2 + y**2
    try:
        sol, *_ = np.linalg.lstsq(A, rhs, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx, cy = sol[0] / 2.0, sol[1] / 2.0
    r2 = sol[2] + cx**2 + cy**2
    if r2 <= 0:
        return None
    r = math.sqrt(r2)
    dev = np.abs(np.hypot(x - cx, y - cy) - r)
    return ((float(cx), float(cy)), r, float(dev.max()))


def bezier_to_arc(b: RawBezier, factor: float = 1.0) -> Optional[EArc]:
    """Convert a Bezier to a circular ARC, or None if it is not circular."""
    if math.dist(b.p0, b.p3) < 1e-6:
        return None
    pts = _bezier_points(b)
    fit = fit_circle(pts)
    if fit is None:
        return None
    center, radius, dev = fit
    if radius > Tol.MAX_ARC_RADIUS:
        return None
    if dev > max(Tol.ARC_FIT_DEV, radius * Tol.ARC_FIT_REL) * factor:
        return None
    a1 = math.degrees(math.atan2(b.p0[1] - center[1], b.p0[0] - center[0]))
    a2 = math.degrees(math.atan2(b.p3[1] - center[1], b.p3[0] - center[0]))
    mid = pts[len(pts) // 2]
    am = math.degrees(math.atan2(mid[1] - center[1], mid[0] - center[0]))
    if not _angle_between(a1, am, a2):
        a1, a2 = a2, a1                     # normalize to CCW a1 -> a2
    return EArc(center=center, radius=radius,
                start_angle=a1 % 360.0, end_angle=a2 % 360.0, style=b.style)


def _angle_between(a1: float, am: float, a2: float) -> bool:
    """Is angle am on the CCW sweep from a1 to a2?"""
    sweep = (a2 - a1) % 360.0
    return (am - a1) % 360.0 <= sweep + 1e-6


# ---------------------------------------------------------------------------
# Arcs -> merged arcs / full circles
# ---------------------------------------------------------------------------
class _UF:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, a: int) -> int:
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _merge_intervals(intervals: List[Tuple[float, float]], gap: float
                     ) -> List[Tuple[float, float]]:
    """Union of angular intervals [s, s+sweep] on a 0..360 circle.
    Returns merged (start, sweep) pairs."""
    pieces = []
    for s, sw in intervals:
        s %= 360.0
        e = s + sw
        if e > 360.0:
            pieces += [(s, 360.0), (0.0, e - 360.0)]
        else:
            pieces.append((s, e))
    pieces.sort()
    merged: List[List[float]] = []
    for s, e in pieces:
        if merged and s <= merged[-1][1] + gap:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    # join across 0 degrees
    if len(merged) > 1 and merged[0][0] <= gap and merged[-1][1] >= 360.0 - gap:
        first = merged.pop(0)
        merged[-1][1] = 360.0 + first[1]
    return [(s, e - s) for s, e in merged]


def merge_arcs(arcs: List[EArc]) -> Tuple[List[EArc], List[ECircle]]:
    """Group arcs sharing style, centre and radius; join contiguous pieces
    into single arcs and closed groups into circles. O(n) with a hash grid."""
    if not arcs:
        return [], []
    qc, qr = Tol.CIRCLE_CENTER, Tol.CIRCLE_RADIUS
    buckets: Dict[tuple, List[int]] = {}
    keys = []
    for i, a in enumerate(arcs):
        k = (style_key(a.style), int(math.floor(a.center[0] / qc)),
             int(math.floor(a.center[1] / qc)), int(math.floor(a.radius / qr)))
        keys.append(k)
        buckets.setdefault(k, []).append(i)
    uf = _UF(len(arcs))
    for i, a in enumerate(arcs):
        sk, gx, gy, gr = keys[i]
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dr in (-1, 0, 1):
                    for j in buckets.get((sk, gx + dx, gy + dy, gr + dr), ()):
                        if j <= i:
                            continue
                        b = arcs[j]
                        if (math.dist(a.center, b.center) < qc
                                and abs(a.radius - b.radius) < qr):
                            uf.union(i, j)
    groups: Dict[int, List[int]] = {}
    for i in range(len(arcs)):
        groups.setdefault(uf.find(i), []).append(i)

    out_arcs: List[EArc] = []
    circles: List[ECircle] = []
    for members in groups.values():
        grp = [arcs[k] for k in members]
        if len(grp) == 1:
            out_arcs.append(grp[0])
            continue
        wsum = sum(max(a.sweep, 1e-6) for a in grp)
        cx = sum(a.center[0] * max(a.sweep, 1e-6) for a in grp) / wsum
        cy = sum(a.center[1] * max(a.sweep, 1e-6) for a in grp) / wsum
        r = sum(a.radius * max(a.sweep, 1e-6) for a in grp) / wsum
        merged = _merge_intervals([(a.start_angle, a.sweep) for a in grp],
                                  Tol.ARC_GAP_DEG)
        total = sum(sw for _, sw in merged)
        if total >= Tol.FULL_CIRCLE_DEG:
            circles.append(ECircle(center=(cx, cy), radius=r,
                                   style=grp[0].style))
            continue
        for s, sw in merged:
            out_arcs.append(EArc(center=(cx, cy), radius=r,
                                 start_angle=s % 360.0,
                                 end_angle=(s + sw) % 360.0,
                                 style=grp[0].style))
    return out_arcs, circles


# Backwards-compatible name used by v2 code and tests
merge_arcs_to_circles = merge_arcs


# ---------------------------------------------------------------------------
# Bezier chains -> one spline per continuous curve
# ---------------------------------------------------------------------------
def _qk(p: Point, q: float) -> Tuple[int, int]:
    return (int(math.floor(p[0] / q)), int(math.floor(p[1] / q)))


def _neighbors(p: Point, q: float):
    gx, gy = _qk(p, q)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            yield (gx + dx, gy + dy)


def _take_bezier(tip: Point, index, used: List[bool],
                 group: List[RawBezier], jd: float):
    """Find an unused Bezier of `group` starting or ending at `tip`.

    Returns its 4 control points oriented to start at `tip`, or None.
    """
    for key in _neighbors(tip, jd):
        for idx, end in index.get(key, ()):
            if used[idx]:
                continue
            b = group[idx]
            pts = [b.p0, b.p1, b.p2, b.p3]
            near = b.p0 if end == 0 else b.p3
            if math.dist(near, tip) <= jd:
                used[idx] = True
                return pts if end == 0 else pts[::-1]
    return None


def chain_beziers(beziers: List[RawBezier]) -> List[ESpline]:
    """Join Beziers that share an endpoint and a style into one ESpline."""
    by_style: Dict[tuple, List[RawBezier]] = {}
    for b in beziers:
        by_style.setdefault(style_key(b.style), []).append(b)
    out: List[ESpline] = []
    jd = Tol.JOIN_DIST
    for group in by_style.values():
        index: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
        for i, b in enumerate(group):
            index.setdefault(_qk(b.p0, jd), []).append((i, 0))
            index.setdefault(_qk(b.p3, jd), []).append((i, 1))
        used = [False] * len(group)
        for i, b in enumerate(group):
            if used[i]:
                continue
            used[i] = True
            cps = [b.p0, b.p1, b.p2, b.p3]
            while True:                                  # grow at the tail
                nxt = _take_bezier(cps[-1], index, used, group, jd)
                if nxt is None:
                    break
                cps += nxt[1:]
            while True:                                  # grow at the head
                nxt = _take_bezier(cps[0], index, used, group, jd)
                if nxt is None:
                    break
                cps = nxt[::-1][:-1] + cps
            out.append(ESpline(control_points=cps, style=b.style))
    return out


def _single_splines(beziers: List[RawBezier]) -> List[ESpline]:
    return [ESpline(control_points=[b.p0, b.p1, b.p2, b.p3], style=b.style)
            for b in beziers]


# ---------------------------------------------------------------------------
# Segment chaining -> polylines
# ---------------------------------------------------------------------------
def dedupe_segments(segments: List[RawSegment]) -> Tuple[List[RawSegment], int]:
    """Remove zero-length artefacts and segments drawn twice (same style)."""
    seen = set()
    out = []
    removed = 0
    for s in segments:
        if math.dist(s.p1, s.p2) < 1e-6:
            removed += 1
            continue
        a = (round(s.p1[0], 2), round(s.p1[1], 2))
        b = (round(s.p2[0], 2), round(s.p2[1], 2))
        key = (style_key(s.style),) + ((a, b) if a <= b else (b, a))
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        out.append(s)
    return out, removed


def _dots(segments: List[RawSegment]) -> List[RawSegment]:
    """Zero-length segments (dots of a dotted pattern), one per place."""
    seen = set()
    out = []
    for s in segments:
        if s.p1 == s.p2:
            key = (style_key(s.style), round(s.p1[0], 2), round(s.p1[1], 2))
            if key not in seen:
                seen.add(key)
                out.append(s)
    return out


def chain_segments(segments: List[RawSegment]) -> List[EPolyline]:
    """Join segments sharing endpoints AND style into polylines; merge
    collinear runs; closed chains become closed LWPOLYLINEs."""
    by_style: Dict[tuple, List[RawSegment]] = {}
    for s in segments:
        if math.dist(s.p1, s.p2) < 1e-6:
            continue
        by_style.setdefault(style_key(s.style), []).append(s)
    result: List[EPolyline] = []
    for segs in by_style.values():
        result.extend(_chain_same_style(segs))
    return result


def _chain_same_style(segs: List[RawSegment]) -> List[EPolyline]:
    style = segs[0].style
    jd = Tol.JOIN_DIST
    endpoint_map: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    for idx, s in enumerate(segs):
        endpoint_map.setdefault(_qk(s.p1, jd), []).append((idx, 0))
        endpoint_map.setdefault(_qk(s.p2, jd), []).append((idx, 1))
    used = [False] * len(segs)
    chains: List[EPolyline] = []

    def find_next(tip: Point):
        for key in _neighbors(tip, jd):
            for idx, end in endpoint_map.get(key, ()):
                if used[idx]:
                    continue
                s = segs[idx]
                near, far = (s.p1, s.p2) if end == 0 else (s.p2, s.p1)
                if math.dist(near, tip) <= jd:
                    return idx, far
        return None

    for start in range(len(segs)):
        if used[start]:
            continue
        used[start] = True
        pts: List[Point] = [segs[start].p1, segs[start].p2]
        for head in (False, True):
            while True:
                tip = pts[0] if head else pts[-1]
                nxt = find_next(tip)
                if nxt is None:
                    break
                idx, far = nxt
                used[idx] = True
                if head:
                    pts.insert(0, far)
                else:
                    pts.append(far)
        closed = len(pts) > 3 and math.dist(pts[0], pts[-1]) <= jd
        if closed:
            pts = pts[:-1]
        pts = _collapse_backtracks(pts)
        pts = _merge_collinear(pts, closed)
        if closed and len(pts) < 3:
            closed = False
        if len(pts) >= 2:
            chains.append(EPolyline(points=pts, closed=closed, style=style))
    return chains


def _collapse_backtracks(pts: List[Point]) -> List[Point]:
    """A -> B -> A paths (auto-closed strokes) collapse to a single A -> B."""
    out = [pts[0]]
    for p in pts[1:]:
        if len(out) >= 2 and math.dist(p, out[-2]) <= Tol.JOIN_DIST:
            continue
        out.append(p)
    return out


def _merge_collinear(pts: List[Point], closed: bool) -> List[Point]:
    """Remove intermediate vertices lying on a straight run."""
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = out[-1], pts[i], pts[i + 1]
        ang1 = math.atan2(b[1] - a[1], b[0] - a[0])
        ang2 = math.atan2(c[1] - b[1], c[0] - b[0])
        d = abs((math.degrees(ang2 - ang1) + 180.0) % 360.0 - 180.0)
        if d > Tol.COLLINEAR_DEG:
            out.append(b)
    out.append(pts[-1])
    if closed and len(out) >= 4:            # the wrap-around vertex
        a, b, c = out[-1], out[0], out[1]
        ang1 = math.atan2(b[1] - a[1], b[0] - a[0])
        ang2 = math.atan2(c[1] - b[1], c[0] - b[0])
        d = abs((math.degrees(ang2 - ang1) + 180.0) % 360.0 - 180.0)
        if d <= Tol.COLLINEAR_DEG:
            out = out[1:]
    return out


# ---------------------------------------------------------------------------
# Page-level orchestration
# ---------------------------------------------------------------------------
def rebuild(page: PageData, fit_arcs: bool = True,
            join_polylines: bool = True, join_splines: bool = True,
            precision: float = 1.0, merge_dashes: bool = True,
            hatch_patterns: bool = True) -> RebuiltPage:
    """Run the full geometry rebuild on one extracted page.

    precision: tolerance multiplier (0.5 fine, 1 normal, 2 loose).
    merge_dashes / hatch_patterns: rebuild the dashed lines and the hatch
    patterns that CAD plotters explode into separate segments
    (see patterns.py)."""
    rp = RebuiltPage(page=page)

    # 1. Beziers: try arcs first; leftovers become splines.
    raw_arcs: List[EArc] = []
    leftovers: List[RawBezier] = []
    for b in page.beziers:
        arc = bezier_to_arc(b, precision) if fit_arcs else None
        if arc is not None:
            raw_arcs.append(arc)
        else:
            leftovers.append(b)
    rp.splines = chain_beziers(leftovers) if join_splines \
        else _single_splines(leftovers)

    # 2. Merge arc pieces; close full turns into circles.
    rp.arcs, rp.circles = merge_arcs(raw_arcs)

    # 3. Segments: remove duplicates, rebuild exploded linetypes and hatch
    #    patterns, then chain what is left into polylines.
    segments, rp.duplicates_removed = dedupe_segments(page.segments)
    if hatch_patterns:
        # textures (sand, gravel, brick...) first: their dots and dashes must
        # not become dotted or dashed lines. Dots are zero-length segments.
        dots = _dots(page.segments)
        found = detect_textures(segments + dots)
        segments = [s for s in found.segments if s.p1 != s.p2]
        rp.texture_hatches = found.hatches
        rp.texture_pieces = found.pieces
    if merge_dashes:
        segments, rp.dashed_lines, rp.dash_pieces = \
            merge_dashed_lines(segments)
    if hatch_patterns:
        found = detect_hatch_patterns(segments)
        segments = found.segments
        rp.hatch_patterns = found.hatches
        rp.hatch_segments = found.hatch_segments
    if join_polylines:
        rp.polylines = chain_segments(segments)
    else:
        rp.polylines = [EPolyline(points=[s.p1, s.p2], closed=False,
                                  style=s.style) for s in segments]
    if rp.texture_hatches:
        # the boundary drawn around a texture becomes its hatch boundary
        snap_boundaries(rp.texture_hatches,
                        [pl.points for pl in rp.polylines if pl.closed]
                        + [[(c.center[0] + c.radius * math.cos(a / 18.0
                                                               * math.pi),
                             c.center[1] + c.radius * math.sin(a / 18.0
                                                               * math.pi))
                            for a in range(36)] for c in rp.circles])
    return rp
