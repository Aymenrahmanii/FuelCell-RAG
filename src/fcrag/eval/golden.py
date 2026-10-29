"""Build the golden question set.

Questions about the fictional systems are derived from the YAML truths and the generator's fact
records, so every expected value, requirement ID and gold source stays correct when the truth
changes. Public-corpus and unanswerable questions are hand-written in ``eval/golden_public.yaml``.
"""

import json
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from fcrag.datagen.common import Fact, format_number, label
from fcrag.datagen.requirements import Requirement, build_requirements
from fcrag.datagen.run import generate
from fcrag.truth import SystemTruth, TruthParameter, load_all
from fcrag.units import display_unit


@dataclass
class GoldenItem:
    id: str
    category: str
    language: str
    question: str
    reference_answer: str
    systems: list[str] = field(default_factory=list)
    answerable: bool = True
    expected_values: list[dict[str, Any]] = field(default_factory=list)
    """Numbers the answer must state: ``{"value", "unit"}``, any convertible unit accepted."""
    expected_terms: list[str] = field(default_factory=list)
    """Strings the answer must contain, e.g. requirement IDs."""
    gold_sources: list[dict[str, Any]] = field(default_factory=list)
    """``{"doc_id", "doc_version"?, "locator"?}``: a retrieved chunk matching any one is a hit."""


# (system, component or None, key, language, question)
PARAMETER_QUESTIONS = [
    ("A", "A-STK", "cell_count", "en", "How many cells does the System A stack have?"),
    ("A", "A-CMP", "air_mass_flow_max", "en", "What is the maximum air mass flow of the System A air compressor?"),
    ("A", None, "h2_consumption_rated", "de", "Wie hoch ist der Wasserstoffverbrauch von System A bei Nennleistung?"),
    ("A", "A-STK", "coolant_outlet_temperature_nominal", "en", "What is the nominal coolant outlet temperature of the System A stack?"),
    ("B", "B-STK", "coolant_outlet_temperature_max", "en", "What is the maximum coolant outlet temperature of System B?"),
    ("B", "B-STK", "pt_loading_cathode", "de", "Wie hoch ist die Platinbeladung der Kathode im Stack von System B?"),
    ("B", "B-CMP", "electrical_power_rated", "en", "How much electrical power does the System B air compressor draw at its rated point?"),
    ("B", None, "system_mass", "de", "Wie schwer ist System B insgesamt?"),
    ("C", "C-STK", "cathode_inlet_pressure_rated", "en", "What is the cathode inlet pressure of the System C stack at rated power?"),
    ("C", None, "thermal_output_rated", "de", "Welche Wärmeleistung liefert System C bei Nennleistung?"),
    ("C", "C-BLW", "pressure_ratio_max", "en", "What maximum pressure ratio does the System C air blower reach?"),
    ("C", "C-STK", "open_circuit_voltage", "de", "Wie hoch ist die Leerlaufspannung des Stacks von System C?"),
]  # fmt: skip

# (key, stack-level?, systems, language, question)
CROSS_SYSTEM_QUESTIONS = [
    ("rated_net_power", False, "ABC", "en", "Compare the rated net power of Systems A, B and C."),
    ("membrane_thickness", True, "ABC", "de", "Vergleiche die Membrandicke der Stacks von System A, B und C."),
    ("design_lifetime", False, "AC", "en", "Which has the longer design lifetime, System A or System C?"),
    ("coolant_outlet_temperature_max", True, "AB", "en", "How do the maximum coolant outlet temperatures of Systems A and B differ?"),
    ("pt_loading_cathode", True, "AC", "de", "Vergleiche die Platinbeladung der Kathode von System A und System C."),
    ("rated_current_density", True, "ABC", "en", "Which system runs its stack at the highest rated current density?"),
]  # fmt: skip

VERSION_QUESTIONS = [
    ("A", "A-HUM", "pressure_drop_dry_side", "en", "Which dry-side pressure drop of the System A humidifier is current?"),
    ("B", None, "design_lifetime", "de", "Welche Auslegungslebensdauer gilt aktuell für System B?"),
    ("C", None, "system_efficiency_rated", "en", "What is the current electrical efficiency of System C at rated power?"),
]  # fmt: skip

