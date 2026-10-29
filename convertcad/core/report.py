"""
report.py — the conversion log.

After every conversion ConvertCAD produces a structured report:
inputs -> options -> per-page notes -> results -> layers -> warnings/errors.
It is shown in the interface (HTML), saved next to the DXF as
<name>_log.txt (plain text) and can be exported as HTML or JSON.
"""

import datetime
import html
import json
from dataclasses import asdict, dataclass, field
from typing import Dict, List

from .. import APP_NAME, APP_VERSION
from .stats import WriteStats

LINE = "-" * 74

# (label, WriteStats attribute) in display order
RESULT_ROWS = [
    ("Lines", "lines"), ("Polylines", "polylines"), ("Arcs", "arcs"),
    ("Circles", "circles"), ("Splines", "splines"), ("Texts", "texts"),
    ("Paragraphs (MTEXT)", "mtexts"), ("SHX texts recovered", "shx_texts"),
    ("OCR texts", "ocr_texts"), ("Hatches", "hatches"),
    ("Hatch patterns rebuilt", "pattern_hatches"),
    ("Dashed lines rebuilt", "dashed_lines"),
    ("Dash pieces merged", "dash_pieces_merged"),
    ("Dimensions (true DIMENSION)", "dimensions"), ("Leaders", "leaders"),
    ("Blocks defined", "blocks_defined"),
    ("Block references (INSERT)", "blocks_inserted"),
    ("Raster images", "images"),
    ("Duplicate segments removed", "duplicates_removed"),
    ("White/background fills ignored", "fills_skipped"),
]


@dataclass
class PageResult:
    number: int
    kind: str = "vector"            # vector | scanned | empty
    note: str = ""
    seconds: float = 0.0


