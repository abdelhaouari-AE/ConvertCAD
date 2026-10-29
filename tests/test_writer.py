"""Step 6 — DXF writing: scale, units, versions, colours, layers, dims."""

import math

import ezdxf
import pytest

from conftest import stroke
from convertcad.core import Options, convert
from convertcad.core.constants import DXF_VERSIONS
from convertcad.core.dxf_writer import (compute_scale, effective_denominator,
                                        group_text_lines, nearest_aci)
from convertcad.core.extractor import RawText
from convertcad.core.layers import color_name, layer_for_style
from convertcad.core.extractor import Style


def test_scale_and_units():
    mm = compute_scale("mm", 100)
    assert math.isclose(mm, 25.4 / 72 * 100)
    assert math.isclose(compute_scale("cm", 100), mm / 10)
    assert math.isclose(compute_scale("m", 100), mm / 1000)
    assert compute_scale("mm", 100, calibrated_units_per_pt=12.5) == 12.5
    assert math.isclose(effective_denominator(mm, "mm"), 100)


def test_aci_mapping():
    assert nearest_aci((0, 0, 0)) == 7 and nearest_aci((255, 255, 255)) == 7
    assert nearest_aci((255, 0, 0)) == 1
    assert nearest_aci((0, 0, 255)) == 5
    assert nearest_aci((128, 128, 128)) == 8
    assert nearest_aci((209, 224, 255)) not in (7, 255)   # pale blue stays blue


def test_layer_naming_modes():
    st = Style(color=(0, 0, 0), width=0.5, linetype="CENTER")
    assert layer_for_style(st, mode="style") == "GEO_BLACK_050_CENTER"
    assert layer_for_style(st, mode="color") == "GEO_BLACK"
    assert layer_for_style(st, mode="single") == "GEOMETRY"
    st.pdf_layer = "S-COLS"
    assert layer_for_style(st, mode="style") == "S-COLS"
    assert layer_for_style(st, use_pdf_layers=False) == "GEO_BLACK_050_CENTER"
    assert color_name((26, 64, 204)) == "BLUE"


def test_text_grouping_never_loses_text():
    def t(s, x, y, h=8.0):
        return RawText(s, (x, y), h, 0.0)
    texts = [t("NOTES", 10, 100), t("line 1", 10, 112), t("line 2", 10, 124),
             t("far away", 10, 300), t("other col", 200, 112)]
    groups = group_text_lines(texts)
    flat = [x.text for g in groups for x in g]
    assert sorted(flat) == sorted(x.text for x in texts)
    assert ["NOTES", "line 1", "line 2"] in [[x.text for x in g]
                                             for g in groups]


@pytest.mark.parametrize("version", list(DXF_VERSIONS))
def test_every_dxf_version_saves_and_reloads(sample_plan, tmp_path, version):
    out = tmp_path / f"plan_{version}.dxf"
    rep = convert(sample_plan, str(out), Options(dxf_version=version,
                                                 scale_denominator=100))
    assert rep.success, rep.errors
    doc = ezdxf.readfile(str(out))
    assert doc.dxfversion == ezdxf.const.acad_release_to_dxf_version[version]
    assert len(doc.modelspace()) > 50


def test_real_world_scale_in_dxf(pdf_factory, tmp_path):
    """A 283.465 pt line at 1:100 is 10 000 mm long."""
    L = 10000 / 100 / (25.4 / 72)
    path = pdf_factory(lambda p: stroke(p, [("line", (50, 50), (50 + L, 50))]))
    out = tmp_path / "s.dxf"
    convert(path, str(out), Options(scale_denominator=100, units="mm"))
    line = ezdxf.readfile(str(out)).modelspace().query("LINE")[0]
    assert abs(line.dxf.start.distance(line.dxf.end) - 10000) < 1e-3
    convert(path, str(out), Options(scale_denominator=100, units="m"))
    line = ezdxf.readfile(str(out)).modelspace().query("LINE")[0]
    assert abs(line.dxf.start.distance(line.dxf.end) - 10.0) < 1e-6


def test_dimensions_are_linear_and_follow_the_pdf_line(sample_plan, tmp_path):
    out = tmp_path / "plan.dxf"
    convert(sample_plan, str(out), Options(scale_denominator=100))
    dims = ezdxf.readfile(str(out)).modelspace().query("DIMENSION")
    assert len(dims) == 8
    angles = sorted(round(d.dxf.angle % 180) for d in dims)
    assert angles == [0, 0, 0, 0, 0, 90, 90, 90]   # horizontal + vertical
    assert sorted(d.dxf.text for d in dims)[0] == "24000"


def test_black_lines_are_aci7_bylayer(sample_plan, tmp_path):
    out = tmp_path / "plan.dxf"
    convert(sample_plan, str(out), Options(scale_denominator=100))
    doc = ezdxf.readfile(str(out))
    assert doc.layers.get("GEO_BLACK_120").dxf.color == 7
    assert doc.layers.get("GEO_GRAY_025_CENTER").dxf.linetype == "CENTER"
    for e in doc.modelspace().query("LINE LWPOLYLINE"):
        if e.dxf.layer.startswith("GEO_BLACK"):
            assert e.dxf.color == 256               # ByLayer
