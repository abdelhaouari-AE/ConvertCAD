"""
blocks.py — STEP 5: detect REPEATED symbols and turn them into BLOCKs.

A door symbol, a bolt, a column section repeated 40x across a plan is the
SAME local geometry translated around. We:

  1. cluster entities that touch or almost touch, LAYER BY LAYER (PDF layer,
     or colour when the PDF has no layers): on a real plan everything
     touches something — equipment touches piping, piping touches racks —
     but a symbol rarely shares its layer with what it touches. Union-find on
     a grid of small "pieces": long lines are cut into chunks, so a wall
     running across the plan never swallows the symbols next to it
  2. compute a translation-invariant FINGERPRINT of each cluster
     (entity types + coordinates relative to the cluster centre, quantized)
  3. clusters sharing a fingerprint >= min_repeats times become one BLOCK
     definition + one INSERT per occurrence.

Rotated and mirrored copies: the fingerprint is computed for the 8
orientations a symbol can take on a drawing (0, 90, 180, 270 degrees, each
also mirrored) and the smallest one is kept, so a door hinged left and the
same door hinged right share one block; each INSERT then carries the
rotation and the mirroring (X scale -1) that reproduce its copy exactly.
Other angles (a symbol turned 30 degrees) are not matched.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .geometry import EArc, ECircle, EPolyline, ESpline, RebuiltPage
from .spatial import GridIndex

Point = Tuple[float, float]


class BTol:
    CLUSTER_GAP = 1.5        # entities closer than this (pt) join one cluster
    QUANT = 0.25             # fingerprint coordinate quantization (pt)
    MIN_REPEATS = 3          # a symbol must appear at least this many times
    MIN_ENTITIES = 2         # ...and contain at least this many entities
    MAX_SIZE_FRAC = 0.20     # clusters larger than 20% of the page diagonal
                             # are layout, not symbols -> never blocked
    MAX_PART_FRAC = 0.06     # a single entity longer than 6% of the diagonal
                             # (beam, wall, axis) is never part of a symbol and
                             # must not glue neighbouring symbols together
    CHUNK = 12.0             # long segments are cut into pieces of this size
    MAX_CLUSTER = 1500       # entities; larger groups are layout, not symbols


@dataclass
class Cluster:
    polylines: List[EPolyline] = field(default_factory=list)
    arcs: List[EArc] = field(default_factory=list)
    circles: List[ECircle] = field(default_factory=list)
    splines: List[ESpline] = field(default_factory=list)
    bbox: Tuple[float, float, float, float] = (0, 0, 0, 0)
    centroid: Point = (0.0, 0.0)
    fingerprint: tuple = ()
    orientation: int = 0             # index in D4: maps it to the canonical form

    def entity_count(self) -> int:
        return (len(self.polylines) + len(self.arcs)
                + len(self.circles) + len(self.splines))

    def entities(self) -> list:
        return self.polylines + self.arcs + self.circles + self.splines


@dataclass
class BlockResult:
    """definitions[k] is inserted at every entry of inserts[k]: a point, or
    (point, rotation in degrees, mirrored) for turned / mirrored copies."""
    definitions: List[Cluster] = field(default_factory=list)
    inserts: List[list] = field(default_factory=list)
    members: List[List[Cluster]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def _entity_bbox(e) -> Tuple[float, float, float, float]:
    if isinstance(e, EPolyline):
        xs = [p[0] for p in e.points]
        ys = [p[1] for p in e.points]
        return min(xs), min(ys), max(xs), max(ys)
    if isinstance(e, ESpline):
        xs = [p[0] for p in e.control_points]
        ys = [p[1] for p in e.control_points]
        return min(xs), min(ys), max(xs), max(ys)
    c, r = e.center, e.radius
    return c[0] - r, c[1] - r, c[0] + r, c[1] + r


def _pieces(e) -> List[Tuple[float, float, float, float]]:
    """Small boxes approximating an entity's footprint."""
    g = BTol.CLUSTER_GAP
    if isinstance(e, (EPolyline, ESpline)):
        pts = e.points if isinstance(e, EPolyline) else e.control_points
        seq = list(pts) + ([pts[0]] if isinstance(e, EPolyline) and e.closed
                           else [])
        boxes = []
        for p, q in zip(seq, seq[1:]):
            n = max(1, int(math.dist(p, q) / BTol.CHUNK))
            for k in range(n):
                t0, t1 = k / n, (k + 1) / n
                a = (p[0] + (q[0] - p[0]) * t0, p[1] + (q[1] - p[1]) * t0)
                b = (p[0] + (q[0] - p[0]) * t1, p[1] + (q[1] - p[1]) * t1)
                boxes.append((min(a[0], b[0]) - g, min(a[1], b[1]) - g,
                              max(a[0], b[0]) + g, max(a[1], b[1]) + g))
        return boxes or [_inflate(_entity_bbox(e))]
    return [_inflate(_entity_bbox(e))]


