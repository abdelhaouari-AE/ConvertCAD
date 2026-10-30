"""Optional update check (off by default): version compare, one request,
failures reported."""

import io
import json
import urllib.error

import pytest

from convertcad.config import Settings
from convertcad.core import updates


def test_versions_compare():
    assert updates.parse_version("v1.2.0") == (1, 2, 0)
    assert updates.parse_version("1.10-beta") == (1, 10)
    assert updates.is_newer("1.2.0", "1.1.2")
    assert updates.is_newer("v1.10", "1.9.9")
    assert not updates.is_newer("1.2", "1.2.0")
    assert not updates.is_newer("1.1.9", "1.2.0")
    assert not updates.is_newer("", "1.0")


def test_check_is_off_by_default():
    assert Settings().check_updates is False


class _Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_check_reads_the_latest_release(monkeypatch):
    sent = {}

    def fake(req, timeout=0, context=None):
        sent["url"] = req.full_url
        sent["headers"] = dict(req.header_items())
        sent["data"] = req.data
        return _Answer(json.dumps({"tag_name": "v9.1.0", "html_url":
                                   "https://example.org/r"}).encode())
    monkeypatch.setattr(updates.urllib.request, "urlopen", fake)
    info = updates.check("1.2.0")
    assert info.newer and info.latest == "9.1.0" and info.url.endswith("/r")
    assert sent["url"] == updates.LATEST_API and sent["data"] is None
    # nothing about the user: only the program name and version
    assert sent["headers"]["User-agent"].startswith("ConvertCAD/")


@pytest.mark.parametrize("error,words", [
    (urllib.error.HTTPError(updates.LATEST_API, 404, "x", {}, None),
     "no published release"),
    (urllib.error.URLError("offline"), "could not be reached")])
def test_check_failures_are_reported(monkeypatch, error, words):
    def fake(req, timeout=0, context=None):
        raise error
    monkeypatch.setattr(updates.urllib.request, "urlopen", fake)
    with pytest.raises(updates.UpdateError, match=words):
        updates.check("1.2.0")
