"""Step 1 — PDF reading: coordinates, rotation, styles, text, page kind."""

import math

from conftest import stroke
from convertcad.core.compat import pymupdf
from convertcad.core.extractor import classify, classify_linetype, extract_page


def test_linetype_classification():
    assert classify_linetype(None) == "CONTINUOUS"
    assert classify_linetype("[] 0") == "CONTINUOUS"
    assert classify_linetype("[ 4 2 ] 0") == "DASHED"
    assert classify_linetype("[12 3 2 3] 0") == "CENTER"
    assert classify_linetype("[12 3 2 3 2 3] 0") == "PHANTOM"
    assert classify_linetype("[6 2 3 2] 0") == "DASHDOT"


def test_page_classification_rules():
    assert classify(3000, 0.0, 50) == "vector"
    assert classify(3, 0.98, 0) == "scanned"
    assert classify(120, 0.95, 0) == "scanned"      # scan + a stamp/frame
    assert classify(0, 0.0, 0) == "empty"
    assert classify(5000, 0.9, 10) == "vector"      # vectors over a photo


def test_unrotated_coordinates(pdf_factory):
    path = pdf_factory(lambda p: stroke(p, [("line", (100, 100), (300, 100))]))
    pd = extract_page(pymupdf.open(path), 0)
    assert pd.width == 600 and pd.height == 400
    s = pd.segments[0]
    assert {s.p1, s.p2} == {(100.0, 100.0), (300.0, 100.0)}


def test_rotated_page_matches_display(pdf_factory):
    """/Rotate 90: geometry and text must follow what the viewer shows."""
    def draw(page):
        stroke(page, [("line", (100, 100), (300, 100))])
        page.insert_text((100, 200), "HELLO", fontsize=20)
    path = pdf_factory(draw, rotation=90)
    pd = extract_page(pymupdf.open(path), 0)
    assert (pd.width, pd.height) == (400, 600)          # displayed size
    s = pd.segments[0]
    xs = sorted(round(v, 3) for v in (s.p1[0], s.p2[0]))
    ys = sorted(round(v, 3) for v in (s.p1[1], s.p2[1]))
    assert xs == [300.0, 300.0] and ys == [100.0, 300.0]   # now vertical
    t = pd.texts[0]
    assert t.text == "HELLO"
    assert abs(t.rotation + 90) < 1e-6                   # reads downward
    assert abs(t.origin[0] - 200) < 1e-3 and abs(t.origin[1] - 100) < 1e-3


def test_styles_colors_and_fills(pdf_factory):
    def draw(page):
        stroke(page, [("line", (10, 10), (100, 10))], color=(1, 0, 0),
               width=0.7, dashes="[12 3 2 3] 0")
        stroke(page, [("rect", 50, 50, 80, 80)], color=None,
               fill=(0, 0.5, 1), close=True)
    pd = extract_page(pymupdf.open(pdf_factory(draw)), 0)
    seg = pd.segments[0]
    assert seg.style.color == (255, 0, 0)
    assert abs(seg.style.width - 0.7) < 1e-6
    assert seg.style.linetype == "CENTER"
    assert len(pd.fills) == 1 and pd.fills[0].color == (0, 128, 255)
    assert abs(pd.fills[0].area - 900) < 1e-6


def test_text_width_and_center(pdf_factory):
    pd = extract_page(pymupdf.open(pdf_factory(
        lambda p: p.insert_text((100, 100), "3500", fontsize=10))), 0)
    t = pd.texts[0]
    assert t.width > 15                                   # 4 digits ~ 22 pt
    cx, cy = t.center()
    assert 100 < cx < 100 + t.width and cy < 100          # above the baseline
    assert math.isclose(t.rotation, 0.0, abs_tol=1e-6)


def test_sample_plan_kinds(sample_plan):
    doc = pymupdf.open(sample_plan)
    assert extract_page(doc, 0).kind == "vector"
    assert extract_page(doc, 1).rotation == 90


def test_sample_scan_is_scanned(sample_scan):
    pd = extract_page(pymupdf.open(sample_scan), 0)
    assert pd.kind == "scanned" and pd.image_coverage > 0.95
    assert pd.images[0].width_px > 1000
