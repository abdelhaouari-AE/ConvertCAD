"""
postprocess.py — finalise a converted DXF when the user saves it.

The interface converts into a private temporary folder first, so the user
can REVIEW the result (DXF view, layer list, report) before saving. Layer
edits made in the interface — rename, recolour, remove — are applied here,
on a fresh read of the temporary DXF, while it is copied to its final place.

Also handles the raster images that accompany a DXF (IMAGEDEF file names
follow the new DXF name) and the conversion log.
"""

import os
import shutil
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import ezdxf
from ezdxf import colors as ezcolors

from .dxf_writer import is_neutral, nearest_aci
from .layer_edits import PROTECTED_LAYERS, LayerEdit, LayerRow

__all__ = ["PROTECTED_LAYERS", "LayerEdit", "LayerRow", "FinalizeResult",
           "layer_summary", "apply_layer_edits", "finalize", "describe_edits"]


@dataclass
class FinalizeResult:
    dxf_path: str
    images: List[str] = field(default_factory=list)
    removed_entities: int = 0
    renamed: Dict[str, str] = field(default_factory=dict)
    log_path: str = ""


def _layer_rgb(layer) -> Tuple[int, int, int]:
    try:
        if layer.has_dxf_attrib("true_color"):
            return tuple(layer.rgb)
    except Exception:                                      # pragma: no cover
        pass
    aci = abs(layer.dxf.color or 7)
    if aci == 7:
        return (255, 255, 255)
    return tuple(ezcolors.aci2rgb(aci))


def layer_summary(doc_or_path) -> List[LayerRow]:
    """Layers of a DXF with their entity counts (model space + blocks)."""
    doc = ezdxf.readfile(doc_or_path) if isinstance(doc_or_path, str) \
        else doc_or_path
    counts: Dict[str, int] = {}
    for e in doc.modelspace():
        key = e.dxf.layer.upper()
        counts[key] = counts.get(key, 0) + 1
    for blk in doc.blocks:
        if blk.name.startswith("*") or blk.is_any_layout:
            continue                                       # dims, layouts
        for e in blk:
            key = e.dxf.layer.upper()
            counts[key] = counts.get(key, 0) + 1
    rows = []
    for layer in doc.layers:
        name = layer.dxf.name
        n = counts.get(name.upper(), 0)
        if name.upper() in PROTECTED_LAYERS and n == 0:
            continue
        rows.append(LayerRow(name=name, rgb=_layer_rgb(layer),
                             aci=abs(layer.dxf.color or 7),
                             linetype=layer.dxf.linetype, count=n,
                             locked=layer.is_locked()))
    rows.sort(key=lambda r: (-r.count, r.name.upper()))
    return rows


def _delete_layer_entities(doc, layer_name: str) -> int:
    removed = 0
    target = layer_name.upper()
    containers = [doc.modelspace()] + [
        b for b in doc.blocks if not b.is_any_layout
        and not b.name.startswith("*")]
    for cont in containers:
        for e in list(cont):
            if e.dxf.layer.upper() == target:
                cont.delete_entity(e)
                removed += 1
    return removed


def _rename_layer(doc, old: str, new: str) -> None:
    if old.upper() == new.upper():
        if old != new:                                     # case change only
            doc.layers.get(old).rename(new)
        return
    if new in doc.layers:                                  # merge into target
        for cont in [doc.modelspace()] + [b for b in doc.blocks
                                          if not b.is_any_layout]:
            for e in cont:
                if e.dxf.layer.upper() == old.upper():
                    e.dxf.layer = new
        try:
            doc.layers.remove(old)
        except Exception:                                  # pragma: no cover
            pass
    else:
        doc.layers.get(old).rename(new)


def apply_layer_edits(doc, edits: Dict[str, LayerEdit],
                      color_mode: str = "aci") -> Tuple[int, Dict[str, str]]:
    """Apply edits to an open ezdxf document. Returns (removed, renames)."""
    removed = 0
    renamed: Dict[str, str] = {}
    for name, ed in edits.items():
        if name not in doc.layers or name.upper() in PROTECTED_LAYERS:
            continue
        if not ed.keep:
            removed += _delete_layer_entities(doc, name)
            try:
                doc.layers.remove(name)            # drop the empty layer
            except Exception:                      # pragma: no cover
                pass
            continue
        layer = doc.layers.get(name)
        if ed.color is not None:
            rgb = tuple(int(c) for c in ed.color)
            layer.color = nearest_aci(rgb)
            if color_mode == "true" and not is_neutral(rgb):
                layer.rgb = rgb
            elif layer.has_dxf_attrib("true_color"):
                layer.dxf.discard("true_color")
    for name, ed in edits.items():
        new = (ed.new_name or "").strip()
        if ed.keep and new and new != name and name in doc.layers \
                and name.upper() not in PROTECTED_LAYERS:
            _rename_layer(doc, name, new)
            renamed[name] = new
    return removed, renamed


