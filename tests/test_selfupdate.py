"""Updates that download only the files that changed (core/selfupdate.py):
list of files, partial download of the release zip over HTTP (range
requests, like GitHub), swap with rollback, clean-up."""

import http.server
import os
import threading
import zipfile

import pytest

from convertcad.core import selfupdate as su


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _make_folder(root, files):
    for rel, data in files.items():
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
    return root


def _read_tree(root):
    out = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            out[os.path.relpath(p, root).replace(os.sep, "/")] = open(p, "rb").read()
    return out


def _release_zip(folder, path, version, platform=None):
    """Like the build: list of files, then a zip whose entries start with
    'ConvertCAD/' (PowerShell's Compress-Archive of dist/ConvertCAD)."""
    su.write_manifest(folder, version, platform or su.platform_tag())
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for d, _, fs in os.walk(folder):
            for f in sorted(fs):
                full = os.path.join(d, f)
                rel = os.path.relpath(full, folder).replace(os.sep, "/")
                zf.write(full, "ConvertCAD/" + rel)
    return path


class _RangeHandler(http.server.SimpleHTTPRequestHandler):
    """Serves files by parts like GitHub's storage: GET with Range only,
    HEAD refused."""
    requests = []

    def log_message(self, *args):
        pass

    def do_HEAD(self):
        self.send_error(401)

    def do_GET(self):
        path = self.translate_path(self.path)
        rng = self.headers.get("Range", "")
        _RangeHandler.requests.append(rng)
        if not os.path.isfile(path) or not rng.startswith("bytes="):
            self.send_error(400)
            return
        size = os.path.getsize(path)
        a, b = rng[6:].split("-")
        a, b = int(a), min(int(b), size - 1)
        with open(path, "rb") as fh:
            fh.seek(a)
            data = fh.read(b - a + 1)
        self.send_response(206)
        self.send_header("Content-Range", f"bytes {a}-{b}/{size}")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "www"
    root.mkdir()

    def handler(*a, **k):
        return _RangeHandler(*a, directory=str(root), **k)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    _RangeHandler.requests = []
    yield root, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


BIG = os.urandom(3 * 2 ** 20)                       # 3 MB, not compressible
OLD = {"ConvertCAD.exe": b"old exe", "ConvertCAD.pkg": BIG,
       "_internal/convertcad/core/a.pyc": b"old code " * 100,
       "_internal/gone.dll": b"removed in the new version",
       "README.md": b"readme"}
NEW = {"ConvertCAD.exe": b"new exe", "ConvertCAD.pkg": BIG,
       "_internal/convertcad/core/a.pyc": b"new code " * 120,
       "_internal/convertcad/core/b.pyc": b"a new module",
       "README.md": b"readme"}


def _setup(tmp_path, www):
    app = _make_folder(str(tmp_path / "app"), OLD)
    su.write_manifest(app, "1.0.0")
    # files of the user's installation that are never touched
    _make_folder(app, {"unins000.exe": b"uninstaller", "settings/s.json": b"{}",
                       "ConvertCAD.portable": b""})
    new = _make_folder(str(tmp_path / "new"), NEW)
    _release_zip(new, str(www / "ConvertCAD-2.0.0-win64-portable.zip"), "2.0.0")
    return app


# ---------------------------------------------------------------------------
def test_manifest_lists_the_program_files_only(tmp_path):
    app = _setup(tmp_path, tmp_path)
    files = su.read_manifest(app)["files"]
    assert set(files) == set(OLD)
    assert files["README.md"]["size"] == 6 and len(files["README.md"]["sha256"]) == 64


