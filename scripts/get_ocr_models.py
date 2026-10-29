"""
get_ocr_models.py — download and check ConvertCAD's downloadable OCR models.

USERS DO NOT NEED THIS SCRIPT: they download models from the program
(Settings > Scanned pages > "OCR languages and models…") or with
`ConvertCAD-cli --get-ocr-model ID`. This script is for maintainers:

    python scripts/get_ocr_models.py --list
        the catalogue (convertcad/core/ocr_catalog.py) and what is installed

    python scripts/get_ocr_models.py arabic latin_max
        download packs into the user models folder (as the program does)

    python scripts/get_ocr_models.py --all --dest vendor/ocr_models
        OFFLINE BUILD: every pack into vendor/ocr_models, which the build
        bundles with the program (adds about 200 MB to it)

    python scripts/get_ocr_models.py --all --dest release --mirror-only
        the files of the GitHub release "ocr-models-v1", from RapidOCR's
        model repository (used by .github/workflows/ocr-models.yml)

    python scripts/get_ocr_models.py --notes release/NOTES.md --dest release
        the release description (packs, files, sizes, SHA-256)

    python scripts/get_ocr_models.py --check DIR [--load]
        verify the checksum of every model file in DIR; --load also opens
        each pack with RapidOCR and reads a test image

Every file is checked against its SHA-256 before it is kept (core/ocr_store).
Standard library only, except --load (needs rapidocr + onnxruntime).
"""

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from convertcad.core import ocr_store  # noqa: E402
from convertcad.core.ocr_catalog import (BY_ID, MIRROR_BASE, MODELS_RELEASE,  # noqa: E402
                                         PACKS)


def _progress(name: str):
    state = {"pct": -1, "t": time.time()}

    def show(done: int, total: int) -> None:
        pct = int(done * 100 / total) if total else 0
        if pct // 10 != state["pct"] // 10 or pct == 100:
            state["pct"] = pct
            mb = done / (1024 * 1024)
            print(f"    {name}: {pct:3d} %  ({mb:.1f} MB)", flush=True)
    return show


def list_packs() -> int:
    print(f"Models folder: {ocr_store.user_models_dir()}")
    print(f"Release: {MODELS_RELEASE}    mirror: {MIRROR_BASE}\n")
    for p in PACKS:
        state = ("built in" if p.builtin else
                 "installed" if ocr_store.is_installed(p) else "-")
        print(f"{p.id:<11} {state:<10} {ocr_store.human_size(p.size):>7}  "
              f"{p.label}")
        for f in p.files:
            print(f"{'':<11} {f.name}  {f.size} B  sha256 {f.sha256[:16]}…")
    return 0


def download(ids, dest: str, mirror_only: bool) -> int:
    failed = 0
    for pid in ids:
        pack = BY_ID[pid]
        if pack.builtin:
            continue
        urls = ({f.name: [MIRROR_BASE + f.path] for f in pack.files}
                if mirror_only else None)
        print(f"{pid}: {pack.label}")
        try:
            folder = ocr_store.download_pack(pid, progress=_progress(pid),
                                             dest=dest or None, urls=urls)
            print(f"    OK -> {folder}")
        except ocr_store.DownloadError as exc:
            print(f"    FAILED: {exc}")
            failed += 1
    return 1 if failed else 0


def check(folder: str, load: bool) -> int:
    bad = 0
    for p in PACKS:
        for f in p.files:
            path = os.path.join(folder, f.name)
            if not os.path.isfile(path):
                print(f"missing   {f.name}")
                bad += 1
                continue
            ok = ocr_store._sha256(path) == f.sha256
            size = os.path.getsize(path)
            size_ok = not f.size or size == f.size
            print(f"{'ok' if ok and size_ok else 'BAD':<9} {f.name}  "
                  f"{size} B")
            bad += 0 if ok and size_ok else 1
    if load and not bad:
        bad += _load_all(folder)
    print("ALL GOOD" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


def notes(path: str, folder: str) -> int:
    """Markdown description of the models release."""
    lines = [
        f"# OCR models for ConvertCAD ({MODELS_RELEASE})", "",
        "Optional OCR models, downloaded from ConvertCAD itself (Settings > "
        "Scanned pages > OCR languages and models…) or with "
        "`ConvertCAD-cli --get-ocr-model ID`. Offline computer: download the "
        ".onnx files here, then use \"Install from file…\" in ConvertCAD.",
        "", "PaddleOCR PP-OCR models in ONNX format, as published by the "
        "RapidOCR project (Apache-2.0).", "",
        "| Pack | Reads | File | Size | SHA-256 |",
        "|---|---|---|---|---|"]
    for p in PACKS:
        if p.builtin:
            continue
        for f in p.files:
            fp = os.path.join(folder, f.name)
            size = os.path.getsize(fp) if os.path.isfile(fp) else f.size
            lines.append(f"| `{p.id}` | {p.languages} | {f.name} | "
                         f"{ocr_store.human_size(size)} | `{f.sha256}` |")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"written: {path}")
    return 0


def _load_all(folder: str) -> int:
    """Open every pack with RapidOCR and read a small test image."""
    import numpy as np

    from convertcad.core import ocr
    os.environ["CONVERTCAD_OCR_MODELS"] = os.path.abspath(folder)
    img = np.full((120, 640), 255, np.uint8)
    import cv2
    cv2.putText(img, "PLAN DE MASSE 1/200", (20, 75),
                cv2.FONT_HERSHEY_SIMPLEX, 1.4, 0, 3)
    bad = 0
    for key, quality in [("latin", "standard"), ("latin", "maximum")] + \
            [(s.id, "standard") for s in PACKS if s.kind == "script"]:
        plan, note = ocr.make_plan(key, quality)
        t = time.time()
        try:
            words = ocr.recognize(img, plan)
            text = " | ".join(w.text for w in words)
            print(f"load ok   {key:<11} {quality:<8} "
                  f"{time.time() - t:5.2f} s  {text!r}  {note}")
        except Exception as exc:
            print(f"LOAD BAD  {key:<11} {quality}: {exc}")
            bad += 1
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("packs", nargs="*", help="pack ids (see --list)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--all", action="store_true",
                    help="every downloadable pack")
    ap.add_argument("--dest", default="",
                    help="folder (default: the user models folder)")
    ap.add_argument("--mirror-only", action="store_true",
                    help="download from RapidOCR's repository only (not "
                         "from the ConvertCAD release)")
    ap.add_argument("--check", metavar="DIR",
                    help="verify the model files in DIR")
    ap.add_argument("--load", action="store_true",
                    help="with --check: also run each pack")
    ap.add_argument("--notes", metavar="FILE",
                    help="write the release description (sizes read in "
                         "--dest)")
    args = ap.parse_args(argv)
    if args.list:
        return list_packs()
    if args.notes:
        return notes(args.notes, args.dest or ".")
    if args.check:
        return check(args.check, args.load)
    ids = [p.id for p in PACKS if not p.builtin] if args.all else args.packs
    unknown = [i for i in ids if i not in BY_ID]
    if unknown or not ids:
        ap.error(f"unknown pack(s): {', '.join(unknown)}" if unknown
                 else "name packs, or use --all / --list")
    return download(ids, args.dest, args.mirror_only)


if __name__ == "__main__":
    sys.exit(main())
