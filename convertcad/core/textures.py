"""
textures.py — rebuild the "texture" hatches that CAD programs explode when
they plot to PDF: dots, sand, concrete, gravel, earth, brick, insulation.

Such a hatch arrives as hundreds of tiny dashes and dots repeating a motif.
For each group of them, and each standard AutoCAD pattern that could have
drawn it (TEXTURES):
  1. scale: the dash lengths (or the spacing of the dots) compared with the
     pattern's; angle: the directions of the pieces compared with the
     pattern's;
  2. origin: the shift that lays the most pattern pieces on PDF pieces
     (a vote);
  3. CHECK: the pattern is drawn again over the group's area (ezdxf) and
     kept only when it reproduces the PDF — the PDF pieces are pieces it
     draws, and the pieces it draws are in the PDF. Sand and concrete look
     random: when their exact position cannot be found, their statistics
     (density, lengths, directions) must agree instead.
Accepted -> ONE pattern HATCH (name, scale, angle, origin, boundary) and the
pieces it explains are removed; otherwise every piece stays (safe fallback).

Coordinates: page points with the y axis turned UP — (x, -y) — like the DXF,
so that angles and the handedness of the patterns are the DXF ones.
"""

import math
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import numpy as np

from .extractor import Point, RawSegment, Style

# Standard patterns recognised (names of AutoCAD's acadiso.pat, as in ezdxf)
TEXTURES = ("DOTS", "AR-SAND", "AR-CONC", "GRAVEL", "EARTH", "BRICK",
            "AR-B816", "AR-BRSTD", "INSUL")
# Patterns designed to look random: accepted on statistics when their exact
# position cannot be found
RANDOM_LOOKING = ("AR-SAND", "AR-CONC")
# Share of dots among the pieces of each pattern (others: no dots); a group
# outside the range is not compared with the pattern at all
DOT_SHARE = {"DOTS": (0.8, 1.0), "AR-SAND": (0.8, 1.0), "AR-CONC": (0.3, 0.9)}


class XTol:
    """Tolerances (page points)."""
    DOT = 0.3                # a piece shorter than this is a dot
    SHORT = 30.0             # texture pieces are shorter than this
    LINK = 10.0              # pieces of one texture lie this close
    MIN_PIECES = 40          # smaller groups are left alone
    MIN_INSIDE = 20          # pieces away from the edges needed to judge
    DISCRETE = 0.6           # dash lengths: few distinct values
    PRECISION = 0.9          # PDF pieces the pattern draws
    RECALL = 0.85            # pattern pieces present in the PDF
    MAX_RENDER = 250_000     # pieces drawn to check a pattern
    TIME_BUDGET = 8.0        # seconds per page, then the rest stays as is


@dataclass
class TextureHatch:
    """A group of PDF pieces rebuilt as one standard pattern hatch."""
    name: str                       # standard pattern (acadiso.pat)
    scale: float                    # pattern unit -> page points
    angle: float                    # degrees, y up (DXF)
    origin: Point                   # pattern base point, y up (page pt)
    boundary: List[Point]           # page coordinates (y down)
    holes: List[List[Point]] = field(default_factory=list)
    style: Style = field(default_factory=Style)
    piece_count: int = 0            # PDF pieces replaced
    exact: bool = True              # False: accepted on statistics
    spacing: float = 0.0            # usual gap between the pieces (pt)


@dataclass
class TextureResult:
    segments: List[RawSegment]      # what is left
    hatches: List[TextureHatch] = field(default_factory=list)
    pieces: int = 0                 # PDF pieces replaced
    timed_out: bool = False         # some groups were not examined


# ---------------------------------------------------------------------------
# Pieces as arrays (y up)
# ---------------------------------------------------------------------------
class _Pieces:
    """Segments and dots as numpy arrays: ends, middles, lengths, angles."""

    def __init__(self, a: np.ndarray):
        a = np.asarray(a, dtype=float).reshape(-1, 4)
        self.a = a
        self.mid = (a[:, :2] + a[:, 2:]) / 2.0
        d = a[:, 2:] - a[:, :2]
        self.len = np.hypot(d[:, 0], d[:, 1])
        self.ang = np.degrees(np.arctan2(d[:, 1], d[:, 0])) % 180.0
        self.dot = self.len < XTol.DOT
        self.ang[self.dot] = -1.0

    def __len__(self) -> int:
        return len(self.a)

    @staticmethod
    def from_segments(segs: List[RawSegment]) -> "_Pieces":
        return _Pieces(np.array([(s.p1[0], -s.p1[1], s.p2[0], -s.p2[1])
                                 for s in segs], dtype=float))


class _Grid:
    """Points hashed in square cells: neighbours within a radius."""

    def __init__(self, pts: np.ndarray, cell: float):
        self.pts = pts
        self.cell = max(cell, 1e-6)
        keys = np.floor(pts / self.cell).astype(np.int64)
        self.cells: Dict[Tuple[int, int], List[int]] = {}
        for i, (kx, ky) in enumerate(keys.tolist()):
            self.cells.setdefault((kx, ky), []).append(i)

    def near(self, p, r: float) -> List[int]:
        c = self.cell
        x0, y0 = int(math.floor((p[0] - r) / c)), int(math.floor((p[1] - r) / c))
        x1, y1 = int(math.floor((p[0] + r) / c)), int(math.floor((p[1] + r) / c))
        out: List[int] = []
        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                out.extend(self.cells.get((gx, gy), ()))
        return out


