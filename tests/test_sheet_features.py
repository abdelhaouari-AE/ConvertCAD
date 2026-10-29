"""
Sheet-level features added in 1.0.0: AutoCAD SHX comments, TrueType text
drawn as outlines, the scale written on the sheet, and the selected area.
"""

import ezdxf
from conftest import stroke

from convertcad.core.clip import (clip_bezier, clip_page, clip_polygon,
                                  clip_segment)
from convertcad.core.compat import pymupdf
from convertcad.core.constants import LAYER_SHX_STROKES, LAYER_SHX_TEXT
from convertcad.core.extractor import (SHX_TITLE, RawBezier, Style,
                                       extract_page)
from convertcad.core.options import Options, normalize_rect
from convertcad.core.pdfinfo import detect_scale
from convertcad.core.pipeline import convert

BLACK = Style(color=(0, 0, 0), width=0.0)


# ---------------------------------------------------------------------------
# AutoCAD SHX text: letters drawn as strokes + a hidden comment
# ---------------------------------------------------------------------------
def _shx_word(page, x, y, content, title=SHX_TITLE, visible=False):
    """Three 'letters' (strokes 10 pt high) and the comment AutoCAD adds."""
    for k in range(3):
        x0 = x + 9 * k
        stroke(page, [("line", (x0, y), (x0, y - 10)),
                      ("line", (x0, y - 10), (x0 + 6, y - 10)),
                      ("line", (x0, y - 5), (x0 + 4, y - 5))], width=0.25)
    annot = page.add_rect_annot(pymupdf.Rect(x - 3, y - 13, x + 27, y + 3))
    annot.set_info(title=title, content=content)
    if visible:                                    # a reviewer's red box
        annot.set_colors(stroke=(1, 0, 0))
        annot.set_border(width=1)
        annot.update()
        return
    # AutoCAD's comment: read-only, no colour, no border, no appearance
    annot.set_flags(pymupdf.PDF_ANNOT_IS_READ_ONLY)
    annot.update()
    doc = page.parent
    for key in ("AP", "C", "BS"):
        doc.xref_set_key(annot.xref, key, "null")
    doc.xref_set_key(annot.xref, "Border", "[0 0 0]")


def test_shx_comment_becomes_text_on_its_letters(pdf_factory):
    pdf = pdf_factory(lambda p: _shx_word(p, 100, 200, "FFF"))
    pd = extract_page(pymupdf.open(pdf), 0)
    assert len(pd.shx_texts) == 1
    t = pd.shx_texts[0]
    assert t.text == "FFF" and t.rotation == 0
    assert abs(t.origin[0] - 100) < 0.5 and abs(t.origin[1] - 200) < 0.5
    assert abs(t.cap_height - 10) < 0.5
    # the 9 letter strokes go to the hidden layer, nothing else does
    moved = [s for s in pd.segments if s.style.pdf_layer == LAYER_SHX_STROKES]
    assert len(moved) == 9


def test_reviewer_markup_is_not_shx(pdf_factory):
    def draw(p):
        _shx_word(p, 100, 200, "Please check", title="Reviewer",
                  visible=True)
    pd = extract_page(pymupdf.open(pdf_factory(draw)), 0)
    assert not pd.shx_texts
    assert not any(s.style.pdf_layer == LAYER_SHX_STROKES
                   for s in pd.segments)


def test_shx_comments_option_and_dxf_layers(pdf_factory, tmp_path):
    pdf = pdf_factory(lambda p: _shx_word(p, 100, 200, "FFF"))
    out = tmp_path / "s.dxf"
    assert convert(pdf, str(out), Options(scale_denominator=1)).success
    doc = ezdxf.readfile(str(out))
    texts = [e for e in doc.modelspace().query("TEXT MTEXT")
             if e.dxf.layer == LAYER_SHX_TEXT]
    assert len(texts) == 1
    assert doc.layers.get(LAYER_SHX_STROKES).is_off()
    out2 = tmp_path / "s2.dxf"
    convert(pdf, str(out2), Options(scale_denominator=1, shx_comments=False))
    doc2 = ezdxf.readfile(str(out2))
    assert not [e for e in doc2.modelspace().query("TEXT MTEXT")
                if e.dxf.layer == LAYER_SHX_TEXT]


# ---------------------------------------------------------------------------
# TrueType text exported as filled outlines + an invisible copy
# ---------------------------------------------------------------------------
def test_letter_outlines_under_invisible_text_are_dropped(pdf_factory):
    def draw(p):
        p.insert_text((100, 200), "TAG-01", fontsize=12, render_mode=3)
        for k in range(6):                       # the drawn "glyphs"
            stroke(p, [("rect", 100 + 7 * k, 191, 105 + 7 * k, 200)],
                   color=None, fill=(0, 0, 0), close=True)
        stroke(p, [("rect", 300, 300, 340, 340)], color=None,
               fill=(0, 0, 0), close=True)       # a real filled shape
    pd = extract_page(pymupdf.open(pdf_factory(draw)), 0)
    assert len(pd.fills) == 1 and pd.text_outlines == 6
    assert [t.text for t in pd.texts] == ["TAG-01"]


