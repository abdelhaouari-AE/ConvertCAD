"""Step 5 — repeated symbols become BLOCK definitions + INSERTs."""

import math

from conftest import stroke
from convertcad.core.blocks import detect_blocks
from convertcad.core.compat import pymupdf
from convertcad.core.extractor import extract_page
from convertcad.core.geometry import rebuild


def _symbols(page, positions, size=8):
    for x, y in positions:
        stroke(page, [("rect", x, y, x + size, y + size)], width=0.5,
               close=True)
        stroke(page, [("line", (x, y), (x + size, y + size)),
                      ("line", (x, y + size), (x + size, y))], width=0.18)


def test_repeated_symbols_become_one_block(pdf_factory):
    pos = [(50 + 60 * i, 80) for i in range(5)]
    rp = rebuild(extract_page(pymupdf.open(
        pdf_factory(lambda p: _symbols(p, pos))), 0))
    br = detect_blocks(rp, min_repeats=3)
    assert len(br.definitions) == 1 and len(br.inserts[0]) == 5
    assert all(e.consumed for e in br.definitions[0].entities())


def test_min_repeats_is_respected(pdf_factory):
    pos = [(50, 80), (150, 80)]
    rp = rebuild(extract_page(pymupdf.open(
        pdf_factory(lambda p: _symbols(p, pos))), 0))
    assert not detect_blocks(rp, min_repeats=3).definitions
    assert len(detect_blocks(rp, min_repeats=2).definitions) == 1


def test_long_lines_do_not_glue_symbols(pdf_factory):
    """A beam/axis line touching every symbol must not merge them."""
    pos = [(50 + 100 * i, 80) for i in range(5)]

    def draw(page):
        _symbols(page, pos)
        stroke(page, [("line", (20, 84), (580, 84))], color=(0, 0, 1),
               width=0.3)
    rp = rebuild(extract_page(pymupdf.open(pdf_factory(draw)), 0))
    br = detect_blocks(rp, min_repeats=3)
    assert len(br.definitions) == 1 and len(br.inserts[0]) == 5


def test_sample_plan_blocks(sample_plan):
    from convertcad.core.annotations import reconstruct
    rp = rebuild(extract_page(pymupdf.open(sample_plan), 0))
    reconstruct(rp)                 # as in the pipeline: dims consumed first
    br = detect_blocks(rp)
    sizes = sorted(len(i) for i in br.inserts)
    assert sizes == [3, 20]                  # doors x3, columns x20


# ---------------------------------------------------------------------------
# Rotated and mirrored copies: one block, INSERTs with rotation / xscale -1.
# The check is geometric: the exploded INSERTs must give exactly the lines
# written when block detection is off.
# ---------------------------------------------------------------------------
_F_SHAPE = [((0, 0), (0, 10)), ((0, 0), (6, 0)), ((0, 5), (4, 5))]
# page-coordinate matrices (y down): identity, 90, 180, 270, mirror,
# mirror + 90, mirror + 180, mirror + 270
_ORIENT = [((1, 0), (0, 1)), ((0, -1), (1, 0)), ((-1, 0), (0, -1)),
           ((0, 1), (-1, 0)), ((-1, 0), (0, 1)), ((0, 1), (1, 0)),
           ((1, 0), (0, -1)), ((0, -1), (-1, 0))]


def _draw_f(page, x, y, m):
    lines = []
    for p, q in _F_SHAPE:
        a = (x + m[0][0] * p[0] + m[0][1] * p[1],
             y + m[1][0] * p[0] + m[1][1] * p[1])
        b = (x + m[0][0] * q[0] + m[0][1] * q[1],
             y + m[1][0] * q[0] + m[1][1] * q[1])
        lines.append(("line", a, b))
    stroke(page, lines, width=0.35)


def _segments(doc):
    """Every straight piece in model space (INSERTs exploded), rounded."""
    from collections import Counter
    out = Counter()

    def add(a, b):
        a = (round(a[0], 1), round(a[1], 1))
        b = (round(b[0], 1), round(b[1], 1))
        out[tuple(sorted((a, b)))] += 1

    def walk(entities):
        for e in entities:
            t = e.dxftype()
            if t == "INSERT":
                walk(e.virtual_entities())
            elif t == "LINE":
                add(e.dxf.start, e.dxf.end)
            elif t == "LWPOLYLINE":
                # WCS, not the raw OCS points: a mirrored INSERT explodes
                # into polylines with extrusion (0, 0, -1)
                pts = [(v.x, v.y) for v in e.vertices_in_wcs()]
                if e.closed:
                    pts.append(pts[0])
                for a, b in zip(pts, pts[1:]):
                    add(a, b)
    walk(doc.modelspace())
    return out