def finalize(src_dxf: str, dst_dxf: str,
             edits: Optional[Dict[str, LayerEdit]] = None,
             color_mode: str = "aci", log_src: str = "",
             log_note: str = "") -> FinalizeResult:
    """Copy a converted DXF (and its images and log) to its final place,
    applying the layer edits. Raises on I/O errors (caller reports them)."""
    os.makedirs(os.path.dirname(os.path.abspath(dst_dxf)), exist_ok=True)
    res = FinalizeResult(dxf_path=dst_dxf)
    src_dir = os.path.dirname(os.path.abspath(src_dxf))
    dst_dir = os.path.dirname(os.path.abspath(dst_dxf))
    src_stem = os.path.splitext(os.path.basename(src_dxf))[0]
    dst_stem = os.path.splitext(os.path.basename(dst_dxf))[0]

    doc = ezdxf.readfile(src_dxf)
    if edits:
        res.removed_entities, res.renamed = apply_layer_edits(doc, edits,
                                                              color_mode)
    # raster images: copy next to the new DXF, renamed after it
    for imgdef in doc.objects.query("IMAGEDEF"):
        fname = os.path.basename(imgdef.dxf.filename)
        src_img = os.path.join(src_dir, fname)
        new_name = fname
        if fname.startswith(src_stem):
            new_name = dst_stem + fname[len(src_stem):]
        dst_img = os.path.join(dst_dir, new_name)
        if os.path.isfile(src_img):
            if os.path.abspath(src_img) != os.path.abspath(dst_img):
                shutil.copyfile(src_img, dst_img)
            res.images.append(dst_img)
        imgdef.dxf.filename = new_name
    doc.saveas(dst_dxf)

    if log_src and os.path.isfile(log_src):
        res.log_path = os.path.join(dst_dir, dst_stem + "_log.txt")
        with open(log_src, "r", encoding="utf-8") as fh:
            text = fh.read()
        text = text.replace(src_dxf, dst_dxf)
        if log_note:
            text += "\n\n" + log_note
        with open(res.log_path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return res


def describe_edits(edits: Dict[str, LayerEdit]) -> str:
    """Human-readable summary appended to the saved log."""
    lines = []
    for name, ed in sorted(edits.items()):
        if not ed.keep:
            lines.append(f"  - layer {name}: removed")
            continue
        parts = []
        if ed.new_name and ed.new_name != name:
            parts.append(f"renamed to {ed.new_name}")
        if ed.color is not None:
            parts.append("colour #%02X%02X%02X" % tuple(ed.color))
        if parts:
            lines.append(f"  - layer {name}: " + ", ".join(parts))
    if not lines:
        return ""
    return "LAYER EDITS APPLIED AT SAVE TIME\n" + "\n".join(lines)


def finalize_dwg(src_dxf: str, dst_dwg: str,
                 edits: Optional[Dict[str, LayerEdit]] = None,
                 color_mode: str = "aci", log_src: str = "",
                 log_note: str = "") -> FinalizeResult:
    """Like finalize(), but the saved file is a DWG (AutoCAD 2000 format,
    written by the bundled LibreDWG converter and read back to check it).
    The source DXF must be an AutoCAD 2000 DXF (Options.output_format
    "dwg"). Raises RuntimeError when the DWG cannot be written."""
    import tempfile

    from .dwg import dxf_to_dwg
    dst_dir = os.path.dirname(os.path.abspath(dst_dwg))
    stem = os.path.splitext(os.path.basename(dst_dwg))[0]
    os.makedirs(dst_dir, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="convertcad_save_") as tmp:
        work = os.path.join(tmp, stem + ".dxf")
        res = finalize(src_dxf, work, edits, color_mode, log_src=log_src,
                       log_note=log_note)
        dwg = dxf_to_dwg(work, dst_dwg, verify=True)
        if not dwg.ok:
            raise RuntimeError(dwg.message)
        images = []
        for img in res.images:
            target = os.path.join(dst_dir, os.path.basename(img))
            shutil.copyfile(img, target)
            images.append(target)
        log_path = ""
        if res.log_path:
            log_path = os.path.join(dst_dir, stem + "_log.txt")
            with open(res.log_path, "r", encoding="utf-8") as fh:
                text = fh.read().replace(work, dst_dwg)
            checked = (f", {dwg.entities_dwg} entities read back"
                       if dwg.entities_dwg >= 0 else "")
            text += (f"\n\nDWG FILE\n  {dst_dwg}\n  AutoCAD 2000 format, "
                     f"written by GNU LibreDWG{checked}.\n")
            with open(log_path, "w", encoding="utf-8") as fh:
                fh.write(text)
    return FinalizeResult(dxf_path=dst_dwg, images=images,
                          removed_entities=res.removed_entities,
                          renamed=res.renamed, log_path=log_path)


def needs_reconversion_for_dwg(dxf_path: str) -> bool:
    """True when a DXF is not an AutoCAD 2000 DXF (MLEADER, true colour...
    cannot go into a DWG 2000): the drawing must be converted again with
    the DWG output format."""
    try:
        with open(dxf_path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(4000)
    except OSError:
        return True
    return "AC1015" not in head
