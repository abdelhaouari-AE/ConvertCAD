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
