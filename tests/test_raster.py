"""Scanned pages: tracing (OpenCV) and OCR (PP-OCR models with RapidOCR,
skipped if RapidOCR is not installed)."""

import pytest

from convertcad.core import Options, convert
from convertcad.core import ocr, ocr_store
from convertcad.core.ocr import OcrWord, merge_script
from convertcad.core.ocr_catalog import BY_ID
from convertcad.core.raster import merge_collinear

HAS_RAPIDOCR = ocr.available()


def test_merge_collinear_fragments():
    segs = [(0, 0, 10, 0), (9.5, 0.2, 20, 0.1), (30, 0, 40, 0),
            (0, 50, 0, 60)]
    merged = merge_collinear(segs)
    horiz = sorted(round(s[0]) for s in merged if abs(s[1] - s[3]) < 1)
    assert len(merged) == 3 and horiz == [0, 30]


def test_scanned_page_is_traced(sample_scan, tmp_path):
    rep = convert(sample_scan, str(tmp_path / "scan.dxf"),
                  Options(scale_denominator=100, ocr=False))
    assert rep.success
    assert rep.stats.lines + rep.stats.polylines > 100
    assert rep.stats.images == 1                     # scan kept underneath
    assert "IMG_RASTER" in rep.stats.layers
    assert any("traced" in n for n in rep.page_notes)


@pytest.mark.skipif(not HAS_RAPIDOCR, reason="RapidOCR not installed")
def test_ocr_reads_the_scan(sample_scan, tmp_path):
    """The built-in model (no download) reads the sample scan."""
    rep = convert(sample_scan, str(tmp_path / "scan.dxf"),
                  Options(scale_denominator=100, ocr=True))
    assert any("OCR text(s) (PP-OCR: English, French" in n
               for n in rep.page_notes)
    assert rep.stats.ocr_texts >= 20
    texts = _texts(tmp_path / "scan.dxf")
    joined = " | ".join(texts)
    assert "COFFRAGE" in joined                      # whole lines are read
    assert "6000" in texts
    assert "5000" in texts                           # vertical text
    assert any("Béton" in t or "Beton" in t for t in texts)


@pytest.fixture
def no_downloads(tmp_path, monkeypatch):
    """An empty models folder: only the built-in model exists."""
    monkeypatch.setenv("CONVERTCAD_OCR_MODELS", str(tmp_path / "models"))
    monkeypatch.setattr(ocr_store, "search_dirs",
                        lambda: [str(tmp_path / "models")])


@pytest.mark.skipif(not HAS_RAPIDOCR, reason="RapidOCR not installed")
def test_ocr_plan_falls_back_to_the_builtin_model(no_downloads):
    plan, note = ocr.make_plan("latin+arabic", "maximum")
    assert [p.pack.id for p in plan.passes] == ["latin"]
    assert plan.passes[0].rec == "" and plan.det == ""      # built in
    assert "Maximum accuracy models are not installed" in note
    assert "'Arabic' unavailable" in note
    plan, note = ocr.make_plan("arabic", "standard")        # script alone
    assert [p.pack.id for p in plan.passes] == ["latin"] and note
    plan, note = ocr.make_plan("eng+fra", "standard")       # 1.0 setting
    assert [p.pack.id for p in plan.passes] == ["latin"] and note == ""
    assert plan.description == "English, French… (Latin script)"


def test_ocr_plan_without_the_engine(monkeypatch):
    monkeypatch.setattr(ocr_store, "builtin_available", lambda: False)
    plan, note = ocr.make_plan("latin", "standard")
    assert plan is None and "OCR skipped" in note
    assert ocr.language_choices() == [("latin", BY_ID["latin"].label, False)]


def test_mixed_scripts_keep_each_reading():
    """Latin + Arabic: where the Arabic model reads Arabic, its reading
    replaces the Latin model's (garbage) reading of the same place."""
    arabic = BY_ID["arabic"].script
    base = [OcrWord("lSlJI", (100, 10, 200, 40), 60.0),
            OcrWord("PLAN DE MASSE", (100, 100, 300, 40), 95.0)]
    extra = [OcrWord("مخطط الكتلة", (95, 8, 210, 44), 90.0),
             OcrWord("PLAN DE MASSE", (100, 100, 300, 40), 70.0)]
    out = merge_script(base, extra, arabic)
    assert sorted(w.text for w in out) == ["PLAN DE MASSE", "مخطط الكتلة"]
    assert ocr.script_share("مخطط 12", arabic) == 1.0     # digits ignored
    assert ocr.script_share("PLAN", arabic) == 0.0


def _texts(path):
    import ezdxf
    msp = ezdxf.readfile(str(path)).modelspace()
    out = {e.dxf.text for e in msp.query("TEXT")}
    out |= {line for e in msp.query("MTEXT")
            for line in e.plain_text().splitlines()}
    return out


def test_tracing_can_be_disabled(sample_scan, tmp_path):
    rep = convert(sample_scan, str(tmp_path / "s.dxf"),
                  Options(raster_mode=False))
    assert rep.success and rep.stats.lines == 0 and rep.stats.images == 1


def test_onnx_runtime_telemetry_is_off():
    """ONNX Runtime records usage data (program path, system…) for Microsoft
    unless ORT_DISABLE_TELEMETRY is set before it is imported."""
    import os
    import convertcad  # noqa: F401
    assert os.environ.get("ORT_DISABLE_TELEMETRY") == "1"


