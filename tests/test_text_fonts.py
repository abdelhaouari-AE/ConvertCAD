"""
Converted text keeps its look (core/fonts.py, dxf_writer.py): the PDF font
gives the DXF text style (Arial, Times New Roman, Courier New, bold /
italic files), its own capital height, a width factor when the PDF text is
condensed, and the alignment of paragraphs. Accented letters survive the
DWG conversion.
"""

import ezdxf
import pymupdf
import pytest

from convertcad.core import dwg, fonts
from convertcad.core.dxf_writer import group_text_paragraphs
from convertcad.core.extractor import RawText
from convertcad.core.pipeline import Options, convert


@pytest.mark.parametrize("pdf_name,flags,family,file", [
    ("ABCDEF+Arial-BoldMT", 0, "Arial", "arialbd.ttf"),
    ("Helvetica", 0, "Arial", "arial.ttf"),
    ("TimesNewRomanPS-ItalicMT", 0, "Times New Roman", "timesi.ttf"),
    ("Times-Roman", 0, "Times New Roman", "times.ttf"),
    ("CourierNewPSMT", 16, "Courier New", "courbd.ttf"),
    ("ArialNarrow", 0, "Arial Narrow", "arialn.ttf"),
    ("XYZABC+Calibri", 2, "Calibri", "calibrii.ttf"),
    ("ISOCPEUR", 0, "ISOCPEUR", "isocpeur.ttf"),
])
def test_pdf_fonts_map_to_cad_fonts(pdf_name, flags, family, file):
    f = fonts.resolve(pdf_name, flags)
    assert (f.family, f.file, f.known) == (family, file, True)


def test_unknown_font_is_shown_with_arial():
    f = fonts.resolve("SomeOddFont-Regular")
    assert f.family == "Arial" and not f.known and f.cap is None


def test_width_factor_keeps_the_pdf_length():
    f = fonts.resolve("Helvetica")
    text = "Réseau d'évacuation des eaux pluviales"
    natural = fonts.natural_width(f, text, 2.5)
    assert fonts.width_factor(f, text, 2.5, natural) == 1.0      # same font
    assert fonts.width_factor(f, text, 2.5, natural * 0.7) == \
        pytest.approx(0.7, abs=0.01)                              # condensed
    assert fonts.width_factor(f, "مرحبا", 2.5, 10) == 1.0          # unmeasured


def _text_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=400)
    page.insert_text((40, 60), "Helvetica: Échelle, béton armé", fontname="helv",
                     fontsize=10)
    page.insert_text((40, 90), "Courier: côte NGM +3,50", fontname="cour",
                     fontsize=10)
    page.insert_text((40, 120), "Times: façade", fontname="tiro", fontsize=10)
    for i, line in enumerate(["STATION D'ÉPURATION", "Lot 3 Génie civil",
                              "Plan de coffrage"]):
        w = pymupdf.get_text_length(line, "helv", 11)
        page.insert_text((400 - w / 2, 250 + i * 15), line, fontname="helv",
                         fontsize=11)
    doc.save(str(path))
    return path


def test_text_size_font_and_alignment(tmp_path):
    pdf = _text_pdf(tmp_path / "t.pdf")
    out = tmp_path / "t.dxf"
    rep = convert(str(pdf), str(out), Options(scale_denominator=100))
    assert rep.success, rep.errors
    doc = ezdxf.readfile(str(out))
    msp = doc.modelspace()
    texts = {e.dxf.text.split(":")[0]: e for e in msp.query("TEXT")}
    mm = 10 * 25.4 / 72 * 100                         # 10 pt at 1:100, in mm
    # each font with its own capital height (Courier New is much smaller)
    assert texts["Helvetica"].dxf.height == pytest.approx(0.716 * mm, rel=0.01)
    assert texts["Courier"].dxf.height == pytest.approx(0.571 * mm, rel=0.01)
    assert texts["Times"].dxf.height == pytest.approx(0.662 * mm, rel=0.01)
    assert texts["Courier"].dxf.style == "Courier New"
    assert doc.styles.get("Times New Roman").dxf.font == "times.ttf"
    assert "é" in texts["Helvetica"].dxf.text
    # the centred title block lines stay centred, as one paragraph
    (title,) = [m for m in msp.query("MTEXT") if "PURATION" in m.text]
    assert title.dxf.attachment_point == 2


def test_centred_and_right_aligned_paragraphs():
    def line(x, y, w, text):
        return RawText(text=text, origin=(x, y), height=10, rotation=0,
                       width=w)
    centred = [line(300 - w / 2, 100 + i * 14, w, f"line {i}")
               for i, w in enumerate((120, 60, 90))]
    right = [line(500 - w, 300 + i * 14, w, f"r {i}")
             for i, w in enumerate((80, 40))]
    groups = group_text_paragraphs(centred + right)
    aligns = sorted(a for g, a in groups if len(g) > 1)
    assert aligns == ["center", "right"]


@pytest.mark.skipif(not dwg.find_tools().available,
                    reason="LibreDWG not built")
def test_accents_survive_the_dwg(tmp_path):
    pdf = _text_pdf(tmp_path / "t.pdf")
    out = tmp_path / "t.dwg"
    rep = convert(str(pdf), str(out), Options(scale_denominator=100))
    assert rep.success, rep.errors
    back = tmp_path / "back.dxf"
    tools = dwg.find_tools()
    dwg._run([tools.dwg2dxf, "-y", "-o", str(back), str(out)], tools)
    doc = ezdxf.readfile(str(back))
    words = " ".join(e.dxf.text for e in doc.modelspace().query("TEXT"))
    words += " ".join(e.text for e in doc.modelspace().query("MTEXT"))
    assert "béton armé" in words and "ÉPURATION" in words
    assert "?" not in words and "�" not in words
