"""
Interface language: every interface string has its French version, the
{placeholders} survive translation, and the engine progress messages are
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


def _tr_literals():
    """(text, location) of every tr("literal") call in the package."""
    for root, _, files in os.walk(PKG):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and getattr(node.func, "id", None) == "tr"
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    rel = os.path.relpath(path, ROOT)
                    yield node.args[0].value, f"{rel}:{node.lineno}"


def test_every_interface_string_has_a_french_version():
    missing = sorted({f"{loc}  {text!r}" for text, loc in _tr_literals()
                      if text and text not in i18n.FR})
    assert not missing, "Add these to FR in convertcad/i18n.py:\n" + \
        "\n".join(missing)


def _fields(text):
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


def test_placeholders_are_kept_in_translations():
    bad = [k for k, v in i18n.FR.items() if _fields(k) != _fields(v)]
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