def test_update_downloads_only_the_changed_files(tmp_path, server):
    www, base = server
    app = _setup(tmp_path, www)
    url = f"{base}/ConvertCAD-2.0.0-win64-portable.zip"
    assert su.can_update_files(app) == (True, "")

    plan = su.prepare(url, app)
    assert plan.version == "2.0.0"
    names = [rel for rel, _ in plan.files]
    assert names == ["ConvertCAD.exe", "_internal/convertcad/core/a.pyc",
                     "_internal/convertcad/core/b.pyc"]
    assert plan.removed == ["_internal/gone.dll"]
    # the 3 MB file is identical: not downloaded
    assert plan.download_bytes < 10_000 < plan.full_bytes

    seen = []
    su.download(plan, app, progress=lambda d, t: seen.append((d, t)))
    assert seen[-1][0] == seen[-1][1] == plan.download_bytes
    assert su.read_pending(app)["version"] == "2.0.0"
    # only small parts of the zip were requested, never the whole file
    sizes = [int(r[6:].split("-")[1]) - int(r[6:].split("-")[0]) + 1
             for r in _RangeHandler.requests]
    assert max(sizes) < len(BIG) / 4

    ok, version, msg = su.apply_pending(app)
    assert (ok, version, msg) == (True, "2.0.0", "")
    tree = _read_tree(app)
    for rel, data in NEW.items():
        assert tree[rel] == data
    assert "_internal/gone.dll" not in tree
    assert tree["_internal/gone.dll.cc-old"] == OLD["_internal/gone.dll"]
    assert tree["unins000.exe"] == b"uninstaller"          # untouched
    assert tree["settings/s.json"] == b"{}"
    assert su.read_manifest(app)["version"] == "2.0.0"
    assert su.read_pending(app) is None

    result = su.take_result(app)
    assert result["ok"] and result["version"] == "2.0.0"
    assert su.take_result(app) is None                     # read once
    assert su.cleanup_old(app) >= 2                        # exe + dll
    assert not any(n.endswith(su.OLD_SUFFIX) for n in _read_tree(app))

    # nothing more to do
    plan = su.prepare(url, app)
    assert plan.files == [] and plan.removed == []


def test_failed_swap_puts_every_file_back(tmp_path, server, monkeypatch):
    www, base = server
    app = _setup(tmp_path, www)
    before = _read_tree(app)
    plan = su.prepare(f"{base}/ConvertCAD-2.0.0-win64-portable.zip", app)
    su.download(plan, app)

    real, calls = su._rename, []

    def flaky(a, b, tries=25):
        calls.append(a)
        if len(calls) == 4:                 # a file locked by another program
            raise PermissionError(13, "file in use", b)
        real(a, b, tries=1)
    monkeypatch.setattr(su, "_rename", flaky)
    ok, version, msg = su.apply_pending(app)
    assert not ok and "file in use" in msg
    after = _read_tree(app)
    for rel, data in before.items():
        if not rel.startswith(su.UPDATE_DIR + "/"):
            assert after[rel] == data, rel
    assert not any(n.endswith(su.OLD_SUFFIX) for n in after)
    assert su.read_pending(app) is None                    # not retried
    assert su.take_result(app)["ok"] is False


def test_a_damaged_download_is_refused(tmp_path, server, monkeypatch):
    www, base = server
    app = _setup(tmp_path, www)
    plan = su.prepare(f"{base}/ConvertCAD-2.0.0-win64-portable.zip", app)
    plan.manifest["files"]["ConvertCAD.exe"]["sha256"] = "0" * 64
    with pytest.raises(su.UpdateError):
        su.download(plan, app)
    assert su.read_pending(app) is None


def test_release_for_another_system_is_refused(tmp_path):
    app = _make_folder(str(tmp_path / "app"), OLD)
    su.write_manifest(app, "1.0.0")
    new = _make_folder(str(tmp_path / "new"), NEW)
    zpath = _release_zip(new, str(tmp_path / "other.zip"), "2.0.0", "other-os")
    with pytest.raises(su.UpdateError):
        su.prepare(zpath, app)                             # local zip path


def test_cancel_stops_the_download(tmp_path, server):
    www, base = server
    app = _setup(tmp_path, www)
    plan = su.prepare(f"{base}/ConvertCAD-2.0.0-win64-portable.zip", app)
    with pytest.raises(su.UpdateCancelled):
        su.download(plan, app, cancelled=lambda: True)
    assert su.read_pending(app) is None


def test_install_kinds(tmp_path, monkeypatch):
    assert su.install_kind() in ("source",) or su.program_dir()
    monkeypatch.setattr(su.sys, "platform", "win32")
    app = _make_folder(str(tmp_path / "w"), {"ConvertCAD.exe": b""})
    assert su.install_kind(app) == "win-portable"          # unpacked zip
    _make_folder(app, {"unins000.exe": b""})
    assert su.install_kind(app) == "win-installed"         # by the installer
    assert su.FULL_DOWNLOAD["win-installed"] == "-win64-setup.exe"