# Requirement whose stated value ties a parameter sheet to the requirements document.
CROSS_DOC_QUESTIONS = [
    ("C", None, "rated_net_power", "en", "Which requirement specifies the rated net power of System C, and what value does the parameter sheet give?"),
    ("A", "A-STK", "membrane_thickness", "en", "Which System A requirement covers the membrane thickness, and what thickness does the parameter list state?"),
    ("B", "B-HUM", "pressure_drop_dry_side", "de", "Welche Anforderung legt den Druckverlust der Trockenseite des Befeuchters von System B fest, und welcher Wert steht in der Parameterliste?"),
    ("A", "A-CLP", "coolant_flow_rated", "en", "Which requirement defines the rated coolant flow of System A, and what flow does the parameter sheet list?"),
    ("B", None, "h2_supply_pressure", "de", "Welche Anforderung regelt den Wasserstoff-Versorgungsdruck von System B, und welcher Wert steht im Datenblatt?"),
]  # fmt: skip

CONFLICT_QUESTIONS = [
    ("A", "A-STK", "coolant_outlet_temperature_max", "en", "Does the System A requirement on the maximum coolant outlet temperature agree with the System A datasheet?"),
    ("B", "B-STK", "cathode_inlet_pressure_rated", "de", "Stimmt die Anforderung zum Kathodeneintrittsdruck von System B mit der Parameterliste überein?"),
    ("C", "C-CLP", "coolant_flow_rated", "en", "Is the System C requirement on the rated coolant flow consistent with the parameter list?"),
]  # fmt: skip

LANG_REQ = {"A": "en", "B": "de", "C": "en"}


def _param(system: SystemTruth, component: str | None, key: str) -> TruthParameter:
    return system.lookup(key, component)


def _value_text(param: TruthParameter, value: float, language: str) -> str:
    unit = "" if param.unit == "-" else f" {display_unit(param.unit)}"
    return f"{format_number(value, language)}{unit}"


def _source(f: Fact) -> dict[str, Any]:
    return {"doc_id": f.doc_id, "doc_version": f.doc_version, "locator": f.locator}


