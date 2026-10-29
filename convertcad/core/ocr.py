"""
ocr.py — three OCR engines for scanned drawings, behind one interface.

    Fast      Tesseract   classic engine, small, good on clean typed text
    Accurate  RapidOCR    PaddleOCR's PP-OCR models run with ONNX Runtime:
                          reads whole text lines, small and rotated text,
                          much better than Tesseract on drawings; models
                          included (about 30 MB), fully offline
    Maximum   PaddleOCR   the largest PP-OCR models: the PaddleOCR library
                          when it is installed (running from source), else
                          the same large models through RapidOCR when their
                          files are in the "ocr_models" folder

"Automatic" picks the best engine available. Every engine returns OcrWord
boxes in image pixels; raster.py turns them into TEXT entities.

All imports are LAZY: nothing here loads at application start.
"""

import os
import shutil
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

ENGINE_ORDER = ("paddleocr", "rapidocr", "tesseract")   # best first

# Optional larger models (see scripts/get_ocr_models.py)
MEDIUM_DET = "PP-OCRv6_det_medium.onnx"
MEDIUM_REC = "PP-OCRv6_rec_medium.onnx"
ARABIC_REC = "arabic_PP-OCRv5_rec_mobile.onnx"


@dataclass
class OcrWord:
    text: str
    box: Tuple[int, int, int, int]       # x, y, w, h (image pixels)
    conf: float                          # 0..100
    vertical: bool = False               # reads bottom-to-top


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------
def _app_dirs() -> List[str]:
    exe_dir = os.path.dirname(getattr(sys, "executable", "") or "")
    project = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    bundle = getattr(sys, "_MEIPASS", "")
    dirs = [exe_dir, project, os.path.join(project, "vendor")]
    if bundle:
        dirs.append(bundle)
    return dirs


def models_dir() -> str:
    """Folder holding the optional OCR models ('' when absent)."""
    env = os.environ.get("CONVERTCAD_OCR_MODELS", "")
    for d in ([env] if env else []) + [os.path.join(x, "ocr_models")
                                       for x in _app_dirs()]:
        if d and os.path.isdir(d):
            return d
    return ""


def _model(name: str) -> str:
    d = models_dir()
    p = os.path.join(d, name) if d else ""
    return p if p and os.path.isfile(p) else ""


def find_tesseract() -> Optional[str]:
    """Locate the Tesseract program without requiring an installation:
      1. a 'tesseract' folder next to ConvertCAD.exe (portable bundle)
      2. on PATH
      3. standard Windows install locations
    Returns the executable path, or None."""
    for d in _app_dirs():
        c = os.path.join(d, "tesseract", "tesseract.exe")
        if os.path.isfile(c):
            return c
    exe = shutil.which("tesseract")
    if exe:
        return exe
    for c in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
              r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
              os.path.expandvars(
                  r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
              "/usr/bin/tesseract", "/usr/local/bin/tesseract",
              "/opt/homebrew/bin/tesseract"):
        if os.path.isfile(c):
            return c
    return None