# ---------------------------------------------------------------------------
# Scale written on the sheet
# ---------------------------------------------------------------------------
def test_detect_scale_variants():
    assert detect_scale("Echelle : 1/100") == 100
    assert detect_scale("SCALE 1:50") == 50
    assert detect_scale("Ech. 2.5:1000") == 400
    assert detect_scale("ÉCHELLE 1/20\nother text") == 20
    assert detect_scale("1:200") == 200               # ratio alone (bar)
    assert detect_scale("2,5:1000") == 400
    assert detect_scale("SCALE 1:2.5") == 2.5


def test_detect_scale_refuses_ambiguity():
    assert detect_scale("") is None
    assert detect_scale("1/2") is None                # a fraction
    assert detect_scale("3/4") is None
    assert detect_scale("SCALE 1:50\nDETAIL SCALE 1:10") is None
    assert detect_scale("Drawing 2024/1000") is None


# ---------------------------------------------------------------------------
# Selected area (clipping)
# ---------------------------------------------------------------------------
R = (0.0, 0.0, 100.0, 50.0)


def test_clip_segment_cases():
    assert clip_segment((10, 10), (20, 20), R) == ((10, 10), (20, 20))
    assert clip_segment((-50, 25), (150, 25), R) == ((0, 25), (100, 25))
    assert clip_segment((-50, -5), (150, -5), R) is None
    a, b = clip_segment((50, 10), (150, 60), R)   # leaves by the right side
    assert a == (50, 10) and abs(b[0] - 100) < 1e-9 and abs(b[1] - 35) < 1e-9
    a, b = clip_segment((50, 25), (75, 75), R)    # leaves by the top side
    assert abs(b[0] - 62.5) < 1e-9 and abs(b[1] - 50) < 1e-9


def test_clip_polygon_and_bezier():
    poly = clip_polygon([(-10, -10), (50, -10), (50, 20), (-10, 20)], R)
    xs = sorted({round(p[0], 6) for p in poly})
    ys = sorted({round(p[1], 6) for p in poly})
    assert xs == [0, 50] and ys == [0, 20]
    bz = RawBezier((-20, 25), (20, 25), (80, 25), (120, 25), BLACK)
    parts = clip_bezier(bz, R)
    assert parts
    assert all(0 - 1e-6 <= p[0] <= 100 + 1e-6
               for part in parts for p in (part.p0, part.p3))


def test_clip_page_keeps_only_the_area(pdf_factory):
    def draw(p):
        stroke(p, [("line", (50, 100), (550, 100))])
        stroke(p, [("line", (400, 300), (550, 350))])  # outside
        p.insert_text((60, 90), "IN", fontsize=10)
        p.insert_text((500, 380), "OUT", fontsize=10)
    pd = extract_page(pymupdf.open(pdf_factory(draw)), 0)
    counts = clip_page(pd, [100, 50, 300, 200])
    assert counts["after"] < counts["before"]
    assert len(pd.segments) == 1
    s = pd.segments[0]
    assert sorted((s.p1[0], s.p2[0])) == [100, 300]
    assert not pd.texts                               # "IN" starts at x=60


def test_area_option_in_the_pipeline(pdf_factory, tmp_path):
    def draw(p):
        stroke(p, [("rect", 50, 50, 250, 150)])
        stroke(p, [("rect", 350, 200, 550, 350)])
    pdf = pdf_factory(draw)
    out = tmp_path / "a.dxf"
    rep = convert(pdf, str(out), Options(scale_denominator=1,
                                         clip_rect=[40, 40, 260, 160]))
    assert rep.success and rep.placements[0]["clip"] == [40, 40, 260, 160]
    doc = ezdxf.readfile(str(out))
    xs = [v[0] for e in doc.modelspace().query("LWPOLYLINE")
          for v in e.get_points("xy")]
    assert xs and max(xs) < 260 * 25.4 / 72 + 1e-6


def test_normalize_rect():
    assert normalize_rect(None) is None
    assert normalize_rect([30, 40, 10, 20]) == [10, 20, 30, 40]
    assert normalize_rect([0, 0, 0.5, 10]) is None           # too thin
    assert normalize_rect(["a", 1, 2, 3]) is None
    assert Options.from_dict({"clip_rect": [5, 5, 1, 1]}).clip_rect == \
        [1, 1, 5, 5]