def test_ocr_reads_large_sheets_at_150_dpi(monkeypatch):
    """The OCR gets the page at 150 dpi (small sheets: at least 2000 px)
    and its boxes come back in page-image pixels. Before 1.1 every page was
    shrunk to 2000 px, which lost the small text of large sheets."""
    import numpy as np

    from convertcad.core import raster
    seen = {}

    def fake_recognize(img, plan):
        seen["shape"] = img.shape
        return [OcrWord("NGF +12.50", (100, 200, 300, 40), 99.0)]
    monkeypatch.setattr(raster.ocr_engines, "recognize", fake_recognize)
    zoom = 300 / 72.0
    a1 = np.full((7016, 9933), 255, np.uint8)            # A1 at 300 dpi
    texts, boxes, warn = raster._run_ocr(a1, zoom, plan=None)
    assert warn is None and abs(seen["shape"][1] - 9933 / 2) <= 1
    assert boxes == [(200, 400, 600, 80)]
    assert abs(texts[0].origin[0] - 200 / zoom) < 0.01
    assert abs(texts[0].origin[1] - 480 / zoom) < 0.01
    a4 = np.full((2480, 3508), 255, np.uint8)            # A4 at 300 dpi
    raster._run_ocr(a4, zoom, plan=None)
    assert seen["shape"][1] == 2000


@pytest.mark.skipif(not HAS_RAPIDOCR, reason="RapidOCR not installed")
def test_engine_settings(monkeypatch):
    """Script models run without the upside-down text classifier (it turns
    Thai, Devanagari and Arabic lines over); no engine shrinks the page."""
    import rapidocr
    made = []

    class FakeRapidOCR:
        def __init__(self, params):
            made.append(params)
    monkeypatch.setattr(rapidocr, "RapidOCR", FakeRapidOCR)
    monkeypatch.setattr(ocr, "_ENGINES", {})
    ocr._engine("", ocr._Pass(BY_ID["thai"], "/models/th.onnx"))
    ocr._engine("", ocr._Pass(BY_ID["latin"]))
    assert made[0]["Global.use_cls"] is False
    assert "Global.use_cls" not in made[1]
    assert all(p["Global.max_side_len"] >= 8000 for p in made)


def test_circles_found_quickly_on_a_large_sheet():
    """A1-size image with grid lines and circles of 20-190 px radius: every
    circle is found, at its place, in seconds (1.1.0: minutes)."""
    import math
    import time

    import cv2
    import numpy as np

    from convertcad.core.raster import find_circles
    img = np.full((4677, 6622), 255, np.uint8)
    for x in range(0, 6622, 400):
        cv2.line(img, (x, 0), (x, 4676), 0, 2)
    for y in range(0, 4677, 400):
        cv2.line(img, (0, y), (6621, y), 0, 2)
    truth = [(600 + 700 * i, 900 + 900 * (i % 4), r)
             for i, r in enumerate((20, 25, 40, 80, 120, 160, 190, 60, 30))]
    for cx, cy, r in truth:
        cv2.circle(img, (cx, cy), r, 0, 2)
    binary = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                   cv2.THRESH_BINARY_INV, 35, 11)
    t = time.time()
    found = find_circles(img, binary)
    assert time.time() - t < 60
    for cx, cy, r in truth:
        assert any(math.hypot(cx - a, cy - b) <= 3 and abs(r - c) <= 3
                   for a, b, c in found), (cx, cy, r)


def _scan_of(pdf_factory, draw, dpi=300):
    """An image-only PDF: the drawing rasterised, like a scanner does."""
    from convertcad.core.compat import pymupdf
    src = pymupdf.open(pdf_factory(draw, width=600, height=420))
    pix = src[0].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)

    def put(page):
        page.insert_image(page.rect, pixmap=pix)
    return pdf_factory(put, width=600, height=420)


ARCS = [((150, 150), 60, -150, -30), ((350, 150), 25, 0, 120),
        ((480, 120), 40, 90, 270), ((420, 320), 15, 180, 300)]


def _arcs_and_lines(page):
    from conftest import arc, stroke
    for c, r, a0, a1 in ARCS:
        arc(page, c, r, a0, a1, width=0.6)
    stroke(page, [("line", (60, 150), (240, 150)),
                  ("line", (300, 60), (300, 260))], width=0.6)
    # a filled disc: its outline is not an arc of a stroke
    sh = page.new_shape()
    sh.draw_circle((250, 330), 22)
    sh.finish(color=None, fill=(0, 0, 0))
    sh.commit()


def test_arcs_traced_on_a_scan(pdf_factory, tmp_path):
    from convertcad.core.compat import pymupdf
    from convertcad.core.raster import vectorize_page
    scan = _scan_of(pdf_factory, _arcs_and_lines)
    res = vectorize_page(pymupdf.open(scan), 0, dpi=300, ocr=False)
    for (cx, cy), r, a0, a1 in ARCS:
        hits = [a for a in res.arcs
                if abs(a.center[0] - cx) < 1.0 and abs(a.center[1] - cy) < 1.0
                and abs(a.radius - r) < 0.5]
        assert len(hits) == 1, (cx, cy, r)
        sweep = (hits[0].end_angle - hits[0].start_angle) % 360.0
        assert abs(sweep - (a1 - a0)) < 10.0
    assert len(res.arcs) <= len(ARCS) + 1          # (+ the disc's outline)
    # the pipeline writes them as ARC entities
    rep = convert(scan, str(tmp_path / "arcs.dxf"),
                  Options(scale_denominator=1, ocr=False, write_log=False))
    assert rep.success and rep.stats.arcs >= len(ARCS)
    assert any("arc(s)" in n for n in rep.page_notes)
