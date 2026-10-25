"""Parameter comparison and requirement checker on records extracted from generated files."""

from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine

from fcrag.apps.checker import check_requirement
from fcrag.apps.compare import compare
from fcrag.datagen import excel, requirements
from fcrag.db.models import Base, Document, ParameterRecord
from fcrag.db.session import session_scope
from fcrag.ingest.extract_params import Vocabulary, extract_parameters
from fcrag.ingest.parsers.excel import ExcelParser
from fcrag.ingest.parsers.requirements import RequirementsParser
from fcrag.models import SourceFile
from fcrag.retrieval.route import SqlParameterStore
from fcrag.truth import SystemTruth


@pytest.fixture(scope="module")
def vocab(repo_root: Path) -> Vocabulary:
    return Vocabulary.from_truth(
        repo_root / "data_gen/systems", repo_root / "data_gen/synonyms.yaml"
    )


@pytest.fixture(scope="module")
def store(
    systems: dict[str, SystemTruth], vocab: Vocabulary, tmp_path_factory: pytest.TempPathFactory
) -> SqlParameterStore:
    out = tmp_path_factory.mktemp("docs")
    engine: Engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    generated = [excel.build_workbook(s, v, out) for s in systems.values() for v in (1, 2)]
    generated += [requirements.WRITERS[c](s, out) for c, s in systems.items()]
    with session_scope(engine) as session:
        for g in generated:
            sf = SourceFile(
                path=out / g.file, sha256="0" * 64, mime_type="x", doc_id=g.doc_id,
                doc_version=g.doc_version, system=g.system, language=g.language, title=g.title,
            )  # fmt: skip
            parser = ExcelParser() if g.file.endswith(".xlsx") else RequirementsParser()
            records = extract_parameters(vocab, sf, list(parser.parse(sf)))
            session.add_all(ParameterRecord(**r.model_dump()) for r in records)
            session.add(
                Document(source_key=sf.source_key, doc_id=g.doc_id, doc_version=g.doc_version,
                         path="x", sha256="0", mime_type="x", title=g.title, status="indexed",
                         attempts=0)
            )  # fmt: skip
    return SqlParameterStore(engine)


def test_comparison_uses_current_values_and_flags_conflicts(store: SqlParameterStore) -> None:
    table = compare(store, ["System A", "System B", "System C"], ["rated_net_power",
                    "coolant_outlet_temperature_max", "pressure_drop_dry_side"])  # fmt: skip
    assert [table["rated_net_power"][s].value for s in ("System A", "System B", "System C")] == [
        80,
        300,
        100,
    ]
    # the A humidifier changed between versions: current value only, both versions listed
    humidifier = table["pressure_drop_dry_side"]["System A"]
    assert humidifier.value == 15
    assert {(s["doc_version"], s["value"]) for s in humidifier.sources} >= {(1, 18), (2, 15)}
    # requirement REQ-A says 90 °C while the parameter sheet says 95 °C (stated there in K)
    coolant = table["coolant_outlet_temperature_max"]["System A"]
    assert coolant.value == pytest.approx(95)
    assert not coolant.agree
    assert table["coolant_outlet_temperature_max"]["System B"].agree


def test_checker_flags_conflict_and_confirms_consistent_values(
    store: SqlParameterStore, vocab: Vocabulary
) -> None:
    system, checks = check_requirement(
        "The fuel cell stack of System A shall not exceed a maximum coolant outlet temperature "
        "of 90 °C.", None, vocab, store,
    )  # fmt: skip
    assert system == "System A"
    (check,) = checks
    assert check.status == "conflict"
    assert {d["doc_id"]: d["agrees"] for d in check.documents}["ps-system-a"] is False

    _, checks = check_requirement(
        "Das Stackmodul muss eine Zellenanzahl von 440 aufweisen.", "System B", vocab, store
    )
    assert [(c.parameter, c.status) for c in checks] == [("cell_count", "consistent")]


def test_checker_without_system_or_values(store: SqlParameterStore, vocab: Vocabulary) -> None:
    assert check_requirement("The stack shall be blue.", None, vocab, store) == (None, [])
    assert check_requirement("The stack shall be blue.", "System C", vocab, store) == (
        "System C",
        [],
    )
