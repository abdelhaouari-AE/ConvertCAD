"""
Downloadable OCR models: catalogue, folders, download (from a local web
server: no internet needed), checksum, fallback address, cancel, offline
installation and removal.
"""

import hashlib
import http.server
import os
import threading

import pytest

from convertcad.core import ocr_catalog, ocr_store
from convertcad.core.ocr_catalog import (BY_ID, PACKS, ModelFile, OcrPack,
                                         language_error, language_set)

GOOD = b"fake onnx model " * 4000                    # about 64 KB
GOOD_SHA = hashlib.sha256(GOOD).hexdigest()


# ---------------------------------------------------------------------------
# catalogue
# ---------------------------------------------------------------------------
def test_catalogue_is_consistent():
    names, shas = set(), set()
    for p in PACKS:
        assert p.builtin == (p.id == "latin")
        assert p.builtin or p.files
        for f in p.files:
            assert len(f.sha256) == 64 and int(f.sha256, 16) >= 0
            assert f.name not in names and f.sha256 not in shas
            names.add(f.name)
            shas.add(f.sha256)
            urls = p.urls[f.name]
            assert urls[0].startswith(ocr_catalog.RELEASE_BASE)
            assert urls[1].startswith(ocr_catalog.MIRROR_BASE)
        if p.kind == "script":
            assert p.lang_type and p.script and len(p.files) == 1


def test_language_keys():
    assert language_set("").key == "latin"
    assert language_set("eng+fra").key == "latin"            # version 1.0
    assert language_set("eng+fra+ara").key == "latin+arabic"
    assert language_set("arabic+latin").key == "latin+arabic"
    assert language_set("Cyrillic").key == "cyrillic"
    assert language_set("latin+arabic").label == "English, French… + Arabic"
    assert language_set("latin").label == "English, French… (Latin script)"
    assert language_error("latin+greek") == ""
    assert language_error("latin_max")
    assert language_error("arabic+greek")
    assert language_error("xx")
    keys = ocr_catalog.all_language_keys()
    assert keys[0] == "latin" and "latin+arabic" in keys and "arabic" in keys


# ---------------------------------------------------------------------------
# folders
# ---------------------------------------------------------------------------
def test_models_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("CONVERTCAD_OCR_MODELS", str(tmp_path / "env"))
    assert ocr_store.user_models_dir() == str(tmp_path / "env")
    monkeypatch.delenv("CONVERTCAD_OCR_MODELS")
    # portable program: the models travel with it
    monkeypatch.setattr(ocr_store, "_program_dir", lambda: str(tmp_path))
    (tmp_path / ocr_store.PORTABLE_MARKER).write_text("")
    assert ocr_store.user_models_dir() == str(tmp_path / "ocr_models")
    (tmp_path / ocr_store.PORTABLE_MARKER).unlink()
    if os.name == "nt":
        assert ocr_store.user_models_dir().endswith(
            os.path.join("ConvertCAD", "ocr_models"))
    else:
        monkeypatch.setattr(ocr_store.sys, "platform", "linux")
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        assert ocr_store.user_models_dir() == str(
            tmp_path / "xdg" / "convertcad" / "ocr_models")
    assert ocr_store.search_dirs()[0] == ocr_store.user_models_dir()


# ---------------------------------------------------------------------------
# a fake pack served by a local web server
# ---------------------------------------------------------------------------
@pytest.fixture
def models(tmp_path, monkeypatch):
    """User models folder in tmp_path, and a test pack "testpack" whose
    only file is GOOD."""
    folder = tmp_path / "models"
    monkeypatch.setenv("CONVERTCAD_OCR_MODELS", str(folder))
    monkeypatch.setattr(ocr_store, "search_dirs", lambda: [str(folder)])
    pack = OcrPack("testpack", "Test", "Test script", "script",
                   files=(ModelFile("test_rec.onnx", "x/test_rec.onnx",
                                    GOOD_SHA, len(GOOD)),),
                   lang_type="ARABIC")
    monkeypatch.setitem(BY_ID, "testpack", pack)
    monkeypatch.setattr(ocr_store, "PACKS", PACKS + (pack,))
    monkeypatch.setitem(ocr_store._BY_SHA, GOOD_SHA, pack.files[0])
    return folder


@pytest.fixture
def server(tmp_path, monkeypatch):
    """http://127.0.0.1:<port>/ serving tmp_path/www."""
    www = tmp_path / "www"
    www.mkdir()
    (www / "good.onnx").write_bytes(GOOD)
    (www / "bad.onnx").write_bytes(b"damaged" + GOOD[7:])
    for var in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY",
                "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(www), **k)

        def log_message(self, *a):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    httpd.shutdown()
    httpd.server_close()


def test_download_checks_the_file(models, server):
    seen = []
    folder = ocr_store.download_pack(
        "testpack", progress=lambda d, t: seen.append((d, t)),
        urls={"test_rec.onnx": [server + "good.onnx"]})
    assert folder == str(models)
    assert (models / "test_rec.onnx").read_bytes() == GOOD
    assert seen and seen[-1] == (len(GOOD), len(GOOD))
    assert ocr_store.is_installed(BY_ID["testpack"])
    assert ocr_store.removable(BY_ID["testpack"])
    assert not list(models.glob("*.part"))


def test_damaged_download_falls_back_to_the_mirror(models, server):
    ocr_store.download_pack("testpack", urls={"test_rec.onnx": [
        server + "bad.onnx", server + "missing.onnx", server + "good.onnx"]})
    assert (models / "test_rec.onnx").read_bytes() == GOOD


def test_failed_download_leaves_nothing(models, server):
    with pytest.raises(ocr_store.DownloadError) as err:
        ocr_store.download_pack("testpack", urls={"test_rec.onnx": [
            server + "bad.onnx", server + "missing.onnx"]})
    assert "checksum" in str(err.value) and "404" in str(err.value)
    assert not (models / "test_rec.onnx").exists()
    assert not list(models.glob("*.part"))
    assert not ocr_store.is_installed(BY_ID["testpack"])


def test_cancelled_download_leaves_nothing(models, server):
    with pytest.raises(ocr_store.DownloadCancelled):
        ocr_store.download_pack("testpack", should_cancel=lambda: True,
                                urls={"test_rec.onnx": [server + "good.onnx"]})
    assert not list(models.iterdir())


def test_unknown_pack_and_builtin():
    with pytest.raises(ocr_store.DownloadError):
        ocr_store.download_pack("no-such-pack")
    assert ocr_store.download_pack("latin") == ""      # nothing to download
    assert not ocr_store.removable(BY_ID["latin"])


def test_file_of_the_wrong_size_does_not_count(models):
    models.mkdir()
    (models / "test_rec.onnx").write_bytes(GOOD[:100])     # interrupted copy
    assert not ocr_store.is_installed(BY_ID["testpack"])


def test_install_from_file_and_remove(models, tmp_path):
    src = tmp_path / "downloaded on another PC.onnx"        # any name
    src.write_bytes(GOOD)
    assert ocr_store.install_files([str(src)]) == ["testpack"]
    assert (models / "test_rec.onnx").read_bytes() == GOOD
    other = tmp_path / "photo.onnx"
    other.write_bytes(b"not a model")
    with pytest.raises(ocr_store.DownloadError):
        ocr_store.install_files([str(other)])
    assert ocr_store.remove_pack("testpack") == 1
    assert not ocr_store.is_installed(BY_ID["testpack"])


def test_human_size():
    assert ocr_store.human_size(0) == "?"
    assert ocr_store.human_size(500) == "1 KB"
    assert ocr_store.human_size(84 * 1024 * 1024) == "84 MB"
