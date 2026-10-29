"""Save-time post-processing: layer edits, images, log."""

import os

import ezdxf

from convertcad.core import Options, convert
from convertcad.core.compat import pymupdf
from convertcad.core.postprocess import (LayerEdit, describe_edits, finalize,
                                         layer_summary)


def test_layer_summary_and_edits(sample_plan, tmp_path):
    tmp = tmp_path / "work" / "sample_plan.dxf"
    rep = convert(sample_plan, str(tmp), Options(scale_denominator=100))
    rows = {r.name: r for r in layer_summary(str(tmp))}
    assert rows["DIM"].count == 8 and rows["BLOCKS"].count == 23
    edits = {"DIM_RAW": LayerEdit(keep=False),
             "GEO_GRAY_025_CENTER": LayerEdit(new_name="AXES",
                                              color=(255, 128, 0)),
             "HATCH": LayerEdit(new_name="TEXT")}           # merge into TEXT
    dst = tmp_path / "final" / "Plan Coffrage.dxf"
    res = finalize(str(tmp), str(dst), edits,
                   log_src=os.path.splitext(str(tmp))[0] + "_log.txt",
                   log_note=describe_edits(edits))
    assert res.removed_entities == 1
    doc = ezdxf.readfile(str(dst))
    names = {lay.dxf.name for lay in doc.layers}
    assert "AXES" in names and "DIM_RAW" not in names and "HATCH" not in names
    assert doc.layers.get("AXES").dxf.color == 30          # orange
    assert len(doc.modelspace().query('*[layer=="AXES"]')) == 9
    assert len(doc.modelspace().query('HATCH[layer=="TEXT"]')) == 21
    with open(res.log_path, encoding="utf-8") as fh:
        log = fh.read()
    assert "LAYER EDITS" in log and str(dst) in log
    assert rep.success


def test_images_follow_the_new_name(tmp_path):
    src_pdf = tmp_path / "photo.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 30), False)
    pix.set_rect(pix.irect, (200, 30, 30))
    page.insert_image(pymupdf.Rect(20, 20, 120, 95), pixmap=pix)
    page.draw_line((0, 0), (300, 200))
    doc.save(str(src_pdf))
    work = tmp_path / "work" / "photo.dxf"
    rep = convert(str(src_pdf), str(work))
    assert rep.stats.images == 1
    res = finalize(str(work), str(tmp_path / "out" / "renamed.dxf"))
    assert len(res.images) == 1
    assert os.path.basename(res.images[0]).startswith("renamed_p1_img")
    out = ezdxf.readfile(res.dxf_path)
    imgdef = out.objects.query("IMAGEDEF")[0]
    assert imgdef.dxf.filename == os.path.basename(res.images[0])
    assert tuple(imgdef.dxf.image_size)[:2] == (40, 30)   # real pixel size
