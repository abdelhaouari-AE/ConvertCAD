"""
pipeline.py — orchestrates a whole conversion. Everything calls ONE function:

    report = convert(pdf_path, out_path, Options(...), progress, should_cancel)

`out_path` ending with ".dwg" produces DWG files (through the bundled
LibreDWG converter, see dwg.py); anything else produces DXF.

The interface, the command-line tool, the batch mode and the tests all use
it, so behaviour is identical everywhere. It never raises: every failure is
captured in the returned ConversionReport.

Per page:  extract -> (trace scan + OCR) -> cut to the selected area
           -> rebuild geometry (arcs, splines, dashed lines, hatch patterns,
              polylines) -> annotations -> blocks -> write DXF entities
"""

import os
import shutil
import tempfile
import time
from dataclasses import asdict, replace
from typing import Callable, List, Optional

from .annotations import reconstruct
from .blocks import detect_blocks
from .compat import pymupdf
from .constants import CURVE_PRECISION
from .dxf_writer import DxfWriter, Transform, WriterSettings
from .extractor import PageData, RawText, Style, extract_page
from .geometry import ECircle, rebuild
from .licensing import check_license
from .options import Options
from .paths import find_pdfs, output_paths
from .patterns import add_mask_holes
from .pdfinfo import detect_scale
from .report import ConversionReport, PageResult
from .units import compute_scale, effective_denominator

__all__ = ["Options", "Cancelled", "convert", "convert_folder", "find_pdfs",
           "output_paths"]

ProgressFn = Callable[[str, float], None]


