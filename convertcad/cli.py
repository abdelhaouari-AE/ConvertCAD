"""
cli.py — ConvertCAD from the command line (automation, batch scripts, CI).

Examples
--------
    python -m convertcad.cli plan.pdf          # -> plan.dxf, scale read on the sheet
    python -m convertcad.cli plan.pdf -o plan.dwg            # native DWG
    python -m convertcad.cli plan.pdf --area 20,30,220,180   # part of the sheet
    python -m convertcad.cli plan.pdf -o out/plan.dxf --scale 100 --units mm
    python -m convertcad.cli plan.pdf --pages 1-3,5 --split-pages
    python -m convertcad.cli drawings/ -o dxf/ --recursive --preset structural
    python -m convertcad.cli scan.pdf --ocr-engine rapidocr --ocr-lang fra
    python -m convertcad.cli --list-presets
    python -m convertcad.cli --list-ocr

Exit code: 0 when every file converted, 1 otherwise, 2 on bad arguments.
"""

import argparse
import json
import os
import sys
from typing import List, Optional

from . import APP_NAME, APP_VERSION
from .core.constants import (DXF_VERSIONS, LAYER_MODES, OCR_ENGINES,
                             OCR_LANGUAGES, PT_TO_MM, UNITS)
from .core.options import Options
from .core.paths import find_pdfs
from .core.presets import BUILTIN_PRESETS, apply_preset


def parse_pages(text: str) -> Optional[List[int]]:
    """'all' -> None ; '1-3,5' -> [1, 2, 3, 5]. Raises ValueError."""
    text = (text or "").strip().lower()
    if text in ("", "all", "tout", "toutes"):
        return None
    pages = set()
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a, b = int(a), int(b)
            if a > b:
                a, b = b, a
            pages.update(range(a, b + 1))
        else:
            pages.add(int(part))
    if not pages or min(pages) < 1:
        raise ValueError("page numbers start at 1")
    return sorted(pages)


