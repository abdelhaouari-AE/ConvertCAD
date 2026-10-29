"""Step 4 — dimensions (arrows and ticks) and leaders."""

from conftest import arrow, stroke
from convertcad.core.annotations import DIM_TEXT_RE, reconstruct
from convertcad.core.compat import pymupdf
from convertcad.core.extractor import extract_page
from convertcad.core.geometry import rebuild


def _analyse(path, **kw):
    pd = extract_page(pymupdf.open(path), 0)
    rp = rebuild(pd)
    return rp, reconstruct(rp, **kw)


def test_dimension_text_regex():
    for ok in ("3500", "3 500", "3.50", "12,5", "R25", "Ø60", "45°",
               "1200 mm", "24000"):
        assert DIM_TEXT_RE.match(ok), ok
    for bad in ("+3.50", "C25/30", "Voile", "2026-10-24", "1/100"):
        assert not DIM_TEXT_RE.match(bad), bad


def _chain(page, xs, y, text_size=8):
    for x in xs:
        stroke(page, [("line", (x, y + 20), (x, y - 5))], width=0.25)
    for xa, xb in zip(xs, xs[1:]):
        stroke(page, [("line", (xa, y), (xb, y))], width=0.25)
        arrow(page, (xa, y), (-1, 0))
        arrow(page, (xb, y), (1, 0))
        page.insert_text(((xa + xb) / 2 - 9, y - 3), str(int(xb - xa) * 10),
                         fontsize=text_size)


def test_arrow_dimension_chain(pdf_factory):
    xs = [50, 150, 300, 420]
    _, ann = _analyse(pdf_factory(lambda p: _chain(p, xs, 100)))
    assert len(ann.dimensions) == 3
    assert sorted(d.text for d in ann.dimensions) == ["1000", "1200", "1500"]
    for d in ann.dimensions:          # each spans exactly one interval
        assert abs(abs(d.tip2[0] - d.tip1[0]) - int(d.text) / 10) < 0.5
    assert not ann.dim_raw_texts


def test_tick_dimension_chain_vertical(pdf_factory):
    ys = [60, 200, 340]

    def draw(page):
        x = 300
        stroke(page, [("line", (x, ys[0] - 6), (x, ys[-1] + 6))], width=0.25)
        for y in ys:
            stroke(page, [("line", (x - 30, y), (x + 5, y))], width=0.25)
            stroke(page, [("line", (x - 3.5, y + 3.5), (x + 3.5, y - 3.5))],
                   width=0.5)
        for ya, yb in zip(ys, ys[1:]):
            page.insert_text((x - 3, (ya + yb) / 2 + 9), "5000", fontsize=8,
                             rotate=90)
    _, ann = _analyse(pdf_factory(draw, width=400, height=420))
    assert len(ann.dimensions) == 2
    assert all(d.kind == "tick" and d.text == "5000" for d in ann.dimensions)


def test_ticks_can_be_disabled(pdf_factory):
    ys = [60, 200]

    def draw(page):
        stroke(page, [("line", (300, 54), (300, 206))], width=0.25)
        for y in ys:
            stroke(page, [("line", (296.5, y + 3.5), (303.5, y - 3.5))],
                   width=0.5)
        page.insert_text((297, 140), "5000", fontsize=8, rotate=90)
    _, ann = _analyse(pdf_factory(draw, width=400, height=300),
                      enable_ticks=False)
    assert not ann.dimensions and len(ann.dim_raw_texts) == 1


def test_leader_with_text_on_the_left(pdf_factory):
    def draw(page):
        tip, mid, land = (300, 200), (260, 150), (225, 150)
        stroke(page, [("poly", [tip, mid, land])], width=0.25)
        arrow(page, tip, (tip[0] - mid[0], tip[1] - mid[1]))
        page.insert_text((176, 153), "Cuve D=3.00", fontsize=8)  # ends 4pt before
    _, ann = _analyse(pdf_factory(draw))
    assert len(ann.leaders) == 1 and ann.leaders[0].text.text == "Cuve D=3.00"


def test_grid_bubble_numbers_are_not_dim_raw(pdf_factory):
    def draw(page):
        stroke(page, [("circle", (100, 100), 10)], width=0.35)
        page.insert_text((96.5, 103.5), "2", fontsize=10)
        page.insert_text((200, 200), "3.50", fontsize=8)
    _, ann = _analyse(pdf_factory(draw))
    assert [t.text for t in ann.dim_raw_texts] == ["3.50"]


def test_sample_plan_annotations(sample_plan):
    pd = extract_page(pymupdf.open(sample_plan), 0)
    rp = rebuild(pd)
    ann = reconstruct(rp)
    texts = sorted(d.text for d in ann.dimensions)
    assert texts == ["24000", "5000", "5000", "5000", "6000", "6000",
                     "6000", "6000"]
    assert len(ann.leaders) == 2
    assert [t.text for t in ann.dim_raw_texts] == ["3.50"]