class Builder:
    def __init__(self, systems: dict[str, SystemTruth], facts: list[Fact]) -> None:
        self.systems = systems
        self.facts = facts
        self.reqs = {code: build_requirements(s, LANG_REQ[code]) for code, s in systems.items()}

    def sources(
        self, code: str, component: str | None, key: str, *, value: float | None = None
    ) -> list[dict[str, Any]]:
        """Documents stating this parameter with its (current) truth value, not a conflict."""
        param = _param(self.systems[code], component, key)
        target = param.value if value is None else value
        return [
            _source(f)
            for f in self.facts
            if f.system == self.systems[code].system and f.component == component and f.key == key
            and f.truth_value == target and _consistent(f)
        ]  # fmt: skip

    def requirement(self, code: str, component: str | None, key: str) -> Requirement:
        return next(
            r for r in self.reqs[code]
            if r.param.key == key and (r.component.id if r.component else None) == component
        )  # fmt: skip

    def parameter_items(self) -> list[GoldenItem]:
        items = []
        for n, (code, comp, key, lang, question) in enumerate(PARAMETER_QUESTIONS, 1):
            p = _param(self.systems[code], comp, key)
            condition = f" ({p.condition})" if p.condition else ""
            items.append(
                GoldenItem(
                    id=f"param-{n:02d}", category="parameter", language=lang, question=question,
                    reference_answer=f"{label(p, lang)}: {_value_text(p, p.value, lang)}{condition}.",
                    systems=[self.systems[code].system],
                    expected_values=[{"value": p.value, "unit": p.unit}],
                    gold_sources=self.sources(code, comp, key),
                )
            )  # fmt: skip
        return items

    def cross_system_items(self) -> list[GoldenItem]:
        items = []
        for n, (key, stack, codes, lang, question) in enumerate(CROSS_SYSTEM_QUESTIONS, 1):
            parts, values, sources = [], [], []
            for code in codes:
                comp = f"{code}-STK" if stack else None
                p = _param(self.systems[code], comp, key)
                parts.append(f"{self.systems[code].system}: {_value_text(p, p.value, lang)}")
                values.append({"value": p.value, "unit": p.unit})
                sources += self.sources(code, comp, key)
            items.append(
                GoldenItem(
                    id=f"cross-sys-{n:02d}", category="cross_system", language=lang,
                    question=question, reference_answer="; ".join(parts) + ".",
                    systems=[self.systems[c].system for c in codes],
                    expected_values=values, gold_sources=sources,
                )
            )  # fmt: skip
        return items

    def version_items(self) -> list[GoldenItem]:
        items = []
        for n, (code, comp, key, lang, question) in enumerate(VERSION_QUESTIONS, 1):
            p = _param(self.systems[code], comp, key)
            old = p.superseded[-1]
            current = _value_text(p, p.value, lang)
            previous = _value_text(p, old.value, lang)
            answer = (
                f"Aktuell gilt {current} (Version {p.current_doc_version}); "
                f"Version {old.doc_version} nannte {previous}."
                if lang == "de"
                else f"The current value is {current} (version {p.current_doc_version}); "
                f"version {old.doc_version} stated {previous}."
            )
            items.append(
                GoldenItem(
                    id=f"version-{n:02d}", category="version_conflict", language=lang,
                    question=question, reference_answer=answer,
                    systems=[self.systems[code].system],
                    expected_values=[{"value": p.value, "unit": p.unit}],
                    gold_sources=self.sources(code, comp, key)
                    + self.sources(code, comp, key, value=old.value),
                )
            )  # fmt: skip
        return items

    def trace_items(self) -> list[GoldenItem]:
        a, b = self.reqs["A"], self.reqs["B"]

        def gold(code: str, *ids: str) -> list[dict[str, Any]]:
            doc = f"req-system-{code.lower()}"
            return [{"doc_id": doc, "locator": {"req_id": i}} for i in ids]

        net_a = next(r for r in a if r.param.key == "rated_net_power" and not r.parent)
        children_a = [r.req_id for r in a if r.parent == net_a.req_id]
        life_b = next(r for r in b if r.param.key == "design_lifetime" and not r.parent)
        children_b = [r.req_id for r in b if r.parent == life_b.req_id]
        flow_c = self.requirement("C", "C-CLP", "coolant_flow_rated")
        linked = next(r for r in a if r.links)
        cells_b = self.requirement("B", "B-STK", "cell_count")
        mass_c = self.requirement("C", "C-STK", "stack_mass")
        specs = [
            ("en", f"Which requirements refine {net_a.req_id}?", ", ".join(children_a),
             children_a, gold("A", net_a.req_id, *children_a), "A"),
            ("de", f"Welche Anforderungen verfeinern {life_b.req_id}?", ", ".join(children_b[:6]) + " …",
             children_b[:3], gold("B", life_b.req_id, *children_b), "B"),
            ("en", f"What is the parent requirement of {flow_c.req_id}?", f"{flow_c.parent}.",
             [flow_c.parent or ""], gold("C", flow_c.req_id), "C"),
            ("en", f"Which other requirement does {linked.req_id} reference?", f"{linked.links[0]}.",
             linked.links[:1], gold("A", linked.req_id), "A"),
            ("de", f"Mit welcher Methode wird {cells_b.req_id} verifiziert?", f"{cells_b.verification}.",
             [cells_b.verification], gold("B", cells_b.req_id), "B"),
            ("en", f"What is the status of requirement {mass_c.req_id}?", f"{mass_c.status}.",
             [mass_c.status], gold("C", mass_c.req_id), "C"),
        ]  # fmt: skip
        return [
            GoldenItem(
                id=f"trace-{n:02d}", category="requirement_trace", language=lang, question=q,
                reference_answer=ref, systems=[self.systems[code].system],
                expected_terms=terms, gold_sources=sources,
            )
            for n, (lang, q, ref, terms, sources, code) in enumerate(specs, 1)
        ]  # fmt: skip

    def cross_doc_items(self) -> list[GoldenItem]:
        items: list[GoldenItem] = []
        for code, comp, key, lang, question in CROSS_DOC_QUESTIONS:
            p = _param(self.systems[code], comp, key)
            req = self.requirement(code, comp, key)
            items.append(
                GoldenItem(
                    id=f"cross-doc-{len(items) + 1:02d}", category="cross_document",
                    language=lang, question=question,
                    reference_answer=f"{req.req_id}; {_value_text(p, p.value, lang)}.",
                    systems=[self.systems[code].system],
                    expected_values=[{"value": p.value, "unit": p.unit}],
                    expected_terms=[req.req_id], gold_sources=self.sources(code, comp, key),
                )
            )  # fmt: skip
        for code, comp, key, lang, question in CONFLICT_QUESTIONS:
            p = _param(self.systems[code], comp, key)
            req = self.requirement(code, comp, key)
            stated = _value_text(p, req.stated_value, lang)
            actual = _value_text(p, p.value, lang)
            answer = (
                f"Nein: {req.req_id} fordert {stated}, die Dokumente nennen {actual}."
                if lang == "de"
                else f"No: {req.req_id} states {stated}, while the documents give {actual}."
            )
            conflict = next(
                _source(f) for f in self.facts
                if f.doc_id.startswith("req-") and f.key == key and f.component == comp
                and f.system == self.systems[code].system
            )  # fmt: skip
            items.append(
                GoldenItem(
                    id=f"cross-doc-{len(items) + 1:02d}", category="cross_document",
                    language=lang, question=question, reference_answer=answer,
                    systems=[self.systems[code].system],
                    expected_values=[{"value": p.value, "unit": p.unit},
                                     {"value": req.stated_value, "unit": p.unit}],
                    expected_terms=[req.req_id],
                    # the conflicting requirement is the evidence that matters
                    gold_sources=[conflict],
                )
            )  # fmt: skip
        return items


