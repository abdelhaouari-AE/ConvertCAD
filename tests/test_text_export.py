"""
List of texts (.csv / .txt): every text of the drawing with its sheet, its
position in the drawing and on the paper sheet — for the conversion, the
command line, several sheets, DWG output and the save of the interface
(layer edits applied).
"""

import csv
import math
import os

import pytest

from conftest import stroke
from convertcad.cli import main as cli_main
from convertcad.core import Options, convert, dwg
from convertcad.core.compat import pymupdf
from convertcad.core.layer_edits import LayerEdit
from convertcad.core.postprocess import finalize
from convertcad.core.text_export import plain_mtext

MM = 72 / 25.4
PT = 25.4 / 72                        # one point in mm
SCALE = 100 * PT                      # 1:100 in mm: drawing mm per point


def _arrow(page, tip, direction, length=2.5 * MM):
    dx, dy = direction
    n = math.hypot(dx, dy)
    dx, dy = dx / n, dy / n
    half = length / 6
    bx, by = tip[0] - dx * length, tip[1] - dy * length
    sh = page.new_shape()
    sh.draw_polyline([tip, (bx - dy * half, by + dx * half),
                      (bx + dy * half, by - dx * half), tip])
    sh.finish(color=None, fill=(0, 0, 0), closePath=True)
    sh.commit()


def _sheet(page):
    """A note, a 2-line paragraph, a dimension, a leader and a value that
    matches no dimension."""
    page.insert_text((100, 50), "GENERAL NOTES", fontsize=10)
    page.insert_text((100, 300), "Concrete C30/37", fontsize=8)
    page.insert_text((100, 312.8), "Steel FeE500", fontsize=8)
    xa, xb, y = 300, 300 + 5000 / SCALE, 150
    for x in (xa, xb):
        stroke(page, [("line", (x, y + 20), (x, y - 2 * MM))], width=0.25)
    stroke(page, [("line", (xa, y), (xb, y))], width=0.25)
    _arrow(page, (xa, y), (-1, 0))
    _arrow(page, (xb, y), (1, 0))
    page.insert_text(((xa + xb) / 2 - 9, y - 1.5), "5000", fontsize=9)
    tip, elbow, end = (150, 200), (190, 240), (230, 240)
    stroke(page, [("poly", [tip, elbow, end])], width=0.25)
    _arrow(page, tip, (tip[0] - elbow[0], tip[1] - elbow[1]))
    page.insert_text((232, 243), "SLAB 20 cm", fontsize=9)
    page.insert_text((450, 350), "3.50", fontsize=9)


def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _by_text(rows):
    return {r["text"]: r for r in rows}


def test_text_list_of_a_drawing(pdf_factory, tmp_path):
    pdf = pdf_factory(_sheet)
    out = tmp_path / "plan.dxf"
    rep = convert(pdf, str(out), Options(scale_denominator=100,
                                         export_texts="both"))
    assert rep.success
    csv_path, txt_path = (str(tmp_path / "plan_texts.csv"),
                          str(tmp_path / "plan_texts.txt"))
    assert rep.text_files == [csv_path, txt_path]
    assert csv_path in rep.render()
    rows = _by_text(_read_csv(csv_path))
    assert {k: rows[k]["kind"] for k in rows} == {
        "GENERAL NOTES": "text",
        "Concrete C30/37\nSteel FeE500": "paragraph",
        "5000": "dimension", "SLAB 20 cm": "leader", "3.50": "value"}
    note = rows["GENERAL NOTES"]
    assert note["pdf"] == os.path.basename(pdf)
    assert note["drawing"] == "plan.dxf" and note["page"] == "1"
    assert note["layer"] == "TEXT" and float(note["rotation"]) == 0
    # position in the drawing (1:100, mm) and on the sheet (mm, top-left)
    assert abs(float(note["x"]) - 100 * SCALE) < 1
    assert abs(float(note["y"]) - (400 - 50) * SCALE) < 1
    assert abs(float(note["sheet_x_mm"]) - 100 * PT) < 0.2
    assert abs(float(note["sheet_y_mm"]) - 50 * PT) < 0.2
    assert rows["5000"]["layer"] == "DIM" and rows["3.50"]["layer"] == \
        "DIM_RAW"
    # reading order: top to bottom
    order = [r["text"] for r in _read_csv(csv_path)]
    assert order.index("GENERAL NOTES") < order.index("5000") < \
        order.index("SLAB 20 cm")
    with open(txt_path, encoding="utf-8") as fh:
        txt = fh.read()
    assert "== Sheet 1 ==" in txt
    assert "Concrete C30/37 // Steel FeE500  [" in txt
    assert "GENERAL NOTES  [3527.78, 12347.22 | 35.3, 17.6 mm | text, " \
           "TEXT]" in txt


