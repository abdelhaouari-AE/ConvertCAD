"""
ocr.py — reading the text of scanned drawings.

One engine: PaddleOCR's PP-OCR models run by RapidOCR + ONNX Runtime
(offline, CPU). They detect whole text lines anywhere on the sheet, at any
angle, small or crossed by lines — far better on drawings than classic OCR.

The models come in packs (see ocr_catalog.py):
  * "latin"      built in: English, French, 45 other Latin-script languages,
                 Chinese, Japanese;
  * "latin_max"  the same languages with larger models (download);
  * one pack per other script (Arabic, Cyrillic, Greek…) (download).

The user chooses
  * the languages: the Latin model, one script, or Latin + one script for
    mixed drawings (e.g. a French plan with an Arabic title block): both
    are read and each line keeps the reading of its own script;
  * the accuracy: standard (built in) or maximum (download).

make_plan() turns that choice into the models to run, falling back to the
built-in model (with a note for the report) when a pack is missing;
recognize() runs the plan on an image and returns OcrWord boxes in pixels.

All imports of RapidOCR / ONNX Runtime are LAZY: nothing loads at start-up.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import ocr_store
from .ocr_catalog import (BUILTIN, BY_ID, MAXIMUM, SCRIPTS, LanguageSet,
                          OcrPack, language_set)

QUALITIES = ("standard", "maximum")


@dataclass
class OcrWord:
    text: str
    box: Tuple[int, int, int, int]       # x, y, w, h (image pixels)
    conf: float                          # 0..100
    vertical: bool = False               # reads bottom-to-top


@dataclass
class _Pass:
    pack: OcrPack
    rec: str = ""                        # model path ("" = built in)
    medium_rec: bool = False


@dataclass
class OcrPlan:
    det: str = ""                        # detection model ("" = built in)
    passes: List[_Pass] = field(default_factory=list)
    description: str = ""                # for the conversion report


# ---------------------------------------------------------------------------
# Availability (for the interface, the command line, the report)
# ---------------------------------------------------------------------------
def available() -> bool:
    """RapidOCR and ONNX Runtime are installed (always true in the
    downloads; from source: pip install -r requirements.txt)."""
    return ocr_store.builtin_available()


def _rtl_ok() -> bool:
    return ocr_store._has_module("bidi")


def pack_usable(pack: OcrPack) -> bool:
    return (ocr_store.is_installed(pack) and available()
            and (not pack.rtl or _rtl_ok()))


def status() -> Dict[str, object]:
    """Cheap: no model is loaded."""
    return {"engine": available(),
            "packs": {p.id: ocr_store.is_installed(p)
                      for p in (BUILTIN, MAXIMUM) + SCRIPTS},
            "folder": ocr_store.user_models_dir()}


def language_choices(include_missing: bool = False
                     ) -> List[Tuple[str, str, bool]]:
    """(key, English label, installed) of the OCR language choices: the
    Latin model, then for each script "Latin + script" and the script
    alone. Missing scripts are listed only with include_missing."""
    out = [("latin", BUILTIN.label, available())]
    for s in SCRIPTS:
        ok = pack_usable(s)
        if ok or include_missing:
            out.append((f"latin+{s.id}", language_set(f"latin+{s.id}").label,
                        ok))
            out.append((s.id, s.label, ok))
    return out


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------
def make_plan(languages: str = "latin", quality: str = "standard"
              ) -> Tuple[Optional[OcrPlan], str]:
    """(plan or None, note for the report or '')."""
    if not available():
        return None, ("OCR skipped: the OCR engine (RapidOCR) is not "
                      "installed; geometry tracing was still performed.")
    notes = []
    lset: LanguageSet = language_set(languages)
    plan = OcrPlan()
    maximum = quality == "maximum"
    if maximum and not pack_usable(MAXIMUM):
        notes.append("Maximum accuracy models are not installed: the "
                     "standard model was used (download them in Settings > "
                     "Scanned pages > OCR languages and models).")
        maximum = False
    if maximum:
        det = next(f for f in MAXIMUM.files if f.role == "det")
        plan.det = ocr_store.find_file(det)
    for pid in lset.packs:
        pack = BY_ID[pid]
        if pack.builtin:
            if maximum:
                rec = next(f for f in MAXIMUM.files if f.role == "rec")
                plan.passes.append(_Pass(pack, ocr_store.find_file(rec),
                                         medium_rec=True))
            else:
                plan.passes.append(_Pass(pack))
            continue
        if not pack_usable(pack):
            why = ("python-bidi is missing" if ocr_store.is_installed(pack)
                   else "it is not installed")
            notes.append(f"OCR language '{pack.label}' unavailable ({why}): "
                         f"the built-in model was used for the other "
                         f"languages.")
            continue
        plan.passes.append(_Pass(pack, ocr_store.find_file(pack.files[0])))
    if not plan.passes:                       # the only script was missing
        plan.passes.append(_Pass(BUILTIN))
    used = LanguageSet("", [p.pack.id for p in plan.passes])
    plan.description = used.label + (", maximum accuracy" if maximum else "")
    return plan, " ".join(notes)


# ---------------------------------------------------------------------------
# Recognition
# ---------------------------------------------------------------------------
_ENGINES: Dict[tuple, object] = {}


def _no_telemetry() -> None:
    """ConvertCAD sends nothing anywhere: ONNX Runtime's usage data is
    switched off by ORT_DISABLE_TELEMETRY (set in convertcad/__init__.py,
    before the library loads); this also switches off its events (Windows
    builds can log them for Microsoft)."""
    try:
        import onnxruntime
        onnxruntime.disable_telemetry_events()
    except Exception:                                      # pragma: no cover
        pass


def _engine(det: str, ps: _Pass):
    """A RapidOCR instance for one detection + recognition model pair.
    Models given by path are used as they are: never downloaded."""
    key = (det, ps.rec, ps.pack.id)
    eng = _ENGINES.get(key)
    if eng is not None:
        return eng
    _no_telemetry()
    from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
    params = {"Global.log_level": "error"}
    if det:
        params["Det.model_path"] = det
        params["Det.model_type"] = ModelType.MEDIUM
    if ps.rec:
        params["Rec.model_path"] = ps.rec
        if ps.medium_rec:
            params["Rec.model_type"] = ModelType.MEDIUM
        elif ps.pack.lang_type:
            # script model: RapidOCR needs its language (Arabic is put back
            # in reading order, right to left, with python-bidi)
            params.update({"Rec.lang_type": LangRec[ps.pack.lang_type],
                           "Rec.ocr_version": OCRVersion.PPOCRV5,
                           "Rec.model_type": ModelType.MOBILE})
    eng = RapidOCR(params=params)
    _ENGINES[key] = eng
    return eng


def _quads_to_words(boxes, texts, scores) -> List[OcrWord]:
    import numpy as np
    words = []
    for quad, text, score in zip(boxes, texts, scores):
        text = (text or "").strip()
        if not text:
            continue
        q = np.asarray(quad, dtype=float).reshape(-1, 2)
        x0, y0 = q.min(axis=0)
        x1, y1 = q.max(axis=0)
        w, h = int(round(x1 - x0)), int(round(y1 - y0))
        vertical = h > 1.5 * w and len(text) > 1
        words.append(OcrWord(text, (int(x0), int(y0), w, h),
                             float(score) * 100.0, vertical))
    return words


def _run(det: str, ps: _Pass, img) -> List[OcrWord]:
    res = _engine(det, ps)(img)
    return _quads_to_words(res.boxes if res.boxes is not None else [],
                           res.txts or (), res.scores or ())


def recognize(img, plan: OcrPlan) -> List[OcrWord]:
    """Run a plan on a grayscale (or RGB) image. Raises on failure."""
    words = _run(plan.det, plan.passes[0], img)
    for ps in plan.passes[1:]:                 # Latin + one script
        extra = _run(plan.det, ps, img)
        words = merge_script(words, extra, ps.pack.script)
    return words


def script_share(text: str, ranges) -> float:
    """Share of the letters of `text` that belong to the given script."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    inside = sum(1 for c in letters
                 if any(a <= ord(c) <= b for a, b in ranges))
    return inside / len(letters)


def merge_script(base: List[OcrWord], extra: List[OcrWord],
                 ranges) -> List[OcrWord]:
    """Keep the second reading where the line is mostly in its script
    (replacing the Latin reading of the same place), the Latin reading
    everywhere else."""
    out = list(base)
    for a in extra:
        if script_share(a.text, ranges) < 0.5:
            continue
        out = [w for w in out if not _overlap(a, w)] + [a]
    return out


def _overlap(a: OcrWord, b: OcrWord) -> bool:
    """The two boxes cover mostly the same place."""
    ax, ay, aw, ah = a.box
    x, y, w, h = b.box
    ix = min(ax + aw, x + w) - max(ax, x)
    iy = min(ay + ah, y + h) - max(ay, y)
    return ix > 0 and iy > 0 and ix * iy > 0.5 * min(aw * ah, w * h)
