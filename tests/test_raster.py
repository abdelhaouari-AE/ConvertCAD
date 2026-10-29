"""Scanned pages: tracing (OpenCV) and OCR (Tesseract, skipped if absent)."""

import pytest

from convertcad.core import Options, convert
from convertcad.core.raster import (merge_collinear, find_tesseract,
                                    tesseract_status)

HAS_TESSERACT = find_tesseract() is not None
try:
    import rapidocr  # noqa: F401
    HAS_RAPIDOCR = True
except ImportError:                                    # pragma: no cover
    HAS_RAPIDOCR = False


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


@pytest.mark.skipif(not HAS_TESSERACT, reason="Tesseract not installed")
def test_ocr_reads_the_scan_tesseract(sample_scan, tmp_path):
    assert tesseract_status()["available"]
    rep = convert(sample_scan, str(tmp_path / "scan.dxf"),
                  Options(scale_denominator=100, ocr=True, ocr_vertical=True,
                          ocr_engine="tesseract"))
    assert rep.stats.ocr_texts >= 20
    assert any("(Tesseract)" in n for n in rep.page_notes)
    words = _texts(tmp_path / "scan.dxf")
    assert {"COFFRAGE", "6000"} <= words
    assert "5000" in words                           # vertical text pass


@pytest.mark.skipif(not HAS_RAPIDOCR, reason="RapidOCR not installed")
def test_ocr_reads_the_scan_rapidocr(sample_scan, tmp_path):
    rep = convert(sample_scan, str(tmp_path / "scan.dxf"),
                  Options(scale_denominator=100, ocr=True,
                          ocr_engine="rapidocr"))
    assert any("(RapidOCR)" in n for n in rep.page_notes)
    texts = _texts(tmp_path / "scan.dxf")
    joined = " | ".join(texts)
    assert "COFFRAGE" in joined                      # whole lines are read
    assert "6000" in texts
    assert "5000" in texts                           # vertical, no 2nd pass
    assert any("Béton" in t or "Beton" in t for t in texts)


def test_ocr_engine_resolution_falls_back():
    from convertcad.core.ocr import resolve_engine
    engine, note = resolve_engine("auto", "eng+fra")
    assert engine in ("tesseract", "rapidocr", "paddleocr", "")
    engine, note = resolve_engine("unknown-engine", "eng")
    assert engine in ("tesseract", "rapidocr", "paddleocr", "")


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
