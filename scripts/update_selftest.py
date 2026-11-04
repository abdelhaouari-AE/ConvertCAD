"""
update_selftest.py — end-to-end test of the per-file update on a BUILT
program (run by the build workflow on Windows and Linux).

    python scripts/update_selftest.py dist/ConvertCAD [release.zip]

1. copies the program folder (the "installed" version) and makes it older:
   README.md changed, one extra file listed in its file list;
2. serves the release zip (the given one, or a zip made from the folder) on
   a local web server that answers only by parts (HTTP range requests, like
   GitHub);
3. runs  <copy>/ConvertCAD-cli --update --update-from http://127.0.0.1/...
   while forcing the files the update program itself runs from (the .exe,
   its .pkg, the Python library, base_library.zip, the updater's own code)
   to be downloaded again: on Windows the update runs from a copy of them
   (_update/runner) so that the originals can be replaced;
4. waits for the applier, then checks that every file matches the new list,
   that the extra file is gone, that the copy still converts a drawing, and
   that the replaced files (*.cc-old) can be deleted.
Exit code 0 when everything is right.
"""

import glob
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from convertcad.core import selfupdate as su  # noqa: E402

EXE = ".exe" if os.name == "nt" else ""


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.translate_path(self.path)
        rng = self.headers.get("Range", "")
        if not os.path.isfile(path) or not rng.startswith("bytes="):
            self.send_error(400, "only range requests")
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


def zip_folder(folder: str, path: str) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for d, _, files in os.walk(folder):
            for f in sorted(files):
                full = os.path.join(d, f)
                zf.write(full, "ConvertCAD/" + os.path.relpath(
                    full, folder).replace(os.sep, "/"))


def check(cond: bool, what: str) -> None:
    print(("  ok    " if cond else "  FAIL  ") + what, flush=True)
    if not cond:
        sys.exit(1)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    app = os.path.abspath(sys.argv[1])
    new_manifest = su.read_manifest(app)
    check(new_manifest is not None, "the build has its list of files")
    work = tempfile.mkdtemp(prefix="cc-update-test-")
    www = os.path.join(work, "www")
    os.makedirs(www)
    zip_name = "ConvertCAD-test-portable.zip"
    if len(sys.argv) > 2:
        shutil.copy(sys.argv[2], os.path.join(www, zip_name))
    else:
        zip_folder(app, os.path.join(www, zip_name))

    # 1. the "installed" older version
    old = os.path.join(work, "installed")
    shutil.copytree(app, old)
    with open(os.path.join(old, "README.md"), "a", encoding="utf-8") as fh:
        fh.write("\nolder version\n")
    extra = "_internal/selftest-removed.txt"
    with open(os.path.join(old, *extra.split("/")), "w") as fh:
        fh.write("only in the old version")
    man_path = os.path.join(old, su.CONTENTS, su.MANIFEST)
    with open(man_path, encoding="utf-8") as fh:
        old_man = json.load(fh)
    old_man["version"] = "0.0.1"
    old_man["files"][extra] = {"size": 23, "sha256": "x"}
    with open(man_path, "w", encoding="utf-8") as fh:
        json.dump(old_man, fh)

    # files the running update itself uses
    cli = f"ConvertCAD-cli{EXE}"
    in_use = [cli, "ConvertCAD-cli.pkg", "_internal/base_library.zip",
              "_internal/convertcad/core/selfupdate.pyc"]
    pattern = "python3*.dll" if os.name == "nt" else "libpython3*.so*"
    in_use += [os.path.relpath(p, old).replace(os.sep, "/")
               for p in glob.glob(os.path.join(old, "_internal", pattern))]
    in_use = [p for p in in_use if os.path.isfile(os.path.join(old, p))]
    print("files in use, downloaded again:", ", ".join(in_use))

    # 2. the web server
    def handler(*a, **k):
        return RangeHandler(*a, directory=www, **k)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/{zip_name}"

    # 3. the update
    env = dict(os.environ, **{su.FORCE_ENV: ",".join(in_use)})
    t0 = time.time()
    run = subprocess.run([os.path.join(old, cli), "--update", "--update-from",
                          url, "-q"], env=env, capture_output=True, text=True,
                         timeout=600)
    print(run.stdout.strip())
    if run.stderr.strip():
        print(run.stderr.strip())
    check(run.returncode == 0, "--update prepared the update")

    # 4. the applier
    result_path = os.path.join(old, su.UPDATE_DIR, su.RESULT)
    while not os.path.isfile(result_path) and time.time() - t0 < 180:
        time.sleep(0.5)
    check(os.path.isfile(result_path), "the applier ran")
    with open(result_path, encoding="utf-8") as fh:
        result = json.load(fh)
    log = os.path.join(os.path.expanduser("~"), ".convertcad", "update.log")
    if os.path.isfile(log):
        print("update.log:\n" + open(log, encoding="utf-8").read()[-1500:])
    check(result.get("ok") is True, f"files swapped ({result})")
    bad = [rel for rel, meta in new_manifest["files"].items()
           if su.sha256_file(os.path.join(old, *rel.split("/"))) != meta["sha256"]]
    check(not bad, f"every file matches the new list ({len(bad)} different)")
    check(not os.path.exists(os.path.join(old, *extra.split("/"))),
          "the file removed in the new version is gone")
    check(su.read_manifest(old)["version"] == new_manifest["version"],
          "the list of files is the new one")
    olds = glob.glob(os.path.join(old, "**", "*" + su.OLD_SUFFIX), recursive=True)
    check(len(olds) >= len(in_use), f"{len(olds)} replaced file(s) kept aside")

    # the updated copy works
    out = os.path.join(work, "check.dxf")
    sample = os.path.join(ROOT, "samples", "sample_plan.pdf")
    if not os.path.isfile(sample):
        subprocess.run([sys.executable, os.path.join(ROOT, "scripts",
                                                     "make_samples.py")],
                       check=True)
    conv = subprocess.run([os.path.join(old, cli), sample, "-o", out, "-q"],
                          capture_output=True, text=True, timeout=600)
    check(conv.returncode == 0 and os.path.isfile(out),
          "the updated program converts a drawing")
    time.sleep(1)
    su.cleanup_old(old)
    left = glob.glob(os.path.join(old, "**", "*" + su.OLD_SUFFIX), recursive=True)
    check(not left, "the replaced files are deleted afterwards")
    check(not os.path.exists(os.path.join(old, su.UPDATE_DIR, su.RUNNER)),
          "the copy of the update helper is deleted afterwards")
    httpd.shutdown()
    shutil.rmtree(work, ignore_errors=True)
    print("SUCCESS: per-file update works")
    return 0


if __name__ == "__main__":
    sys.exit(main())
