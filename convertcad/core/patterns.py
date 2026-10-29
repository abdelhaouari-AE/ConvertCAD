"""
patterns.py — rebuild what CAD programs EXPLODE when they print to PDF.

AutoCAD (and most CAD programs) do not keep linetypes and hatch patterns
when they plot a drawing to PDF:
  * a dashed axis arrives as hundreds of tiny separate segments,
  * a hatch arrives as hundreds of separate parallel lines.
Converted naively, a single sheet gives 100 000 loose LINE entities, a heavy
file and a slow preview. This module puts them back together:

  merge_dashed_lines()     collinear pieces with a regular gap pattern
                           -> ONE line carrying a linetype (CENTER, DASHED,
                              DOT...) whose dash lengths are measured on the
                              PDF, so it looks exactly like the original
  detect_hatch_patterns()  families of equally spaced parallel lines
                           -> ONE pattern HATCH (angle, spacing, boundary)

SAFE BY DESIGN: a group is rebuilt only when every regularity test passes;
otherwise its segments are returned untouched. All coordinates are page
points (y down), like the rest of the engine.
"""

import math
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple

from .extractor import Point, RawSegment, Style
from .spatial import GridIndex


class PTol:
    """Tolerances (page points; 1 pt = 0.353 mm on paper)."""
    # ---- dashed lines ----
    MAX_PIECE = 40.0         # a dash longer than this is a real line
    MAX_GAP = 9.0            # gap between dashes (3 mm on paper)
    MIN_GAP = 0.05
    OFFSET_TOL = 0.12        # pieces of one line lie this close to its axis
    ANGLE_STEP = 0.5         # angle bucket (degrees)
    DOT_LEN = 0.25           # a piece shorter than this is a dot
    GAP_REL = 0.45           # gaps may vary +-45 % around their median
    MIN_PIECES = 3
    # ---- hatch patterns ----
    MIN_SPACING = 0.6
    MAX_SPACING = 30.0       # 10 mm on paper
    SPACING_REL = 0.12       # spacing regularity (+-12 %)
    MIN_ROWS_OBLIQUE = 6     # 45 deg hatching: 6 parallel rows are enough
    MIN_ROWS_AXIS = 12       # horizontal / vertical rows: stairs, gratings
                             # and racks look alike, so ask for more...
    MIN_GRID_ROWS = 5        # ...unless rows cross rows at 90 deg (a grid)
    MIN_HATCH_LINE = 0.5     # ignore crumbs
    ROW_TOL = 0.15           # lines of one row share their offset


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
@dataclass
class HatchPattern:
    """A family of parallel lines rebuilt as one pattern hatch."""
    style: Style
    angle: float                     # direction of the lines, page degrees
    spacing: float                   # distance between lines (pt)
    origin: Point                    # a point on one of the lines
    boundary: List[Point]            # outer polygon (page coords)
    holes: List[List[Point]] = field(default_factory=list)
    line_count: int = 0              # PDF segments replaced


@dataclass
class PatternResult:
    segments: List[RawSegment]       # what is left (+ rebuilt dashed lines)
    hatches: List[HatchPattern] = field(default_factory=list)
    dashed_lines: int = 0
    dash_pieces: int = 0
    hatch_segments: int = 0


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _base_key(s: Style) -> tuple:
    return (s.color, round(s.width, 2), s.pdf_layer)


def _axis(angle_deg: float):
    a = math.radians(angle_deg)
    u = (math.cos(a), math.sin(a))
    n = (-u[1], u[0])
    return u, n


def _dot(p, v) -> float:
    return p[0] * v[0] + p[1] * v[1]


def _line_angle(p: Point, q: Point) -> float:
    return math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 180.0


