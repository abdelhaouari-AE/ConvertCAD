"""
stats.py — the entity counters reported in the conversion log.

A plain dataclass with no heavy import, shared by the DXF writer (which
fills it) and the report (which displays it). Keeping it here lets the
interface show reports without loading ezdxf.
"""

from dataclasses import dataclass, field
from typing import Dict, List

# counters added together when several pages / files are merged
COUNTERS = ("lines", "polylines", "arcs", "circles", "splines", "texts",
            "mtexts", "shx_texts", "ocr_texts", "hatches", "pattern_hatches",
            "images", "dimensions", "leaders", "blocks_defined",
            "blocks_inserted", "duplicates_removed", "fills_skipped",
            "dashed_lines", "dash_pieces_merged")


@dataclass
class WriteStats:
    lines: int = 0
    polylines: int = 0
    arcs: int = 0
    circles: int = 0
    splines: int = 0
    texts: int = 0
    mtexts: int = 0
    shx_texts: int = 0
    ocr_texts: int = 0
    hatches: int = 0                 # solid fills
    pattern_hatches: int = 0         # line-pattern hatches rebuilt
    images: int = 0
    dimensions: int = 0
    leaders: int = 0
    blocks_defined: int = 0
    blocks_inserted: int = 0
    duplicates_removed: int = 0
    fills_skipped: int = 0
    dashed_lines: int = 0            # dashed lines rebuilt from pieces
    dash_pieces_merged: int = 0      # ...and the pieces they replaced
    layers: List[str] = field(default_factory=list)
    layer_counts: Dict[str, int] = field(default_factory=dict)
    # entities that live inside block definitions (drawn once per INSERT)
    block_layer_counts: Dict[str, int] = field(default_factory=dict)
    block_report: List[str] = field(default_factory=list)
    image_files: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def total_entities(self) -> int:
        """Entities written in model space (what CAD shows in the drawing)."""
        return (self.lines + self.polylines + self.arcs + self.circles
                + self.splines + self.texts + self.mtexts + self.shx_texts
                + self.ocr_texts + self.hatches + self.pattern_hatches
                + self.images + self.dimensions + self.leaders
                + self.blocks_inserted)

    def merge(self, other: "WriteStats") -> None:
        """Accumulate another page/file (used for multi-file outputs)."""
        for f in COUNTERS:
            setattr(self, f, getattr(self, f) + getattr(other, f))
        for name in other.layers:
            if name not in self.layers:
                self.layers.append(name)
        for k, v in other.layer_counts.items():
            self.layer_counts[k] = self.layer_counts.get(k, 0) + v
        for k, v in other.block_layer_counts.items():
            self.block_layer_counts[k] = self.block_layer_counts.get(k, 0) + v
        self.block_report += other.block_report
        self.image_files += other.image_files
        self.warnings += other.warnings
