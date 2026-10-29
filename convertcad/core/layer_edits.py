"""
layer_edits.py — what the Layers panel shows and what the user changes.

Plain dataclasses, no heavy import: the interface builds its layer table
with them at start-up; postprocess.py applies the edits when saving.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

PROTECTED_LAYERS = {"0", "DEFPOINTS"}


@dataclass
class LayerRow:
    """One line of the interface layer table."""
    name: str
    rgb: Tuple[int, int, int]
    aci: int
    linetype: str
    count: int
    locked: bool = False


@dataclass
class LayerEdit:
    """What the user changed for one layer ('' / None = unchanged)."""
    new_name: str = ""
    keep: bool = True
    color: Optional[Tuple[int, int, int]] = None
