# ADR 0003: Two-phase ingestion with a parsed-element cache

- Status: accepted
- Date: 2026-10-25

## Context

The first full ingestion ran parsing (Docling layout and TableFormer models) and embedding
(bge-m3) per file in one process on a 6 GB laptop GPU, with about 3.5 GB already used by other
programs. A 13-page slide deck took 230 s in the pipeline but 21 s on its own: on Windows the
driver does not fail when VRAM runs out, it silently spills to system memory and everything
slows down about tenfold.

A second problem appeared later: CadQuery (OpenCascade) and docling-parse cannot load their
native libraries into the same Windows process.

## Decision

1. `Pipeline.run` works in two phases: parse every file that needs work, release the parser
   models (`release_models()`), then enrich, chunk, embed and index.
2. Parsed elements are cached on disk by content hash (`data/processed/elements/`), so
   re-chunking and re-embedding experiments never re-parse, and a crashed run resumes cheaply.
3. STEP geometry is read in a child process (`step_geometry`), which keeps OpenCascade out of
   the ingestion process.

## Consequences

- Throughput rose to about 1,150 PDF pages per hour on the laptop GPU, meeting the 1,000
  pages/hour target. TableFormer's fast mode (`FCRAG_PDF_TABLE_MODE=fast`) is 3x faster on
  slides if accuracy allows.
- Elements of a whole batch are held in memory between the phases; for very large batches the
  run should be split (the worker can be given `only=` globs).
- Bump `ELEMENTS_VERSION` whenever a parser's output changes, or stale cache entries are reused.
