# ADR 0004: One YAML truth per system; generators record facts as gold sources

- Status: accepted
- Date: 2026-10-25

## Context

Measuring retrieval and citation quality needs labelled gold sources: for each question, which
page, cell range or requirement holds the answer. Labelling by hand does not scale, breaks
whenever a document is regenerated, and confidential engineering documents cannot be used.

## Decision

- Each fictional system is defined once in `data_gen/systems/*.yaml`. Tests check the physics
  (V = N·V_cell, P = V·I, H₂ flow from Faraday's law, efficiency from the lower heating value).
- Generators turn the truth into datasheets (PDF), parameter sheets (XLSX), requirement specs
  (ReqIF, DOCX, CSV) and STEP assemblies, with realism injections: German documents, unit
  variants, two document versions, hidden obsolete rows, merged headers, prose-only links, and
  one requirement per system that contradicts the parameter sheet.
- While writing, each generator records every value it states and where (page, sheet and
  cells, requirement ID): `facts.jsonl`. The golden set and the parameter-extraction metric
  read these facts, so gold labels are exact and regenerate with the documents.

## Consequences

- Parameter extraction can be scored exactly (99.5 % recall and precision through Docling).
- Synthetic documents are cleaner than real ones; the public DOE/NREL/open-access corpus keeps
  the evaluation honest on messy layouts, and its 12 questions are written and checked by hand.
