"""
terminators.py — the ENDS of dimension and leader lines (used by
annotations.py): filled arrows, outline arrows, open arrows, dots — and any
other small shape repeated at the ends of dimension lines ("learned" from
the sheet: end_shape / similar).

A terminator is found from the PDF primitives; nothing is changed here.
Stroked terminators (open / outline arrows) are often joined by the
geometry step to the line they end (one polyline: stroke, dimension line,
stroke): they keep a reference to the strokes (polyline + the two points of
each segment) so that, when the terminator is used, the strokes can be cut
out of that polyline (annotations._Context.detach).

Sizes follow the drawing: `size_at(point)` gives the usual font size of the
dimension values near a point (so a detail drawn larger next to a small
one keeps its own limits).
"""

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple, Union

from .constants import LAYER_SHX_STROKES
from .extractor import Point, RawFill
from .geometry import EPolyline
from .spatial import GridIndex

SizeAt = Union[float, Callable[[Point], float]]


class TTol:
    """Terminator tolerances (page points, or x the local value size)."""
    ARROW_MAX_AREA = 14.0      # filled triangle area above this -> not an
    ARROW_REL_AREA = 0.35      # arrow, unless below this x (value size)²
    ARROW_MIN_AREA = 0.15      # (arrows up to ~2x the letter height)
    STROKE_MIN = 0.8           # shortest stroke of an open / outline arrow
    STROKE_REL = 1.6           # longest: x the local value size
    STROKE_ABS = 14.0          # ...never less than this
    V_HALF_MIN = 5.0           # open arrow: half opening angle (degrees)
    V_HALF_MAX = 40.0
    V_RATIO = 1.35             # its two strokes have about the same length
    JOIN = 0.3                 # stroke ends meeting at the tip
    DOT_MIN = 0.6              # dot diameter
    DOT_REL = 0.9              # ...at most x the local value size
    DOT_ABS = 6.0              # ...never less than this


@dataclass
class Arrowhead:
    """Any terminator. `direction` points from the base to the tip, (0, 0)
    for a dot. `length` is base -> tip (a dot: its diameter)."""
    tip: Point
    direction: Tuple[float, float]
    fill: Optional[RawFill] = None
    used: bool = False
    length: float = 0.0
    kind: str = "filled"       # filled | blank | open | dot | learned
    # stroked terminators: (polyline, a, b) for each segment a-b drawn
    strokes: List[Tuple[EPolyline, Point, Point]] = field(default_factory=list)
    half_angle: float = 0.0    # open arrows: half opening angle, degrees
    extra_fills: List[RawFill] = field(default_factory=list)
    # two open arrows tip to tip drawn as one X: each one knows the other
    # and the ends of its own V (to draw it again if only one is used)
    twin: Optional["Arrowhead"] = field(default=None, repr=False)
    v_ends: Tuple[Point, ...] = ()
    restored: bool = False

    @property
    def has_direction(self) -> bool:
        return self.kind != "dot"

    def base(self) -> Point:
        return (self.tip[0] - self.direction[0] * self.length,
                self.tip[1] - self.direction[1] * self.length)

    def cad_arrow(self) -> str:
        """ezdxf / AutoCAD arrow block name for this terminator."""
        if self.kind == "blank":
            return "CLOSEDBLANK"
        if self.kind == "dot":
            return "DOT"
        if self.kind == "open":
            # AutoCAD: _OPEN 9.5°, _OPEN30 15°, _OPEN90 45° (half angles)
            return min((("OPEN", 9.5), ("OPEN30", 15.0), ("OPEN90", 45.0)),
                       key=lambda x: abs(x[1] - self.half_angle))[0]
        if self.kind == "learned":
            return "NONE"
        return ""                                   # closed filled


def _size(size_at: SizeAt, p: Point) -> float:
    return size_at(p) if callable(size_at) else float(size_at or 0.0)


def polygon_area(pts: List[Point]) -> float:
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def dedupe(pts: List[Point], tol: float = 0.05) -> List[Point]:
    out: List[Point] = []
    for p in pts:
        if all(math.dist(p, q) > tol for q in out):
            out.append(p)
    return out


