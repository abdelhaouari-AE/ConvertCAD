"""
Interface languages (French, Spanish, German, Arabic): every interface
string is translated, the {placeholders} survive translation, the long
texts exist in every language, and the engine progress messages are
translated for the activity log.
"""

import ast
import os
import string

import pytest

from convertcad import i18n
from convertcad.core.pipeline import Options, convert

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "convertcad")


@pytest.fixture
def french():
    i18n.set_language("fr")
    yield
    i18n.set_language("en")


def _translated_calls(node):
    """Literal strings that reach tr(): tr("…"), and the menu actions
    A("…", tip="…") / self._act("…") of the main window."""
    if not isinstance(node, ast.Call):
        return
    name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
    if name not in ("tr", "A", "_act"):
        return
    if node.args and isinstance(node.args[0], ast.Constant) \
            and isinstance(node.args[0].value, str):
        yield node.args[0].value
    if name != "tr":
        for kw in node.keywords:
            if kw.arg == "tip" and isinstance(kw.value, ast.Constant):
                yield kw.value.value


def _tr_literals():
    """(text, location) of every string the interface translates."""
    for root, _, files in os.walk(PKG):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                for text in _translated_calls(node):
                    rel = os.path.relpath(path, ROOT)
                    yield text, f"{rel}:{node.lineno}"


LANGS = [code for code in i18n.LANGUAGES if code != "en"]


@pytest.mark.parametrize("lang", LANGS)
def test_every_interface_string_is_translated(lang):
    table = i18n.table(lang)
    missing = sorted({f"{loc}  {text!r}" for text, loc in _tr_literals()
                      if text and text not in table})
    where = "FR in convertcad/i18n.py" if lang == "fr" else \
        f"convertcad/locales/{lang}.py"
    assert not missing, f"Add these to {where}:\n" + "\n".join(missing)


@pytest.mark.parametrize("lang", LANGS)
def test_ocr_catalogue_and_choices_are_translated(lang):
    """The OCR model names and languages are shown with tr(variable)."""
    from convertcad.core.constants import OCR_QUALITIES
    from convertcad.core.ocr_catalog import PACKS
    texts = [p.label for p in PACKS] + [p.languages for p in PACKS] + \
        [p.short for p in PACKS if p.short] + list(OCR_QUALITIES.values())
    missing = [t for t in texts if t not in i18n.table(lang)]
    assert not missing, missing


@pytest.mark.parametrize("lang", LANGS)
def test_no_stale_translations(lang):
    """Every translated text is still used (the French list is the
    reference: the other languages translate exactly its texts)."""
    extra = set(i18n.table(lang)) - set(i18n.FR)
    assert not extra, sorted(extra)


@pytest.mark.parametrize("lang", ["en"] + LANGS)
@pytest.mark.parametrize("stem", ["guide", "terms", "ocr"])
def test_long_texts_exist_in_every_language(lang, stem):
    path = os.path.join(PKG, "resources", f"{stem}_{lang}.md")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    assert text.startswith("# ") and len(text) > 500


def test_arabic_is_right_to_left():
    try:
        i18n.set_language("ar")
        assert i18n.is_rtl() and i18n.tr("Convert") == "تحويل"
        i18n.set_language("de")
        assert not i18n.is_rtl() and i18n.tr("Convert") == "Konvertieren"
        i18n.set_language("xx")                     # unknown -> English
        assert i18n.language() == "en" and i18n.tr("Convert") == "Convert"
    finally:
        i18n.set_language("en")


def _fields(text):
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


@pytest.mark.parametrize("lang", LANGS)
def test_placeholders_are_kept_in_translations(lang):
    bad = [k for k, v in i18n.table(lang).items()
           if _fields(k) != _fields(v)]
    assert not bad, bad


def test_tr_formats_and_falls_back(french):
    assert i18n.tr("Open PDF…") != "Open PDF…"
    assert i18n.tr("A sentence nobody translated") == \
        "A sentence nobody translated"
    assert "3" in i18n.tr("{n} PDF file(s) found.", n=3)


def test_engine_progress_messages_are_translated(sample_plan, tmp_path,
                                                 french):
    messages = []
    rep = convert(sample_plan, str(tmp_path / "p.dxf"), Options(),
                  progress=lambda m, f: messages.append(m))
    assert rep.success and messages
    for m in messages:
        assert i18n.tr_progress(m) != m, f"untranslated progress: {m!r}"


def test_progress_unchanged_in_english():
    msg = "Page 1/2: rebuilding geometry…"
    assert i18n.tr_progress(msg) == msg
