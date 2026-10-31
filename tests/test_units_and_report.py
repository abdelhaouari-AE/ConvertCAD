"""
Imperial units (inches, feet, 1/4" = 1'-0" scales) and the report in the
interface language (options, page notes, block list).
"""

import ezdxf
import pytest

from convertcad import i18n
from convertcad.core.constants import IMPERIAL_SCALES, UNITS
from convertcad.core.options import Options
from convertcad.core.pdfinfo import detect_scale, parse_imperial_scale
from convertcad.core.pipeline import convert
from convertcad.core.units import compute_scale

LANGS = [code for code in i18n.LANGUAGES if code != "en"]


@pytest.mark.parametrize("text,n", [
    ('1/4" = 1\'-0"', 48), ('SCALE: 1/8" = 1\'-0"', 96), ('1" = 20\'', 240),
    ('1 1/2" = 1\'-0"', 8), ("3/16” = 1’-0”", 64)])
def test_imperial_scales_are_read(text, n):
    assert parse_imperial_scale(text) == n
    assert detect_scale(text) == n


def test_metric_scales_still_read():
    assert detect_scale("Echelle : 1/100") == 100
    assert parse_imperial_scale("1:100") is None


def test_imperial_scale_list_is_consistent():
    for text, n in IMPERIAL_SCALES:
        assert parse_imperial_scale(text) == n


def test_inches_and_feet():
    # 1 pt on paper at 1/4" = 1'-0" (1:48) is 48/72 in = 0.6667 in
    assert compute_scale("in", 48) == pytest.approx(48 / 72)
    assert compute_scale("ft", 48) == pytest.approx(48 / 72 / 12)


def test_imperial_dxf_header(sample_plan, tmp_path):
    out = tmp_path / "plan.dxf"
    rep = convert(sample_plan, str(out), Options(units="ft",
                                                 scale_denominator=96))
    assert rep.success, rep.errors
    hdr = ezdxf.readfile(str(out)).header
    assert hdr["$INSUNITS"] == UNITS["ft"]["insunits"] == 2
    assert hdr["$MEASUREMENT"] == 0


@pytest.mark.parametrize("lang", LANGS)
def test_report_texts_are_translated(lang):
    """Options of the report, unit names and every report message shape."""
    table = i18n.table(lang)
    needed = set(i18n.NOTE_TEMPLATES) | {u["label"] for u in UNITS.values()}

    def record(text, **kw):
        needed.add(text)
        return text
    for opt in (Options(), Options(calibrated_units_per_pt=2.0,
                                   clip_rect=(0, 0, 10, 10), ocr=True,
                                   block_rotations=False,
                                   output_format="dwg", raster_mode=True)):
        opt.describe(record)
    missing = sorted(t for t in needed if t not in table)
    assert not missing, missing


def test_report_messages_in_french():
    i18n.set_language("fr")
    try:
        assert i18n.tr_note("Page 2: scale 1:100 read on the sheet.") == \
            "Feuille 2 : échelle 1:100 lue sur la feuille."
        assert i18n.tr_note("CC_SYMBOL_001: 3 entities x 20 insertions") == \
            "CC_SYMBOL_001 : 3 entités x 20 insertions"
        assert i18n.tr_note("Something new") == "Something new"
        opts = Options().describe(i18n.tr)
        assert opts["Zone"] == "feuille entière" and "Échelle" in opts
    finally:
        i18n.set_language("en")


def test_log_stays_english():
    assert Options().describe()["Area"] == "whole sheet"
