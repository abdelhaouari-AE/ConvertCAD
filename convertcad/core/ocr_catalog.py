"""
ocr_catalog.py — the OCR models ConvertCAD knows: one built in, the others
downloaded from the interface (Settings > Scanned pages > OCR languages and
models) or with `ConvertCAD-cli --get-ocr-model ID`.

All models are PaddleOCR's PP-OCR models in ONNX format, as published by the
RapidOCR project (Apache-2.0). They are run by RapidOCR + ONNX Runtime.

    pack        what it reads                                   kind
    latin       English, French, 45 other Latin-script          built in (the
                languages, Chinese, Japanese                    rapidocr package)
    latin_max   the same, maximum accuracy (larger models)      download
    arabic, cyrillic, greek, korean, devanagari, thai,          download
    tamil, telugu       one script each, used alone or together
                        with the Latin model

A download is first tried from ConvertCAD's own GitHub release
(MODELS_RELEASE), then from RapidOCR's model repository (MIRROR_BASE); every
file is checked against its SHA-256 before it is kept.

Standard library only: the interface reads this file at start-up.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

# Where the downloadable files are published (scripts/get_ocr_models.py and
# .github/workflows/ocr-models.yml copy them there).
MODELS_RELEASE = "ocr-models-v1"
RELEASE_BASE = ("https://github.com/abdelhaouari-AE/ConvertCAD/releases/"
                f"download/{MODELS_RELEASE}/")
RELEASE_PAGE = ("https://github.com/abdelhaouari-AE/ConvertCAD/releases/tag/"
                f"{MODELS_RELEASE}")
MIRROR_BASE = ("https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/"
               "v3.10.0/onnx/")


# the built-in model (PP-OCRv6 small detection + recognition + the text
# orientation classifier), inside the rapidocr package: about 30 MB
BUILTIN_SIZE = 9_929_594 + 21_234_383 + 585_532


@dataclass(frozen=True)
class ModelFile:
    name: str               # file name (also the GitHub release asset name)
    path: str               # path under MIRROR_BASE
    sha256: str
    size: int = 0           # bytes (0 = unknown)
    role: str = "rec"       # det | rec


@dataclass(frozen=True)
class OcrPack:
    id: str
    label: str              # short English name (translated in the interface)
    languages: str          # what it reads (English, translated)
    kind: str               # "base": detection + Latin recognition
                            # "script": recognition of one script
    builtin: bool = False
    files: Tuple[ModelFile, ...] = ()
    lang_type: str = ""     # RapidOCR LangRec member (script packs)
    script: Tuple[Tuple[int, int], ...] = ()   # Unicode ranges of the script
    rtl: bool = False       # right-to-left (needs python-bidi)
    short: str = ""         # shorter label in combinations ("… + Arabic")

    @property
    def size(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def urls(self) -> Dict[str, List[str]]:
        """file name -> download addresses, in the order they are tried."""
        return {f.name: [RELEASE_BASE + f.name, MIRROR_BASE + f.path]
                for f in self.files}


def _rec(name: str, sha: str, size: int = 0) -> ModelFile:
    return ModelFile(name, f"PP-OCRv5/rec/{name}", sha, size, "rec")


PACKS: Tuple[OcrPack, ...] = (
    OcrPack(
        "latin", "English, French… (Latin script)",
        "English, French, Spanish, German, Italian, Portuguese, Dutch, "
        "Polish, Turkish, Vietnamese and 37 other Latin-script languages; "
        "Chinese; Japanese",
        "base", builtin=True, short="English, French…"),
    OcrPack(
        "latin_max", "Maximum accuracy",
        "The same languages as the built-in model, with larger models: "
        "better on poor scans and small text, about 3 times slower",
        "base", files=(
            ModelFile("PP-OCRv6_det_medium.onnx",
                      "PP-OCRv6/det/PP-OCRv6_det_medium.onnx",
                      "92078b7355007ccfffcd4c8cd441a3afd4538904d06881b29a155e"
                      "1e679907c2", 0, "det"),
            ModelFile("PP-OCRv6_rec_medium.onnx",
                      "PP-OCRv6/rec/PP-OCRv6_rec_medium.onnx",
                      "eef444829dbbe18d7fea59a3f6eb75647518d2b3a9568d27c92e42"
                      "940204894b", 0, "rec"))),
    OcrPack(
        "arabic", "Arabic", "Arabic, Persian, Urdu (Arabic script)",
        "script", files=(_rec("arabic_PP-OCRv5_rec_mobile.onnx",
                              "c1192e632d0baa9146ae5b756a0e635e3dc63c1733737e"
                              "bfd1629e87144e9295"),),
        lang_type="ARABIC", rtl=True,
        script=((0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF),
                (0xFB50, 0xFDFF), (0xFE70, 0xFEFF))),
    OcrPack(
        "cyrillic", "Cyrillic",
        "Russian, Ukrainian, Belarusian, Bulgarian, Serbian, Macedonian, "
        "Kazakh, Mongolian (Cyrillic script)",
        "script", files=(_rec("cyrillic_PP-OCRv5_rec_mobile.onnx",
                              "90f761b4bfcce0c8c561c0cb5c887b0971d3ec01c32164"
                              "bdf7374a35b0982711"),),
        lang_type="CYRILLIC", script=((0x0400, 0x052F),)),
    OcrPack(
        "greek", "Greek", "Greek",
        "script", files=(_rec("el_PP-OCRv5_rec_mobile.onnx",
                              "b4368bccd557123c702b7549fee6cd1e94b581337d1c9b"
                              "65310f109131542b7f"),),
        lang_type="EL", script=((0x0370, 0x03FF), (0x1F00, 0x1FFF))),
    OcrPack(
        "korean", "Korean", "Korean (Hangul)",
        "script", files=(_rec("korean_PP-OCRv5_rec_mobile.onnx",
                              "cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9"
                              "c41a2e541a25773c9b"),),
        lang_type="KOREAN",
        script=((0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F))),
    OcrPack(
        "devanagari", "Devanagari", "Hindi, Marathi, Nepali (Devanagari)",
        "script", files=(_rec("devanagari_PP-OCRv5_rec_mobile.onnx",
                              "d6f0a906580e3fa6b324a318718f1f31f268b6ea8ef985"
                              "f91c2012a37f52c91e"),),
        lang_type="DEVANAGARI", script=((0x0900, 0x097F),)),
    OcrPack(
        "thai", "Thai", "Thai",
        "script", files=(_rec("th_PP-OCRv5_rec_mobile.onnx",
                              "de541dd83161c241ff426f7ecfd602a0ba77d686cf3ab9"
                              "a6c255ea82fd08006e"),),
        lang_type="TH", script=((0x0E00, 0x0E7F),)),
    OcrPack(
        "tamil", "Tamil", "Tamil",
        "script", files=(_rec("ta_PP-OCRv5_rec_mobile.onnx",
                              "a42448808b7dea87597336f12438935f40353f1949e836"
                              "0acd9e06b4da21bfe1"),),
        lang_type="TA", script=((0x0B80, 0x0BFF),)),
    OcrPack(
        "telugu", "Telugu", "Telugu",
        "script", files=(_rec("te_PP-OCRv5_rec_mobile.onnx",
                              "a3690451b50028a09a3316a1274f7c05728151ea3f8fd3"
                              "92696397a7fefcbd92"),),
        lang_type="TE", script=((0x0C00, 0x0C7F),)),
)

BY_ID: Dict[str, OcrPack] = {p.id: p for p in PACKS}
BUILTIN = BY_ID["latin"]
MAXIMUM = BY_ID["latin_max"]
SCRIPTS: Tuple[OcrPack, ...] = tuple(p for p in PACKS if p.kind == "script")

# OCR language codes of version 1.0 (Tesseract) -> 1.1 packs, so old
# settings, presets and scripts keep working ("eng+fra+ara" -> latin+arabic)
OLD_LANGUAGE_CODES = {"eng": "latin", "fra": "latin", "ara": "arabic",
                      "rus": "cyrillic", "ell": "greek", "kor": "korean",
                      "hin": "devanagari", "tha": "thai", "tam": "tamil",
                      "tel": "telugu"}


def _parts(key: str) -> List[str]:
    """'Latin + Arabic' / 'eng+fra+ara' -> ['latin', 'arabic']."""
    out: List[str] = []
    for p in str(key or "").lower().replace(" ", "").split("+"):
        p = OLD_LANGUAGE_CODES.get(p, p)
        if p and p not in out:
            out.append(p)
    return out


def unknown_parts(key: str) -> List[str]:
    """The parts of a language key that are not OCR languages (for error
    messages: 'latin_max' is a quality, not a language)."""
    return [p for p in _parts(key) if p not in BY_ID or p == "latin_max"]


@dataclass
class LanguageSet:
    """One choice of the "OCR languages" list: the Latin model, one script
    model, or the Latin model + one script model (mixed drawings, e.g. a
    French plan with an Arabic title block)."""
    key: str
    packs: List[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        """'English, French… (Latin script)', 'Arabic',
        'English, French… + Arabic'."""
        return " + ".join(self.names())

    def names(self) -> List[str]:
        """Pack names, short ones in a combination (English: the interface
        translates each one)."""
        if len(self.packs) == 1:
            return [BY_ID[self.packs[0]].label]
        return [BY_ID[p].short or BY_ID[p].label for p in self.packs]


def language_error(key: str) -> str:
    """'' when `key` is a valid OCR language choice, else why not."""
    bad = unknown_parts(key)
    if "latin_max" in bad:
        return ("'latin_max' is not a language: choose the maximum accuracy "
                "instead")
    if bad:
        return f"unknown OCR language(s): {', '.join(bad)}"
    if len([p for p in _parts(key) if p != "latin"]) > 1:
        return "one script at a time, alone or with latin (e.g. latin+arabic)"
    return ""


def language_set(key: str) -> LanguageSet:
    """Parse "latin", "arabic", "latin+arabic"… (unknown parts dropped;
    empty -> latin)."""
    parts = [p for p in _parts(key) if p in BY_ID and p != "latin_max"]
    if not parts:
        parts = ["latin"]
    if "latin" in parts:                       # Latin first, one script max
        scripts = [p for p in parts if p != "latin"][:1]
        parts = ["latin"] + scripts
    else:
        parts = parts[:1]
    return LanguageSet("+".join(parts), parts)


def all_language_keys() -> List[str]:
    keys = ["latin"]
    for s in SCRIPTS:
        keys += [f"latin+{s.id}", s.id]
    return keys
