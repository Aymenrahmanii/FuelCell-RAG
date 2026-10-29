# ADR 0005: Drawings read by text position, vision model optional

- Status: accepted
- Date: 2026-10-29

## Context

FR-01 requires drawings and schematics (PDF, PNG). What engineers ask about them is exact:
a drawing number, the current revision and what it changed, which line connects which two
components. The plan proposed OCR for title blocks plus a vision LLM for component
descriptions, and flagged the risk: a vision model invents tags and connections.

Drawings carry most of their meaning as positioned text: a title block (label above value),
a revision table, a line list, and tags with names inside symbols. Docling's layout model is
trained on reports, not drawings, and does not read a title block as fields.

## Decision

1. A dedicated `DrawingParser` claims every file with `doc_type: drawing`, whatever its
   extension (`parser_for` now checks a parser's `doc_types` before extensions), and every
   image file.
2. Text comes from the PDF text layer (pypdfium2, character by character in content order,
   so labels hidden under a symbol are not read into it), or from RapidOCR when a page has no
   text layer. OCR gets up to 4,200 px: RapidOCR's default of 2,000 px misreads 6 pt labels on
   an A3 sheet.
3. Layout is read from geometry, the same way for both sources: tables by their header rows,
   title block fields by their labels, components by tag pattern with the centred lines below.
   Text that fits no structure is kept as notes, so a drawing without a line list or title
   block is still searchable.
4. The vision model is off by default (`FCRAG_DRAWING_VLM`). When on, its description is a
   separate element with `confidence: low` and a citation that says "vision model
   description". In restricted mode only a local vision model is used, or none.

## Consequences

- On the generated schematics, the vector PDFs and the raster PNG (through RapidOCR) both
  yield every component, line and revision exactly; a unit test checks the line list against
  the generator.
- Layout rules assume a conventional sheet: a header row naming the columns, labels above
  values. Unusual title blocks fall back to notes, which are searchable but not structured.
- OCR of one A3 sheet takes about 30 s on CPU; acceptable for ingestion, not for queries.