def _inflate(b):
    g = BTol.CLUSTER_GAP
    return (b[0] - g, b[1] - g, b[2] + g, b[3] + g)


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, a: int) -> int:
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _cluster_entities(entities: list) -> List[List[int]]:
    """Group entity indices whose footprints overlap."""
    uf = _UnionFind(len(entities))
    grid: GridIndex[int] = GridIndex(BTol.CHUNK)
    for i, e in enumerate(entities):
        for box in _pieces(e):
            for j in grid.query(*box):
                if j != i:
                    uf.union(i, j)
            grid.insert(i, box)
    groups: Dict[int, List[int]] = {}
    for i in range(len(entities)):
        groups.setdefault(uf.find(i), []).append(i)
    return list(groups.values())


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------
def _q(v: float) -> int:
    return round(v / BTol.QUANT)


def _style_sig(e) -> tuple:
    s = e.style
    return (s.color, round(s.width, 2), s.linetype, s.pdf_layer)


# The 8 orientations (page coordinates, y down): rotations by 0/90/180/270
# degrees, then the same mirrored left-right. 2x2 integer matrices.
D4 = (((1, 0), (0, 1)), ((0, -1), (1, 0)), ((-1, 0), (0, -1)),
      ((0, 1), (-1, 0)), ((-1, 0), (0, 1)), ((0, 1), (1, 0)),
      ((1, 0), (0, -1)), ((0, -1), (-1, 0)))


def _apply(m, x: float, y: float) -> Tuple[float, float]:
    return (m[0][0] * x + m[0][1] * y, m[1][0] * x + m[1][1] * y)


def _fingerprint(cl: Cluster, m=D4[0]) -> tuple:
    """Signature of the cluster seen through orientation `m`."""
    cx, cy = cl.centroid

    def q(p):
        x, y = _apply(m, p[0] - cx, p[1] - cy)
        return (_q(x), _q(y))
    sig = []
    for pl in cl.polylines:
        pts = tuple(sorted(q(p) for p in pl.points))
        sig.append(("P", pl.closed, pts, _style_sig(pl)))
    for a in cl.arcs:
        r = a.radius
        ends = []
        for ang in (a.start_angle, a.end_angle,
                    a.start_angle + a.sweep / 2.0):
            t = math.radians(ang)
            ends.append(q((a.center[0] + r * math.cos(t),
                           a.center[1] + r * math.sin(t))))
        sig.append(("A", q(a.center), _q(r), tuple(sorted(ends[:2])),
                    ends[2], _style_sig(a)))
    for c in cl.circles:
        sig.append(("C", q(c.center), _q(c.radius), _style_sig(c)))
    for sp in cl.splines:
        pts = tuple(q(p) for p in sp.control_points)
        sig.append(("S", min(pts, pts[::-1]), _style_sig(sp)))
    return tuple(sorted(sig, key=repr))


def _canonical(cl: Cluster, rotations: bool) -> Tuple[tuple, int]:
    """Smallest fingerprint over the allowed orientations + its index."""
    if not rotations:
        return _fingerprint(cl), 0
    best, best_k = None, 0
    for k, m in enumerate(D4):
        fp = _fingerprint(cl, m)
        if best is None or repr(fp) < repr(best):
            best, best_k = fp, k
    return best, best_k


def _mat_mul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(2))
                       for j in range(2)) for i in range(2))


def _mat_inv(m):
    """Inverse of an orthogonal integer matrix = its transpose."""
    return ((m[0][0], m[1][0]), (m[0][1], m[1][1]))