class Cancelled(Exception):
    """Raised internally when the user cancels a running conversion."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _dedupe_texts(texts: List[RawText]) -> List[RawText]:
    """Drop texts printed twice at the same place (fake bold, overlays)."""
    seen, out = set(), []
    for t in texts:
        key = (t.text, round(t.origin[0], 1), round(t.origin[1], 1))
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def convert(pdf_path: str, out_path: str, opt: Optional[Options] = None,
            progress: Optional[ProgressFn] = None,
            should_cancel: Optional[Callable[[], bool]] = None
            ) -> ConversionReport:
    """Full conversion. Never raises; read the returned report."""
    opt = opt or Options()
    if out_path.lower().endswith(".dwg"):
        if opt.output_format != "dwg":
            opt = replace(opt, output_format="dwg")
        return _convert_to_dwg(pdf_path, out_path, opt, progress,
                               should_cancel)
    return _convert_dxf(pdf_path, out_path, opt, progress, should_cancel)


def _convert_dxf(pdf_path: str, dxf_path: str, opt: Options,
                 progress: Optional[ProgressFn],
                 should_cancel: Optional[Callable[[], bool]]
                 ) -> ConversionReport:
    t0 = time.time()
    rep = ConversionReport(pdf_path=pdf_path, dxf_path=dxf_path,
                           options=opt.describe())
    rep.source_options = opt          # lets the interface translate them

    def say(msg: str, frac: float) -> None:
        if should_cancel and should_cancel():
            raise Cancelled()
        if progress:
            try:
                progress(msg, max(0.0, min(1.0, frac)))
            except Cancelled:
                raise
            except Exception:                              # pragma: no cover
                pass

    ok, msg = check_license()                 # licensing hook (licensing.py)
    if not ok:
        rep.errors.append(msg)
        rep.duration_s = time.time() - t0
        return rep

    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:
        rep.errors.append(f"Cannot open PDF: {exc}")
        rep.duration_s = time.time() - t0
        return rep
    if doc.needs_pass:
        rep.errors.append("The PDF is password-protected. Remove the "
                          "password (print to PDF) and try again.")
        rep.duration_s = time.time() - t0
        return rep

    meta = doc.metadata or {}
    rep.producer = " / ".join(v for v in (meta.get("creator"),
                                          meta.get("producer")) if v)
    rep.pages_total = doc.page_count
    pages = [p for p in (opt.pages or range(1, doc.page_count + 1))
             if 1 <= p <= doc.page_count]
    rep.pages_converted = pages
    if not pages:
        rep.errors.append("No valid pages selected.")
        rep.duration_s = time.time() - t0
        return rep

    version = opt.writer_dxf_version()
    scale = compute_scale(opt.units, opt.scale_denominator,
                          opt.calibrated_units_per_pt)
    settings = WriterSettings(
        dxf_version=version, units=opt.units,
        layer_mode=opt.layer_mode, use_pdf_layers=opt.use_pdf_layers,
        color_mode=opt.color_mode, text_height_factor=opt.text_height_factor,
        effective_scale=effective_denominator(scale, opt.units),
        ignore_white_fills=opt.ignore_white_fills,
        ignore_background_fills=opt.ignore_background_fills)
    outputs = output_paths(dxf_path, pages, opt.page_mode)
    rep.outputs = list(outputs)
    try:                                   # images are written page by page
        os.makedirs(os.path.dirname(os.path.abspath(dxf_path)), exist_ok=True)
    except OSError as exc:
        rep.errors.append(f"Cannot create the output folder: {exc}")
        rep.duration_s = time.time() - t0
        doc.close()
        return rep
    precision = CURVE_PRECISION.get(opt.curve_precision, 1.0)
    # hatch patterns need HATCH entities: not in DXF R12 (lines are kept)
    patterns = opt.hatch_patterns and version != "R12"
    n = len(pages)
    writers = []
    saved: List[str] = []

    try:
        writer = None
        x_offset = 0.0
        for k, pno in enumerate(pages):
            base = k / n * 0.94

            def step(msg, f, _b=base, _p=pno):
                say(f"Page {_p}/{rep.pages_total}: {msg}", _b + f * 0.94 / n)

            if writer is None or opt.page_mode == "split":
                writer = DxfWriter(WriterSettings(**asdict(settings)))
                writers.append(writer)
                x_offset = 0.0
            out_path = outputs[min(k, len(outputs) - 1)]
            t_page = time.time()
            try:
                step("reading the PDF…", 0.0)
                pd = extract_page(doc, pno - 1,
                                  read_shx_comments=opt.shx_comments,
                                  text_outlines=opt.shx_comments)
                rep.warnings.extend(pd.warnings)
                if pd.text_outlines:
                    rep.page_notes.append(
                        f"Page {pno}: {pd.text_outlines} letter outline(s) "
                        f"replaced by the real text written over them.")
                kind = pd.kind
                traced_circles = _scanned_page(doc, pd, opt, rep, step)
                pd.texts = _dedupe_texts(pd.texts)
                if opt.clip_rect:
                    traced_circles = _clip(pd, opt, rep, traced_circles)
                masks = []
                if opt.ignore_white_fills:
                    masks = _drop_white(pd, rep)

                page_scale = _page_scale(pd, opt, scale, rep)
                if k == 0 and page_scale != scale:     # linetype scale
                    writer.set_ltscale(effective_denominator(page_scale,
                                                             opt.units))
                tr = Transform(pd.height, page_scale, x_offset)
                rep.placements.append({
                    "page": pno, "file": outputs.index(out_path),
                    "x_offset": x_offset, "scale": page_scale,
                    "width_pt": pd.width, "height_pt": pd.height,
                    "clip": list(opt.clip_rect) if opt.clip_rect else None})
                step("rebuilding geometry…", 0.45)
                rp = rebuild(pd, fit_arcs=opt.fit_arcs,
                             join_polylines=opt.join_polylines,
                             join_splines=opt.join_splines,
                             precision=precision,
                             merge_dashes=opt.merge_dashes,
                             hatch_patterns=patterns)
                if masks and rp.hatch_patterns:
                    add_mask_holes(rp.hatch_patterns, masks)
                if traced_circles:
                    tstyle = Style(color=(0, 0, 0), width=0.4,
                                   pdf_layer="TRACE_LINES")
                    rp.circles.extend(ECircle(center=c.center, radius=c.radius,
                                              style=tstyle)
                                      for c in traced_circles)
                if not opt.recognize_linetypes:
                    for e in (rp.polylines + rp.arcs + rp.circles
                              + rp.splines):
                        e.style = replace(e.style, dash_pattern="",
                                          linetype="DASHED" if e.style.dashed
                                          else "CONTINUOUS")

                step("reconstructing dimensions and leaders…", 0.6)
                ann = reconstruct(rp, enable_dims=opt.dimensions,
                                  enable_leaders=opt.leaders,
                                  enable_ticks=opt.tick_dimensions,
                                  units_per_pt=page_scale)

                step("detecting repeated symbols…", 0.7)
                br = (detect_blocks(rp, opt.block_min_repeats,
                                    rotations=opt.block_rotations)
                      if opt.block_detection else None)

                step("writing DXF entities…", 0.8)
                writer.prepare_layers(rp)
                image_base = os.path.splitext(out_path)[0]
                if opt.include_images:
                    writer.write_images(pd, tr, image_base)
                if opt.hatches:
                    writer.write_hatches(pd, ann.consumed_fills, tr)
                writer.write_pattern_hatches(rp, tr)
                if br is not None:
                    writer.write_blocks(br, tr)
                writer.write_geometry(rp, tr)
                if opt.text_entities:
                    writer.write_texts(pd.texts, ann.consumed_texts,
                                       {id(t) for t in ann.dim_raw_texts},
                                       tr, group_mtext=opt.group_mtext)
                    if pd.shx_texts:
                        sizes = [t.height for t in pd.texts] or [9.9]
                        writer.write_shx_texts(pd.shx_texts, tr,
                                               sorted(sizes)[len(sizes) // 2])
                        rep.page_notes.append(
                            f"Page {pno}: {len(pd.shx_texts)} AutoCAD SHX "
                            f"text(s) recovered on layer TEXT_SHX.")
                writer.write_annotations(ann, tr)
                _rebuild_notes(rp, pno, rep)
                rep.pages.append(PageResult(pno, kind,
                                            seconds=time.time() - t_page))
                if opt.page_mode != "split":
                    x_offset += pd.width * page_scale * opt.page_gap_factor
            except Cancelled:
                raise
            except Exception as exc:                      # page-level safety
                rep.errors.append(f"Page {pno}: conversion failed ({exc}).")
                rep.pages.append(PageResult(pno, "error", note=str(exc)))

            if opt.page_mode == "split":
                say(f"Saving {os.path.basename(out_path)}…",
                    (k + 1) / n * 0.94)
                if _save(writer, out_path, rep):
                    saved.append(out_path)

        if opt.page_mode != "split" and writers:
            say(f"Saving {os.path.basename(outputs[0])}…", 0.96)
            if _save(writers[0], outputs[0], rep):
                saved.append(outputs[0])
    except Cancelled:
        rep.cancelled = True
        rep.errors.append("Conversion cancelled by the user.")
    finally:
        doc.close()

    for w in writers:
        rep.stats.merge(w.stats)
    # remove duplicate layer names from the merged list, keep order
    rep.stats.layers = list(dict.fromkeys(rep.stats.layers))
    ok_pages = [p for p in rep.pages if p.kind != "error"]
    rep.success = (not rep.cancelled and bool(ok_pages)
                   and len(saved) == len(outputs))
    rep.duration_s = time.time() - t0
    if opt.write_log and not rep.cancelled:
        try:
            rep.save(os.path.splitext(dxf_path)[0] + "_log.txt")
        except Exception as exc:
            rep.warnings.append(f"Could not write the log file: {exc}")
    if progress and not rep.cancelled:
        try:
            progress("Done.", 1.0)
        except Exception:                                  # pragma: no cover
            pass
    return rep


def _convert_to_dwg(pdf_path: str, dwg_path: str, opt: Options,
                    progress: Optional[ProgressFn],
                    should_cancel: Optional[Callable[[], bool]]
                    ) -> ConversionReport:
    """Write AutoCAD 2000 DXF file(s) in a private folder, convert them to
    DWG next to `dwg_path` and move their raster images there."""
    from .dwg import dxf_to_dwg, find_tools
    t0 = time.time()
    tools = find_tools()
    final_dir = os.path.dirname(os.path.abspath(dwg_path))
    stem = os.path.splitext(os.path.basename(dwg_path))[0]
    tmp = tempfile.mkdtemp(prefix="convertcad_dwg_")
    try:
        inner = replace(opt, write_log=False)
        rep = _convert_dxf(pdf_path, os.path.join(tmp, stem + ".dxf"), inner,
                           None if progress is None else
                           (lambda m, f: progress(m, f * 0.9)),
                           should_cancel)
        rep.options = opt.describe()
        rep.source_options = opt
        rep.dxf_path = dwg_path
        if not rep.success:
            rep.outputs = [os.path.join(final_dir, os.path.basename(p))
                           .rsplit(".", 1)[0] + ".dwg" for p in rep.outputs]
            return rep
        if not tools.available:
            rep.errors.append("DWG output unavailable: the LibreDWG converter "
                              "(dxf2dwg) was not found next to ConvertCAD.")
            rep.success = False
            return rep
        os.makedirs(final_dir, exist_ok=True)
        dwgs = []
        for k, dxf in enumerate(rep.outputs):
            target = os.path.join(final_dir, os.path.splitext(
                os.path.basename(dxf))[0] + ".dwg")
            if progress:
                progress(f"Saving {os.path.basename(target)}…",
                         0.9 + 0.1 * k / max(len(rep.outputs), 1))
            res = dxf_to_dwg(dxf, target, verify=True, tools=tools)
            if not res.ok:
                # never leave the user empty-handed: the DXF (AutoCAD 2000)
                # is saved where the DWG was expected
                kept = os.path.splitext(target)[0] + ".dxf"
                try:
                    shutil.copyfile(dxf, kept)
                    res.message += (f" The drawing was saved as DXF "
                                    f"instead: {os.path.basename(kept)}")
                except OSError:
                    pass
                rep.errors.append(f"{os.path.basename(target)}: "
                                  f"{res.message}")
                continue
            dwgs.append(target)
            checked = (f", {res.entities_dwg} entities verified"
                       if res.entities_dwg >= 0 else "")
            rep.page_notes.append(
                f"{os.path.basename(target)}: DWG written by GNU LibreDWG "
                f"{tools.version} (AutoCAD 2000 format{checked}).")
        for img in rep.stats.image_files:                  # images follow
            if os.path.isfile(img):
                dst = os.path.join(final_dir, os.path.basename(img))
                shutil.copyfile(img, dst)
        rep.stats.image_files = [os.path.join(final_dir, os.path.basename(p))
                                 for p in rep.stats.image_files]
        rep.outputs = dwgs
        rep.success = len(dwgs) == len(output_paths(
            dwg_path, rep.pages_converted, opt.page_mode))
        rep.duration_s = time.time() - t0
        if opt.write_log:
            try:
                rep.save(os.path.join(final_dir, stem + "_log.txt"))
            except Exception as exc:
                rep.warnings.append(f"Could not write the log file: {exc}")
        if progress and rep.success:
            progress("Done.", 1.0)
        return rep
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _save(writer: DxfWriter, path: str, rep: ConversionReport) -> bool:
    try:
        folder = os.path.dirname(os.path.abspath(path))
        os.makedirs(folder, exist_ok=True)
        writer.save(path)
        return True
    except Exception as exc:
        rep.errors.append(f"Cannot save {os.path.basename(path)}: {exc}")
        return False


def _clip(pd: PageData, opt: Options, rep: ConversionReport,
          traced_circles: list) -> list:
    """Cut the page (and traced circles) to the selected area."""
    from .clip import clip_page
    counts = clip_page(pd, opt.clip_rect)
    x0, y0, x1, y1 = opt.clip_rect
    kept = [c for c in traced_circles
            if x0 <= c.center[0] <= x1 and y0 <= c.center[1] <= y1]
    rep.page_notes.append(
        f"Page {pd.number}: selected area only — {counts['after']} of "
        f"{counts['before']} PDF elements kept.")
    return kept


def _is_white(rgb) -> bool:
    return min(rgb[:3]) >= 250


def _drop_white(pd: PageData, rep: ConversionReport) -> list:
    """White strokes and texts are invisible on the paper sheet (masks,
    erased content); in CAD they would turn black or white and show. They
    are left out. Returns the outlines of the white FILLS (masks), used to
    cut holes in rebuilt hatches."""
    n0 = len(pd.segments) + len(pd.beziers) + len(pd.texts)
    pd.segments = [s for s in pd.segments if not _is_white(s.style.color)]
    pd.beziers = [b for b in pd.beziers if not _is_white(b.style.color)]
    pd.texts = [t for t in pd.texts if not _is_white(t.color)]
    dropped = n0 - (len(pd.segments) + len(pd.beziers) + len(pd.texts))
    if dropped:
        rep.page_notes.append(f"Page {pd.number}: {dropped} white (invisible)"
                              f" line(s) or text(s) left out.")
    page_area = pd.width * pd.height
    return [f.points for f in pd.fills
            if _is_white(f.color) and not f.background
            and f.area < 0.5 * page_area]


def _rebuild_notes(rp, pno: int, rep: ConversionReport) -> None:
    if rp.dashed_lines:
        rep.page_notes.append(
            f"Page {pno}: {rp.dashed_lines} dashed line(s) rebuilt from "
            f"{rp.dash_pieces} separate pieces (linetypes measured on the "
            f"PDF).")
    if rp.hatch_patterns:
        rep.page_notes.append(
            f"Page {pno}: {len(rp.hatch_patterns)} hatch pattern(s) rebuilt "
            f"from {rp.hatch_segments} parallel lines.")
    if rp.texture_hatches:
        names = sorted({t.name for t in rp.texture_hatches})
        rough = [t.name for t in rp.texture_hatches if not t.exact]
        rep.page_notes.append(
            f"Page {pno}: {len(rp.texture_hatches)} pattern hatch(es) "
            f"({', '.join(names)}) rebuilt from {rp.texture_pieces} dashes "
            f"and dots" + (f"; {', '.join(sorted(set(rough)))}: scale and "
                           f"position estimated (random-looking pattern)"
                           if rough else "") + ".")


def _page_scale(pd: PageData, opt: Options, default: float,
                rep: ConversionReport) -> float:
    """Units per point for one sheet.

    With ``auto_scale`` (and no calibration) the scale written on the sheet
    ('Echelle : 1/100', 'SCALE 1:50', '2.5:1000'...) is used; when none or
    several different ones are written, the default scale is kept. The
    report says which scale each sheet received, so the user can check it.
    """
    if not opt.auto_scale or opt.calibrated_units_per_pt > 0:
        return default
    den = detect_scale("\n".join(t.text for t in pd.texts + pd.shx_texts))
    if den:
        rep.page_notes.append(f"Page {pd.number}: scale 1:{den:g} read on "
                              f"the sheet.")
        return compute_scale(opt.units, den, 0.0)
    rep.page_notes.append(f"Page {pd.number}: no single scale written on the "
                          f"sheet; 1:{opt.scale_denominator:g} used.")
    return default


def _scanned_page(doc, pd: PageData, opt: Options, rep: ConversionReport,
                  step) -> list:
    """Raster tracing + OCR of a scanned page; returns traced circles."""
    if pd.kind != "scanned":
        if pd.kind == "empty":
            rep.page_notes.append(f"Page {pd.number}: no drawing content.")
        return []
    if not opt.raster_mode:
        rep.page_notes.append(
            f"Page {pd.number}: scanned page — image kept on locked layer "
            f"IMG_RASTER (tracing disabled).")
        return []
    has_text_layer = bool(pd.texts) and opt.use_pdf_text_layer
    do_ocr = opt.ocr and not has_text_layer
    step(f"scanned page — tracing at {opt.raster_dpi} dpi"
         + (" + OCR…" if do_ocr else "…"), 0.1)
    from .raster import merge_into_page, vectorize_page
    try:
        rres = vectorize_page(doc, pd.number - 1, dpi=opt.raster_dpi,
                              ocr=do_ocr, ocr_lang=opt.ocr_lang,
                              ocr_quality=opt.ocr_quality)
    except Exception as exc:
        rep.warnings.append(f"Page {pd.number}: raster tracing failed "
                            f"({exc}); image inserted only.")
        return []
    merge_into_page(pd, rres)
    src = ("text layer already in the PDF used" if has_text_layer
           else f"{len(rres.texts)} OCR text(s) (PP-OCR: {rres.ocr_model})"
           if do_ocr and rres.ocr_model else "OCR skipped" if do_ocr
           else "no OCR")
    rep.page_notes.append(
        f"Page {pd.number}: scanned page traced at {rres.dpi_used} dpi — "
        f"{len(rres.segments)} line(s), {len(rres.circles)} circle(s), "
        f"{len(rres.arcs)} arc(s), {src}; "
        f"original scan kept on locked layer IMG_RASTER for checking.")
    return rres.circles


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------
def convert_folder(input_dir: str, output_dir: str,
                   opt: Optional[Options] = None,
                   progress: Optional[ProgressFn] = None,
                   should_cancel: Optional[Callable[[], bool]] = None,
                   per_file: Optional[Callable[[int, ConversionReport], None]]
                   = None, recursive: bool = False,
                   files: Optional[List[str]] = None) -> dict:
    """Convert every PDF of a folder; each gets its own DXF (or DWG when
    opt.output_format is "dwg") and log. Sub-folders are mirrored in the
    output folder when recursive."""
    opt = opt or Options()
    ext = ".dwg" if opt.output_format == "dwg" else ".dxf"
    pdfs = files if files is not None else find_pdfs(input_dir, recursive)
    summary = {"total": len(pdfs), "ok": 0, "failed": 0, "cancelled": False,
               "reports": []}
    os.makedirs(output_dir, exist_ok=True)
    for k, pdf in enumerate(pdfs):
        if should_cancel and should_cancel():
            summary["cancelled"] = True
            break
        rel = os.path.relpath(pdf, input_dir) if input_dir else \
            os.path.basename(pdf)
        if rel.startswith(".."):
            rel = os.path.basename(pdf)
        out = os.path.join(output_dir, os.path.splitext(rel)[0] + ext)

        name = os.path.basename(pdf)

        def sub(msg, frac, _k=k, _name=name):
            if progress:
                progress(f"[{_k + 1}/{len(pdfs)}] {_name} — {msg}",
                         (_k + frac) / max(len(pdfs), 1))

        rep = convert(pdf, out, opt, progress=sub, should_cancel=should_cancel)
        if rep.cancelled:
            summary["cancelled"] = True
        summary["ok" if rep.success else "failed"] += 1
        summary["reports"].append(rep)
        if per_file:
            per_file(k, rep)
        if rep.cancelled:
            break
    return summary