@dataclass
class ConversionReport:
    # ---- inputs ----
    pdf_path: str = ""
    dxf_path: str = ""                       # main output (first file)
    outputs: List[str] = field(default_factory=list)   # all DXF files
    pages_converted: List[int] = field(default_factory=list)
    pages_total: int = 0
    producer: str = ""
    # ---- options ----
    options: Dict[str, str] = field(default_factory=dict)
    # ---- results ----
    stats: WriteStats = field(default_factory=WriteStats)
    pages: List[PageResult] = field(default_factory=list)
    page_notes: List[str] = field(default_factory=list)
    # where each sheet sits in the DXF (overlay check in the interface):
    # {"page", "file", "x_offset", "scale", "width_pt", "height_pt", "clip"}
    placements: List[dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    duration_s: float = 0.0
    success: bool = False
    cancelled: bool = False
    created: str = field(default_factory=lambda: datetime.datetime.now()
                         .strftime("%Y-%m-%d %H:%M:%S"))

    # ------------------------------------------------------------------ text --
    def all_warnings(self) -> List[str]:
        return self.warnings + self.stats.warnings

    def status_word(self) -> str:
        if self.cancelled:
            return "CANCELLED"
        return "SUCCESS" if self.success else "FAILED"

    def render(self) -> str:
        """Plain-text report (log file)."""
        s = self.stats
        out = [
            f"{APP_NAME} v{APP_VERSION} — Conversion log / Journal de conversion",
            f"Date: {self.created}",
            LINE, "INPUT",
            f"  PDF file        : {self.pdf_path}",
            f"  Producer        : {self.producer or '-'}",
            f"  Pages converted : {', '.join(map(str, self.pages_converted))}"
            f" (of {self.pages_total})",
            LINE, "OPTIONS",
        ]
        out += [f"  {k:<32}: {v}" for k, v in self.options.items()]
        out += [LINE, "OUTPUT"]
        out += [f"  {p}" for p in (self.outputs or [self.dxf_path])]
        out += [LINE, "RESULTS"]
        out += [f"  {label:<32}: {getattr(s, attr)}"
                for label, attr in RESULT_ROWS]
        out.append(f"  {'Total entities':<32}: {s.total_entities()}")
        out += [LINE, f"LAYERS ({len(s.layers)})"]
        for name in sorted(s.layers):
            inb = s.block_layer_counts.get(name, 0)
            extra = f"  (+{inb} inside blocks)" if inb else ""
            out.append(f"  {name:<40} {s.layer_counts.get(name, 0):>8}{extra}")
        if s.block_report:
            out += [LINE, "BLOCKS"]
            out += [f"  {b}" for b in s.block_report]
        if self.page_notes:
            out += [LINE, "PAGE NOTES"]
            out += [f"  {n}" for n in self.page_notes]
        warns = self.all_warnings()
        out += [LINE, f"WARNINGS ({len(warns)})"]
        out += [f"  ! {w}" for w in warns] or ["  (none)"]
        out += [LINE, f"ERRORS ({len(self.errors)})"]
        out += [f"  X {e}" for e in self.errors] or ["  (none)"]
        out += [LINE,
                f"Status   : {self.status_word()}",
                f"Duration : {self.duration_s:.1f} s", "",
                "Engineering check: verify the scale on a known distance, "
                "spot-check layer DIM",
                "against the PDF and review layer DIM_RAW (measurement texts "
                "not matched)."]
        return "\n".join(out)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.render())

    # ------------------------------------------------------------------ html --
    def to_html(self, dark: bool = False, t=None) -> str:
        """Styled HTML for the interface report panel / HTML export.

        ``t`` is an optional translation function (the interface passes its
        ``tr``) so the report panel follows the interface language. The core
        stays independent of the UI: without ``t`` the report is in English.
        """
        t = t or (lambda text: text)
        s = self.stats
        e = html.escape
        fg, mut, bd, ok, warn, err, card = (
            ("#e6e8eb", "#9aa3ad", "#2c3238", "#4ade80", "#fbbf24", "#f87171",
             "#1d2227") if dark else
            ("#1b1f24", "#5d6670", "#dfe3e8", "#15803d", "#b45309", "#b91c1c",
             "#f6f8fa"))
        status_color = ok if self.success else (warn if self.cancelled else err)

        def h3(title: str, color: str = "") -> str:
            style = f" style='color:{color}'" if color else ""
            return f"<h3{style}>{e(t(title).upper())}</h3>"

        rows = "".join(
            f"<tr><td>{e(t(label))}</td><td align='right'><b>{getattr(s, a)}"
            f"</b></td></tr>" for label, a in RESULT_ROWS if getattr(s, a))

        def _layer_cell(n):
            inb = s.block_layer_counts.get(n, 0)
            extra = (f" <span style='color:{mut}'>(+{inb} "
                     f"{e(t('in blocks'))})</span>" if inb else "")
            return f"{s.layer_counts.get(n, 0)}{extra}"
        layers = "".join(
            f"<tr><td>{e(n)}</td><td align='right'>{_layer_cell(n)}"
            f"</td></tr>" for n in sorted(s.layers))
        opts = "".join(f"<tr><td>{e(k)}</td><td>{e(str(v))}</td></tr>"
                       for k, v in self.options.items())
        warns = "".join(f"<li>{e(w)}</li>" for w in self.all_warnings())
        errs = "".join(f"<li>{e(x)}</li>" for x in self.errors)
        notes = "".join(f"<li>{e(n)}</li>" for n in self.page_notes)
        outs = "<br>".join(e(p) for p in (self.outputs or [self.dxf_path]))
        blocks = "".join(f"<li>{e(b)}</li>" for b in s.block_report)
        none = f"<div class='muted'>{e(t('none'))}</div>"
        css = (f"body{{color:{fg};font-size:10pt}} h2{{margin:2px 0 6px}}"
               f"h3{{margin:14px 0 4px;color:{mut};font-size:9pt;"
               f"letter-spacing:1px}} td{{padding:2px 10px 2px 0}}"
               f".muted{{color:{mut}}} table{{border-collapse:collapse}}")
        pages = ", ".join(map(str, self.pages_converted))
        parts = [
            f"<html><head><style>{css}</style></head><body>",
            f"<h2 style='color:{status_color}'>"
            f"{e(t(self.status_word().capitalize()).upper())}</h2>",
            f"<div class='muted'>{e(APP_NAME)} v{APP_VERSION} · {self.created}"
            f" · {self.duration_s:.1f} s · {s.total_entities()} "
            f"{e(t('entities'))}</div>",
            h3("Input"), f"<div>{e(self.pdf_path)}</div>",
            f"<div class='muted'>{e(t('Pages'))} {pages} "
            f"{e(t('of'))} {self.pages_total} · "
            f"{e(self.producer or t('unknown producer'))}</div>",
            h3("Output"), f"<div>{outs}</div>",
            h3("Results"), f"<table>{rows}</table>",
            f"<h3>{e(t('Layers').upper())} ({len(s.layers)})</h3>"
            f"<table>{layers}</table>",
        ]
        if blocks:
            parts.append(h3("Blocks") + f"<ul>{blocks}</ul>")
        if notes:
            parts.append(h3("Page notes") + f"<ul>{notes}</ul>")
        parts.append(f"<h3 style='color:{warn}'>{e(t('Warnings').upper())} "
                     f"({len(self.all_warnings())})</h3>"
                     + (f"<ul>{warns}</ul>" if warns else none))
        parts.append(f"<h3 style='color:{err}'>{e(t('Errors').upper())} "
                     f"({len(self.errors)})</h3>"
                     + (f"<ul>{errs}</ul>" if errs else none))
        parts.append(h3("Options") + f"<table>{opts}</table>")
        footer = t("Verify the scale on a known distance, spot-check layer "
                   "DIM and review layer DIM_RAW.")
        parts.append(f"<p class='muted' style='border-top:1px solid {bd};"
                     f"padding-top:6px'>{e(footer)}</p>")
        parts.append("</body></html>")
        return "".join(parts)

    # ------------------------------------------------------------------ json --
    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status_word()
        d["total_entities"] = self.stats.total_entities()
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
