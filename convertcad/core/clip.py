"""
clip.py — convert only a selected AREA of the sheet.

The user draws a rectangle on the sheet (Select area tool). Everything is
cut to that rectangle right after extraction, so every later step (arcs,
dimensions, blocks, layers) only sees what is inside:

  * straight segments  -> clipped exactly (Liang-Barsky)
  * curves (Bezier)    -> kept when inside; cut ones are split at the edge
                          (de Casteljau subdivision), the outside part dropped
  * filled areas       -> clipped polygon (Sutherland-Hodgman); the page
                          background keeps its mark (extractor.py), so the
                          cut piece is not taken for a coloured fill
  * texts              -> kept when their anchor point is inside
  * images             -> kept when they overlap the area

Coordinates stay those of the sheet: the DXF keeps the drawing's real
position, so an area converted later lines up with the rest of the sheet.
"""

from typing import List, Optional, Sequence, Tuple

from .extractor import PageData, Point, RawBezier, RawFill, RawSegment

Rect = Tuple[float, float, float, float]


def _inside(p: Point, r: Rect, eps: float = 1e-6) -> bool:
    return r[0] - eps <= p[0] <= r[2] + eps and r[1] - eps <= p[1] <= r[3] + eps


def clip_segment(p: Point, q: Point, r: Rect) -> Optional[Tuple[Point, Point]]:
    """Liang-Barsky: the part of p-q inside r, or None."""
    x0, y0 = p
    dx, dy = q[0] - x0, q[1] - y0
    t0, t1 = 0.0, 1.0
    for pk, qk in ((-dx, x0 - r[0]), (dx, r[2] - x0),
                   (-dy, y0 - r[1]), (dy, r[3] - y0)):
        if pk == 0:
            if qk < 0:
                return None                    # parallel and outside
            continue
        t = qk / pk
        if pk < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    a = (x0 + t0 * dx, y0 + t0 * dy)
    b = (x0 + t1 * dx, y0 + t1 * dy)
    if abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9:
        return None
    return a, b


def _split_bezier(pts: Sequence[Point], t: float):
    """de Casteljau: split a cubic Bezier at parameter t."""
    p0, p1, p2, p3 = pts

    def lerp(a, b):
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    a, b, c = lerp(p0, p1), lerp(p1, p2), lerp(p2, p3)
    d, e = lerp(a, b), lerp(b, c)
    f = lerp(d, e)
    return (p0, a, d, f), (f, e, c, p3)


def _bezier_point(pts, t: float) -> Point:
    mt = 1 - t
    return (mt ** 3 * pts[0][0] + 3 * mt * mt * t * pts[1][0]
            + 3 * mt * t * t * pts[2][0] + t ** 3 * pts[3][0],
            mt ** 3 * pts[0][1] + 3 * mt * mt * t * pts[1][1]
            + 3 * mt * t * t * pts[2][1] + t ** 3 * pts[3][1])


def clip_bezier(b: RawBezier, r: Rect, depth: int = 0) -> List[RawBezier]:
    """Pieces of a Bezier inside r (curves crossing the edge are split)."""
    pts = (b.p0, b.p1, b.p2, b.p3)
    if all(_inside(p, r) for p in pts):
        return [b]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    if max(xs) < r[0] or min(xs) > r[2] or max(ys) < r[1] or min(ys) > r[3]:
        return []                                 # hull outside: nothing
    if depth >= 7:                                # tiny piece on the edge
        mid = _bezier_point(pts, 0.5)
        return [b] if _inside(mid, r) else []
    left, right = _split_bezier(pts, 0.5)
    out = []
    for half in (left, right):
        out += clip_bezier(RawBezier(*half, style=b.style), r, depth + 1)
    return _merge_pieces(out)


def _merge_pieces(pieces: List[RawBezier]) -> List[RawBezier]:
    """Consecutive halves that both survived are kept as they are; they
    chain again into one spline later in geometry.py."""
    return pieces


def clip_polygon(points: List[Point], r: Rect) -> List[Point]:
    """Sutherland-Hodgman polygon clipping against the rectangle."""
    def clip_edge(poly, inside, cross):
        out = []
        for i, cur in enumerate(poly):
            prev = poly[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(cross(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cross(prev, cur))
        return out

    def x_cross(x):
        def f(a, b):
            t = (x - a[0]) / (b[0] - a[0])
            return (x, a[1] + t * (b[1] - a[1]))
        return f

    def y_cross(y):
        def f(a, b):
            t = (y - a[1]) / (b[1] - a[1])
            return (a[0] + t * (b[0] - a[0]), y)
        return f

    poly = list(points)
    for inside, cross in ((lambda p: p[0] >= r[0], x_cross(r[0])),
                          (lambda p: p[0] <= r[2], x_cross(r[2])),
                          (lambda p: p[1] >= r[1], y_cross(r[1])),
                          (lambda p: p[1] <= r[3], y_cross(r[3]))):
        if not poly:
            break
        poly = clip_edge(poly, inside, cross)
    return poly


def clip_page(pd: PageData, rect: Sequence[float]) -> dict:
    """Cut every primitive of the page to `rect` (in place). Returns counts
    of what was kept, for the conversion report."""
    r: Rect = (float(rect[0]), float(rect[1]), float(rect[2]),
               float(rect[3]))
    before = len(pd.segments) + len(pd.beziers) + len(pd.fills) \
        + len(pd.texts)
    segs: List[RawSegment] = []
    for s in pd.segments:
        c = clip_segment(s.p1, s.p2, r)
        if c is not None:
            segs.append(RawSegment(c[0], c[1], s.style))
    pd.segments = segs
    curves: List[RawBezier] = []
    for b in pd.beziers:
        curves += clip_bezier(b, r)
    pd.beziers = curves
    fills: List[RawFill] = []
    for f in pd.fills:
        poly = clip_polygon(f.points, r)
        if len(poly) >= 3:
            fills.append(RawFill(points=poly, color=f.color,
                                 pdf_layer=f.pdf_layer,
                                 background=f.background))
    pd.fills = fills
    pd.texts = [t for t in pd.texts if _inside(t.origin, r)]
    pd.shx_texts = [t for t in pd.shx_texts if _inside(t.origin, r)]
    pd.images = [im for im in pd.images
                 if im.bbox[0] < r[2] and im.bbox[2] > r[0]
                 and im.bbox[1] < r[3] and im.bbox[3] > r[1]]
    after = len(pd.segments) + len(pd.beziers) + len(pd.fills) \
        + len(pd.texts)
    return {"before": before, "after": after}