def _has_module(name: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Availability (for the interface, the CLI and "Automatic")
# ---------------------------------------------------------------------------
def engine_status(probe_versions: bool = False) -> Dict[str, dict]:
    """{engine: {"available": bool, "detail": str}} — cheap: no model is
    loaded. probe_versions=True also asks Tesseract its version."""
    st: Dict[str, dict] = {}
    tess = find_tesseract() if _has_module("pytesseract") else None
    detail = ""
    if tess and probe_versions:
        try:
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = tess
            detail = f"Tesseract {pytesseract.get_tesseract_version()}"
        except Exception:                                  # pragma: no cover
            detail = "Tesseract"
    st["tesseract"] = {"available": bool(tess), "detail": detail or
                       ("Tesseract" if tess else "Tesseract not found")}
    rapid = _has_module("rapidocr") and _has_module("onnxruntime")
    st["rapidocr"] = {"available": rapid,
                      "detail": "RapidOCR (PP-OCR models, ONNX Runtime)"
                      if rapid else "RapidOCR not installed"}
    paddle_lib = _has_module("paddleocr") and _has_module("paddle")
    medium = rapid and bool(_model(MEDIUM_DET) and _model(MEDIUM_REC))
    st["paddleocr"] = {
        "available": paddle_lib or medium,
        "detail": ("PaddleOCR library" if paddle_lib else
                   "PaddleOCR large models (via RapidOCR)" if medium else
                   "PaddleOCR / large models not installed")}
    st["arabic_rapid"] = {"available": rapid and _has_module("bidi")
                          and bool(_model(ARABIC_REC)),
                          "detail": "Arabic model for RapidOCR"}
    return st


def resolve_engine(requested: str, lang: str = "eng") -> Tuple[str, str]:
    """(engine actually used, note for the report or '')."""
    st = engine_status()
    wants_arabic = "ara" in (lang or "")
    if requested in ("", "auto"):
        for name in ENGINE_ORDER:
            if name == "rapidocr" and wants_arabic and \
                    not st["arabic_rapid"]["available"]:
                continue
            if st[name]["available"]:
                return name, ""
        return "", "No OCR engine is available."
    if st.get(requested, {}).get("available"):
        if requested == "rapidocr" and wants_arabic and \
                not st["arabic_rapid"]["available"] and \
                st["tesseract"]["available"]:
            return "tesseract", ("Arabic text: the Arabic model for RapidOCR "
                                 "is not installed, Tesseract was used.")
        return requested, ""
    for name in ENGINE_ORDER[ENGINE_ORDER.index(requested) + 1:] \
            if requested in ENGINE_ORDER else ENGINE_ORDER:
        if st[name]["available"]:
            return name, (f"OCR engine '{requested}' is not installed; "
                          f"'{name}' was used instead.")
    return "", "No OCR engine is available."


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------
def _tesseract(img, lang: str) -> List[OcrWord]:
    import pytesseract
    exe = find_tesseract()
    if exe is None:
        raise RuntimeError("Tesseract not found")
    pytesseract.pytesseract.tesseract_cmd = exe
    data, err = None, None
    for language in (lang, "eng"):
        try:
            data = pytesseract.image_to_data(
                img, lang=language, output_type=pytesseract.Output.DICT,
                config="--psm 11")
            break
        except Exception as exc:                          # missing language
            err = exc
    if data is None:
        raise RuntimeError(f"OCR failed: {err}")
    words = []
    for i, word in enumerate(data["text"]):
        word = (word or "").strip()
        if not word:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        words.append(OcrWord(word, (int(data["left"][i]), int(data["top"][i]),
                                    int(data["width"][i]),
                                    int(data["height"][i])), conf))
    return words


_RAPID_CACHE: Dict[tuple, object] = {}


def _no_telemetry() -> None:
    """ConvertCAD sends nothing anywhere: switch off ONNX Runtime's usage
    events (Windows builds can log them for Microsoft)."""
    try:
        import onnxruntime
        onnxruntime.disable_telemetry_events()
    except Exception:                                      # pragma: no cover
        pass


def _rapid_engine(det: str = "", rec: str = ""):
    """RapidOCR with its own small models, or with model files given by
    path (larger models, Arabic). A model given by path is used as is: no
    download is ever attempted, so the engine works offline."""
    key = (det, rec)
    eng = _RAPID_CACHE.get(key)
    if eng is None:
        _no_telemetry()
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
        params = {"Global.log_level": "error"}
        if det:
            params["Det.model_path"] = det
            if os.path.basename(det) == MEDIUM_DET:
                params["Det.model_type"] = ModelType.MEDIUM
        if rec:
            params["Rec.model_path"] = rec
            if os.path.basename(rec) == MEDIUM_REC:
                params["Rec.model_type"] = ModelType.MEDIUM
            elif os.path.basename(rec) == ARABIC_REC:
                # Arabic: RapidOCR puts the letters back in reading order
                # (right to left, with python-bidi) - DXF text stores them
                # in that order.
                params.update({"Rec.lang_type": LangRec.ARABIC,
                               "Rec.ocr_version": OCRVersion.PPOCRV5,
                               "Rec.model_type": ModelType.MOBILE})
        eng = RapidOCR(params=params)
        _RAPID_CACHE[key] = eng
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


def _rapidocr(img, lang: str, large: bool = False) -> List[OcrWord]:
    det = rec = ""
    if large:
        det, rec = _model(MEDIUM_DET), _model(MEDIUM_REC)
    res = _rapid_engine(det, rec)(img)
    words = _quads_to_words(res.boxes if res.boxes is not None else [],
                            res.txts or (), res.scores or ())
    if "ara" in (lang or "") and _model(ARABIC_REC) and _has_module("bidi"):
        ara = _rapid_engine(det, _model(ARABIC_REC))(img)
        words = _merge_arabic(words, _quads_to_words(
            ara.boxes if ara.boxes is not None else [], ara.txts or (),
            ara.scores or ()), only_arabic=lang != "ara")
    return words


def _arabic_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if "\u0600" <= c <= "\u06ff") / len(letters)


