"""Find numeric values with units in an answer and compare them to the truth after unit
normalisation, so "85 °C", "358.15 K" and "85 °C" in German ("85 °C", "2,6 g/s") all match."""

import re
from dataclasses import dataclass

from fcrag.truth import parse_unit, ureg
from fcrag.units import UNITS

_UNIT_RE = "|".join(
    re.escape(u) for u in sorted(UNITS, key=len, reverse=True) if u not in {"-", "–"}
)
NUMBER = re.compile(
    r"(?<![\w.,-])(?P<num>[-−–]?\d{1,3}(?:[ .,  ]\d{3})+(?:[.,]\d+)?|[-−–]?\d+(?:[.,]\d+)?)"
    rf"(?:\s?(?P<unit>{_UNIT_RE})(?![\w/]))?"
)


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: str | None
    """pint unit string, or None if no unit followed the number."""


def parse_number(text: str, language: str) -> float:
    """Parse "25,000", "25.000", "2,6", "0.35" or "25 000" according to the answer language."""
    s = text.replace("−", "-").replace("–", "-").replace(" ", "").replace(" ", "")
    s = s.replace(" ", "")
    if "," in s and "." in s:
        decimal = "," if s.rfind(",") > s.rfind(".") else "."
    elif "," in s:
        # One comma: German decimal comma, unless English with exactly three digits after it.
        decimal = "," if language == "de" or not re.search(r",\d{3}$", s) else ""
    elif "." in s:
        decimal = "" if language == "de" and re.search(r"\.\d{3}$", s) else "."
    else:
        decimal = ""
    thousands = {",", "."} - {decimal}
    for sep in thousands:
        s = s.replace(sep, "")
    return float(s.replace(",", ".")) if decimal == "," else float(s)


def extract_quantities(text: str, language: str) -> list[Quantity]:
    return [
        Quantity(parse_number(m.group("num"), language), UNITS.get(m.group("unit") or ""))
        for m in NUMBER.finditer(text)
    ]


def value_found(text: str, value: float, unit: str, language: str, rel_tol: float = 0.005) -> bool:
    """True if the text states ``value`` in ``unit`` or in any convertible unit."""
    target = parse_unit(unit)
    for q in extract_quantities(text, language):
        candidate = q.value
        if q.unit is not None:
            try:
                candidate = ureg.Quantity(q.value, parse_unit(q.unit)).to(target).magnitude
            except Exception:  # incompatible dimensions: a different quantity
                continue
        if abs(candidate - value) <= max(abs(value) * rel_tol, 1e-9):
            return True
    return False
