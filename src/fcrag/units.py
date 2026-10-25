"""Unit spellings found in documents, mapped to pint units, plus conversion helpers."""

from typing import Any

from fcrag.truth import parse_unit, ureg

# Display forms to pint units. Matching uses longest first, so "mg/cm²" wins over "cm²".
UNITS = {
    "mg/cm²": "mg/cm**2", "mg/cm2": "mg/cm**2", "A/cm²": "A/cm**2", "A/cm2": "A/cm**2",
    "cm²": "cm**2", "cm2": "cm**2", "L/min": "L/min", "l/min": "L/min", "g/s": "g/s",
    "°C": "degC", "kPa": "kPa", "bar": "bar", "kW": "kW", "W": "W", "kWh": "kWh",
    "µm": "um", "μm": "um", "um": "um", "kg": "kg", "rpm": "rpm", "min⁻¹": "rpm",
    "%": "%", "h": "h", "V": "V", "A": "A", "K": "K", "L": "L", "mm": "mm",
    "–": "-", "-": "-",
}  # fmt: skip


def to_pint(unit: str) -> str | None:
    """Pint unit for a document's unit text, or None if unknown."""
    text = unit.strip()
    if not text:
        return "-"
    return UNITS.get(text)


def convert_value(value: float, unit: str, target: str) -> float | None:
    """Convert between pint units; None if the dimensions do not match."""
    if unit == target:
        return value
    try:
        quantity: Any = ureg.Quantity(value, parse_unit(unit)).to(parse_unit(target))
    except Exception:
        return None
    return float(quantity.magnitude)


UNIT_DISPLAY = {
    "degC": "°C",
    "cm**2": "cm²",
    "A/cm**2": "A/cm²",
    "mg/cm**2": "mg/cm²",
    "um": "µm",
    "-": "–",
}


def display_unit(unit: str) -> str:
    return UNIT_DISPLAY.get(unit, unit)
