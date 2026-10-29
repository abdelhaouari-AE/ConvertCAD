"""
units.py — drawing scale arithmetic (no heavy imports).

Kept apart from dxf_writer.py on purpose: the interface needs these two
small functions at start-up, and importing the DXF writer would also load
ezdxf (about 0.3 s). Pure Python, standard library only.
"""

from .constants import PT_TO_MM, UNITS


def compute_scale(units: str, scale_denominator: float,
                  calibrated_units_per_pt: float = 0.0) -> float:
    """Real-world units per page point (calibration wins when provided).

    Example: 1:100 in millimetres -> 1 pt = 0.3528 mm on paper = 35.28 mm
    in reality, so the result is 35.28."""
    if calibrated_units_per_pt > 0:
        return calibrated_units_per_pt
    factor = UNITS.get(units, UNITS["mm"])["factor"]
    return PT_TO_MM * float(scale_denominator) * factor


def effective_denominator(units_per_pt: float, units: str) -> float:
    """Equivalent paper scale 1:N of a calibration (sanity check for users)."""
    factor = UNITS.get(units, UNITS["mm"])["factor"]
    return units_per_pt / (PT_TO_MM * factor) if units_per_pt > 0 else 0.0
