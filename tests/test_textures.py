"""Texture hatches (sand, concrete, gravel, earth, brick, insulation, dots)
exploded by the CAD plotter into dashes and dots -> one standard HATCH."""

import math

import ezdxf
import pytest

from convertcad.core import Options, convert
from convertcad.core.compat import pymupdf
from convertcad.core.extractor import RawSegment, Style, extract_page
from convertcad.core.geometry import _dots, dedupe_segments, rebuild
from convertcad.core.textures import detect_textures, render

AREA = [(80, 60), (420, 80), (460, 330), (150, 360), (60, 250)]   # page pt


def _draw(page, name, scale, angle, origin=(0.0, 0.0), area=AREA):
    """Draw a standard pattern like AutoCAD plots it (every dash a line,
    every dot a zero-length line with round caps), with its boundary."""
    pieces = render(name, scale, angle, origin, [(x, -y) for x, y in area])
    sh = page.new_shape()
    for x1, y1, x2, y2 in pieces:
        sh.draw_line((x1, -y1), (x2, -y2))
    sh.finish(color=(0, 0, 0), width=0.18, lineCap=1)
    sh.commit()
    sh = page.new_shape()
    sh.draw_polyline(list(area) + [area[0]])
    sh.finish(color=(0, 0, 0), width=0.5)
    sh.commit()
    return len(pieces)


def _detect(path):
    pd = extract_page(pymupdf.open(path), 0)
    segs, _ = dedupe_segments(pd.segments)
    return detect_textures(segs + _dots(pd.segments))


@pytest.mark.parametrize("name,scale,angle,same", [
    ("DOTS", 2.0, 0.0, 180),       # dots
    ("GRAVEL", 1.0, 30.0, 360),    # many dash lengths, turned
    ("EARTH", 1.5, 45.0, 90),
    ("BRICK", 1.3, 45.0, 180),     # long courses + joints
    ("INSUL", 2.5, 0.0, 180),      # lines + dashed lines
])
def test_texture_recognised_exactly(pdf_factory, name, scale, angle, same):
    n = [0]

    def draw(page):
        n[0] = _draw(page, name, scale, angle, (0.7, 0.3))
    res = _detect(pdf_factory(draw, width=600, height=420))
    assert [h.name for h in res.hatches] == [name]
    h = res.hatches[0]
    assert h.exact and abs(h.scale / scale - 1.0) < 0.005
    d = (h.angle - angle) % same              # pattern symmetry
    assert min(d, same - d) < 0.5
    assert h.piece_count >= 0.98 * n[0]       # nearly every piece replaced
    assert len(res.segments) <= 7             # the drawn boundary stays


def test_random_looking_texture(pdf_factory):
    # sand: dots only, no small repeat -> accepted on its statistics
    small = [(100, 100), (300, 100), (300, 260), (100, 260)]
    res = _detect(pdf_factory(lambda p: _draw(p, "AR-SAND", 0.15, 0.0,
                                              area=small),
                              width=400, height=360))
    assert [h.name for h in res.hatches] == ["AR-SAND"]
    assert not res.hatches[0].exact
    assert abs(res.hatches[0].scale / 0.15 - 1.0) < 0.15


def test_textures_leave_other_drawings_alone():
    st = Style(color=(0, 0, 0), width=0.18)
    segs = []
    # text strokes of a few lengths and directions
    for w in range(300):
        x0, y0 = (w % 20) * 30.0, (w // 20) * 12.0
        for c in range(6):
            for k, (length, a) in enumerate([(2.0, 90), (1.2, 0), (2.5, 60),
                                             (1.6, 120)]):
                x, y = x0 + c * 3.0 + 0.3 * k, y0 + 0.5 * k
                segs.append(RawSegment((x, y), (
                    x + length * math.cos(math.radians(a)),
                    y + length * math.sin(math.radians(a))), st))
    # a grid of small squares (ceiling tiles)
    for i in range(40):
        for j in range(30):
            x, y = 700 + i * 8.0, 100 + j * 8.0
            segs += [RawSegment((x, y), (x + 6, y), st),
                     RawSegment((x + 6, y), (x + 6, y + 6), st),
                     RawSegment((x + 6, y + 6), (x, y + 6), st),
                     RawSegment((x, y + 6), (x, y), st)]
    res = detect_textures(segs)
    assert not res.hatches and len(res.segments) == len(segs)


def test_texture_hatch_written(pdf_factory, tmp_path):
    def draw(page):
        _draw(page, "EARTH", 1.5, 45.0, (0.5, 0.2))
    pdf = pdf_factory(draw, width=600, height=420)
    base = dict(scale_denominator=50, units="mm", auto_scale=False,
                write_log=False, block_detection=False)
    out = tmp_path / "earth.dxf"
    rep = convert(pdf, str(out), Options(**base))
    assert rep.success and rep.stats.pattern_hatches == 1
    assert any("EARTH" in n for n in rep.page_notes)
    msp = ezdxf.readfile(str(out)).modelspace()
    (h,) = msp.query("HATCH")
    assert h.dxf.pattern_name == "EARTH"
    # 1.5 pattern units per point, 1 pt = 25.4/72 mm on paper, 1:50
    assert h.dxf.pattern_scale == pytest.approx(1.5 * 25.4 / 72 * 50, rel=0.005)
    assert len(msp.query("LINE")) == 0 and len(msp.query("LWPOLYLINE")) == 1
    # the hatch keeps the drawn boundary (5 corners)
    assert len(h.paths[0].vertices) == 5
    # R12 has no HATCH: the pieces stay as lines
    out12 = tmp_path / "earth12.dxf"
    rep = convert(pdf, str(out12), Options(dxf_version="R12", **base))
    assert rep.success and rep.stats.pattern_hatches == 0
    assert len(ezdxf.readfile(str(out12)).modelspace().query("LINE")) > 1000


def test_texture_option_off(pdf_factory):
    pdf = pdf_factory(lambda p: _draw(p, "BRICK", 2.0, 0.0), width=600,
                      height=420)
    pd = extract_page(pymupdf.open(pdf), 0)
    assert not rebuild(pd, hatch_patterns=False).texture_hatches
    assert [t.name for t in rebuild(pd).texture_hatches] == ["BRICK"]
