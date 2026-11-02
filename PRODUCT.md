# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Static HTML, CSS and JavaScript served by the existing FastAPI app (user decision, 2026-11-02). No new Python packages (the lock file cannot be regenerated without the PyTorch index), no Node or build step. The Streamlit UI in `src/fcrag/ui/` stays until the new one covers all five screens.

## Users

Primary: engineers at a fuel cell or automotive supplier who search datasheets, parameter sheets, requirement specifications, STEP assemblies, drawings and public reports, in German and English, and need an answer they can trust and trace.

Second audience, equal weight (user decision): a hiring team reviewing this as a portfolio project, usually through a short demo video or a few minutes in the running app.

## Product Purpose

FuelCell-RAG answers questions over fuel cell engineering documents and cites a page, table cell, requirement ID or CAD part for every claim. It refuses to answer when the documents do not contain the answer. Success for an engineer: the right value, with the source open next to it, in seconds. Success for a reviewer: it is obvious within a minute that this is a real, measured system and not a mock-up.

## Positioning

Every answer is checkable and the product shows its own measurements: a 70-question golden set with exact gold sources (25 in German), an evaluation page that lists the failing questions with reasons, and version labels that mark which source is latest and which is superseded. A generic chat front end over documents does not show its failures.

## Operating Context

Five existing screens, all backed by the FastAPI endpoints in `src/fcrag/api/app.py`:
- Chat: streamed answers (server-sent events `sources`, `token`, `done`, `error`), filters (system, document type, latest versions only), follow-up questions with the rewritten search query shown, source list with cited markers, version labels and score, page preview for PDFs, copy-with-citations, thumbs rating with comment.
- Documents: registry of ingested files with status, counts and errors; re-ingest job with status polling.
- Parameter comparison: values per system for chosen parameters; disagreements between current documents flagged.
- Requirement checker: a draft requirement checked against current documents, with similar and linked requirements.
- Evaluation: saved runs, headline metrics, comparison of two runs with the configuration that differs, recall per category, failing questions with the reason, prompt-injection result.

Content is German and English. The API can require an `X-API-Key` header; the UI must work with and without it. Three fictional PEM fuel cell systems (A passenger car 80 kW, B heavy-duty truck 2 × 150 kW, C stationary CHP 100 kW) plus about 204 public reports and papers (corpus of 254 documents on 2026-11-02).

## Capabilities and Constraints

- The UI never talks to Qdrant or Postgres; only the API.
- Streaming answers arrive token by token; citations are written `[S1]`, `[S2]`.
- Sources carry `label`, `title`, `doc_version`, `is_latest`, `location`, `locator` (page, cell, requirement ID), `score`, `text`.
- Retrieval takes 0.6–2 s; generation takes 2–25 s depending on the model and rate limits, so waiting states matter.
- Undecided: authentication beyond the API-key and group stub; deployment hosting.

## Brand Commitments

Name: FuelCell-RAG. No logo, colours or typefaces exist yet. The user wants it professional, clean and appealing, and "nothing AI-sloppy". No other commitments.

## Evidence on Hand

Measured results exist and may be shown (README, `docs/STATUS.md`, `eval/runs/`): recall@5 0.921 to 0.937, value accuracy 92.7 %, citation precision 95.6 %, 7 of 7 correct refusals, faithfulness 0.918 (judge), 10-user retrieval p95 4.9 s. Real answers and failures are in the saved eval runs.

Absent and not to be invented: customers, testimonials, company logos, any claim of use at Bosch or another company, pricing, uptime figures.

## Product Principles

1. The source is always one glance away from the claim it supports.
2. Show uncertainty and failure honestly: refusals, superseded versions, failing questions.
3. Density and calm over spectacle: engineers scan; waiting states are explicit.
4. German and English are equal; labels and number formats must not break in either.
5. Every number on screen comes from the system, never from a mock.

## Accessibility & Inclusion

No product-specific standard was set. Keyboard operation, visible focus and WCAG AA contrast are the working floor.