def _nn_distances(pts: np.ndarray, sample: Optional[np.ndarray] = None,
                  k: int = 1) -> np.ndarray:
    """Distance from each (sampled) point to its k-th nearest neighbour."""
    n = len(pts)
    if n < 2:
        return np.zeros(0)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    area = max((hi[0] - lo[0]) * (hi[1] - lo[1]), 1e-6)
    cell = max(math.sqrt(area / n), 1e-3)
    grid = _Grid(pts, cell)
    idx = np.arange(n) if sample is None else sample
    out = np.empty(len(idx))
    for j, i in enumerate(idx.tolist()):
        r = cell
        while True:
            cand = [c for c in grid.near(pts[i], r) if c != i]
            if len(cand) >= k or r > 64 * cell:
                break
            r *= 2.0
        if not cand:
            out[j] = np.inf
            continue
        d = np.sort(np.hypot(*(pts[cand] - pts[i]).T))
        out[j] = d[min(k, len(d)) - 1]
    return out


# ---------------------------------------------------------------------------
# Standard patterns (ezdxf's copy of acadiso.pat) drawn again
# ---------------------------------------------------------------------------
def render(name: str, scale: float, angle: float, origin: Point,
           polygon: List[Point]) -> np.ndarray:
    """Pieces (x1, y1, x2, y2) of a standard pattern at `scale` and `angle`
    with its base point moved to `origin`, inside `polygon` (y up)."""
    from ezdxf.entities import Hatch
    from ezdxf.math import Vec2
    from ezdxf.render import hatching
    from ezdxf.tools.pattern import ISO_PATTERN
    h = Hatch.new()
    h.set_pattern_fill(name, scale=scale, angle=angle,
                       definition=ISO_PATTERN[name])
    if origin[0] or origin[1]:
        for line in h.pattern.lines:
            line.base_point = Vec2(line.base_point) + Vec2(origin)
    h.paths.add_polyline_path(polygon, is_closed=True)
    out = [(s.x, s.y, e.x, e.y)
           for s, e in hatching.hatch_entity(h, jiggle_origin=False)]
    return np.array(out, dtype=float).reshape(-1, 4)


@dataclass
class _Signature:
    dot_share: float
    lengths: np.ndarray             # lengths of the dashes (not the dots)
    ang_hist: np.ndarray            # 180 bins (1 degree), dashes
    dir_hist: np.ndarray            # 180 bins: directions to neighbours
    nn: float                       # median distance to the nearest piece
    density: float                  # pieces per square unit


def _hist180(values: np.ndarray, weights=None) -> np.ndarray:
    """Circular histogram of directions (0..180, 1 degree) smoothed."""
    h = np.bincount(np.floor(values).astype(int) % 180, weights=weights,
                    minlength=180).astype(float)
    kernel = np.array([0.25, 0.5, 1.0, 0.5, 0.25])
    h = sum(np.roll(h, s - 2) * kernel[s] for s in range(5))
    total = h.sum()
    return h / total if total > 0 else h


def _neighbour_directions(pts: np.ndarray, sample: np.ndarray) -> np.ndarray:
    """Directions (0..180) from sampled points to their 4 nearest
    neighbours: the rows of a dot pattern."""
    if len(pts) < 6:
        return np.zeros(0)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    cell = max(math.sqrt(max((hi - lo).prod(), 1e-6) / len(pts)), 1e-3)
    grid = _Grid(pts, cell)
    out = []
    for i in sample.tolist():
        cand = [c for c in grid.near(pts[i], 2.5 * cell) if c != i]
        if not cand:
            continue
        v = pts[cand] - pts[i]
        d = np.hypot(v[:, 0], v[:, 1])
        for j in np.argsort(d)[:4]:
            out.append(math.degrees(math.atan2(v[j, 1], v[j, 0])) % 180.0)
    return np.array(out)