def _triangle_arrow(pts: List[Point], max_area: float):
    """(tip, direction, length) of an arrow-shaped triangle (or 4-gon),
    None when it is not one: small, clearly longer than wide."""
    area = polygon_area(pts)
    if not TTol.ARROW_MIN_AREA <= area <= max_area:
        return None
    best_tip, best_d, best_base = None, -1.0, (0.0, 0.0)
    for i, p in enumerate(pts):
        others = [q for j, q in enumerate(pts) if j != i]
        bx = sum(q[0] for q in others) / len(others)
        by = sum(q[1] for q in others) / len(others)
        d = math.dist(p, (bx, by))
        if d > best_d:
            best_tip, best_d, best_base = p, d, (bx, by)
    if best_d < 1e-6:
        return None
    base_w = 2.0 * area / best_d
    if best_d < 1.2 * base_w:                  # longer than wide
        return None
    return best_tip, ((best_tip[0] - best_base[0]) / best_d,
                      (best_tip[1] - best_base[1]) / best_d), best_d


def max_arrow_area(value_size: float) -> float:
    return max(TTol.ARROW_MAX_AREA, TTol.ARROW_REL_AREA * value_size ** 2)


def find_arrowheads(fills: List[RawFill], size_at: SizeAt = 0.0
                    ) -> List[Arrowhead]:
    """Small filled triangles are arrowheads; tip = the sharpest vertex.
    The largest arrow accepted grows with the value size near it."""
    arrows: List[Arrowhead] = []
    for f in fills:
        if len(f.points) > 12 or f.background:
            continue
        pts = dedupe(f.points)
        if not 3 <= len(pts) <= 4:
            continue
        c = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        hit = _triangle_arrow(pts, max_arrow_area(_size(size_at, c)))
        if hit is None:
            continue
        tip, direction, length = hit
        arrows.append(Arrowhead(tip=tip, direction=direction, fill=f,
                                length=length))
    return arrows


def find_dots(fills: List[RawFill], size_at: SizeAt = 0.0) -> List[Arrowhead]:
    """Small filled discs (dot terminators): round, centred on the line."""
    dots: List[Arrowhead] = []
    for f in fills:
        if len(f.points) < 8 or f.background:
            continue
        pts = f.points
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
        rs = [math.dist(p, (cx, cy)) for p in pts]
        r = sum(rs) / len(rs)
        if r <= 0 or max(rs) - min(rs) > 0.2 * r:
            continue
        if abs(f.area - math.pi * r * r) > 0.2 * math.pi * r * r:
            continue
        s = _size(size_at, (cx, cy))
        if not TTol.DOT_MIN <= 2 * r <= max(TTol.DOT_ABS, TTol.DOT_REL * s):
            continue
        dots.append(Arrowhead(tip=(cx, cy), direction=(0.0, 0.0), fill=f,
                              length=2 * r, kind="dot"))
    return dots


def _segments(polylines: List[EPolyline]):
    """Every segment of the unconsumed polylines (letter strokes of SHX
    texts excluded): (polyline, a, b, length)."""
    for pl in polylines:
        if pl.consumed or pl.style.pdf_layer == LAYER_SHX_STROKES:
            continue
        pts = pl.points
        pairs = list(zip(pts, pts[1:]))
        if pl.closed and len(pts) > 2:
            pairs.append((pts[-1], pts[0]))
        for a, b in pairs:
            L = math.dist(a, b)
            if L > 1e-9:
                yield pl, a, b, L