def parse_area(text: str) -> List[float]:
    """'20,30,220,180' (mm on paper) -> [x0, y0, x1, y1] in page points."""
    try:
        vals = [float(v) for v in text.replace(";", ",").split(",")]
    except ValueError:
        raise ValueError("--area: expected X0,Y0,X1,Y1 in millimetres") \
            from None
    if len(vals) != 4 or vals[2] == vals[0] or vals[3] == vals[1]:
        raise ValueError("--area: expected X0,Y0,X1,Y1 in millimetres")
    x0, x1 = sorted((vals[0], vals[2]))
    y0, y1 = sorted((vals[1], vals[3]))
    return [x0 / PT_TO_MM, y0 / PT_TO_MM, x1 / PT_TO_MM, y1 / PT_TO_MM]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="convertcad",
        description=f"{APP_NAME} {APP_VERSION} — convert PDF drawings to "
                    f"editable DXF (real CAD entities).")
    p.add_argument("input", nargs="?", help="PDF file or folder of PDFs")
    p.add_argument("-o", "--output", help="DXF file, or folder for batch mode")
    p.add_argument("--version", action="version",
                   version=f"{APP_NAME} {APP_VERSION}")
    p.add_argument("--list-presets", action="store_true",
                   help="list the built-in option presets and exit")
    p.add_argument("--list-ocr", action="store_true",
                   help="list the OCR engines and whether they are "
                        "installed, then exit")
    p.add_argument("--preset", choices=sorted(BUILTIN_PRESETS),
                   help="start from a built-in preset")
    p.add_argument("--options-json", metavar="FILE",
                   help="JSON file of options (keys of Options)")
    g = p.add_argument_group("scale & output")
    g.add_argument("--scale", metavar="N|auto", default="auto",
                   help="paper scale denominator, e.g. 100 for 1:100, or "
                        "'auto' to read it on each sheet (default: auto, "
                        "1:50 or the preset's scale when none is written)")
    g.add_argument("--units", choices=sorted(UNITS))
    g.add_argument("--calibrate", type=float, metavar="UNITS_PER_PT",
                   help="real units per PDF point (overrides --scale)")
    g.add_argument("--pages", default="all", help="e.g. all, 1-3,5")
    g.add_argument("--format", choices=["dxf", "dwg"], dest="output_format",
                   help="output file format (default: from -o, else dxf). "
                        "DWG = AutoCAD 2000 format, written by the bundled "
                        "GNU LibreDWG")
    g.add_argument("--area", metavar="X0,Y0,X1,Y1",
                   help="convert only this rectangle of each sheet, in mm "
                        "on the paper from the sheet's top-left corner")
    g.add_argument("--dxf-version", choices=list(DXF_VERSIONS))
    g.add_argument("--split-pages", action="store_true",
                   help="one DXF per page")
    g.add_argument("--layer-mode", choices=sorted(LAYER_MODES))
    g.add_argument("--true-color", action="store_true",
                   help="keep exact RGB colours instead of the ACI palette")
    f = p.add_argument_group("features (all on by default)")
    for flag, dest, help_ in (
            ("--no-arcs", "fit_arcs", "keep curves as splines"),
            ("--no-polylines", "join_polylines", "one LINE per segment"),
            ("--no-text", "text_entities", "do not export text"),
            ("--no-mtext", "group_mtext", "no paragraph grouping"),
            ("--no-hatch", "hatches", "do not export solid fills"),
            ("--no-hatch-patterns", "hatch_patterns",
             "keep hatch patterns as separate lines"),
            ("--no-dashes", "merge_dashes",
             "keep dashed lines as separate dashes"),
            ("--no-block-rotations", "block_rotations",
             "blocks: identical orientation only"),
            ("--no-dims", "dimensions", "no dimension reconstruction"),
            ("--no-ticks", "tick_dimensions", "no tick-mark dimensions"),
            ("--no-leaders", "leaders", "no leader reconstruction"),
            ("--no-blocks", "block_detection", "no block detection"),
            ("--no-pdf-layers", "use_pdf_layers", "ignore PDF layers"),
            ("--no-linetypes", "recognize_linetypes", "dashed/solid only"),
            ("--no-raster", "raster_mode", "do not trace scanned pages"),
            ("--no-ocr", "ocr", "do not OCR scanned pages"),
            ("--no-images", "include_images", "drop raster images"),
            ("--no-shx", "shx_comments", "ignore AutoCAD SHX comments"),
            ("--no-log", "write_log", "no _log.txt next to the DXF")):
        f.add_argument(flag, dest=dest, action="store_false", default=None,
                       help=help_)
    f.add_argument("--min-repeats", type=int, metavar="N",
                   help="block detection: minimum occurrences (default 3)")
    f.add_argument("--precision", choices=["fine", "normal", "loose"],
                   help="curve fitting tolerance")
    s = p.add_argument_group("scanned pages")
    s.add_argument("--ocr-engine", choices=list(OCR_ENGINES),
                   help="auto (default), tesseract (fast), rapidocr "
                        "(accurate), paddleocr (maximum)")
    s.add_argument("--ocr-lang", choices=OCR_LANGUAGES)
    s.add_argument("--ocr-vertical", action="store_true", default=None,
                   help="also read vertical text (slower)")
    s.add_argument("--dpi", type=int, metavar="DPI", help="tracing resolution")
    b = p.add_argument_group("batch")
    b.add_argument("--recursive", action="store_true",
                   help="include sub-folders (folder input)")
    p.add_argument("--json", metavar="FILE", help="write the report(s) as JSON")
    p.add_argument("-q", "--quiet", action="store_true", help="no progress")
    return p