def _median(values: List[float]) -> float:
    v = sorted(values)
    n = len(v)
    if n == 0:
        return 0.0
    return v[n // 2] if n % 2 else 0.5 * (v[n // 2 - 1] + v[n // 2])


# ---------------------------------------------------------------------------
# Dashed lines
# ---------------------------------------------------------------------------
@dataclass
class _Piece:
    t0: float
    t1: float
    seg: Optional[RawSegment]
    d: float                         # offset of the piece's axis
    dot_idx: int = -1                # index in the dot list (dots only)


def _classify_pattern(lengths: List[float], gaps: List[float]
                      ) -> Optional[Tuple[str, Tuple[float, ...]]]:
    """(family, one period [dash, -gap, ...]) or None when irregular.

    `lengths` are the INTERIOR pieces (first/last may be cut short)."""
    gap = _median(gaps)
    if not lengths:
        return None
    tol = lambda x: 0.18 + 0.12 * x                          # noqa: E731
    period = 0
    for p in (1, 2, 3, 4):
        if len(lengths) < p + 1 and p > 1:
            break
        if all(abs(lengths[i] - lengths[i + p]) <= tol(max(lengths[i],
                                                             lengths[i + p]))
               for i in range(len(lengths) - p)):
            period = p
            break
    if not period:
        return None
    unit = lengths[:period]
    k = unit.index(max(unit))                 # start with the longest dash
    unit = unit[k:] + unit[:k]
    unit = [0.0 if v < PTol.DOT_LEN else v for v in unit]
    elements: List[float] = []
    for v in unit:
        elements += [round(v, 3), -round(gap, 3)]
    dots = sum(1 for v in unit if v == 0.0)
    if period == 1:
        family = "DOT" if dots else "DASHED"
    elif period == 2:
        family = "DASHDOT" if dots else "CENTER"
    else:
        family = "DIVIDE" if dots else "PHANTOM"
    if dots == len(unit):
        family = "DOT"
    return family, tuple(elements)


def _validate_run(run: List[_Piece]):
    """Regularity tests on a candidate run -> pattern or None."""
    if len(run) < PTol.MIN_PIECES:
        return None
    gaps = [b.t0 - a.t1 for a, b in zip(run, run[1:])]
    if min(gaps) < PTol.MIN_GAP or max(gaps) > PTol.MAX_GAP:
        return None
    g = _median(gaps)
    lo, hi = g * (1 - PTol.GAP_REL), g * (1 + PTol.GAP_REL) + 0.1
    if sum(1 for x in gaps if lo <= x <= hi) < 0.85 * len(gaps):
        return None
    lengths = [p.t1 - p.t0 for p in run]
    interior = lengths[1:-1] if len(lengths) > 3 else lengths
    if any(v > PTol.MAX_PIECE for v in lengths):
        return None
    return _classify_pattern(interior, gaps)


def _split_runs(pieces: List[_Piece]) -> List[List[_Piece]]:
    """Consecutive pieces along one axis, cut where the gap is too large
    or the pieces overlap."""
    pieces.sort(key=lambda p: p.t0)
    runs, cur = [], [pieces[0]]
    for p in pieces[1:]:
        gap = p.t0 - cur[-1].t1
        if PTol.MIN_GAP <= gap <= PTol.MAX_GAP:
            cur.append(p)
        else:
            runs.append(cur)
            cur = [p]
    runs.append(cur)
    return runs


def merge_dashed_lines(segments: List[RawSegment]
                       ) -> Tuple[List[RawSegment], int, int]:
    """Returns (segments with dashed runs merged, lines made, pieces used)."""
    out: List[RawSegment] = []
    made = used = 0
    groups: Dict[tuple, List[RawSegment]] = {}
    for s in segments:
        L = math.dist(s.p1, s.p2)
        if s.style.linetype != "CONTINUOUS" or L > PTol.MAX_PIECE:
            out.append(s)
        else:
            groups.setdefault(_base_key(s.style), []).append(s)
    style_cache: Dict[tuple, Style] = {}
    for segs in groups.values():
        merged_ids = set()
        dots = [s for s in segs if math.dist(s.p1, s.p2) < PTol.DOT_LEN]
        dot_index: GridIndex[int] = GridIndex(PTol.MAX_GAP)
        dot_used = [False] * len(dots)
        for k, s in enumerate(dots):
            c = ((s.p1[0] + s.p2[0]) / 2, (s.p1[1] + s.p2[1]) / 2)
            dot_index.insert(k, (c[0], c[1], c[0], c[1]))
        # --- 1. oriented pieces grouped by angle, then by axis offset ----------
        by_angle: Dict[int, List[RawSegment]] = {}
        for s in segs:
            if math.dist(s.p1, s.p2) >= PTol.DOT_LEN:
                b = int(round(_line_angle(s.p1, s.p2) / PTol.ANGLE_STEP)) \
                    % int(180 / PTol.ANGLE_STEP)
                by_angle.setdefault(b, []).append(s)
        for b, items in by_angle.items():
            angle = b * PTol.ANGLE_STEP
            u, n = _axis(angle)
            rows = sorted((((_dot(s.p1, n) + _dot(s.p2, n)) / 2, id(s), s)
                           for s in items), key=lambda r: (r[0], r[1]))
            k = 0
            while k < len(rows):
                j = k + 1
                while j < len(rows) and rows[j][0] - rows[j - 1][0] \
                        <= PTol.OFFSET_TOL:
                    j += 1
                axis_items = [r[2] for r in rows[k:j]]
                d = sum(r[0] for r in rows[k:j]) / (j - k)
                k = j
                if len(axis_items) < 2:
                    continue
                pieces = []
                for s in axis_items:
                    t0, t1 = sorted((_dot(s.p1, u), _dot(s.p2, u)))
                    pieces.append(_Piece(t0, t1, s, d))
                # dots lying on this axis
                lo = min(p.t0 for p in pieces) - PTol.MAX_GAP
                hi = max(p.t1 for p in pieces) + PTol.MAX_GAP
                corners = [(u[0] * t + n[0] * d, u[1] * t + n[1] * d)
                           for t in (lo, hi)]
                for idx in dot_index.query(
                        min(c[0] for c in corners) - 1,
                        min(c[1] for c in corners) - 1,
                        max(c[0] for c in corners) + 1,
                        max(c[1] for c in corners) + 1):
                    if dot_used[idx]:
                        continue
                    s = dots[idx]
                    c = ((s.p1[0] + s.p2[0]) / 2, (s.p1[1] + s.p2[1]) / 2)
                    if abs(_dot(c, n) - d) <= PTol.OFFSET_TOL:
                        t = _dot(c, u)
                        if lo <= t <= hi:
                            pieces.append(_Piece(t, t, s, d, idx))
                            dot_used[idx] = True
                for run in _split_runs(pieces):
                    pat = _validate_run(run)
                    if pat is None:
                        for p in run:              # dots go back to the pool
                            if p.dot_idx >= 0:
                                dot_used[p.dot_idx] = False
                        continue
                    family, elements = pat
                    st0 = run[0].seg.style
                    key = (id(st0), family, elements)
                    st = style_cache.get(key)
                    if st is None:
                        st = replace(st0, dashed=True, linetype=family,
                                     dash_pattern="pt:" + ",".join(
                                         f"{v:g}" for v in elements))
                        style_cache[key] = st
                    a = (u[0] * run[0].t0 + n[0] * d,
                         u[1] * run[0].t0 + n[1] * d)
                    z = (u[0] * run[-1].t1 + n[0] * d,
                         u[1] * run[-1].t1 + n[1] * d)
                    out.append(RawSegment(a, z, st))
                    made += 1
                    used += len(run)
                    merged_ids.update(id(p.seg) for p in run)
        # --- 2. lines made of dots only ------------------------------------------
        made_d, used_d, dot_lines = _dotted_lines(dots, dot_used, dot_index,
                                                  style_cache)
        made += made_d
        used += used_d
        out.extend(dot_lines)
        for k, s in enumerate(dots):
            if dot_used[k]:
                merged_ids.add(id(s))
        out.extend(s for s in segs if id(s) not in merged_ids)
    return out, made, used


def _dotted_lines(dots, dot_used, dot_index, style_cache):
    """Chains of equally spaced dots -> dotted lines (DOT linetype)."""
    made = used = 0
    out: List[RawSegment] = []
    centers = [((s.p1[0] + s.p2[0]) / 2, (s.p1[1] + s.p2[1]) / 2)
               for s in dots]

    def nearest(c, exclude, radius):
        best, bd = None, radius
        for idx in dot_index.near(c[0], c[1], radius):
            if dot_used[idx] or idx in exclude:
                continue
            dd = math.dist(c, centers[idx])
            if PTol.MIN_GAP < dd <= bd:
                best, bd = idx, dd
        return best, bd

    for seed in range(len(dots)):
        if dot_used[seed]:
            continue
        nb, gap = nearest(centers[seed], {seed}, PTol.MAX_GAP)
        if nb is None:
            continue
        a, b = centers[seed], centers[nb]
        u = ((b[0] - a[0]) / gap, (b[1] - a[1]) / gap)
        chain = [seed, nb]
        for direction in (1, -1):
            cur = chain[-1] if direction == 1 else chain[0]
            while True:
                c = centers[cur]
                expect = (c[0] + direction * u[0] * gap,
                          c[1] + direction * u[1] * gap)
                best, bd = None, 0.3 * gap + 0.05
                for idx in dot_index.near(expect[0], expect[1], bd):
                    if dot_used[idx] or idx in chain:
                        continue
                    dd = math.dist(expect, centers[idx])
                    if dd <= bd:
                        best, bd = idx, dd
                if best is None:
                    break
                if direction == 1:
                    chain.append(best)
                else:
                    chain.insert(0, best)
                cur = best
        if len(chain) < 4:
            continue
        st0 = dots[seed].style
        elements = (0.0, -round(gap, 3))
        key = (id(st0), "DOT", elements)
        st = style_cache.get(key)
        if st is None:
            st = replace(st0, dashed=True, linetype="DOT",
                         dash_pattern="pt:" + ",".join(f"{v:g}"
                                                       for v in elements))
            style_cache[key] = st
        out.append(RawSegment(centers[chain[0]], centers[chain[-1]], st))
        for idx in chain:
            dot_used[idx] = True
        made += 1
        used += len(chain)
    return made, used, out


def parse_dash_pattern(text: str) -> Tuple[float, ...]:
    """'pt:1.95,-1.05,0,-1.05' -> (1.95, -1.05, 0.0, -1.05) (page points)."""
    if not text or not text.startswith("pt:"):
        return ()
    try:
        return tuple(float(v) for v in text[3:].split(",") if v)
    except ValueError:
        return ()


# ---------------------------------------------------------------------------
# Hatch patterns
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


def _is_axis_aligned(angle: float) -> bool:
    a = angle % 90.0
    return a < 3.0 or a > 87.0


def detect_hatch_patterns(segments: List[RawSegment]) -> PatternResult:
    """Find hatch families; returns the remaining segments + the hatches."""
    keep: List[RawSegment] = []
    families: Dict[tuple, List[RawSegment]] = {}
    for s in segments:
        if s.style.linetype != "CONTINUOUS" or \
                math.dist(s.p1, s.p2) < PTol.MIN_HATCH_LINE:
            keep.append(s)
            continue
        b = int(round(_line_angle(s.p1, s.p2) / PTol.ANGLE_STEP)) \
            % int(180 / PTol.ANGLE_STEP)
        families.setdefault((_base_key(s.style), b), []).append(s)
    res = PatternResult(segments=keep)
    consumed: set = set()
    grid_candidates: List[tuple] = []     # (style key, hatch, segment ids)
    for (skey, b), segs in families.items():
        if len(segs) < PTol.MIN_GRID_ROWS:
            continue
        _hatch_family(segs, b * PTol.ANGLE_STEP, skey, res, consumed,
                      grid_candidates)
    _pair_grids(grid_candidates, res, consumed)
    for segs in families.values():
        keep.extend(s for s in segs if id(s) not in consumed)
    return res


def _bbox(points: List[Point]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _pair_grids(cands: List[tuple], res: PatternResult,
                consumed: set) -> None:
    """Horizontal + vertical rows over the same area = a grid hatch (grating,
    net, square pattern): accepted even with few rows, because stairs and
    racks, the usual false alarms, have rows in one direction only."""
    used = [False] * len(cands)
    for i, (ki, hi, ids_i) in enumerate(cands):
        if used[i]:
            continue
        bi = _bbox(hi.boundary)
        for j in range(i + 1, len(cands)):
            kj, hj, ids_j = cands[j]
            if used[j] or kj != ki:
                continue
            if abs(abs(hi.angle - hj.angle) - 90.0) > 1.0:
                continue
            bj = _bbox(hj.boundary)
            ix = min(bi[2], bj[2]) - max(bi[0], bj[0])
            iy = min(bi[3], bj[3]) - max(bi[1], bj[1])
            if ix <= 0 or iy <= 0:
                continue
            inter = ix * iy
            area = min((bi[2] - bi[0]) * (bi[3] - bi[1]),
                       (bj[2] - bj[0]) * (bj[3] - bj[1]))
            if area > 0 and inter >= 0.7 * area:
                for h, ids in ((hi, ids_i), (hj, ids_j)):
                    res.hatches.append(h)
                    res.hatch_segments += h.line_count
                    consumed.update(ids)
                used[i] = used[j] = True
                break


def _hatch_family(segs: List[RawSegment], angle: float, skey: tuple,
                  res: PatternResult, consumed: set,
                  grid_candidates: List[tuple]) -> None:
    """Union neighbouring rows of one family; validate every component."""
    u, n = _axis(angle)
    items = []
    for s in segs:
        d = (_dot(s.p1, n) + _dot(s.p2, n)) / 2
        t0, t1 = sorted((_dot(s.p1, u), _dot(s.p2, u)))
        items.append((d, t0, t1, s))
    items.sort(key=lambda it: it[0])
    uf = _UF(len(items))
    for i, (d, t0, t1, _) in enumerate(items):
        best_j, best_dd = -1, PTol.MAX_SPACING + 1
        checked = 0
        for j in range(i + 1, len(items)):
            dj, u0, u1, _ = items[j]
            dd = dj - d
            if dd > PTol.MAX_SPACING or checked > 400:
                break
            checked += 1
            if dd <= PTol.ROW_TOL:                  # same row, other piece
                continue
            if dd < PTol.MIN_SPACING or dd > best_dd + PTol.ROW_TOL:
                continue
            overlap = min(t1, u1) - max(t0, u0)
            if overlap >= 0.3 * min(t1 - t0, u1 - u0):
                if dd < best_dd:
                    best_j, best_dd = j, dd
        if best_j >= 0:
            uf.union(i, best_j)
    comps: Dict[int, List[int]] = {}
    for i in range(len(items)):
        comps.setdefault(uf.find(i), []).append(i)
    axis = _is_axis_aligned(angle)
    for members in comps.values():
        if len(members) < PTol.MIN_GRID_ROWS:
            continue
        group = [items[k] for k in members]
        ids = {id(items[k][3]) for k in members}
        hatch = _build_hatch(group, angle, u, n,
                             PTol.MIN_ROWS_AXIS if axis
                             else PTol.MIN_ROWS_OBLIQUE)
        if hatch is not None:
            res.hatches.append(hatch)
            res.hatch_segments += hatch.line_count
            consumed.update(ids)
        elif axis:
            small = _build_hatch(group, angle, u, n, PTol.MIN_GRID_ROWS)
            if small is not None:
                grid_candidates.append((skey, small, ids))


def _build_hatch(items, angle: float, u, n, min_rows: int
                 ) -> Optional[HatchPattern]:
    """Regularity tests + boundary of one candidate family component."""
    if len(items) < min_rows:
        return None
    # rows: pieces sharing an offset
    items = sorted(items, key=lambda it: it[0])
    rows: List[List[tuple]] = [[items[0]]]
    for it in items[1:]:
        if it[0] - rows[-1][-1][0] <= PTol.ROW_TOL:
            rows[-1].append(it)
        else:
            rows.append([it])
    if len(rows) < min_rows:
        return None
    offsets = [sum(it[0] for it in r) / len(r) for r in rows]
    gaps = [b - a for a, b in zip(offsets, offsets[1:])]
    s = _median(gaps)
    if not PTol.MIN_SPACING <= s <= PTol.MAX_SPACING:
        return None
    regular = exact = 0
    for g in gaps:
        k = max(1, round(g / s))
        if abs(g - k * s) <= PTol.SPACING_REL * s:
            regular += 1
            if k == 1:
                exact += 1
    if regular < 0.9 * len(gaps) or exact < 0.6 * len(gaps):
        return None
    extents = [(min(it[1] for it in r), max(it[2] for it in r)) for r in rows]
    if _median([b - a for a, b in extents]) < 1.5 * s:
        return None                          # short ticks, not a hatch
    # ---- boundary: row starts, then row ends backwards -----------------------
    def P(t, d):
        return (u[0] * t + n[0] * d, u[1] * t + n[1] * d)

    half = s / 2.0
    starts = [P(extents[0][0], offsets[0] - half)]
    starts += [P(e[0], d) for e, d in zip(extents, offsets)]
    starts.append(P(extents[-1][0], offsets[-1] + half))
    ends = [P(extents[-1][1], offsets[-1] + half)]
    ends += [P(e[1], d) for e, d in zip(reversed(extents), reversed(offsets))]
    ends.append(P(extents[0][1], offsets[0] - half))
    boundary = starts + ends
    # ---- holes: gaps inside rows (text windows, symbols) -------------------------
    holes = _holes(rows, offsets, half, P)
    st = rows[0][0][3].style
    return HatchPattern(style=st, angle=angle, spacing=s,
                        origin=P(extents[0][0], offsets[0]),
                        boundary=boundary, holes=holes,
                        line_count=len(items))


def _holes(rows, offsets, half, P) -> List[List[Point]]:
    """Gaps between pieces of consecutive rows that overlap -> hole polygons."""
    row_gaps = []
    for r in rows:
        pieces = sorted((it[1], it[2]) for it in r)
        gaps = []
        end = pieces[0][1]
        for a, b in pieces[1:]:
            if a > end + 0.05:
                gaps.append((end, a))
            end = max(end, b)
        row_gaps.append(gaps)
    holes: List[List[Point]] = []
    open_groups: List[dict] = []
    for k, gaps in enumerate(row_gaps):
        next_open = []
        for g in gaps:
            owner = None
            for grp in open_groups:
                last = grp["gaps"][-1]
                if grp["row"][-1] == k - 1 and \
                        min(last[1], g[1]) - max(last[0], g[0]) > 0:
                    owner = grp
                    break
            if owner is None:
                owner = {"gaps": [], "row": []}
            owner["gaps"].append(g)
            owner["row"].append(k)
            if owner not in next_open:
                next_open.append(owner)
        for grp in open_groups:
            if grp not in next_open:
                holes.append(_hole_polygon(grp, offsets, half, P))
        open_groups = next_open
    for grp in open_groups:
        holes.append(_hole_polygon(grp, offsets, half, P))
    return holes


def _hole_polygon(grp, offsets, half, P) -> List[Point]:
    rows = grp["row"]
    gaps = grp["gaps"]
    ds = [offsets[r] for r in rows]
    left = [P(gaps[0][0], ds[0] - half)]
    left += [P(g[0], d) for g, d in zip(gaps, ds)]
    left.append(P(gaps[-1][0], ds[-1] + half))
    right = [P(gaps[-1][1], ds[-1] + half)]
    right += [P(g[1], d) for g, d in zip(reversed(gaps), reversed(ds))]
    right.append(P(gaps[0][1], ds[0] - half))
    return left + right


# ---------------------------------------------------------------------------
# White masks over hatches
# ---------------------------------------------------------------------------
def _point_in_polygon(p: Point, poly: List[Point]) -> bool:
    x, y = p
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and \
                x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _area(poly: List[Point]) -> float:
    a = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def add_mask_holes(hatches: List[HatchPattern],
                   masks: List[List[Point]]) -> int:
    """A white filled shape drawn over a hatch (the "text window" CAD
    programs put behind a label) hides the hatch lines there. The rebuilt
    hatch gets a hole at that place, so the label stays readable without
    any masking entity. Returns the number of holes added."""
    added = 0
    for h in hatches:
        hb = _bbox(h.boundary)
        h_area = _area(h.boundary)
        for m in masks:
            if len(m) < 3:
                continue
            mb = _bbox(m)
            if mb[0] < hb[0] or mb[1] < hb[1] or mb[2] > hb[2] \
                    or mb[3] > hb[3]:
                continue
            if _area(m) > 0.6 * h_area:
                continue
            if all(_point_in_polygon(p, h.boundary) for p in m):
                h.holes.append(list(m))
                added += 1
    return added