def test_text_list_formats_and_off(pdf_factory, tmp_path):
    pdf = pdf_factory(_sheet)
    convert(pdf, str(tmp_path / "a.dxf"), Options())
    assert not [f for f in os.listdir(tmp_path) if "_texts" in f]
    rep = convert(pdf, str(tmp_path / "b.dxf"), Options(export_texts="csv"))
    assert [os.path.basename(p) for p in rep.text_files] == ["b_texts.csv"]
    assert Options.from_dict({"export_texts": "xls"}).export_texts == ""


def _two_sheets(path):
    doc = pymupdf.open()
    for k, (w, h) in enumerate(((600, 400), (400, 600))):
        page = doc.new_page(width=w, height=h)
        page.insert_text((50 + 10 * k, 60), f"SHEET {k + 1}", fontsize=10)
        page.insert_text((w - 100, h - 30), f"END {k + 1}", fontsize=10)
    doc.save(path)
    return path


@pytest.mark.parametrize("mode", ["single", "split"])
def test_text_list_of_several_sheets(tmp_path, mode):
    pdf = _two_sheets(str(tmp_path / "two.pdf"))
    rep = convert(pdf, str(tmp_path / "two.dxf"),
                  Options(scale_denominator=100, page_mode=mode,
                          export_texts="csv"))
    assert rep.success
    rows = _by_text(_read_csv(str(tmp_path / "two_texts.csv")))
    for k in (1, 2):
        start, end = rows[f"SHEET {k}"], rows[f"END {k}"]
        assert start["page"] == end["page"] == str(k)
        # positions are measured on each sheet, from its own corner
        assert abs(float(start["sheet_x_mm"]) - (40 + 10 * k) * PT) < 0.2
        assert abs(float(start["sheet_y_mm"]) - 60 * PT) < 0.2
        drawing = "two.dxf" if mode == "single" else f"two_p{k}.dxf"
        assert start["drawing"] == drawing
    assert [r["text"] for r in _read_csv(str(tmp_path / "two_texts.csv"))] \
        == ["SHEET 1", "END 1", "SHEET 2", "END 2"]


def test_list_follows_the_layer_edits_made_before_saving(pdf_factory,
                                                         tmp_path):
    pdf = pdf_factory(_sheet)
    work = tmp_path / "work" / "plan.dxf"
    rep = convert(pdf, str(work), Options(export_texts="both"))
    edits = {"TEXT": LayerEdit(new_name="NOTES"),
             "DIM_RAW": LayerEdit(keep=False)}
    res = finalize(str(work), str(tmp_path / "final.dxf"), edits,
                   text_pages=rep.placements, pdf_name="plan.pdf")
    rows = _by_text([vars(r) for r in res.text_rows])
    assert rows["GENERAL NOTES"]["layer"] == "NOTES"
    assert rows["GENERAL NOTES"]["drawing"] == "final.dxf"
    assert "3.50" not in rows                     # its layer was removed


def test_cli_texts_option(pdf_factory, tmp_path):
    pdf = pdf_factory(_sheet)
    out = tmp_path / "cli.dxf"
    assert cli_main([pdf, "-o", str(out), "--texts", "txt", "-q"]) == 0
    assert (tmp_path / "cli_texts.txt").is_file()
    assert not (tmp_path / "cli_texts.csv").exists()


@pytest.mark.skipif(not dwg.find_tools().available,
                    reason="LibreDWG not built")
def test_text_list_next_to_the_dwg(pdf_factory, tmp_path):
    pdf = pdf_factory(_sheet)
    rep = convert(pdf, str(tmp_path / "out" / "plan.dwg"),
                  Options(export_texts="csv"))
    assert rep.success
    rows = _read_csv(str(tmp_path / "out" / "plan_texts.csv"))
    assert rows and {r["drawing"] for r in rows} == {"plan.dwg"}


def test_stacked_values_read_as_written():
    assert plain_mtext("3\\S50^ ;") == "3⁵⁰"
    assert plain_mtext("25\\S+0.1^ -0.2;") == "25 +0.1/-0.2"
    assert plain_mtext("3\\S1/2;\"") == "3 1/2\""
    assert plain_mtext("{\\W0.8;NOTES\\P1. Concrete}") == "NOTES\n1. Concrete"
