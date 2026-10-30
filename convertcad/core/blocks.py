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

Any other angle (a valve on a pipe at 30 degrees): the clusters left alone
by the fingerprints are compared by their key points (vertices, centres,
arc ends) seen from their mean point — the same distances, then the same
points once turned (and mirrored) — and the copies found get the measured
rotation.
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
    TURN_TOL = 0.35          # turned copies: key points agree within (pt)
    TURN_MAX_KEYS = 300      # symbols with more key points: not compared


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

    leftovers = []
    for group in list(by_fp.values()):
        if len(group) < max(2, min_repeats):
            leftovers += group
    if rotations and leftovers:
        _turned_copies(leftovers, max(2, min_repeats), res)
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


# ---------------------------------------------------------------------------
# Copies turned by any angle
# ---------------------------------------------------------------------------
@dataclass
class _Keys:
    """Key points of a cluster around their mean point (page coordinates):
    xy (n x 2), the kind of each point, its size (radius) and distance."""
    cluster: Cluster
    mean: Point
    xy: list
    kind: list
    size: list
    dist: list
    profile: list = field(default_factory=list)    # sorted distances


def _key_points(cl: Cluster) -> _Keys:
    pts, kinds, sizes = [], [], []
    for pl in cl.polylines:
        for p in pl.points:
            pts.append(p)
            kinds.append(("P", pl.closed, _style_sig(pl)))
            sizes.append(0.0)
    for a in cl.arcs:
        lab = ("A", _style_sig(a))
        pts.append(a.center)
        kinds.append(lab + ("c",))
        sizes.append(a.radius)
        for ang in (a.start_angle, a.end_angle, a.start_angle + a.sweep / 2):
            t = math.radians(ang)
            pts.append((a.center[0] + a.radius * math.cos(t),
                        a.center[1] + a.radius * math.sin(t)))
            kinds.append(lab + ("e",))
            sizes.append(a.radius)
    for c in cl.circles:
        pts.append(c.center)
        kinds.append(("C", _style_sig(c)))
        sizes.append(c.radius)
    for sp in cl.splines:
        for p in sp.control_points:
            pts.append(p)
            kinds.append(("S", _style_sig(sp)))
            sizes.append(0.0)
    mx = sum(p[0] for p in pts) / len(pts)
    my = sum(p[1] for p in pts) / len(pts)
    xy = [(p[0] - mx, p[1] - my) for p in pts]
    return _Keys(cl, (mx, my), xy, kinds, sizes,
                 [math.hypot(x, y) for x, y in xy])


def _turn(xy, theta: float, mirror: bool):
    c, s = math.cos(theta), math.sin(theta)
    out = []
    for x, y in xy:
        if mirror:
            x = -x
        out.append((c * x - s * y, s * x + c * y))
    return out


def _align(ref: _Keys, mem: _Keys):
    """Rotation (radians, page coordinates) and mirroring that lay the key
    points of `ref` on those of `mem`, or None."""
    tol = BTol.TURN_TOL
    far = max(range(len(ref.xy)), key=lambda i: ref.dist[i])
    if ref.dist[far] < 4 * tol:
        return None                              # a dot: no angle
    by_kind: Dict[tuple, List[int]] = {}
    for j, k in enumerate(mem.kind):
        by_kind.setdefault(k, []).append(j)
    for mirror in (False, True):
        fx, fy = ref.xy[far]
        a0 = math.atan2(fy, -fx if mirror else fx)
        for j in by_kind.get(ref.kind[far], ()):
            if abs(mem.dist[j] - ref.dist[far]) > tol or \
                    abs(mem.size[j] - ref.size[far]) > tol:
                continue
            theta = math.atan2(mem.xy[j][1], mem.xy[j][0]) - a0
            turned = _turn(ref.xy, theta, mirror)
            pairs = []
            for i, (x, y) in enumerate(turned):
                q = next((q for q in by_kind.get(ref.kind[i], ())
                          if abs(mem.xy[q][0] - x) <= tol
                          and abs(mem.xy[q][1] - y) <= tol
                          and abs(mem.size[q] - ref.size[i]) <= tol), None)
                if q is None:
                    break
                pairs.append((i, q))
            else:
                # best angle from all the points (least squares)
                flat = _turn(ref.xy, 0.0, mirror)
                sc = sum(flat[i][0] * mem.xy[q][1] - flat[i][1] * mem.xy[q][0]
                         for i, q in pairs)
                cc = sum(flat[i][0] * mem.xy[q][0] + flat[i][1] * mem.xy[q][1]
                         for i, q in pairs)
                return math.atan2(sc, cc), mirror
    return None


def _turned_copies(clusters: List[Cluster], min_repeats: int,
                   res: "BlockResult") -> None:
    """Group the clusters that are copies of each other turned by any angle
    (see the module docstring); groups of min_repeats or more become
    blocks. Their base point is the mean of the key points."""
    keys = []
    for cl in clusters:
        k = _key_points(cl)
        if 2 <= len(k.xy) <= BTol.TURN_MAX_KEYS:
            keys.append(k)
    # quick filter: same kinds of points, same distances to the mean
    buckets: Dict[tuple, List[_Keys]] = {}
    for k in keys:
        sig = tuple(sorted((repr(x), keys_count) for x, keys_count in
                           _count(k.kind).items()))
        buckets.setdefault(sig, []).append(k)
    tol = BTol.TURN_TOL
    for group in buckets.values():
        if len(group) < min_repeats:
            continue
        for k in group:
            k.profile = sorted(k.dist)
        done = [False] * len(group)
        for i, ref in enumerate(group):
            if done[i]:
                continue
            found = [(ref, 0.0, False)]
            for j in range(i + 1, len(group)):
                mem = group[j]
                if done[j] or any(abs(a - b) > 2 * tol for a, b in
                                  zip(ref.profile, mem.profile)):
                    continue
                al = _align(ref, mem)
                if al is not None:
                    found.append((mem, al[0], al[1]))
                    done[j] = True
            if len(found) < min_repeats:
                continue
            done[i] = True
            ref.cluster.centroid = ref.mean
            res.definitions.append(ref.cluster)
            inserts = []
            for mem, theta, mirror in found:
                mem.cluster.centroid = mem.mean
                # page (y down) -> DXF (y up): the angle changes sign
                rot = round(-math.degrees(theta) % 360.0, 6)
                inserts.append((mem.mean, rot, mirror) if (rot or mirror)
                               else mem.mean)
            res.inserts.append(inserts)
            res.members.append([m.cluster for m, _, _ in found])
            for m, _, _ in found:
                for e in m.cluster.entities():
                    e.consumed = True


def _count(items: list) -> Dict:
    out: Dict = {}
    for x in items:
        out[x] = out.get(x, 0) + 1
    return out


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
