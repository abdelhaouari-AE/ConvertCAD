"""End-to-end conversions: counts, options, multi-page, cancel, errors."""

import json
import os

import ezdxf

from conftest import stroke
from convertcad.core import Cancelled, Options, convert, convert_folder
from convertcad.core.compat import pymupdf
from convertcad.core.pipeline import find_pdfs, output_paths


def test_sample_plan_full_conversion(sample_plan, tmp_path):
    out = tmp_path / "plan.dxf"
    progress = []
    rep = convert(sample_plan, str(out), Options(scale_denominator=100),
                  progress=lambda m, f: progress.append(f))
    assert rep.success and not rep.errors
    s = rep.stats
    assert s.dimensions == 8 and s.leaders == 2
    assert s.blocks_defined == 2 and s.blocks_inserted == 23
    assert s.circles == 12 and s.splines == 1 and s.mtexts >= 1
    assert s.layer_counts["DIM_RAW"] == 1
    assert progress[-1] == 1.0 and progress == sorted(progress)
    assert os.path.isfile(tmp_path / "plan_log.txt")
    doc = ezdxf.readfile(str(out))
    assert len(doc.blocks.get("CC_SYMBOL_001")) > 0


def test_features_can_be_switched_off(sample_plan, tmp_path):
    opt = Options(dimensions=False, leaders=False, block_detection=False,
                  text_entities=False, hatches=False, write_log=False)
    rep = convert(sample_plan, str(tmp_path / "p.dxf"), opt)
    s = rep.stats
    assert rep.success
    assert s.dimensions == s.leaders == s.blocks_defined == 0
    assert s.texts == s.mtexts == s.hatches == 0
    assert not os.path.exists(tmp_path / "p_log.txt")


def test_split_pages(sample_plan, tmp_path):
    out = str(tmp_path / "plan.dxf")
    rep = convert(sample_plan, out, Options(page_mode="split"))
    assert rep.success
    assert rep.outputs == output_paths(out, [1, 2], "split")
    assert all(os.path.isfile(p) for p in rep.outputs)


def test_page_selection(sample_plan, tmp_path):
    rep = convert(sample_plan, str(tmp_path / "p2.dxf"), Options(pages=[2]))
    assert rep.success and rep.pages_converted == [2]
    rep = convert(sample_plan, str(tmp_path / "x.dxf"), Options(pages=[9]))
    assert not rep.success and rep.errors


def test_cancellation(sample_plan, tmp_path):
    rep = convert(sample_plan, str(tmp_path / "c.dxf"), Options(),
                  should_cancel=lambda: True)
    assert rep.cancelled and not rep.success
    assert not os.path.exists(tmp_path / "c.dxf")


def test_bad_inputs(tmp_path):
    rep = convert(str(tmp_path / "missing.pdf"), str(tmp_path / "o.dxf"))
    assert not rep.success and "Cannot open PDF" in rep.errors[0]
    doc = pymupdf.open()
    doc.new_page()
    enc = str(tmp_path / "locked.pdf")
    doc.save(enc, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o",
             user_pw="u")
    rep = convert(enc, str(tmp_path / "o.dxf"))
    assert not rep.success and "password" in rep.errors[0]


def test_white_and_background_fills_are_ignored(pdf_factory, tmp_path):
    def draw(page):
        stroke(page, [("rect", 0, 0, 600, 400)], color=None,
               fill=(1, 1, 1), close=True)                  # page background
        stroke(page, [("rect", 10, 10, 50, 50)], color=None,
               fill=(1, 1, 1), close=True)                  # white mask
        stroke(page, [("rect", 100, 100, 150, 150)], color=None,
               fill=(0.5, 0.5, 0.5), close=True)            # real hatch
        stroke(page, [("line", (5, 5), (500, 300))])
    rep = convert(pdf_factory(draw), str(tmp_path / "f.dxf"))
    assert rep.stats.hatches == 1 and rep.stats.fills_skipped == 2


def test_report_formats(sample_plan, tmp_path):
    rep = convert(sample_plan, str(tmp_path / "r.dxf"))
    text = rep.render()
    assert "RESULTS" in text and "SUCCESS" in text
    assert "<html>" in rep.to_html() and "SUCCESS" in rep.to_html(dark=True)
    data = json.loads(rep.to_json())
    assert data["status"] == "SUCCESS" and data["total_entities"] > 50


def test_options_roundtrip_and_old_presets():
    opt = Options(scale_denominator=75, layer_mode="color")
    again = Options.from_dict(opt.to_dict())
    assert again == opt
    legacy = Options.from_dict({"scale_denominator": 20, "unknown_key": 1,
                                "curve_precision": "bogus"})
    assert legacy.scale_denominator == 20
    assert legacy.curve_precision == "normal"


def test_batch_folder(sample_plan, tmp_path):
    src = tmp_path / "in"
    (src / "sub").mkdir(parents=True)
    for name in ("a.pdf", "B.PDF", os.path.join("sub", "c.pdf")):
        with open(sample_plan, "rb") as fh, open(src / name, "wb") as out:
            out.write(fh.read())
    (src / "notes.txt").write_text("x")
    assert len(find_pdfs(str(src))) == 2
    assert len(find_pdfs(str(src), recursive=True)) == 3
    seen = []
    summary = convert_folder(str(src), str(tmp_path / "out"),
                             Options(pages=[1]), recursive=True,
                             per_file=lambda i, r: seen.append(r))
    assert summary["ok"] == 3 and summary["failed"] == 0 and len(seen) == 3
    assert os.path.isfile(tmp_path / "out" / "sub" / "c.dxf")


def test_cancelled_is_an_exception_type():
    assert issubclass(Cancelled, Exception)


def _dim_values(path):
    doc = ezdxf.readfile(str(path))
    return sorted(round(d.get_measurement()) for d in
                  doc.modelspace().query("DIMENSION"))


def test_auto_scale_reads_the_title_block(sample_plan, tmp_path):
    # the sample sheet says "Echelle : 1/100": the 6 m bays must measure
    # 6000 mm although the fallback scale is 1:50
    out = tmp_path / "auto.dxf"
    rep = convert(sample_plan, str(out),
                  Options(auto_scale=True, scale_denominator=50, pages=[1]))
    assert rep.success
    assert any("scale 1:100 read" in n for n in rep.page_notes)
    assert 6000 in _dim_values(out)
    # without auto scale the fallback 1:50 is used -> half the size
    fixed = tmp_path / "fixed.dxf"
    convert(sample_plan, str(fixed), Options(scale_denominator=50, pages=[1]))
    assert 3000 in _dim_values(fixed) and 6000 not in _dim_values(fixed)


def test_auto_scale_falls_back_and_calibration_wins(sample_plan, tmp_path):
    rep = convert(sample_plan, str(tmp_path / "p2.dxf"),
                  Options(auto_scale=True, scale_denominator=20, pages=[2]))
    assert any("no single scale" in n and "1:20" in n for n in rep.page_notes)
    rep = convert(sample_plan, str(tmp_path / "cal.dxf"),
                  Options(auto_scale=True, calibrated_units_per_pt=1.0,
                          pages=[1]))
    assert not any("read on the sheet" in n for n in rep.page_notes)