def cad_items(systems: dict[str, SystemTruth]) -> list[GoldenItem]:
    """Questions on the STEP assemblies and the BOM sheets that explain their part names."""
    from fcrag.datagen.cad import CELL_PITCH_MM

    def part(code: str, part_id: str) -> dict[str, Any]:
        return {"doc_id": f"cad-stack-{code.lower()}", "locator": {"part_id": part_id}}

    def bom(code: str) -> dict[str, Any]:
        """The BOM sheet lists every part with its assembly, quantity and size."""
        return {"doc_id": f"ps-system-{code.lower()}", "locator": {"sheet": "BOM"}}

    cells_b = systems["B"].lookup("cell_count", "B-STK").value
    block_b = round(cells_b * CELL_PITCH_MM["B"], 1)
    specs = [
        ("en", "A", "Which parts make up the end plate assembly EPA-02 of System A?",
         "EP-02 (end plate, wet side), INS-02 (insulation plate) and CC-02 (current collector).",
         [], ["EP-02", "INS-02", "CC-02"], [part("A", "EPA-02"), bom("A")]),
        ("de", "B", "Welche Teile gehören zur Endplattenbaugruppe EPA-01 von System B?",
         "EP-01, INS-01 und CC-01.", [], ["EP-01", "INS-01", "CC-01"], [part("B", "EPA-01"), bom("B")]),
        ("en", "C", "How many tie rods hold the System C stack together?",
         "Four tie rods (TR-01.1 to TR-01.4).", [{"value": 4, "unit": "-"}], [],
         [{"doc_id": "cad-stack-c"}, bom("C")]),
        ("en", "A", "What is part EP-02 in the System A stack?",
         "EP-02 is the end plate on the wet side, part of end plate assembly EPA-02.", [],
         ["end plate"], [bom("A"),
                         part("A", "EP-02")]),
        ("en", "B", "How long is the cell block CB-01 of the System B stack?",
         f"About {block_b:g} mm along the stack axis.", [{"value": block_b, "unit": "mm"}], [],
         [part("B", "CB-01"), bom("B")]),
        ("de", "C", "Welche Unterbaugruppen enthält das Stack-Assembly von System C?",
         "Die Endplattenbaugruppen EPA-01 und EPA-02.", [], ["EPA-01", "EPA-02"],
         [part("C", "C-STK-ASM"), part("C", "EPA-01"), part("C", "EPA-02"), bom("C")]),
    ]  # fmt: skip
    return [
        GoldenItem(
            id=f"cad-{n:02d}", category="drawing_step", language=lang, question=q,
            reference_answer=ref, systems=[systems[code].system], expected_values=values,
            expected_terms=terms, gold_sources=gold,
        )
        for n, (lang, code, q, ref, values, terms, gold) in enumerate(specs, 1)
    ]  # fmt: skip


