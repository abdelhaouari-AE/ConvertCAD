"""
Native DWG output (core/dwg.py): an AutoCAD 2000 DXF is cleaned, given the
handles AutoCAD expects, converted by the bundled GNU LibreDWG and read back.

The conversion tests are skipped when the LibreDWG programs are missing
(build them with ./scripts/build_libredwg.sh linux).
"""

import os

import ezdxf
import pytest

from convertcad.core import dwg
from convertcad.core.pipeline import Options, convert

HAVE_DWG = dwg.find_tools().available
needs_dwg = pytest.mark.skipif(not HAVE_DWG, reason="LibreDWG not built")


def _handles(path):
    """(handle -> entity type) of every object, and the duplicate count."""
    seen, dup = {}, 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = [ln.strip() for ln in fh]
    kind = None
    for k in range(0, len(lines) - 1, 2):
        code, value = lines[k], lines[k + 1]
        if code == "0":
            kind = value
        elif code == "5" and kind:
            h = int(value, 16)
            dup += h in seen
            seen[h] = kind
    return seen, dup


def test_prepared_dxf_has_autocad_handles(sample_plan, tmp_path):
    src = tmp_path / "plan.dxf"
    convert(sample_plan, str(src), Options(dxf_version="R2000", pages=[1],
                                           scale_denominator=100))
    out = tmp_path / "prep.dxf"
    dwg.prepare_dxf_for_dwg(str(src), str(out))
    handles, dup = _handles(str(out))
    assert dup == 0
    # table heads at the handles AutoCAD itself uses
    for name, h in (("LAYER", 0x2), ("STYLE", 0x3), ("LTYPE", 0x5),
                    ("BLOCK_RECORD", 0x1)):
        assert handles.get(h) == "TABLE", name
    assert handles.get(dwg.MODEL_SPACE_HANDLE) == "BLOCK_RECORD"
    # nothing left in the reserved range 0x0C-0x2F except *Model_Space
    assert not [h for h in handles if 0xB < h < 0x30
                and h != dwg.MODEL_SPACE_HANDLE]
    doc = ezdxf.readfile(str(out))
    assert doc.dxfversion == "AC1015"
    assert len(doc.modelspace()) == dwg.count_dxf_entities(str(src))


def test_missing_converter_is_reported(tmp_path):
    res = dwg.dxf_to_dwg("x.dxf", str(tmp_path / "x.dwg"),
                         tools=dwg.DwgTools())
    assert not res.ok and "not found" in res.message
    assert not (tmp_path / "x.dwg").exists()


def test_writer_version_for_dwg():
    assert Options(output_format="dwg").writer_dxf_version() == "R2000"
    assert Options(dxf_version="R2013").writer_dxf_version() == "R2013"
    assert Options.from_dict({"output_format": "pdf"}).output_format == "dxf"


@needs_dwg
def test_pipeline_writes_a_verified_dwg(sample_plan, tmp_path):
    out = tmp_path / "plan.dwg"
    rep = convert(sample_plan, str(out), Options(scale_denominator=100))
    assert rep.success, rep.errors
    assert out.read_bytes()[:6] == b"AC1015"
    assert rep.outputs == [str(out)]
    assert not list(tmp_path.glob("*.dxf"))          # no DXF left behind
    log = (tmp_path / "plan_log.txt").read_text(encoding="utf-8")
    assert "DWG written by GNU LibreDWG" in log and "verified" in log
    # read back with LibreDWG: every entity of the DXF is there
    back = tmp_path / "back.dxf"
    tools = dwg.find_tools()
    dwg._run([tools.dwg2dxf, "-y", "-o", str(back), str(out)], tools)
    doc = ezdxf.readfile(str(back))
    assert len(doc.modelspace()) >= rep.stats.total_entities()


@needs_dwg
def test_rotated_blocks_survive_the_dwg(pdf_factory, tmp_path):
    """Mirrored / rotated INSERTs read back from the DWG still rebuild the
    exact drawing (same check as tests/test_blocks.py)."""
    from test_blocks import _ORIENT, _draw_f, _segments

    def draw(page):
        for x in (60, 110, 160):
            _draw_f(page, x, 60, _ORIENT[0])
        for k, m in enumerate(_ORIENT[1:]):
            _draw_f(page, 60 + 50 * k, 160, m)
    pdf = pdf_factory(draw, width=500, height=260)
    kw = dict(scale_denominator=50, dimensions=False, leaders=False,
              merge_dashes=False, hatch_patterns=False)
    plain = tmp_path / "plain.dxf"
    convert(pdf, str(plain), Options(block_detection=False, **kw))
    out = tmp_path / "f.dwg"
    rep = convert(pdf, str(out), Options(output_format="dwg", **kw))
    assert rep.success and rep.stats.blocks_inserted == 10
    back = tmp_path / "back.dxf"
    tools = dwg.find_tools()
    dwg._run([tools.dwg2dxf, "-y", "-o", str(back), str(out)], tools)
    assert _segments(ezdxf.readfile(str(back))) == \
        _segments(ezdxf.readfile(str(plain)))


@needs_dwg
def test_dwg_conversion_failure_keeps_nothing(tmp_path):
    bad = tmp_path / "bad.dxf"
    bad.write_text("0\nSECTION\n2\nENTITIES\n0\nLINE\n", encoding="utf-8")
    res = dwg.dxf_to_dwg(str(bad), str(tmp_path / "bad.dwg"))
    assert not res.ok and res.message
    assert not os.path.exists(tmp_path / "bad.dwg")


def test_insert_scales_are_completed_for_libredwg():
    lines = ["  0", "INSERT", "  8", "BLOCKS", "  2", "B", " 10", "5.0",
             " 20", "7.0", " 30", "0.0", " 41", "-1.0", " 50", "90.0",
             "  0", "INSERT", "  2", "B", " 10", "1.0", " 20", "2.0",
             " 30", "0.0", "  0", "EOF"]
    out = dwg._complete_insert_scales(lines)
    first = out[:out.index("INSERT", 2) - 1]
    pairs = dict(zip([c.strip() for c in first[0::2]], first[1::2]))
    assert (pairs["41"], pairs["42"], pairs["43"]) == ("-1.0", "1.0", "1.0")
    # the order LibreDWG expects: point, then the three factors
    codes = [c.strip() for c in first[0::2]]
    assert codes.index("30") < codes.index("41") < codes.index("42") \
        < codes.index("43")
    # an INSERT without any factor is left exactly as it was
    assert out[len(first):] == lines[len(first) - 4:]


def test_insert_transforms_reads_defaults(tmp_path):
    p = tmp_path / "t.dxf"
    p.write_text("0\nSECTION\n2\nENTITIES\n0\nINSERT\n2\nB\n10\n1.5\n20\n"
                 "2.5\n30\n0\n41\n-1\n0\nINSERT\n2\nB\n10\n3\n20\n4\n30\n0\n"
                 "0\nENDSEC\n0\nEOF\n", encoding="utf-8")
    t = dwg.insert_transforms(str(p))
    assert t == {(1.5, 2.5, -1.0, 1.0, 1.0, 0.0): 1,
                 (3.0, 4.0, 1.0, 1.0, 1.0, 0.0): 1}