def _merge_arabic(latin: List[OcrWord], arabic: List[OcrWord],
                  only_arabic: bool) -> List[OcrWord]:
    """Keep the Arabic reading where the line is mostly Arabic script."""
    if not only_arabic:
        return arabic
    out = list(latin)
    for a in arabic:
        if _arabic_share(a.text) < 0.5:
            continue
        ax, ay, aw, ah = a.box
        replaced = False
        for k, w in enumerate(out):
            x, y, ww, hh = w.box
            ix = min(ax + aw, x + ww) - max(ax, x)
            iy = min(ay + ah, y + hh) - max(ay, y)
            if ix > 0 and iy > 0 and ix * iy > 0.5 * min(aw * ah, ww * hh):
                out[k] = a
                replaced = True
                break
        if not replaced:
            out.append(a)
    return out


_PADDLE: Dict[str, object] = {}          # one PaddleOCR per language


def _paddleocr(img, lang: str) -> List[OcrWord]:
    import numpy as np
    plang = "ar" if lang == "ara" else "fr" if "fra" in lang else "en"
    engine = _PADDLE.get(plang)
    if engine is None:
        from paddleocr import PaddleOCR
        engine = _PADDLE[plang] = PaddleOCR(
            lang=plang, use_doc_orientation_classify=False,
            use_doc_unwarping=False, use_textline_orientation=True)
    rgb = np.stack([img] * 3, axis=-1) if img.ndim == 2 else img
    words: List[OcrWord] = []
    for res in engine.predict(rgb):
        data = res if isinstance(res, dict) else getattr(res, "json", {})
        data = data.get("res", data)
        words += _quads_to_words(data.get("rec_polys", []),
                                 data.get("rec_texts", []),
                                 data.get("rec_scores", []))
    return words


def recognize(img, lang: str, engine: str) -> List[OcrWord]:
    """Run one engine on a grayscale image. Raises on failure."""
    if engine == "tesseract":
        return _tesseract(img, lang)
    if engine == "rapidocr":
        return _rapidocr(img, lang)
    if engine == "paddleocr":
        if _has_module("paddleocr") and _has_module("paddle"):
            return _paddleocr(img, lang)
        return _rapidocr(img, lang, large=True)
    raise ValueError(f"unknown OCR engine: {engine}")


def reads_any_orientation(engine: str) -> bool:
    """PP-OCR engines find vertical text themselves; Tesseract needs the
    extra 'vertical text' pass on the image turned 90 degrees."""
    return engine in ("rapidocr", "paddleocr")
