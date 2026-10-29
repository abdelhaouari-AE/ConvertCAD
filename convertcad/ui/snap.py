"""
snap.py — object snap for the measuring and calibration tools (Qt-free).

Like AutoCAD's OSNAP, a click near a drawn object jumps to its exact
geometric point:
    end  endpoint of a line / curve, corner of a rectangle   (square glyph)
    mid  midpoint of a straight segment                       (triangle)
    int  intersection of two straight segments                (cross)
    cen  centre of a circle or arc                            (circle)

Built once per page from PyMuPDF's raw path list (fast), in DISPLAYED page
coordinates (rotation applied), stored in a spatial grid.
"""

import math
from dataclasses import dataclass
from typing import Iterable, List, Optional, Set, Tuple

import numpy as np

from ..core.compat import page_matrix, transform_point
from ..core.geometry import fit_circle
from ..core.spatial import GridIndex, point_segment_distance, \
    segment_intersection

Point = Tuple[float, float]
PRIORITY = {"int": 0, "end": 1, "cen": 2, "mid": 3}


@dataclass
class SnapHit:
    point: Point
    kind: str                       # end | mid | int | cen


class SnapEngine:
    def __init__(self, segments: Iterable[Tuple[Point, Point]],
                 points: Iterable[Tuple[Point, str]]):
        self.seg_index: GridIndex = GridIndex(24.0)
        self.pt_index: GridIndex = GridIndex(24.0)
        self.n_segments = 0
        seen: Set[Tuple[int, int, str]] = set()
        for a, b in segments:
            if math.dist(a, b) < 1e-6:
                continue
            self.seg_index.insert_segment((a, b), a, b)
            self.n_segments += 1
        for p, kind in points:
            key = (round(p[0] * 20), round(p[1] * 20), kind)
            if key in seen:
                continue
            seen.add(key)
            self.pt_index.insert((p, kind), (p[0], p[1], p[0], p[1]))

    # ------------------------------------------------------------------
    @classmethod
    def from_page(cls, page) -> "SnapEngine":
        m = page_matrix(page)
        P = lambda q: transform_point(m, q[0], q[1])          # noqa: E731
        segs: List[Tuple[Point, Point]] = []
        pts: List[Tuple[Point, str]] = []

        def add_seg(a, b):
            segs.append((a, b))
            pts.append((a, "end"))
            pts.append((b, "end"))
            pts.append((((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), "mid"))

        try:
            paths = page.get_cdrawings()
        except Exception:                                  # pragma: no cover
            paths = []
        for path in paths:
            for it in path.get("items", ()):
                k = it[0]
                if k == "l":
                    add_seg(P(it[1]), P(it[2]))
                elif k == "re":
                    x0, y0, x1, y1 = it[1]
                    c = [P((x0, y0)), P((x1, y0)), P((x1, y1)), P((x0, y1))]
                    for i in range(4):
                        add_seg(c[i], c[(i + 1) % 4])
                elif k == "qu":
                    ul, ur, ll, lr = (P(q) for q in it[1])
                    c = [ul, ur, lr, ll]
                    for i in range(4):
                        add_seg(c[i], c[(i + 1) % 4])
                elif k == "c":
                    p0, p1, p2, p3 = (P(q) for q in it[1:5])
                    pts.append((p0, "end"))
                    pts.append((p3, "end"))
                    t = np.linspace(0.0, 1.0, 9)[:, None]
                    arr = ((1 - t) ** 3 * np.array(p0)
                           + 3 * (1 - t) ** 2 * t * np.array(p1)
                           + 3 * (1 - t) * t ** 2 * np.array(p2)
                           + t ** 3 * np.array(p3))
                    fit = fit_circle(arr)
                    if fit and fit[2] < max(0.15, fit[1] * 0.01) \
                            and fit[1] < 5000:
                        pts.append((fit[0], "cen"))
        return cls(segs, pts)

    # ------------------------------------------------------------------
    def query(self, x: float, y: float, tol: float,
              modes: Set[str]) -> Optional[SnapHit]:
        """Best snap point within `tol` (page units) of (x, y)."""
        if not modes:
            return None
        best: Optional[Tuple[float, int, SnapHit]] = None

        def consider(p: Point, kind: str) -> None:
            nonlocal best
            d = math.dist(p, (x, y))
            if d > tol:
                return
            # the nearest wins; near-ties go to the stronger snap kind
            score = d + PRIORITY[kind] * tol * 0.15
            if best is None or score < best[0]:
                best = (score, PRIORITY[kind], SnapHit(p, kind))

        for p, kind in self.pt_index.near(x, y, tol):
            if kind in modes:
                consider(p, kind)
        if "int" in modes:
            near = [s for s in self.seg_index.near(x, y, tol)
                    if point_segment_distance((x, y), s[0], s[1]) <= tol]
            near = near[:60]
            for i in range(len(near)):
                for j in range(i + 1, len(near)):
                    ip = segment_intersection(*near[i], *near[j])
                    if ip is not None:
                        consider(ip, "int")
        return best[2] if best else None