def insert_orientation(def_k: int, member_k: int) -> Tuple[float, bool]:
    """(rotation in degrees, mirrored) of an INSERT reproducing a member from
    the block definition, expressed in DXF coordinates (y up)."""
    mp = _mat_mul(_mat_inv(D4[member_k]), D4[def_k])      # page coords
    f = ((1, 0), (0, -1))
    md = _mat_mul(_mat_mul(f, mp), f)                     # flip y both ways
    det = md[0][0] * md[1][1] - md[0][1] * md[1][0]
    if det > 0:
        rot = math.degrees(math.atan2(md[1][0], md[0][0]))
        return round(rot % 360.0, 6), False
    rot = math.degrees(math.atan2(-md[1][0], -md[0][0]))
    return round(rot % 360.0, 6), True


def _make_cluster(entities: list, idxs: List[int]) -> Cluster:
    cl = Cluster()
    xs, ys = [], []
    for i in idxs:
        e = entities[i]
        if isinstance(e, EPolyline):
            cl.polylines.append(e)
        elif isinstance(e, EArc):
            cl.arcs.append(e)
        elif isinstance(e, ECircle):
            cl.circles.append(e)
        else:
            cl.splines.append(e)
        b = _entity_bbox(e)
        xs += [b[0], b[2]]
        ys += [b[1], b[3]]
    cl.bbox = (min(xs), min(ys), max(xs), max(ys))
    cl.centroid = ((cl.bbox[0] + cl.bbox[2]) / 2.0,
                   (cl.bbox[1] + cl.bbox[3]) / 2.0)
    return cl


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def detect_blocks(rp: RebuiltPage, min_repeats: int = BTol.MIN_REPEATS,
                  rotations: bool = True) -> BlockResult:
    res = BlockResult()
    page_diag = math.hypot(rp.page.width, rp.page.height)
    max_size = page_diag * BTol.MAX_SIZE_FRAC
    max_part = page_diag * BTol.MAX_PART_FRAC
    pool = []
    for e in rp.polylines + rp.arcs + rp.circles + rp.splines:
        if e.consumed:
            continue
        b = _entity_bbox(e)
        if math.hypot(b[2] - b[0], b[3] - b[1]) > max_part:
            continue                      # walls, beams, axes: never symbols
        pool.append(e)
    if not pool:
        return res

    layered = any(e.style.pdf_layer for e in pool)
    by_layer: Dict[tuple, list] = {}
    for e in pool:
        key = (e.style.pdf_layer,) if layered else (e.style.color,)
        by_layer.setdefault(key, []).append(e)
    clusters: List[Cluster] = []
    for group in by_layer.values():
        clusters += _symbol_candidates(group, rotations, max_size)

    by_fp: Dict[tuple, List[Cluster]] = {}
    for cl in clusters:
        by_fp.setdefault(cl.fingerprint, []).append(cl)

    for group in by_fp.values():
        if len(group) < max(2, min_repeats):
            continue
        ref = group[0]
        res.definitions.append(ref)
        inserts = []
        for cl in group:
            rot, mirror = insert_orientation(ref.orientation, cl.orientation)
            inserts.append((cl.centroid, rot, mirror) if (rot or mirror)
                           else cl.centroid)
        res.inserts.append(inserts)
        res.members.append(group)
        for cl in group:                  # never drawn twice
            for e in cl.entities():
                e.consumed = True
    return res


def _symbol_candidates(pool: list, rotations: bool, max_size: float
                       ) -> List[Cluster]:
    """Clusters of one layer that may be symbols, fingerprinted."""
    clusters: List[Cluster] = []
    for idxs in _cluster_entities(pool):
        if len(idxs) > BTol.MAX_CLUSTER:
            continue                      # layout, not a symbol
        cl = _make_cluster(pool, idxs)
        w, h = cl.bbox[2] - cl.bbox[0], cl.bbox[3] - cl.bbox[1]
        complexity = (sum(len(p.points) for p in cl.polylines)
                      + 3 * (len(cl.arcs) + len(cl.circles) + len(cl.splines)))
        if ((cl.entity_count() >= BTol.MIN_ENTITIES or complexity >= 5)
                and math.hypot(w, h) < max_size and max(w, h) > 0.5):
            cl.fingerprint, cl.orientation = _canonical(cl, rotations)
            clusters.append(cl)
    return clusters
