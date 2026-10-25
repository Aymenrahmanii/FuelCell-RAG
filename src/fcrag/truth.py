"""Ground-truth system definitions (``data_gen/systems/*.yaml``).

Each fictional fuel cell system is described once, in YAML. The data generators turn it into
parameter sheets, datasheets, requirements and CAD files, and the evaluation harness reads it to
know the exact answer to every parameter question.

Truth values use one canonical unit per quantity; unit variants (K vs °C, bar vs kPa) are
injected by the generators, not stored here.
"""

from pathlib import Path
from typing import Any, Literal, Self

import pint
import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

ureg = pint.UnitRegistry()

DIMENSIONLESS = {"-", ""}

ComponentType = Literal[
    "stack",
    "air_compressor",
    "air_blower",
    "humidifier",
    "coolant_pump",
    "h2_recirculation",
]


def parse_unit(unit: str) -> Any:
    """Parse a unit string with pint; ``"-"`` means dimensionless."""
    if unit in DIMENSIONLESS:
        return ureg.dimensionless
    return ureg.parse_units(unit)


class Revision(BaseModel):
    """A value that an older document version stated before it was superseded."""

    doc_version: int
    value: float
    note: str | None = None


class TruthParameter(BaseModel):
    key: str
    label_en: str
    label_de: str
    value: float
    unit: str
    condition: str | None = None
    superseded: list[Revision] = Field(default_factory=list)
    """Older document versions that stated a different value. The current value is ``value``."""

    @field_validator("unit")
    @classmethod
    def _unit_parses(cls, unit: str) -> str:
        parse_unit(unit)
        return unit

    @property
    def current_doc_version(self) -> int:
        return max((r.doc_version for r in self.superseded), default=0) + 1

    def quantity(self) -> Any:
        return ureg.Quantity(self.value, parse_unit(self.unit))


def _check_unique_keys(params: list[TruthParameter], owner: str) -> None:
    keys = [p.key for p in params]
    duplicates = {k for k in keys if keys.count(k) > 1}
    if duplicates:
        raise ValueError(f"{owner}: duplicate parameter keys {sorted(duplicates)}")


class Component(BaseModel):
    id: str
    name: str
    type: ComponentType
    attributes: dict[str, str] = Field(default_factory=dict)
    """Non-numeric facts such as materials or design type."""
    parameters: list[TruthParameter]

    @model_validator(mode="after")
    def _unique_keys(self) -> Self:
        _check_unique_keys(self.parameters, self.id)
        return self


class SystemTruth(BaseModel):
    system: str
    code: str
    application: str
    description: str
    parameters: list[TruthParameter]
    components: list[Component]

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        _check_unique_keys(self.parameters, self.system)
        ids = [c.id for c in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{self.system}: duplicate component ids")
        return self

    def component(self, component_id: str) -> Component:
        for c in self.components:
            if c.id == component_id:
                return c
        raise KeyError(f"{self.system} has no component {component_id!r}")

    def lookup(self, key: str, component_id: str | None = None) -> TruthParameter:
        """Find a parameter at system level (``component_id=None``) or on a component."""
        params = (
            self.parameters if component_id is None else self.component(component_id).parameters
        )
        for p in params:
            if p.key == key:
                return p
        where = component_id or "system level"
        raise KeyError(f"{self.system} has no parameter {key!r} at {where}")


def load_system(path: Path) -> SystemTruth:
    with path.open(encoding="utf-8") as f:
        return SystemTruth.model_validate(yaml.safe_load(f))


def load_all(directory: Path) -> dict[str, SystemTruth]:
    """Load every system YAML in ``directory``, keyed by system code (``"A"``, ``"B"``, ...)."""
    systems = [load_system(p) for p in sorted(directory.glob("*.yaml"))]
    return {s.code: s for s in systems}
