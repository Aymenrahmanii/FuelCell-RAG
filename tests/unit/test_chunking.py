from pathlib import Path

from fcrag.ingest.chunking import ChunkingConfig, build_chunks, chunk_id, estimate_tokens
from fcrag.models import Element, SourceFile

SOURCE = SourceFile(
    path=Path("ds.pdf"), sha256="a" * 64, mime_type="application/pdf", doc_id="ds", title="Stack DS"
)


def text(content: str, heading: list[str], page: int = 1) -> Element:
    return Element(kind="text", content=content, heading_path=heading, locator={"page": page})


def test_section_chunks_follow_headings_and_carry_context() -> None:
    elements = [
        text("Intro sentence. " * 30, ["1 Introduction"]),
        text("Coolant outlet max 85 °C. " * 30, ["3 Limits", "3.2 Temperatures"], page=4),
        text("Inlet min 5 °C. " * 30, ["3 Limits", "3.2 Temperatures"], page=5),
    ]
    chunks = build_chunks(elements, SOURCE, ChunkingConfig(min_tokens=20))
    assert len(chunks) == 2
    limits = chunks[1]
    assert limits.heading_path == ["3 Limits", "3.2 Temperatures"]
    assert limits.locator == {"page": 4, "pages": [4, 5]}
    assert limits.embed_text.startswith("Stack DS > 3 Limits > 3.2 Temperatures\n\n")
    assert not limits.text.startswith("Stack DS")


def test_small_sections_merge_into_previous_chunk() -> None:
    elements = [text("Short.", ["1 A"]), text("Also short.", ["2 B"])]
    chunks = build_chunks(elements, SOURCE, ChunkingConfig(min_tokens=50))
    assert len(chunks) == 1
    assert chunks[0].text == "Short.\n\n2 B\n\nAlso short."


def test_tables_and_rows_stay_standalone() -> None:
    elements = [
        text("Before the table.", ["2 Data"]),
        Element(kind="table", content="| a | b |", heading_path=["2 Data"], locator={"page": 2}),
        Element(kind="table_row", content="T | a: 1", heading_path=["2 Data"], locator={"page": 2}),
        text("After.", ["2 Data"]),
    ]
    kinds = [c.kind for c in build_chunks(elements, SOURCE, ChunkingConfig())]
    assert kinds == ["text", "table", "table_row", "text"]


def test_long_text_is_split_under_the_cap() -> None:
    long = "Sentence about membranes. " * 400
    chunks = build_chunks([text(long, ["1 X"])], SOURCE, ChunkingConfig(max_tokens=200))
    assert len(chunks) > 1
    assert all(estimate_tokens(c.text) <= 200 for c in chunks)


def test_fixed_strategy_windows_with_overlap() -> None:
    elements = [text(f"Paragraph {i}. " + "word " * 100, ["1 X"], page=i) for i in range(1, 9)]
    cfg = ChunkingConfig(strategy="fixed", fixed_tokens=150, overlap_tokens=20, max_tokens=800)
    chunks = build_chunks(elements, SOURCE, cfg)
    assert len(chunks) > 3
    assert chunks[0].locator["page"] == 1
    assert chunks[-1].locator["page"] > 1


def test_ids_are_deterministic_and_headers_optional() -> None:
    a = build_chunks([text("x", [])], SOURCE, ChunkingConfig(contextual_headers=False))
    b = build_chunks([text("x", [])], SOURCE, ChunkingConfig(contextual_headers=False))
    assert a[0].chunk_id == b[0].chunk_id == chunk_id("a" * 64, 0)
    assert a[0].embed_text == "x"
    assert "embed_text" not in a[0].model_dump()