def find_stroke_arrows(polylines: List[EPolyline], size_at: SizeAt = 0.0
                       ) -> List[Arrowhead]:
    """Open arrows (two short strokes meeting at the tip, a V) and outline
    arrows (three short strokes closing a thin triangle). At the joint of a
    chain, the strokes of two open arrows tip to tip often come as two
    straight lines crossing (an X): two arrows."""
    short, lims = [], []
    for pl, a, b, L in _segments(polylines):
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        lim = max(TTol.STROKE_ABS, TTol.STROKE_REL * _size(size_at, mid))
        if TTol.STROKE_MIN <= L <= 2.0 * lim:      # X strokes: two long
            short.append((pl, a, b, L))
            lims.append(lim)
    if not short:
        return []
    ends: GridIndex[Tuple[int, int]] = GridIndex(4.0)
    mids: GridIndex[int] = GridIndex(4.0)
    for k, (_pl, a, b, L) in enumerate(short):
        if L <= lims[k]:
            ends.insert((k, 0), (a[0], a[1], a[0], a[1]))
            ends.insert((k, 1), (b[0], b[1], b[0], b[1]))
        m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        mids.insert(k, (m[0], m[1], m[0], m[1]))
    out: List[Arrowhead] = []
    seen_pairs: set = set()
    # --- V: two strokes sharing an end -----------------------------------
    for k, (pl, a, b, L) in enumerate(short):
        if L > lims[k]:
            continue
        for end, p in ((0, a), (1, b)):
            for j, e2 in ends.near(p[0], p[1], TTol.JOIN):
                if j <= k:
                    continue
                q = short[j][1] if e2 == 0 else short[j][2]
                if math.dist(p, q) > TTol.JOIN:
                    continue
                key = (k, j, round(p[0], 1), round(p[1], 1))
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                far_k = b if end == 0 else a
                far_j = short[j][2] if e2 == 0 else short[j][1]
                hit = _v_arrow(p, far_k, far_j)
                if hit is None:
                    continue
                direction, length, half = hit
                strokes = [(pl, a, b), (short[j][0], short[j][1], short[j][2])]
                # a third stroke closing the V: an outline arrow
                closing = _closing(short, ends, far_k, far_j)
                if closing is not None:
                    tri = [p, far_k, far_j]
                    t_hit = _triangle_arrow(tri, max_arrow_area(
                        _size(size_at, p)))
                    if t_hit is not None and math.dist(t_hit[0], p) < 1e-6:
                        out.append(Arrowhead(
                            tip=p, direction=t_hit[1], length=t_hit[2],
                            kind="blank",
                            strokes=strokes + [closing]))
                    continue
                out.append(Arrowhead(tip=p, direction=direction,
                                     length=length, kind="open",
                                     strokes=strokes, half_angle=half))
    # --- X: two strokes crossing at their middles -------------------------
    for k, (pl, a, b, L) in enumerate(short):
        mk = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        for j in mids.near(mk[0], mk[1], TTol.JOIN + 0.2):
            if j <= k:
                continue
            pl2, c, d, L2 = short[j]
            mj = ((c[0] + d[0]) / 2, (c[1] + d[1]) / 2)
            if math.dist(mk, mj) > TTol.JOIN + 0.2 or \
                    max(L, L2) > TTol.V_RATIO * min(L, L2):
                continue
            p = ((mk[0] + mj[0]) / 2, (mk[1] + mj[1]) / 2)
            for f1, f2 in ((a, c), (a, d)):        # the two acute halves
                g1 = (2 * p[0] - f1[0], 2 * p[1] - f1[1])
                g2 = (2 * p[0] - f2[0], 2 * p[1] - f2[1])
                h1, h2 = _v_arrow(p, f1, f2), _v_arrow(p, g1, g2)
                if h1 is None or h2 is None:
                    continue
                strokes = [(pl, a, b), (pl2, c, d)]
                pair = []
                for hit, v in ((h1, (f1, f2)), (h2, (g1, g2))):
                    direction, length, half = hit
                    pair.append(Arrowhead(tip=p, direction=direction,
                                          length=length, kind="open",
                                          strokes=strokes, half_angle=half,
                                          v_ends=v))
                pair[0].twin, pair[1].twin = pair[1], pair[0]
                out.extend(pair)
                break
    return _dedupe_terminators(out)


def _v_arrow(p: Point, f1: Point, f2: Point):
    """(direction, length, half angle) of an open arrow with tip p and
    stroke ends f1, f2; None when it is not one."""
    v1 = (f1[0] - p[0], f1[1] - p[1])
    v2 = (f2[0] - p[0], f2[1] - p[1])
    l1, l2 = math.hypot(*v1), math.hypot(*v2)
    if min(l1, l2) < TTol.STROKE_MIN or \
            max(l1, l2) > TTol.V_RATIO * min(l1, l2):
        return None
    cosang = (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)
    half = math.degrees(math.acos(max(-1.0, min(1.0, cosang)))) / 2.0
    if not TTol.V_HALF_MIN <= half <= TTol.V_HALF_MAX:
        return None
    bx, by = v1[0] / l1 + v2[0] / l2, v1[1] / l1 + v2[1] / l2
    n = math.hypot(bx, by)
    if n < 1e-9:
        return None
    length = (l1 + l2) / 2.0 * math.cos(math.radians(half))
    return (-bx / n, -by / n), length, half


def _closing(short, ends, f1: Point, f2: Point):
    """The short stroke joining f1 and f2 (third side of a triangle)."""
    for j, e in ends.near(f1[0], f1[1], TTol.JOIN):
        pl, a, b, L = short[j]
        p, q = (a, b) if e == 0 else (b, a)
        if math.dist(p, f1) <= TTol.JOIN and math.dist(q, f2) <= TTol.JOIN:
            return (pl, a, b)
    return None


