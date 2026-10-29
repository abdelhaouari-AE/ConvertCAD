"""
get_ocr_models.py — download the optional OCR models bundled with ConvertCAD.

ConvertCAD's "Accurate — RapidOCR" engine works out of the box: its PP-OCR
models come with the rapidocr package. Two optional extras are downloaded
here, once, by whoever BUILDS ConvertCAD (users never run this):

  * PP-OCRv6 "medium" detection + recognition models: the larger models
    used by "Maximum — PaddleOCR" in the portable program and the
    installers (where the PaddleOCR library itself is too big to bundle);
  * the PP-OCRv5 Arabic recognition model (Arabic text on scanned sheets).

Files are saved to vendor/ocr_models/ (not stored in Git). The build
scripts copy that folder next to ConvertCAD.exe as "ocr_models".

    python scripts/get_ocr_models.py              download what is missing
    python scripts/get_ocr_models.py --no-arabic  skip the Arabic model
    python scripts/get_ocr_models.py --check      also test-load the models

Source: RapidOCR's model repository (PaddleOCR models converted to ONNX,
Apache-2.0). Each file is checked against the SHA-256 published by
RapidOCR 3.10.0 before it is kept.
"""

import argparse
import hashlib
import os
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "vendor", "ocr_models")
BASE = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx"

# file name -> (URL, SHA-256)   (from rapidocr 3.10.0, default_models.yaml)
MODELS = {
    "PP-OCRv6_det_medium.onnx": (
        f"{BASE}/PP-OCRv6/det/PP-OCRv6_det_medium.onnx",
        "92078b7355007ccfffcd4c8cd441a3afd4538904d06881b29a155e1e679907c2"),
    "PP-OCRv6_rec_medium.onnx": (
        f"{BASE}/PP-OCRv6/rec/PP-OCRv6_rec_medium.onnx",
        "eef444829dbbe18d7fea59a3f6eb75647518d2b3a9568d27c92e42940204894b"),
}
ARABIC = {
    "arabic_PP-OCRv5_rec_mobile.onnx": (
        f"{BASE}/PP-OCRv5/rec/arabic_PP-OCRv5_rec_mobile.onnx",
        "c1192e632d0baa9146ae5b756a0e635e3dc63c1733737ebfd1629e87144e9295"),
}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, target: str, expected: str, tries: int = 3) -> None:
    """Download to a temporary file, check the SHA-256, then move in place:
    a broken or interrupted download never leaves a bad model behind."""
    last = None
    for attempt in range(1, tries + 1):
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target),
                                   suffix=".part")
        os.close(fd)
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "ConvertCAD-build"})
            with urllib.request.urlopen(req, timeout=60) as resp, \
                    open(tmp, "wb") as out:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    block = resp.read(1 << 20)
                    if not block:
                        break
                    out.write(block)
                    done += len(block)
                    if total:
                        print(f"\r    {done / total:6.1%} of "
                              f"{total / 1e6:.1f} MB", end="", flush=True)
            print()
            got = sha256(tmp)
            if got != expected:
                raise ValueError(f"checksum mismatch (got {got[:12]}…)")
            os.replace(tmp, target)
            return
        except Exception as exc:              # network error, bad checksum
            last = exc
            print(f"    attempt {attempt} failed: {exc}")
            time.sleep(2 * attempt)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    raise RuntimeError(f"could not download {os.path.basename(target)}: "
                       f"{last}")


def check(dest: str) -> bool:
    """Load the models with ConvertCAD's OCR module and read a test image."""
    os.environ["CONVERTCAD_OCR_MODELS"] = dest
    sys.path.insert(0, ROOT)
    import cv2
    import numpy as np

    from convertcad.core import ocr
    img = np.full((140, 700), 255, np.uint8)
    cv2.putText(img, "BEAM 300x600", (20, 95), cv2.FONT_HERSHEY_SIMPLEX,
                1.8, 0, 4)
    ok = True
    for engine in ("rapidocr", "paddleocr"):
        try:
            words = ocr.recognize(img, "eng+fra", engine)
            text = " ".join(w.text for w in words)
            print(f"    {engine:<9} -> {text!r}")
            ok &= "BEAM" in text.upper()
        except Exception as exc:
            print(f"    {engine:<9} FAILED: {exc}")
            ok = False
    st = ocr.engine_status()
    print(f"    Maximum engine uses: {st['paddleocr']['detail']}")
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--dest", default=DEST, help=f"folder (default {DEST})")
    ap.add_argument("--no-arabic", action="store_true",
                    help="skip the Arabic recognition model")
    ap.add_argument("--check", action="store_true",
                    help="test-load the models after downloading")
    args = ap.parse_args(argv)
    os.makedirs(args.dest, exist_ok=True)
    wanted = dict(MODELS)
    if not args.no_arabic:
        wanted.update(ARABIC)
    for name, (url, digest) in wanted.items():
        target = os.path.join(args.dest, name)
        if os.path.isfile(target) and sha256(target) == digest:
            print(f"ok      {name}")
            continue
        print(f"get     {name}")
        try:
            download(url, target, digest)
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    with open(os.path.join(args.dest, "README.txt"), "w",
              encoding="utf-8") as fh:
        fh.write("PaddleOCR models (PP-OCRv6 medium, PP-OCRv5 Arabic) in "
                 "ONNX format, from the RapidOCR project.\n"
                 "Licence: Apache License 2.0 - "
                 "https://github.com/PaddlePaddle/PaddleOCR\n"
                 "Used by ConvertCAD's 'Maximum' OCR engine and for "
                 "Arabic text.\n")
    print(f"Models ready in {args.dest}")
    if args.check:
        print("Checking the models …")
        if not check(args.dest):
            print("ERROR: the models did not read the test image.",
                  file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
