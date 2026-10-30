"""
spatial.py — a small uniform-grid spatial index.

Real drawings contain tens of thousands of segments. Questions such as
"which lines pass near this arrow tip?" must not scan the whole drawing each
time (that is O(n^2) and takes minutes). The grid answers them by looking only
at the few cells around the query point.

Used by: annotations.py (dimensions, leaders), blocks.py (clustering),
and the interface snap engine. Pure Python, no dependencies.
"""

import math
from typing import Dict, Generic, Iterable, List, Set, Tuple, TypeVar

T = TypeVar("T")
BBox = Tuple[float, float, float, float]


class GridIndex(Generic[T]):
    """Stores items by bounding box; queries return candidate items."""

    def __init__(self, cell: float = 16.0):
        self.cell = float(cell)
        self._cells: Dict[Tuple[int, int], List[int]] = {}
        self._items: List[T] = []
        self._boxes: List[BBox] = []

    def __len__(self) -> int:
        return len(self._items)

    def _range(self, x0: float, y0: float, x1: float, y1: float):
        c = self.cell
        return (int(math.floor(x0 / c)), int(math.floor(y0 / c)),
                int(math.floor(x1 / c)), int(math.floor(y1 / c)))

    def insert(self, item: T, bbox: BBox) -> int:
        """Add an item; returns its integer id."""
        idx = len(self._items)
        self._items.append(item)
        self._boxes.append(bbox)
        gx0, gy0, gx1, gy1 = self._range(*bbox)
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                self._cells.setdefault((gx, gy), []).append(idx)
        return idx

    def insert_segment(self, item: T, p: Tuple[float, float],
                       q: Tuple[float, float]) -> int:
        """Add a segment, registering only the cells it actually crosses.
        (A long diagonal line must not claim every cell of its bounding box.)"""
        idx = len(self._items)
        self._items.append(item)
        self._boxes.append((min(p[0], q[0]), min(p[1], q[1]),
                            max(p[0], q[0]), max(p[1], q[1])))
        length = math.dist(p, q)
        steps = max(1, int(length / (self.cell * 0.5)))
        seen: Set[Tuple[int, int]] = set()
        for k in range(steps + 1):
            t = k / steps
            x = p[0] + (q[0] - p[0]) * t
            y = p[1] + (q[1] - p[1]) * t
            key = (int(math.floor(x / self.cell)), int(math.floor(y / self.cell)))
            if key not in seen:
                seen.add(key)
                self._cells.setdefault(key, []).append(idx)
        return idx

    def insert_path(self, item: T, points: List[Tuple[float, float]]) -> int:
        """Add an item drawn along a polyline (e.g. a sampled arc), under ONE
        id, registering only the cells the polyline crosses. (A large arc
        must not claim every cell of its circle's bounding box.)"""
        idx = len(self._items)
        self._items.append(item)
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        self._boxes.append((min(xs), min(ys), max(xs), max(ys)))
        seen: Set[Tuple[int, int]] = set()
        for p, q in zip(points, points[1:]):
            steps = max(1, int(math.dist(p, q) / (self.cell * 0.5)))
            for k in range(steps + 1):
                t = k / steps
                key = (int(math.floor((p[0] + (q[0] - p[0]) * t) / self.cell)),
                       int(math.floor((p[1] + (q[1] - p[1]) * t) / self.cell)))
                if key not in seen:
                    seen.add(key)
                    self._cells.setdefault(key, []).append(idx)
        return idx

    def query_ids(self, x0: float, y0: float, x1: float, y1: float) -> Set[int]:
        """Ids of items whose cells intersect the box (candidates only)."""
        out: Set[int] = set()
        gx0, gy0, gx1, gy1 = self._range(x0, y0, x1, y1)
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                ids = self._cells.get((gx, gy))
                if ids:
                    out.update(ids)
        return out

    def query(self, x0: float, y0: float, x1: float, y1: float) -> List[T]:
        """Items whose bounding box overlaps the query box."""
        res = []
        for i in self.query_ids(x0, y0, x1, y1):
            b = self._boxes[i]
            if b[0] <= x1 and x0 <= b[2] and b[1] <= y1 and y0 <= b[3]:
                res.append(self._items[i])
        return res

    def near(self, x: float, y: float, radius: float) -> List[T]:
        """Items whose bounding box comes within `radius` of (x, y)."""
        return self.query(x - radius, y - radius, x + radius, y + radius)

    def items(self) -> Iterable[T]:
        return iter(self._items)


# ---------------------------------------------------------------------------
# Small geometry helpers shared by several modules
# ---------------------------------------------------------------------------
def point_segment_distance(p, a, b) -> float:
    """Shortest distance from point p to segment a-b."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-18:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def point_line_distance(p, a, b) -> float:
    """Distance from p to the INFINITE line through a-b."""
    L = math.dist(a, b)
    if L < 1e-12:
        return math.dist(p, a)
    return abs((b[0] - a[0]) * (a[1] - p[1]) - (a[0] - p[0]) * (b[1] - a[1])) / L


def segment_intersection(a, b, c, d, eps: float = 1e-3):
    """Intersection point of segments a-b and c-d (with a small tolerance on
    the segment parameters), or None when parallel / not crossing."""
    x1, y1 = a
    x2, y2 = b
    x3, y3 = c
    x4, y4 = d
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-12:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    u = ((x1 - x3) * (y1 - y2) - (y1 - y3) * (x1 - x2)) / den
    if -eps <= t <= 1 + eps and -eps <= u <= 1 + eps:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


def angle_deg(v) -> float:
    """Angle of a vector in degrees (-180, 180]."""
    return math.degrees(math.atan2(v[1], v[0]))


def angle_diff_mod180(a: float, b: float) -> float:
    """Smallest difference between two LINE directions (0..90 degrees)."""
    d = abs((a - b) % 180.0)
    return min(d, 180.0 - d)