def _dedupe_terminators(arrows: List[Arrowhead]) -> List[Arrowhead]:
    out: List[Arrowhead] = []
    for ar in arrows:
        dup = False
        for o in out:
            if math.dist(o.tip, ar.tip) < 0.3 and \
                    o.direction[0] * ar.direction[0] \
                    + o.direction[1] * ar.direction[1] > 0.95:
                if ar.kind == "blank" and o.kind == "open":
                    o.kind, o.strokes = "blank", ar.strokes   # the closed one
                dup = True
                break
        if not dup:
            out.append(ar)
    return out


def merge_outlined_fills(filled: List[Arrowhead], stroked: List[Arrowhead]
                         ) -> List[Arrowhead]:
    """A filled arrow drawn with an outline too: one arrow (the outline
    strokes are consumed with it). Returns the stroked arrows left."""
    if not filled or not stroked:
        return stroked
    index: GridIndex[Arrowhead] = GridIndex(4.0)
    for a in filled:
        index.insert(a, (a.tip[0], a.tip[1], a.tip[0], a.tip[1]))
    left = []
    for s in stroked:
        twin = None
        for a in index.near(s.tip[0], s.tip[1], 0.6):
            if a.direction[0] * s.direction[0] + \
                    a.direction[1] * s.direction[1] > 0.9:
                twin = a
                break
        if twin is not None and s.kind == "blank":
            twin.strokes.extend(s.strokes)
        else:
            left.append(s)
    return left


# ---------------------------------------------------------------------------
# Shapes learned from the sheet
# ---------------------------------------------------------------------------
GRID = 7


def end_shape(items: List[Tuple[str, object]], end: Point,
              inward: Tuple[float, float], r: float) -> frozenset:
    """Signature of the small shape at a line end: the cells of a GRID x
    GRID grid (radius r around the end, x axis pointing into the line)
    touched by its strokes and fills. Two ends with the same terminator
    give the same signature, whatever the line direction."""
    ux, uy = inward
    vx, vy = -uy, ux
    cells = set()

    def mark(p: Point):
        dx, dy = p[0] - end[0], p[1] - end[1]
        x, y = dx * ux + dy * uy, dx * vx + dy * vy
        i = int((x / r + 1.0) / 2.0 * GRID)
        j = int((y / r + 1.0) / 2.0 * GRID)
        if 0 <= i < GRID and 0 <= j < GRID:
            cells.add((i, j))

    for kind, obj in items:
        if kind == "seg":
            a, b = obj
            n = max(2, int(math.dist(a, b) / (r / GRID * 0.5)) + 1)
            for k in range(n + 1):
                mark((a[0] + (b[0] - a[0]) * k / n,
                      a[1] + (b[1] - a[1]) * k / n))
        else:                                      # a fill: outline + inside
            pts = obj.points
            for p, q in zip(pts, pts[1:] + pts[:1]):
                n = max(2, int(math.dist(p, q) / (r / GRID * 0.5)) + 1)
                for k in range(n + 1):
                    mark((p[0] + (q[0] - p[0]) * k / n,
                          p[1] + (q[1] - p[1]) * k / n))
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            mark(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))
    return frozenset(cells)


def similar(a: frozenset, b: frozenset) -> float:
    """Similarity of two shape signatures (0..1): the share of cells of
    each that the other has too, or in a neighbouring cell (a shape drawn
    a fraction of a cell aside is the same shape)."""
    if not a or not b:
        return 0.0

    def matched(x, y):
        return sum(1 for i, j in x
                   if any(abs(i - k) <= 1 and abs(j - m) <= 1 for k, m in y))
    return (matched(a, b) + matched(b, a)) / (len(a) + len(b))


def mirrored(sig: frozenset) -> frozenset:
    """The same signature seen in a mirror (across the line)."""
    return frozenset((i, GRID - 1 - j) for i, j in sig)


def best_similarity(a: frozenset, b: frozenset) -> float:
    return max(similar(a, b), similar(a, mirrored(b)))


def size_lookup(cache: Dict[Tuple[int, int], float], cell: float,
                compute: Callable[[Point], float]) -> Callable[[Point], float]:
    """Memoised size_at(point) by grid cell."""
    def size_at(p: Point) -> float:
        key = (int(p[0] // cell), int(p[1] // cell))
        v = cache.get(key)
        if v is None:
            v = cache[key] = compute(((key[0] + 0.5) * cell,
                                      (key[1] + 0.5) * cell))
        return v
    return size_at