def _signature(p: _Pieces, inside: np.ndarray, area: float) -> _Signature:
    sel = np.where(inside)[0]
    dashes = sel[~p.dot[sel]]
    step = max(1, len(sel) // 600)
    sample = sel[::step]
    nn = _nn_distances(p.mid, sample)
    nn = nn[np.isfinite(nn)]
    return _Signature(
        dot_share=float(p.dot[sel].mean()) if len(sel) else 0.0,
        lengths=p.len[dashes],
        ang_hist=_hist180(p.ang[dashes]) if len(dashes) else np.zeros(180),
        dir_hist=_hist180(_neighbour_directions(p.mid, sample)),
        nn=float(np.median(nn)) if len(nn) else 0.0,
        density=len(sel) / max(area, 1e-9))


@dataclass
class _Reference:
    name: str
    sig: _Signature
    dash_lengths: List[float]        # distinct dash lengths, most used first
    cell: float                      # repeat distance of the whole motif


@lru_cache(maxsize=None)
def reference(name: str) -> _Reference:
    """The pattern at scale 1, angle 0: its signature and repeat distance."""
    probe = render(name, 1.0, 0.0, (0.0, 0.0),
                   [(0, 0), (100, 0), (100, 100), (0, 100)])
    density = max(len(probe), 1) / 1e4
    size = min(max(math.sqrt(6000.0 / density), 100.0), 50000.0)
    pieces = _Pieces(render(name, 1.0, 0.0, (0.0, 0.0),
                            [(0, 0), (size, 0), (size, size), (0, size)]))
    m = pieces.mid
    inside = ((m[:, 0] > 0.2 * size) & (m[:, 0] < 0.8 * size)
              & (m[:, 1] > 0.2 * size) & (m[:, 1] < 0.8 * size))
    sig = _signature(pieces, inside, (0.6 * size) ** 2)
    # continuous pattern lines (brick courses) cross the whole square: they
    # are not dashes and do not show the repeat
    short = pieces.len < 0.25 * size
    sig.lengths = sig.lengths[sig.lengths < 0.25 * size]
    lengths = np.round(sig.lengths, 3)
    values, counts = np.unique(lengths, return_counts=True)
    order = np.argsort(-counts)
    dash = [float(values[i]) for i in order if values[i] > XTol.DOT]
    return _Reference(name, sig, dash,
                      _repeat_distance(pieces, inside & short, size))


def _repeat_distance(p: _Pieces, inside: np.ndarray, size: float) -> float:
    """Length of the longest of the two shortest translations that repeat
    the whole motif (the diameter of one tile); `size` when none is found."""
    key = np.where(p.dot, -1.0, np.round(p.ang) % 180.0)     # kind of piece
    q = 0.02
    table = {(int(round(x / q)), int(round(y / q)), k)
             for (x, y), k in zip(p.mid.tolist(), key.tolist())}
    inner = np.where(inside)[0]
    if len(inner) == 0:
        return size
    ref = inner[len(inner) // 2]
    same = np.where(key == key[ref])[0]
    vec = p.mid[same] - p.mid[ref]
    d = np.hypot(vec[:, 0], vec[:, 1])
    order = [i for i in np.argsort(d) if 0 < d[i] < 0.3 * size]
    test = inner[:: max(1, len(inner) // 150)].tolist()
    allowed = int(0.05 * len(test))
    found: List[np.ndarray] = []
    for i in order[:5000]:
        v = vec[i]
        misses = 0
        for j in test:                         # stop at the first misses
            x, y = p.mid[j] + v
            if not any((int(round(x / q)) + a, int(round(y / q)) + b, key[j])
                       in table for a in (-1, 0, 1) for b in (-1, 0, 1)):
                misses += 1
                if misses > allowed:
                    break
        if misses > allowed:
            continue
        if not found or abs(found[0][0] * v[1] - found[0][1] * v[0]) > \
                0.17 * np.linalg.norm(found[0]) * np.linalg.norm(v):
            found.append(v)
        if len(found) == 2:
            return float(max(np.linalg.norm(found[0]),
                             np.linalg.norm(found[1])))
    return size


# ---------------------------------------------------------------------------
# Region covered by a group of pieces
# ---------------------------------------------------------------------------
class _Region:
    """Outline of a group of pieces (raster, OpenCV): outer polygon, holes,
    and an 'inside, away from the edges' test (y up coordinates)."""

    def __init__(self, p: _Pieces, spacing: float):
        import cv2
        lo = p.a.reshape(-1, 2).min(axis=0)
        hi = p.a.reshape(-1, 2).max(axis=0)
        span = float(max(hi - lo))
        self.cell = max(spacing / 2.0, span / 3000.0, 0.05)
        pad = int(math.ceil(3.0 * spacing / self.cell)) + 2
        self.lo = lo - pad * self.cell
        w = int((hi[0] - lo[0]) / self.cell) + 2 * pad + 1
        h = int((hi[1] - lo[1]) / self.cell) + 2 * pad + 1
        img = np.zeros((h, w), np.uint8)
        px = ((p.a.reshape(-1, 2) - self.lo) / self.cell).round().astype(int)
        for (x1, y1), (x2, y2) in zip(px[0::2].tolist(), px[1::2].tolist()):
            cv2.line(img, (x1, y1), (x2, y2), 255, 1)
        r = max(1, int(math.ceil(1.6 * spacing / self.cell)))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                           (2 * r + 1, 2 * r + 1))
        self.mask = cv2.morphologyEx(img, cv2.MORPH_CLOSE, kernel)
        contours, hier = cv2.findContours(self.mask, cv2.RETR_CCOMP,
                                          cv2.CHAIN_APPROX_SIMPLE)
        self.outer: List[Point] = []
        self.holes: List[List[Point]] = []
        self.area = 0.0
        if not contours:
            return
        big = max(range(len(contours)),
                  key=lambda i: cv2.contourArea(contours[i]))
        eps = max(1.0, 0.5 * spacing / self.cell)
        self.outer = self._poly(cv2.approxPolyDP(contours[big], eps, True))
        self.area = cv2.contourArea(contours[big]) * self.cell ** 2
        for i, c in enumerate(contours):
            if hier[0][i][3] == big and \
                    cv2.contourArea(c) * self.cell ** 2 > (4 * spacing) ** 2:
                self.holes.append(self._poly(cv2.approxPolyDP(c, eps, True)))
                self.area -= cv2.contourArea(c) * self.cell ** 2
        # only the main part counts as the region
        only = np.zeros_like(self.mask)
        cv2.drawContours(only, contours, big, 255, -1)
        for i in range(len(contours)):
            if hier[0][i][3] == big:
                cv2.drawContours(only, contours, i, 0, -1)
        self.mask = only
        self._eroded: Dict[int, np.ndarray] = {}

    def _poly(self, c) -> List[Point]:
        return [(float(x * self.cell + self.lo[0]),
                 float(y * self.cell + self.lo[1]))
                for x, y in c.reshape(-1, 2).tolist()]

    def inside(self, pts: np.ndarray, margin: float = 0.0) -> np.ndarray:
        """Points inside the region and at least `margin` from its edge
        (a negative margin: up to that distance outside)."""
        import cv2
        r = int(math.ceil(abs(margin) / self.cell)) * (1 if margin >= 0 else -1)
        if r not in self._eroded:
            n = abs(r)
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                          (2 * n + 1, 2 * n + 1))
            self._eroded[r] = self.mask if not r else (
                cv2.erode(self.mask, k) if r > 0 else cv2.dilate(self.mask, k))
        m = self._eroded[r]
        ij = np.floor((pts - self.lo) / self.cell + 0.5).astype(int)
        ok = ((ij[:, 0] >= 0) & (ij[:, 0] < m.shape[1])
              & (ij[:, 1] >= 0) & (ij[:, 1] < m.shape[0]))
        out = np.zeros(len(pts), bool)
        out[ok] = m[ij[ok, 1], ij[ok, 0]] > 0
        return out


# ---------------------------------------------------------------------------
# Matching a group with one pattern
# ---------------------------------------------------------------------------
def _scales(sig: _Signature, ref: _Reference) -> List[float]:
    """Scale candidates: dash lengths, or the spacing of the dots."""
    if ref.sig.dot_share > 0.9 or not ref.dash_lengths:
        if sig.dot_share < 0.8 or ref.sig.nn <= 0:
            return []
        return [sig.nn / ref.sig.nn]
    if sig.dot_share > 0.9 or len(sig.lengths) < 10:
        return []
    # the most common PDF dash length (mean of its 3 % class: precise)
    bins = np.round(np.log(sig.lengths) / 0.03)
    values, counts = np.unique(bins, return_counts=True)
    top = values[np.argmax(counts)]
    mode = float(sig.lengths[np.abs(bins - top) <= 1].mean())
    ref_l = np.array(ref.dash_lengths[:60])
    out = []
    for length in ref_l:
        k = mode / length
        ratio = sig.lengths[:, None] / (k * ref_l[None, :])
        near = np.argmin(np.abs(ratio - 1.0), axis=1)
        ok = np.abs(ratio[np.arange(len(near)), near] - 1.0) < 0.05
        if ok.mean() < 0.6:
            continue
        # refine: every matched dash votes for the scale
        k = float(np.median(sig.lengths[ok] / ref_l[near[ok]]))
        out.append((float(ok.mean()), k))
    out.sort(reverse=True)
    picked: List[float] = []
    for _, k in out:
        if all(abs(k / q - 1.0) > 0.01 for q in picked):
            picked.append(k)
        if len(picked) == 2:
            break
    return picked


def _angles(sig: _Signature, ref: _Reference) -> List[float]:
    """Angle candidates: directions of the dashes (or rows of the dots)."""
    a, b = (sig.ang_hist, ref.sig.ang_hist) if ref.sig.dot_share < 0.9 \
        else (sig.dir_hist, ref.sig.dir_hist)
    if a.sum() <= 0 or b.sum() <= 0:
        return [0.0, 180.0]
    corr = np.array([float(np.dot(np.roll(b, s), a)) for s in range(180)])
    # the directions must agree once turned (cosine of the histograms)
    if corr.max() < 0.6 * float(np.linalg.norm(a) * np.linalg.norm(b)):
        return []
    peaks: List[int] = []
    for s in np.argsort(-corr):
        if all(min(abs(s - q), 180 - abs(s - q)) >= 5 for q in peaks):
            peaks.append(int(s))
        if len(peaks) == 2 or corr[s] < 0.5 * corr.max():
            break
    out = []
    for s in peaks:
        out += [float(s), float(s) + 180.0]
    return out


def _types_match(p: _Pieces, i: int, g: _Pieces, j: np.ndarray) -> np.ndarray:
    """Same kind of piece: dot with dot; dashes of one direction/length."""
    if p.dot[i]:
        return g.dot[j]
    da = np.abs(g.ang[j] - p.ang[i]) % 180.0
    da = np.minimum(da, 180.0 - da)
    return (~g.dot[j]) & (da < 3.0) & \
        (np.abs(g.len[j] - p.len[i]) <= 0.1 * p.len[i] + 0.1)


def _vote_origin(p: _Pieces, sample: np.ndarray, g: _Pieces, reach: float,
                 binsize: float) -> Tuple[float, float, float]:
    """Shift that lays the most pattern pieces on PDF pieces: every pair
    (PDF piece, pattern piece of the same kind) votes for its offset.
    Returns (dx, dy, share of the sampled pieces that agree)."""
    if len(g) == 0 or len(sample) == 0:
        return 0.0, 0.0, 0.0
    # keep the number of votes reasonable on dense patterns
    area = max(float(np.ptp(g.mid[:, 0]) * np.ptp(g.mid[:, 1])), 1e-9)
    per = max(1.0, len(g) * min(1.0, math.pi * reach * reach / area))
    n = int(min(len(sample), max(20, 1_500_000 / per)))
    sample = sample[np.linspace(0, len(sample) - 1, n).astype(int)]
    dots = np.where(g.dot)[0]
    offsets = []
    for i in sample.tolist():
        if p.dot[i]:
            cand = dots
        else:
            da = np.abs(g.ang - p.ang[i]) % 180.0
            da = np.minimum(da, 180.0 - da)
            cand = np.where((~g.dot) & (da < 3.0) &
                            (np.abs(g.len - p.len[i]) <= 0.1 * p.len[i] + 0.1))[0]
        off = p.mid[i] - g.mid[cand]
        offsets.append(off[(np.abs(off[:, 0]) <= reach)
                           & (np.abs(off[:, 1]) <= reach)])
    q = np.round(np.vstack(offsets) / binsize).astype(np.int64)
    if not len(q):
        return 0.0, 0.0, 0.0
    shift = 1 << 30                       # keys of positive numbers only
    keys, counts = np.unique(((q[:, 0] + shift) << 32) + q[:, 1] + shift,
                             return_counts=True)
    table = dict(zip(keys.tolist(), counts.tolist()))

    def around(key: int) -> int:
        return sum(table.get(key + (x << 32) + y, 0)
                   for x in (-1, 0, 1) for y in (-1, 0, 1))
    best = max(keys[np.argsort(-counts)[:50]].tolist(), key=around)
    a, b = (best >> 32) - shift, (best & 0xFFFFFFFF) - shift
    sx = sy = w = 0.0
    for x in (-1, 0, 1):
        for y in (-1, 0, 1):
            c = table.get(best + (x << 32) + y, 0)
            sx += c * (a + x)
            sy += c * (b + y)
            w += c
    return sx / w * binsize, sy / w * binsize, around(best) / len(sample)


def _keys(mid: np.ndarray, ang: np.ndarray, dot: np.ndarray, cell: float,
          spread: bool) -> np.ndarray:
    """Integer keys (cell of the middle, direction class) of pieces; with
    `spread`, also the neighbouring cells and direction classes."""
    ix = np.floor(mid[:, 0] / cell).astype(np.int64) + (1 << 22)
    iy = np.floor(mid[:, 1] / cell).astype(np.int64) + (1 << 22)
    ab = np.where(dot, 99, np.floor(ang / 4.0).astype(np.int64) % 45)
    if not spread:
        return (ix << 31) + (iy << 7) + ab
    out = []
    for a in (-1, 0, 1):
        for b in (-1, 0, 1):
            for c in (-1, 0, 1):
                ab2 = np.where(dot, 99, (ab + c) % 45)
                if c and dot.all():
                    continue
                out.append(((ix + a) << 31) + ((iy + b) << 7) + ab2)
    return np.concatenate(out)


def _explained(p: _Pieces, idx: np.ndarray, g: _Pieces, tol: float,
               within=None) -> np.ndarray:
    """Which pieces p[idx] are pieces of g: a short piece has the middle
    and direction of one of them; a long piece (brick course) lies on them
    all along — or only where `within(points)` is true, when given."""
    out = np.zeros(len(idx), bool)
    if len(idx) == 0 or len(g) == 0:
        return out
    cell = 2.0 * tol
    short = p.len[idx] <= XTol.SHORT
    if short.any():
        si = idx[short]
        mine = _keys(p.mid[si], p.ang[si], p.dot[si], cell, False)
        theirs = _keys(g.mid, g.ang, g.dot, cell, True)
        out[short] = np.isin(mine, theirs)
    rest = np.where(~short)[0]
    if len(rest):
        out[rest] = _lying_on(p, idx[rest], g, tol, within)
    return out


def _lying_on(p: _Pieces, idx: np.ndarray, g: _Pieces, tol: float,
              within=None) -> np.ndarray:
    """Pieces p[idx] whose every sample point (where `within` is true, if
    given) is within `tol` of a piece of g of the same direction (slow:
    only for the few long pieces)."""
    cell = max(4.0 * tol, 1e-3)
    grid: Dict[Tuple[int, int], List[int]] = {}
    for j, (x1, y1, x2, y2) in enumerate(g.a.tolist()):
        n = max(1, int(math.hypot(x2 - x1, y2 - y1) / cell))
        seen = set()
        for k in range(n + 1):
            t = k / n
            key = (int(math.floor((x1 + (x2 - x1) * t) / cell)),
                   int(math.floor((y1 + (y2 - y1) * t) / cell)))
            if key not in seen:
                seen.add(key)
                grid.setdefault(key, []).append(j)
    out = np.zeros(len(idx), bool)
    for n_i, i in enumerate(idx.tolist()):
        x1, y1, x2, y2 = p.a[i]
        steps = 1 if p.dot[i] else max(3, min(40, int(p.len[i] / (2 * cell))))
        ts = [0.5] if steps == 1 else \
            [0.05 + 0.9 * k / (steps - 1) for k in range(steps)]
        pts = np.array([(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t) for t in ts])
        if within is not None:
            pts = pts[within(pts)]
        ok = len(pts) > 0
        for x, y in pts.tolist():
            cx, cy = int(math.floor(x / cell)), int(math.floor(y / cell))
            cand = []
            for a in (-1, 0, 1):
                for b in (-1, 0, 1):
                    cand.extend(grid.get((cx + a, cy + b), ()))
            if cand and not p.dot[i]:
                cand = np.unique(cand)
                da = np.abs(g.ang[cand] - p.ang[i]) % 180.0
                da = np.minimum(da, 180.0 - da)
                cand = cand[(da < 3.0) | g.dot[cand]]
            if len(cand) == 0 or \
                    _point_segment_dist(x, y, g.a[cand]).min() > tol:
                ok = False
                break
        out[n_i] = ok
    return out


def _point_segment_dist(x: float, y: float, segs: np.ndarray) -> np.ndarray:
    ax, ay, bx, by = segs[:, 0], segs[:, 1], segs[:, 2], segs[:, 3]
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = np.where(L2 > 1e-18, ((x - ax) * dx + (y - ay) * dy)
                 / np.maximum(L2, 1e-18), 0.0)
    t = np.clip(t, 0.0, 1.0)
    return np.hypot(x - (ax + t * dx), y - (ay + t * dy))


def _similar(a: _Signature, b: _Signature) -> bool:
    """Two groups of pieces with the same statistics (random patterns)."""
    if b.density <= 0 or not 0.75 <= a.density / b.density <= 1.33:
        return False
    if abs(a.dot_share - b.dot_share) > 0.1:
        return False
    if b.nn > 0 and not 0.8 <= a.nn / b.nn <= 1.25:
        return False
    if len(a.lengths) >= 10 and len(b.lengths) >= 10:
        hi = max(a.lengths.max(), b.lengths.max())
        ha = np.histogram(a.lengths, bins=20, range=(0, hi))[0]
        hb = np.histogram(b.lengths, bins=20, range=(0, hi))[0]
        if np.minimum(ha / ha.sum(), hb / hb.sum()).sum() < 0.7:
            return False
        if np.minimum(a.ang_hist, b.ang_hist).sum() < 0.65:
            return False
    return True


@dataclass
class _Match:
    name: str
    scale: float
    angle: float
    origin: Tuple[float, float]
    explained: np.ndarray            # indices (in the group) replaced
    score: float
    exact: bool


def _match(name: str, p: _Pieces, region: _Region, sig: _Signature,
           spacing: float, inner: np.ndarray, others: _Pieces
           ) -> Optional[_Match]:
    """Try one standard pattern on a group (see the module docstring)."""
    ref = reference(name)
    best: Optional[_Match] = None
    lo = p.a.reshape(-1, 2).min(axis=0)
    hi = p.a.reshape(-1, 2).max(axis=0)
    span = float(max(hi - lo))
    tol = max(0.15, 0.12 * spacing)
    random_looking = name in RANDOM_LOOKING
    if random_looking and abs(sig.dot_share - ref.sig.dot_share) > 0.15:
        return None                     # sand and concrete have their dots
    centre = np.median(p.mid[inner], axis=0)
    near_centre = inner[np.argsort(np.hypot(*(p.mid[inner] - centre).T))]
    count = len(np.where(region.inside(p.mid))[0])
    for k in _scales(sig, ref):
        if not 0.55 <= count / max(ref.sig.density / (k * k) * region.area,
                                   1e-9) <= 1.8:
            continue                                  # wrong density
        # random-looking patterns: dots only (their scale is a statistic)
        # or too few repeats to align -> judged on statistics
        exact_possible = not random_looking or (
            ref.sig.dot_share < 0.9 and ref.cell * k <= 0.5 * span)
        reach = min(ref.cell * k, span) + tol
        box_lo, box_hi = lo - reach, hi + reach
        if ref.sig.density / (k * k) * float((box_hi - box_lo).prod()) > \
                XTol.MAX_RENDER:
            continue
        box = [(box_lo[0], box_lo[1]), (box_hi[0], box_lo[1]),
               (box_hi[0], box_hi[1]), (box_lo[0], box_hi[1])]
        # the origin is voted on a small window around the centre: a wrong
        # pattern costs little
        win = near_centre[:80]
        wlo = p.mid[win].min(axis=0) - reach
        whi = p.mid[win].max(axis=0) + reach
        window = [(wlo[0], wlo[1]), (whi[0], wlo[1]), (whi[0], whi[1]),
                  (wlo[0], whi[1])]
        for theta in _angles(sig, ref):
            dx = dy = 0.0
            exact = False
            if exact_possible:
                gw = _Pieces(render(name, k, theta, (0.0, 0.0), window))
                dx, dy, agree = _vote_origin(p, win, gw, reach,
                                             max(tol / 2, 0.05))
                exact = agree >= 0.5
                if exact:
                    gw = _Pieces(gw.a + np.array([dx, dy, dx, dy]))
                    exact = _explained(p, win[:60], gw, tol).mean() >= \
                        XTol.PRECISION - 0.1
            if not exact and not random_looking:
                continue
            g = _Pieces(render(name, k, theta, (dx, dy), box))
            g_in = np.where(region.inside(g.mid, 2.0 * spacing))[0]
            if len(g_in) < XTol.MIN_INSIDE:
                continue
            if exact:
                prec = _explained(p, inner, g, tol).mean()
                both = _Pieces(np.vstack([p.a, others.a])) \
                    if len(others) else p
                rec = _explained(g, g_in, both, tol, lambda q: region.inside(
                    q, spacing)).mean()
                exact = prec >= XTol.PRECISION and rec >= XTol.RECALL
                score = prec + rec
            if not exact:
                if not random_looking:
                    continue
                gsig = _signature(g, region.inside(g.mid), region.area)
                if not _similar(sig, gsig):
                    continue
                score = 1.0
            if best is None or (exact, score) > (best.exact, best.score):
                if exact:
                    ok = _explained(p, np.arange(len(p)), g, tol)
                    # pieces cut by the edge of the area: on a pattern piece
                    rest = np.where(~ok & region.inside(p.mid,
                                                        -2.0 * spacing))[0]
                    if len(rest):
                        ok[rest] = _lying_on(p, rest, g, tol)
                    expl = np.where(ok)[0]
                else:
                    expl = np.where(region.inside(p.mid, -spacing))[0]
                best = _Match(name, k, theta % 360.0, (dx, dy), expl, score,
                              exact)
    return best


# ---------------------------------------------------------------------------
# The drawn boundary
# ---------------------------------------------------------------------------
def _polygon_area(poly: List[Point]) -> float:
    a = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def _edge_points(poly: List[Point]) -> List[Point]:
    """Vertices and edge middles of a polygon."""
    out = []
    for p, q in zip(poly, poly[1:] + poly[:1]):
        out += [p, ((p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0)]
    return out


def _distance_to_outline(p: Point, poly: List[Point]) -> float:
    best = 1e18
    for a, b in zip(poly, poly[1:] + poly[:1]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 < 1e-18 else max(0.0, min(1.0, (
            (p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
        best = min(best, math.hypot(p[0] - a[0] - t * dx,
                                    p[1] - a[1] - t * dy))
    return best


def snap_boundaries(hatches: List[TextureHatch],
                    outlines: List[List[Point]]) -> int:
    """The outline of a texture is measured on its pieces, so it is a little
    rough. CAD programs usually draw the hatch boundary too: when a closed
    outline of the drawing follows the measured one (within a few gaps of
    the pattern, all around), it becomes the hatch boundary. Returns the
    number of hatches snapped (page coordinates)."""
    done = 0
    for h in hatches:
        tol = 3.0 * max(h.spacing, 1.0)
        area = _polygon_area(h.boundary)
        xs = [p[0] for p in h.boundary]
        ys = [p[1] for p in h.boundary]
        best, best_err = None, 1e18
        for poly in outlines:
            if len(poly) < 3:
                continue
            px = [p[0] for p in poly]
            py = [p[1] for p in poly]
            if min(px) > max(xs) + tol or max(px) < min(xs) - tol or \
                    min(py) > max(ys) + tol or max(py) < min(ys) - tol:
                continue
            if not 0.7 * area <= _polygon_area(poly) <= 1.4 * area:
                continue
            err = max(max(_distance_to_outline(p, poly)
                          for p in _edge_points(h.boundary)),
                      max(_distance_to_outline(p, h.boundary)
                          for p in _edge_points(poly)))
            if err <= tol and err < best_err:
                best, best_err = poly, err
        if best is not None:
            h.boundary = list(best)
            done += 1
    return done


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def _links(p: _Pieces, idx: np.ndarray) -> List[float]:
    """Link distances to try, small first: a few times the usual gap
    between the pieces, then larger for sparse patterns (bricks...)."""
    nn = _nn_distances(p.mid[idx],
                       np.arange(0, len(idx), max(1, len(idx) // 2000)))
    nn = nn[np.isfinite(nn)]
    first = min(max(2.5 * float(np.median(nn)) if len(nn) else XTol.LINK,
                    3.0), 25.0)
    out = [first]
    for f in (2.0, 4.0):
        if first * f <= 2.0 * XTol.SHORT and first * f > 1.3 * out[-1]:
            out.append(first * f)
    return out


def _groups(p: _Pieces, idx: np.ndarray, link: float) -> List[np.ndarray]:
    """Pieces lying within about `link` of each other: their middles are
    marked on a coarse raster whose connected areas are the groups (fast,
    even with 100 000 pieces)."""
    import cv2
    pts = p.mid[idx]
    lo = pts.min(axis=0)
    cell = link / 2.0
    span = pts.max(axis=0) - lo
    cell = max(cell, float(max(span)) / 8000.0)
    ij = np.floor((pts - lo) / cell).astype(int) + 1
    w, h = (ij.max(axis=0) + 2).tolist()
    img = np.zeros((h, w), np.uint8)
    img[ij[:, 1], ij[:, 0]] = 255
    img = cv2.dilate(img, np.ones((3, 3), np.uint8))
    _, labels = cv2.connectedComponents(img, connectivity=8)
    lab = labels[ij[:, 1], ij[:, 0]]
    order = np.argsort(lab, kind="stable")
    cuts = np.flatnonzero(np.diff(lab[order])) + 1
    return [idx[g] for g in np.split(order, cuts)
            if len(g) >= XTol.MIN_PIECES]


def _repetitive(p: _Pieces, grp: np.ndarray) -> bool:
    """Texture pieces repeat a few shapes: dots, or dashes of a few
    distinct lengths (text strokes and drawing details do not)."""
    if p.dot[grp].mean() >= 0.7:
        return True
    lengths = p.len[grp][~p.dot[grp]]
    if len(lengths) < 10:
        return False
    bins = np.round(np.log(lengths) / 0.03)
    counts = np.unique(bins, return_counts=True)[1]
    big = counts[counts >= max(3, 0.01 * len(lengths))]
    return len(big) <= 60 and big.sum() >= 0.7 * len(lengths)


def _style_key(s: Style) -> tuple:
    return (s.color, round(s.width, 2), s.pdf_layer)


def detect_textures(segments: List[RawSegment],
                    names=TEXTURES) -> TextureResult:
    """Find the standard texture patterns among the segments (dots are
    segments of zero length). Returns the remaining segments + hatches."""
    by_style: Dict[tuple, List[int]] = {}
    for i, s in enumerate(segments):
        if s.style.linetype == "CONTINUOUS":
            by_style.setdefault(_style_key(s.style), []).append(i)
    res = TextureResult(segments=[])
    used: set = set()
    t0 = time.monotonic()
    for ids in by_style.values():
        segs = [segments[i] for i in ids]
        p = _Pieces.from_segments(segs)
        short = np.where(p.len <= XTol.SHORT)[0]
        if len(short) < XTol.MIN_PIECES:
            continue
        long_ = np.where(p.len > XTol.SHORT)[0]
        free = np.ones(len(p), bool)
        tried: set = set()
        for link in _links(p, short):
            left = short[free[short]]
            if len(left) < XTol.MIN_PIECES:
                break
            for grp in _groups(p, left, link):
                key = (len(grp), int(grp[0]), int(grp[-1]))
                if key in tried or not _repetitive(p, grp):
                    continue                  # same group as before
                if time.monotonic() - t0 > XTol.TIME_BUDGET:
                    res.timed_out = True      # safe: pieces stay as lines
                    break
                tried.add(key)
                hatch, gone = _recognise(p, grp, long_[free[long_]], segs)
                if hatch is not None:
                    res.hatches.append(hatch)
                    res.pieces += len(gone)
                    free[gone] = False
                    used.update(ids[j] for j in gone)
    res.segments = [s for i, s in enumerate(segments) if i not in used]
    return res


def _recognise(p: _Pieces, grp: np.ndarray, long_: np.ndarray,
               segs: List[RawSegment]):
    """Best standard pattern for one group, or (None, [])."""
    gp = _Pieces(p.a[grp])
    nn = _nn_distances(gp.mid, np.arange(0, len(gp), max(1, len(gp) // 800)))
    nn = nn[np.isfinite(nn)]
    if not len(nn):
        return None, []
    spacing = float(np.percentile(nn, 90))
    if spacing <= 0:
        return None, []
    region = _Region(gp, spacing)
    if not region.outer or region.area <= 0:
        return None, []
    inner = np.where(region.inside(gp.mid, 2.0 * spacing))[0]
    if len(inner) < XTol.MIN_INSIDE:
        return None, []
    sig = _signature(gp, region.inside(gp.mid), region.area)
    # long lines of the same style in the area (brick courses, insulation)
    near = long_[region.inside(p.mid[long_])] if len(long_) else long_
    others = _Pieces(p.a[near]) if len(near) else _Pieces(np.zeros((0, 4)))
    best: Optional[_Match] = None
    for name in TEXTURES:
        low, high = DOT_SHARE.get(name, (0.0, 0.2))
        if not low <= sig.dot_share <= high:
            continue
        m = _match(name, gp, region, sig, spacing, inner, others)
        if m is not None and (best is None or (m.exact, m.score)
                              > (best.exact, best.score)):
            best = m
    if best is None:
        return None, []
    gone = [int(grp[j]) for j in best.explained.tolist()]
    if best.exact and len(near):
        # long lines (brick courses): drawn a little beyond the area so the
        # PDF lines lie on them from end to end
        lo = p.a[near].reshape(-1, 2).min(axis=0) - 2.0 * spacing
        hi = p.a[near].reshape(-1, 2).max(axis=0) + 2.0 * spacing
        g = _Pieces(render(best.name, best.scale, best.angle, best.origin,
                           [(lo[0], lo[1]), (hi[0], lo[1]), (hi[0], hi[1]),
                            (lo[0], hi[1])]))
        ok = _explained(others, np.arange(len(others)), g,
                        max(0.15, 0.12 * spacing))
        gone += [int(near[j]) for j in np.where(ok)[0].tolist()]
    st = segs[int(grp[0])].style

    def down(poly):
        return [(x, -y) for x, y in poly]
    hatch = TextureHatch(name=best.name, scale=best.scale, angle=best.angle,
                         origin=best.origin, boundary=down(region.outer),
                         holes=[down(h) for h in region.holes], style=st,
                         piece_count=len(gone), exact=best.exact,
                         spacing=spacing)
    return hatch, gone