def drawing_items(systems: dict[str, SystemTruth]) -> list[GoldenItem]:
    """Questions on the system schematics: title block, revision history, line list."""
    from fcrag.datagen.drawing import DRAWINGS, lines

    def line(code: str, line_id: str) -> Any:
        drawing = DRAWINGS[code][-1]
        return next(ln for ln in lines(systems[code], drawing) if ln.line_id == line_id)

    def dwg(code: str, version: int | None = None) -> dict[str, Any]:
        gold: dict[str, Any] = {"doc_id": DRAWINGS[code][-1].doc_id}
        if version is not None:
            gold["doc_version"] = version
        return gold

    a = DRAWINGS["A"][-1]
    l02_b, l08_c, l12_a = line("B", "L02"), line("C", "L08"), line("A", "L12")
    specs = [
        ("en", "A", "What is the drawing number and the current revision of the System A system schematic?",
         f"{a.drawing_no}, revision {a.revision} ({a.revisions[-1].date}).", [a.drawing_no],
         [dwg("A", a.version)]),
        ("en", "A", f"What changed in revision {a.revision} of the System A schematic?",
         "The humidifier bypass valve A-BPV was added, with lines L14 and L15.", ["A-BPV"],
         [dwg("A", a.version)]),
        ("de", "B", "Welche Komponente fördert laut Systemschema von System B die Luft zum Befeuchter?",
         f"Der elektrische Turboverdichter B-{l02_b.source} (Leitung {l02_b.line_id}).",
         [f"B-{l02_b.source}"], [dwg("B")]),
        ("en", "C", "In the System C schematic, which line carries recirculated hydrogen from the blower back to the stack?",
         f"Line {l08_c.line_id}, from C-{l08_c.source} to C-{l08_c.target}.", [l08_c.line_id],
         [dwg("C")]),
        ("de", "A", f"Wohin führt die Leitung {l12_a.line_id} im Systemschema von System A?",
         f"Vom Stack A-{l12_a.source} zum Kühler A-{l12_a.target} ({l12_a.medium_de}).",
         [f"A-{l12_a.target}"], [dwg("A")]),
    ]  # fmt: skip
    return [
        GoldenItem(
            id=f"dwg-{n:02d}", category="drawing_step", language=lang, question=q,
            reference_answer=ref, systems=[systems[code].system], expected_terms=terms,
            gold_sources=gold,
        )
        for n, (lang, code, q, ref, terms, gold) in enumerate(specs, 1)
    ]  # fmt: skip


def _consistent(f: Fact) -> bool:
    """False for facts that deliberately contradict the truth (conflicting requirements)."""
    from fcrag.datagen.common import convert

    expected = (
        f.truth_value
        if f.stated_unit == f.truth_unit
        else convert(f.truth_value, f.truth_unit, f.stated_unit)
    )
    return abs(f.stated_value - expected) <= 1e-6 * max(1.0, abs(expected))


def load_public(path: Path) -> list[GoldenItem]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    items = []
    for raw in data["items"]:
        gold_docs = raw.pop("gold_docs", [])
        item = GoldenItem(**raw, answerable=raw["category"] != "unanswerable")
        item.gold_sources = [{"doc_id": d} for d in gold_docs]
        items.append(item)
    return items


def build_golden(systems_dir: Path, public_path: Path) -> list[GoldenItem]:
    systems = load_all(systems_dir)
    with tempfile.TemporaryDirectory() as tmp:
        generated = generate(systems_dir, Path(tmp))
    facts = [f for g in generated for f in g.facts]
    builder = Builder(systems, facts)
    public = load_public(public_path)
    derived = (
        builder.parameter_items() + builder.cross_system_items() + builder.version_items()
        + builder.trace_items() + builder.cross_doc_items() + cad_items(systems)
        + drawing_items(systems)
    )  # fmt: skip
    return (
        [i for i in public if i.category == "fact_text"]
        + derived
        + [i for i in public if i.category == "unanswerable"]
    )


def write_golden(items: list[GoldenItem], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")


def read_golden(path: Path) -> list[GoldenItem]:
    with path.open(encoding="utf-8") as f:
        return [GoldenItem(**json.loads(line)) for line in f if line.strip()]