def options_from_args(args) -> Options:
    opt = Options()
    if args.preset:
        opt = apply_preset(opt, BUILTIN_PRESETS[args.preset]["options"])
    if args.options_json:
        with open(args.options_json, "r", encoding="utf-8") as fh:
            data = opt.to_dict()
            data.update(json.load(fh))
            opt = Options.from_dict(data)
    scale = str(args.scale or "auto").strip().lower()
    if scale == "auto":
        opt.auto_scale = True
    else:
        scale = scale.replace("1:", "").replace("1/", "").replace(",", ".")
        try:
            opt.scale_denominator = float(scale)
        except ValueError:
            raise ValueError(f"--scale: expected a number or 'auto', got "
                             f"{args.scale!r}") from None
        if opt.scale_denominator <= 0:
            raise ValueError("--scale must be greater than 0")
        opt.auto_scale = False
    simple = {"units": "units",
              "calibrate": "calibrated_units_per_pt",
              "dxf_version": "dxf_version", "layer_mode": "layer_mode",
              "min_repeats": "block_min_repeats",
              "precision": "curve_precision", "ocr_lang": "ocr_lang",
              "ocr_vertical": "ocr_vertical", "dpi": "raster_dpi",
              "ocr_engine": "ocr_engine", "output_format": "output_format"}
    for arg, field_ in simple.items():
        val = getattr(args, arg, None)
        if val is not None:
            setattr(opt, field_, val)
    for dest in ("fit_arcs", "join_polylines", "text_entities", "group_mtext",
                 "hatches", "hatch_patterns", "merge_dashes",
                 "block_rotations", "dimensions", "tick_dimensions", "leaders",
                 "block_detection", "use_pdf_layers", "recognize_linetypes",
                 "raster_mode", "ocr", "include_images", "shx_comments",
                 "write_log"):
        val = getattr(args, dest, None)
        if val is not None:
            setattr(opt, dest, val)
    if args.area:
        opt.clip_rect = parse_area(args.area)
    if args.split_pages:
        opt.page_mode = "split"
    if args.true_color:
        opt.color_mode = "true"
    opt.pages = parse_pages(args.pages)
    return opt


def _printer(quiet: bool):
    state = {"last": ""}

    def progress(msg: str, frac: float) -> None:
        if quiet:
            return
        line = f"[{frac * 100:5.1f}%] {msg}"
        if line != state["last"]:
            print(line, file=sys.stderr, flush=True)
            state["last"] = line
    return progress


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_presets:
        for key, p in BUILTIN_PRESETS.items():
            print(f"{key:<14} {p['label']}")
        return 0
    if args.list_ocr:
        from .core.ocr import engine_status
        st = engine_status(probe_versions=True)
        for key in ("tesseract", "rapidocr", "paddleocr"):
            mark = "installed " if st[key]["available"] else "missing   "
            print(f"{key:<10} {mark} {OCR_ENGINES[key]:<24} "
                  f"{st[key]['detail']}")
        return 0
    if not args.input:
        parser.print_usage(sys.stderr)
        return 2
    try:
        opt = options_from_args(args)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    progress = _printer(args.quiet)
    from .core.pipeline import convert, convert_folder

    if os.path.isdir(args.input):                          # batch mode
        out_dir = args.output or os.path.join(args.input, opt.output_format)
        files = find_pdfs(args.input, args.recursive)
        if not files:
            print("No PDF found.", file=sys.stderr)
            return 1
        reports = []
        summary = convert_folder(args.input, out_dir, opt, progress=progress,
                                 per_file=lambda i, r: reports.append(r),
                                 recursive=args.recursive, files=files)
        for r in reports:
            mark = "OK " if r.success else "ERR"
            print(f"{mark} {r.pdf_path} -> {', '.join(r.outputs)}"
                  f"  ({r.stats.total_entities()} entities, "
                  f"{r.duration_s:.1f} s)")
            for e in r.errors:
                print(f"     {e}")
        print(f"{summary['ok']}/{summary['total']} converted -> {out_dir}")
        if args.json:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump([r.to_dict() for r in reports], fh, indent=2,
                          ensure_ascii=False)
        return 0 if summary["failed"] == 0 else 1

    if not os.path.isfile(args.input):
        print(f"error: file not found: {args.input}", file=sys.stderr)
        return 2
    if args.output and args.output.lower().endswith(".dwg") and \
            args.output_format is None:
        opt.output_format = "dwg"
    ext = "." + opt.output_format
    out = args.output or os.path.splitext(args.input)[0] + ext
    if os.path.isdir(out):
        out = os.path.join(out, os.path.splitext(
            os.path.basename(args.input))[0] + ext)
    out = os.path.splitext(out)[0] + ext
    rep = convert(args.input, out, opt, progress=progress)
    if not args.quiet:
        print(rep.render())
    else:
        print(f"{rep.status_word()}: {', '.join(rep.outputs)}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(rep.to_json())
    return 0 if rep.success else 1


if __name__ == "__main__":
    sys.exit(main())