def test_rotated_and_mirrored_copies_are_exact(pdf_factory, tmp_path):
    import ezdxf

    from convertcad.core.pipeline import Options, convert

    def draw(page):
        k = 0
        for x in (60, 110, 160):                    # 3 upright copies
            _draw_f(page, x, 60, _ORIENT[0])
        for m in _ORIENT[1:]:                       # 7 other orientations
            _draw_f(page, 60 + 50 * k, 160, m)
            k += 1
    pdf = pdf_factory(draw, width=500, height=260)
    with_blocks = tmp_path / "b.dxf"
    without = tmp_path / "n.dxf"
    rep = convert(pdf, str(with_blocks),
                  Options(scale_denominator=50, dimensions=False,
                          leaders=False, merge_dashes=False,
                          hatch_patterns=False))
    assert rep.success
    assert rep.stats.blocks_defined == 1 and rep.stats.blocks_inserted == 10
    convert(pdf, str(without),
            Options(scale_denominator=50, dimensions=False, leaders=False,
                    merge_dashes=False, hatch_patterns=False,
                    block_detection=False))
    a = _segments(ezdxf.readfile(str(with_blocks)))
    b = _segments(ezdxf.readfile(str(without)))
    assert a == b and sum(a.values()) == 30
    inserts = ezdxf.readfile(str(with_blocks)).modelspace().query("INSERT")
    mirrored = [i for i in inserts if i.dxf.xscale < 0]
    assert len(mirrored) == 4


def test_rotations_can_be_switched_off(pdf_factory):
    def draw(page):
        for x in (60, 110, 160):
            _draw_f(page, x, 60, _ORIENT[0])
        _draw_f(page, 260, 60, _ORIENT[1])
    rp = rebuild(extract_page(pymupdf.open(pdf_factory(draw)), 0))
    assert len(detect_blocks(rp, 3, rotations=False).inserts[0]) == 3
    rp = rebuild(extract_page(pymupdf.open(pdf_factory(draw)), 0))
    assert len(detect_blocks(rp, 3, rotations=True).inserts[0]) == 4


def _draw_turned(page, x, y, degrees, mirror=False):
    """The F shape and a small arc, turned by any angle (page, y down)."""
    from conftest import arc
    t = math.radians(degrees)
    c, s = math.cos(t), math.sin(t)

    def at(p):
        px = -p[0] if mirror else p[0]
        return (x + c * px - s * p[1], y + s * px + c * p[1])
    stroke(page, [("line", at(p), at(q)) for p, q in _F_SHAPE], width=0.35)
    centre = at((3, 12))
    a0 = (180.0 if mirror else 0.0) + degrees
    arc(page, centre, 2.0, a0 - 60 if mirror else a0, a0 if mirror
        else a0 + 60, width=0.35)


def test_copies_turned_by_any_angle(pdf_factory, tmp_path):
    import ezdxf

    from convertcad.core.pipeline import Options, convert
    angles = [0, 30, 75, 133, 210, 301]

    def draw(page):
        for k, a in enumerate(angles):
            _draw_turned(page, 60 + 60 * k, 80, a)
        _draw_turned(page, 200, 180, 50, mirror=True)
    pdf = pdf_factory(draw, width=500, height=260)
    rp = rebuild(extract_page(pymupdf.open(pdf), 0))
    br = detect_blocks(rp, min_repeats=3)
    assert len(br.definitions) == 1 and len(br.inserts[0]) == 7
    opt = dict(scale_denominator=50, dimensions=False, leaders=False,
               merge_dashes=False, hatch_patterns=False, write_log=False)
    rep = convert(pdf, str(tmp_path / "b.dxf"), Options(**opt))
    assert rep.stats.blocks_defined == 1 and rep.stats.blocks_inserted == 7
    convert(pdf, str(tmp_path / "n.dxf"),
            Options(block_detection=False, **opt))
    msp = ezdxf.readfile(str(tmp_path / "b.dxf")).modelspace()
    rots = sorted(round(i.dxf.rotation) % 360 for i in msp.query("INSERT")
                  if i.dxf.xscale > 0)
    # page angles turn clockwise on the sheet: DXF angles are opposite
    assert rots == sorted((-a) % 360 for a in angles)
    assert sum(1 for i in msp.query("INSERT") if i.dxf.xscale < 0) == 1
    # the exploded copies lie on the lines written without blocks (0.05 mm)
    with_b = _segments(ezdxf.readfile(str(tmp_path / "b.dxf")))
    without = _segments(ezdxf.readfile(str(tmp_path / "n.dxf")))
    assert sum(with_b.values()) == sum(without.values()) == 21
    for (a, b) in with_b:
        assert any(math.dist(a, p) < 0.2 and math.dist(b, q) < 0.2
                   for p, q in without), (a, b)
