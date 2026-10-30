"""
Shared fixtures: synthetic PDF drawings generated on the fly.

Nothing binary is stored in the repository: every test PDF is drawn with
PyMuPDF (see convertcad/samples.py for the full demonstration plan).
"""

import os
import sys
import warnings

import pytest

warnings.simplefilter("ignore", FutureWarning)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from convertcad.core.compat import pymupdf  # noqa: E402
from convertcad.samples import make_sample_plan, make_sample_scan  # noqa: E402


@pytest.fixture(scope="session")
def sample_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("samples")


@pytest.fixture(scope="session")
def sample_plan(sample_dir):
    """2-page vector PDF: formwork plan (A3) + a page with /Rotate 90."""
    return make_sample_plan(str(sample_dir / "sample_plan.pdf"))


@pytest.fixture(scope="session")
def sample_scan(sample_dir):
    """Image-only version of the plan (simulated scan)."""
    return make_sample_scan(str(sample_dir / "sample_scan.pdf"))


def make_pdf(path, draw, width=600, height=400, rotation=0, metadata=None):
    """Create a one-page PDF; `draw(page)` adds the content."""
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    draw(page)
    if rotation:
        page.set_rotation(rotation)
    if metadata:
        doc.set_metadata(metadata)
    doc.save(str(path))
    doc.close()
    return str(path)


def stroke(page, items, color=(0, 0, 0), width=0.5, dashes=None,
           fill=None, close=False):
    """Draw a list of ('line', p, q) / ('bezier', p0, p1, p2, p3) /
    ('rect', x0, y0, x1, y1) / ('circle', c, r) / ('poly', [pts])."""
    sh = page.new_shape()
    for it in items:
        kind = it[0]
        if kind == "line":
            sh.draw_line(it[1], it[2])
        elif kind == "bezier":
            sh.draw_bezier(*it[1:5])
        elif kind == "rect":
            sh.draw_rect(pymupdf.Rect(*it[1:5]))
        elif kind == "circle":
            sh.draw_circle(it[1], it[2])
        elif kind == "poly":
            sh.draw_polyline(it[1])
    sh.finish(color=color if fill is None or color else None, width=width,
              dashes=dashes, fill=fill, closePath=close)
    sh.commit()


def arrow(page, tip, direction, length=7.0, half=1.2):
    import math
    dx, dy = direction
    n = math.hypot(dx, dy)
    dx, dy = dx / n, dy / n
    bx, by = tip[0] - dx * length, tip[1] - dy * length
    px, py = -dy * half, dx * half
    sh = page.new_shape()
    sh.draw_polyline([tip, (bx + px, by + py), (bx - px, by - py), tip])
    sh.finish(color=None, fill=(0, 0, 0), closePath=True)
    sh.commit()


def arc(page, center, r, a0, a1, width=0.25):
    """Circular arc from page angle a0 to a1 (degrees, y down like EArc:
    increasing angles turn clockwise on the sheet)."""
    import math
    sh = page.new_shape()
    p = (center[0] + r * math.cos(math.radians(a0)),
         center[1] + r * math.sin(math.radians(a0)))
    sh.draw_sector(center, p, a0 - a1, fullSector=False)   # beta > 0 turns
    sh.finish(color=(0, 0, 0), width=width, closePath=False)  # the other way
    sh.commit()


@pytest.fixture
def pdf_factory(tmp_path):
    counter = {"n": 0}

    def factory(draw, **kw):
        counter["n"] += 1
        return make_pdf(tmp_path / f"t{counter['n']}.pdf", draw, **kw)
    return factory
